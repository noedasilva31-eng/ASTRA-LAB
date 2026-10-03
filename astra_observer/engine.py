import json,sqlite3,time
from fractions import Fraction
from pathlib import Path
from .spine import canonical,sha,require,decode_frame,decoder_hash
from .risk import Policy,evaluate

def rat(v):return {'numerator':str(v.numerator),'denominator':str(v.denominator)}
def frac(v):return Fraction(int(v['numerator']),int(v['denominator']))
def code_hash():
    from . import risk
    return sha([Path(__file__).read_text(encoding='utf-8'),Path(risk.__file__).read_text(encoding='utf-8'),decoder_hash()])
class Engine:
    """Incremental bounded-window observatory. Heavy audits run only on request.
    Coverage is an observed subset, never a claim to have scanned every Solana slot.
    """
    def __init__(self,path,network,policy=None,horizons=(60,300,1800,3600,86400),window=64):
        from .spine import NETWORKS
        require(network in NETWORKS and type(window)==int and 2<=window<=1024,'invalid_engine_configuration')
        require(0<len(horizons)<=6 and len(set(horizons))==len(horizons) and all(type(x)==int and 1<=x<=86400 for x in horizons),'invalid_horizons')
        self.version=code_hash();self.policy=policy or Policy();self.window=window;self.horizons=sorted(horizons);self.network=network
        cfg=canonical({'network':network,'policy':self.policy.document(),'horizons':self.horizons,'window':window,'code':code_hash()})
        p=Path(path);p.parent.mkdir(parents=True,exist_ok=True);self.db=sqlite3.connect(p)
        try:
            self.db.execute('PRAGMA journal_mode=WAL');self.db.execute('PRAGMA synchronous=FULL')
            self.db.executescript('''CREATE TABLE IF NOT EXISTS config(document TEXT);
CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY,id TEXT UNIQUE,document TEXT,hash TEXT,semantic TEXT);
CREATE TABLE IF NOT EXISTS pools(id TEXT PRIMARY KEY,state TEXT);
CREATE TABLE IF NOT EXISTS wallets(pool TEXT,wallet TEXT,PRIMARY KEY(pool,wallet));
CREATE TABLE IF NOT EXISTS outcomes(pool TEXT,horizon INTEGER,due_ns INTEGER,document TEXT,PRIMARY KEY(pool,horizon));
CREATE INDEX IF NOT EXISTS due_outcomes ON outcomes(pool,due_ns);
CREATE TABLE IF NOT EXISTS decisions(event_id TEXT PRIMARY KEY,document TEXT,hash TEXT);
CREATE TABLE IF NOT EXISTS operator(id INTEGER PRIMARY KEY CHECK(id=1),kill INTEGER);
CREATE TABLE IF NOT EXISTS timings(seq INTEGER PRIMARY KEY,decode_ns INTEGER,features_decision_ns INTEGER,commit_ns INTEGER);
''')
            row=self.db.execute('SELECT document FROM config').fetchone()
            if row:require(row[0]==cfg,'immutable_engine_configuration')
            else:self.db.execute('INSERT INTO config VALUES(?)',(cfg,))
            self.db.execute('INSERT OR IGNORE INTO operator VALUES(1,0)')
            for table in ('events','decisions','config'):
                for op in ('UPDATE','DELETE'):self.db.execute(f"CREATE TRIGGER IF NOT EXISTS no_{op}_{table} BEFORE {op} ON {table} BEGIN SELECT RAISE(ABORT,'immutable'); END")
            self.db.commit()
        except BaseException:self.db.close();raise
    def close(self):self.db.close()
    def ingest(self,archive,seq,genesis_seq,hook=None):
        require(archive.network==self.network,'engine_network_mismatch');start=time.perf_counter_ns();decoded=decode_frame(archive,seq,genesis_seq);decode_ns=time.perf_counter_ns()-start
        for event in decoded['events']:self._event(event,decode_ns,hook)
        return decoded
    def _event(self,e,decode_ns=0,hook=None):
        require(e['network']==self.network and e['availability_ns']>0,'invalid_event');doc=canonical(e);semantic=sha({k:v for k,v in e.items() if k not in ('availability_ns','provenance','commitment')})
        start=time.perf_counter_ns()
        with self.db:
            self.db.execute('BEGIN IMMEDIATE');old=self.db.execute('SELECT semantic FROM events WHERE id=?',(e['id'],)).fetchone()
            if old:require(old[0]==semantic,'event_identity_conflict');return
            latest=self.db.execute('SELECT document FROM events ORDER BY seq DESC LIMIT 1').fetchone()
            if latest:require(e['availability_ns']>=json.loads(latest[0])['availability_ns'],'availability_clock_regression')
            cur=self.db.execute('INSERT INTO events(id,document,hash,semantic) VALUES(?,?,?,?)',(e['id'],doc,sha(e),semantic));seq=cur.lastrowid
            row=self.db.execute('SELECT state FROM pools WHERE id=?',(e['pool'],)).fetchone()
            s=json.loads(row[0]) if row else {'pool':e['pool'],'base_mint':e['base_mint'],'quote_mint':e['quote_mint'],'first_observed_ns':e['availability_ns'],'window':[],'events':0,'created_time':None,'lifecycle':'AMM','anchor':None,'peak':None,'drawdown':rat(Fraction(0)),'last_slot':e['slot']}
            require((s['base_mint'],s['quote_mint'])==(e['base_mint'],e['quote_mint']),'pool_identity_conflict')
            s['events']+=1;s['last_observed_ns']=e['availability_ns'];s['late_event']=e['slot']<s['last_slot'];s['last_slot']=max(s['last_slot'],e['slot'])
            if e['kind']=='pool_created':s['created_time']=e['event_time']
            if e['kind']=='swap':
                f=e['fields'];buy=e['instruction']!='sell';base=int(f['base_amount_out' if buy else 'base_amount_in']);quote=int(f['user_quote_amount_in' if buy else 'user_quote_amount_out']);require(base>0 and quote>0,'zero_swap_amount')
                price=Fraction(quote,base);w={'id':e['id'],'slot':e['slot'],'availability_ns':e['availability_ns'],'event_time':e['event_time'],'wallet':e['wallet'],'quote_raw':str(quote),'side':'buy' if buy else 'sell','price':rat(price)}
                s['window']=(s['window']+[w])[-self.window:];s['last_price']=rat(price)
                cursor=self.db.execute('INSERT OR IGNORE INTO wallets VALUES(?,?)',(e['pool'],e['wallet']));s['new_wallet_observed']=cursor.rowcount==1
                if s['anchor'] is None:
                    s['anchor']={'price':rat(price),'availability_ns':e['availability_ns'],'event_id':e['id']};s['peak']=rat(price)
                    for horizon in self.horizons:self.db.execute('INSERT INTO outcomes VALUES(?,?,?,NULL)',(e['pool'],horizon,e['availability_ns']+horizon*1_000_000_000))
                s['peak']=rat(max(frac(s['peak']),price));s['drawdown']=rat(min(frac(s['drawdown']),price/frac(s['peak'])-1))
                for horizon,due in self.db.execute('SELECT horizon,due_ns FROM outcomes WHERE pool=? AND due_ns<=? AND document IS NULL',(e['pool'],e['availability_ns'])).fetchall():
                    value={'pool':e['pool'],'horizon_seconds':horizon,'due_ns':due,'observed_ns':e['availability_ns'],'delay_ns':e['availability_ns']-due,'anchor_event':s['anchor']['event_id'],'mark_event':e['id'],'observed_mark_return':rat(price/frac(s['anchor']['price'])-1),'observed_drawdown':s['drawdown'],'coverage':'PARTIAL','liquidable_price':{'status':'NOT_COLLECTED'},'survival':'NOT_COLLECTED','provenance':e['provenance']}
                    self.db.execute('UPDATE outcomes SET document=? WHERE pool=? AND horizon=?',(canonical(value),e['pool'],horizon))
                state=self.opportunity(s,e);risk=evaluate(state,{'exposure':0,'positions':0,'loss':0},self.policy.max_position,e['availability_ns'],self.policy,bool(self.db.execute('SELECT kill FROM operator WHERE id=1').fetchone()[0]))
                decision={'id':sha(['observe-v1',e['id']]),'event_id':e['id'],'strategy':'observe-v1','action':'NO_TRADE','opportunity':state,'risk':risk,'paper_status':'BLOCKED_MISSING_EXECUTION_EVIDENCE','live_execution':False}
                self.db.execute('INSERT INTO decisions VALUES(?,?,?)',(e['id'],canonical(decision),sha(decision)))
            self.db.execute('INSERT OR REPLACE INTO pools VALUES(?,?)',(e['pool'],canonical(s)))
            if hook:hook('before_commit')
            elapsed=time.perf_counter_ns()-start;self.db.execute('INSERT INTO timings VALUES(?,?,?,0)',(seq,decode_ns,elapsed));commit_start=time.perf_counter_ns()
        commit_ns=time.perf_counter_ns()-commit_start
        with self.db:self.db.execute('UPDATE timings SET commit_ns=? WHERE seq=?',(commit_ns,seq))
        if hook:hook('committed')
    def opportunity(self,s,e):
        window=s['window'];mid=len(window)//2;a=sum(int(w['quote_raw']) for w in window[:mid]);b=sum(int(w['quote_raw']) for w in window[mid:]);p=frac(s['last_price'])
        return {'schema':1,'network':self.network,'pool':s['pool'],'base_mint':s['base_mint'],'quote_mint':s['quote_mint'],'venue':'pumpswap','lifecycle':'AMM',
        'slot':e['slot'],'event_time':e['event_time'],'availability_ns':e['availability_ns'],'heartbeat_ns':e['availability_ns'],'data_health':'PARTIAL','coverage':'PARTIAL',
        'market':{'status':'PARTIAL','price_quote_raw_per_base_raw':s['last_price'],'price_change_window':rat(p/frac(window[0]['price'])-1),'volume_quote_raw':str(a+b),'half_window_volume_change_raw':str(b-a),'volume_acceleration_per_second':{'status':'NOT_COLLECTED'},'swaps_observed':len(window),'buy_count':sum(w['side']=='buy' for w in window),'sell_count':sum(w['side']=='sell' for w in window),'wallets_unique_window':len({w['wallet'] for w in window}),'new_wallet_observed':s['new_wallet_observed'],'late_event':s['late_event'],'liquidity':{'status':'NOT_COLLECTED'}},
        'execution_quote':{'status':'NOT_COLLECTED'},'authority_state':'NOT_COLLECTED','holders':{'status':'NOT_COLLECTED'},'bundles':{'status':'NOT_COLLECTED'},'social':{'status':'NOT_COLLECTED'},'pool_creation_time':s['created_time'],'version':self.version,'feature_events':[w['id'] for w in window],'provenance':e['provenance']}
    def export(self):
        return {'network':self.network,'universe_coverage':'OBSERVED_SUBSET','pools':[json.loads(r[0]) for r in self.db.execute('SELECT state FROM pools ORDER BY id')],
        'decisions':[json.loads(r[0]) for r in self.db.execute('SELECT document FROM decisions ORDER BY event_id')],
        'outcomes':[json.loads(doc) if doc else {'pool':p,'horizon_seconds':h,'due_ns':due,'status':'NOT_COLLECTED'} for p,h,due,doc in self.db.execute('SELECT * FROM outcomes ORDER BY pool,horizon')]}
    def latencies(self):
        out={}
        for i,key in enumerate(('decode_ns','features_decision_ns','commit_ns')):
            rows=sorted(r[i] for r in self.db.execute('SELECT decode_ns,features_decision_ns,commit_ns FROM timings ORDER BY seq DESC LIMIT 10000'))
            out[key]={'samples':len(rows),'p95':rows[min(len(rows)-1,(len(rows)*95+99)//100-1)] if rows else None,'p99':rows[min(len(rows)-1,(len(rows)*99+99)//100-1)] if rows else None}
        return out
    def verify(self):
        for doc,h in self.db.execute('SELECT document,hash FROM events'):require(sha(json.loads(doc))==h,'event_hash_mismatch')
        for doc,h in self.db.execute('SELECT document,hash FROM decisions'):require(sha(json.loads(doc))==h,'decision_hash_mismatch')
        return {'events':self.db.execute('SELECT COUNT(*) FROM events').fetchone()[0],'decisions':self.db.execute('SELECT COUNT(*) FROM decisions').fetchone()[0]}
    def verify_reconstruction(self,archive):
        import tempfile
        self.verify()
        with tempfile.TemporaryDirectory(prefix='observer-audit-') as tmp:
            rebuilt=Engine(Path(tmp)/'engine.sqlite',self.network,self.policy,tuple(self.horizons),self.window)
            try:
                replay(archive,rebuilt);require(self.export()==rebuilt.export(),'materialization_replay_mismatch')
            finally:rebuilt.close()
        return {'status':'PASS','output_sha256':sha(self.export())}

def replay(archive,engine):
    archive.audit();genesis=None;states=[]
    for seq,doc in archive.db.execute('SELECT seq,document FROM frames ORDER BY seq'):
        frame=json.loads(doc);method=frame['metadata'].get('method')
        if method=='getGenesisHash':
            from .spine import NETWORKS,result,base64
            if frame['raw'] and result(base64.b64decode(frame['raw']))==NETWORKS[archive.network]:genesis=seq
        if method=='getTransaction' and not frame['raw']:
            states.append({'status':'unresolved','reason':frame['metadata'].get('transport_error','raw_missing'),'frame_sequence':seq})
        if method=='getTransaction' and frame['raw']:
            from .spine import strict
            if 'error' in strict(base64.b64decode(frame['raw'])):
                states.append({'status':'error','reason':'rpc_error','frame_sequence':seq});continue
            require(genesis is not None,'genesis_proof_required');states.extend(engine.ingest(archive,seq,genesis)['states'])
    return {'output':engine.export(),'states':states}
