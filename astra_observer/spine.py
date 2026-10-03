import base64,json,sqlite3,time
from pathlib import Path
from astra_blocks.rpc import canonical,digest,result,Rpc,strict,DEVNET_GENESIS
from astra_pipeline.decode import keys_of
from astra_dex import pumpswap
NETWORKS={'devnet':DEVNET_GENESIS,'mainnet':'5eykt4UsFv8P8NJdTREpY1vzqKqZKvdpKuc147dw2N9d'}
READ_METHODS={'getGenesisHash','getSignaturesForAddress','getTransaction'}
def require(ok,code):
    if not ok:raise ValueError(code)
def sha(obj):return digest(canonical(obj).encode())
def decoder_hash():
    from astra_execution import routed
    return digest(Path(__file__).read_bytes()+Path(pumpswap.__file__).read_bytes()+pumpswap.SCHEMA_PATH.read_bytes()+Path(routed.__file__).read_bytes())

class Archive:
    def __init__(self,path,network):
        require(network in NETWORKS,'network_required');self.network=network;p=Path(path);p.parent.mkdir(parents=True,exist_ok=True)
        self.db=sqlite3.connect(p)
        try:
            self.db.execute('PRAGMA journal_mode=WAL');self.db.execute('PRAGMA synchronous=FULL')
            self.db.executescript('CREATE TABLE IF NOT EXISTS config(network TEXT);CREATE TABLE IF NOT EXISTS frames(seq INTEGER PRIMARY KEY,document TEXT,previous TEXT,hash TEXT);')
            old=self.db.execute('SELECT network FROM config').fetchone()
            if old:require(old[0]==network,'network_mismatch')
            else:self.db.execute('INSERT INTO config VALUES(?)',(network,))
            for table in ('frames','config'):
                for op in ('UPDATE','DELETE'):self.db.execute(f"CREATE TRIGGER IF NOT EXISTS no_{op}_{table} BEFORE {op} ON {table} BEGIN SELECT RAISE(ABORT,'immutable'); END")
            self.db.commit()
        except BaseException:self.db.close();raise
    def close(self):self.db.close()
    def append(self,kind,raw,metadata=None,observed_ns=None):
        doc=canonical({'kind':kind,'network':self.network,'raw':None if raw is None else base64.b64encode(raw).decode(),'metadata':metadata or {},'observed_ns':time.time_ns() if observed_ns is None else observed_ns})
        with self.db:
            self.db.execute('BEGIN IMMEDIATE');last=self.db.execute('SELECT seq,hash FROM frames ORDER BY seq DESC LIMIT 1').fetchone();seq=last[0]+1 if last else 1;prev=last[1] if last else '0'*64;h=sha([seq,doc,prev]);self.db.execute('INSERT INTO frames VALUES(?,?,?,?)',(seq,doc,prev,h))
        return seq
    def audit(self):
        prev='0'*64;seq=0
        for n,doc,p,h in self.db.execute('SELECT * FROM frames ORDER BY seq'):
            require(n==seq+1 and p==prev and h==sha([n,doc,p]),'archive_hash_mismatch');o=strict(doc);require(o['network']==self.network,'archive_network_mismatch');seq=n;prev=h
        require(self.db.execute('PRAGMA integrity_check').fetchone()[0]=='ok','archive_integrity');return {'frames':seq,'head':prev}
    def frame(self,seq):
        r=self.db.execute('SELECT document,previous,hash FROM frames WHERE seq=?',(seq,)).fetchone();require(r is not None and sha([seq,r[0],r[1]])==r[2],'frame_hash_mismatch');return strict(r[0]),r[2]

class ReadOnlyRpc:
    def __init__(self,archive,endpoint,limit=40,timeout=5):
        require(type(limit)==int and 1<=limit<=1000,'invalid_budget');self.archive=archive;self.rpc=Rpc(endpoint,timeout=timeout);self.limit=limit;self.verified=False
        with archive.db:
            archive.db.execute('CREATE TABLE IF NOT EXISTS rpc_budget(id INTEGER PRIMARY KEY CHECK(id=1),limit_value INTEGER,used INTEGER)')
            old=archive.db.execute('SELECT limit_value FROM rpc_budget WHERE id=1').fetchone()
            if old:require(old[0]==limit,'immutable_budget')
            else:archive.db.execute('INSERT INTO rpc_budget VALUES(1,?,0)',(limit,))
    def call(self,method,params):
        require(method in READ_METHODS,'read_only_method_refused');require(self.verified or method=='getGenesisHash','network_not_verified')
        with self.archive.db:
            self.archive.db.execute('BEGIN IMMEDIATE');used=self.archive.db.execute('SELECT used FROM rpc_budget WHERE id=1').fetchone()[0];require(used<self.limit,'quota_exhausted');self.archive.db.execute('UPDATE rpc_budget SET used=used+1 WHERE id=1')
        start=time.perf_counter_ns();raw,error=self.rpc.call(method,params);elapsed=time.perf_counter_ns()-start
        seq=self.archive.append('rpc',raw,{'method':method,'params':params,'transport_error':error,'transport_ns':elapsed})
        if error:raise ValueError('rpc_transport_failure')
        value=result(raw)
        return value,seq
    def identity(self):
        value,seq=self.call('getGenesisHash',[]);require(value==NETWORKS[self.archive.network],'genesis_mismatch');self.verified=True;self.genesis_seq=seq;return seq
    def transaction(self,signature):
        require(self.verified,'network_not_verified')
        return self.call('getTransaction',[signature,{'encoding':'json','commitment':'confirmed','maxSupportedTransactionVersion':1}])

def decode_frame(archive,seq,genesis_seq):
    identity,_=archive.frame(genesis_seq);require(identity['metadata'].get('method')=='getGenesisHash','genesis_proof_required');require(result(base64.b64decode(identity['raw']))==NETWORKS[archive.network],'genesis_mismatch')
    frame,h=archive.frame(seq);require(frame['metadata'].get('method')=='getTransaction','transaction_frame_required')
    params=frame['metadata']['params'];require(params[1]['commitment'] in ('confirmed','finalized'),'commitment_required')
    raw=base64.b64decode(frame['raw']);tx=result(raw)
    if tx is None:return {'events':[],'states':[{'status':'unresolved','reason':'transaction_missing'}]}
    require(type(tx['slot'])==int and tx['slot']>=0,'invalid_slot');require(tx['transaction']['signatures'][0]==params[0],'signature_mismatch')
    if tx['meta']['err'] is not None:return {'events':[],'states':[{'status':'failed','reason':'transaction_failed'}]}
    keys=keys_of(tx);outer=tx['transaction']['message']['instructions'];groups={};events=[];states=[]
    for g in tx['meta'].get('innerInstructions') or []:
        require(type(g['index'])==int and 0<=g['index']<len(outer) and g['index'] not in groups,'invalid_inner_group');groups[g['index']]=g['instructions']
    for index,ix in enumerate(outer):
        pi=ix['programIdIndex'];require(type(pi)==int and 0<=pi<len(keys),'invalid_program')
        state={'instruction_index':index,'status':'unsupported','reason':'protocol_not_supported'}
        if keys[pi]==pumpswap.PROGRAM:
            try:state.update(pumpswap.decode(ix,groups.get(index,[]),keys))
            except (ValueError,KeyError,TypeError,IndexError):state.update(status='error',reason='invalid_protocol_evidence')
        elif any(type(i.get('programIdIndex'))==int and 0<=i['programIdIndex']<len(keys) and keys[i['programIdIndex']]==pumpswap.PROGRAM for i in groups.get(index,[])):
            state['reason']='routed_protocol_present'
            from astra_execution.routed import decode_routed
            for child in decode_routed(groups.get(index,[]),keys):
                if child['status']=='decoded':
                    event=child.pop('event');event.update(network=archive.network,slot=tx['slot'],event_time=tx.get('blockTime'),availability_ns=frame['observed_ns'],signature=params[0],instruction_index=index,commitment=params[1]['commitment'])
                    event['id']=sha([archive.network,params[0],index,event['parent_inner_index'],event['inner_instruction_index']]);event['provenance']={'frame_sequence':seq,'frame_sha256':h,'raw_sha256':digest(raw),'genesis_sequence':genesis_seq,'decoder_sha256':decoder_hash()};events.append(event)
                states.append(dict(child,outer_instruction_index=index))
        if state['status']=='decoded':
            event=state.pop('event');event.update(network=archive.network,slot=tx['slot'],event_time=tx.get('blockTime'),availability_ns=frame['observed_ns'],signature=params[0],instruction_index=index,commitment=params[1]['commitment'])
            event['id']=sha([archive.network,params[0],index,event['inner_instruction_index']]);event['provenance']={'frame_sequence':seq,'frame_sha256':h,'raw_sha256':digest(raw),'genesis_sequence':genesis_seq,'decoder_sha256':decoder_hash()};events.append(event)
        states.append(state)
    return {'events':events,'states':states}
