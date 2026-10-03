"""Single-writer, evidence-gated conditional paper bridge; no transaction API."""
import json,time,tempfile,base64
from pathlib import Path
from astra_observer.spine import canonical,sha,require,decode_frame,result,strict,NETWORKS
from astra_observer.engine import Engine
from astra_observer.risk import Policy
from astra_execution.paper import Paper,Model
from astra_execution.quotes import quote
from .evidence import EvidenceRpc,Quotes,WSOL,bindings,opportunity
from .diagnostics import diagnose

POLICY=Policy(max_position=20_000_000,max_exposure=40_000_000,min_liquidity=1_000_000_000,max_session_loss=10_000_000)
MODEL=Model(fee_quote_raw=2_100_000)

def fingerprint():
    from . import evidence,diagnostics,tokens
    return sha([Path(__file__).read_text(encoding='utf-8'),Path(evidence.__file__).read_text(encoding='utf-8'),Path(diagnostics.__file__).read_text(encoding='utf-8'),Path(tokens.__file__).read_text(encoding='utf-8')])

def reason(exc):
    return diagnose(exc,'bridge')['code']

class Collector:
    def __init__(self,archive,endpoint,key=None,limit=200):
        self.archive=archive;self.rpc=EvidenceRpc(archive,endpoint,limit=limit);self.quotes=Quotes(archive,key)
    def collect(self,event,side,amount,model):
        if not self.rpc.verified:self.rpc.identity()
        addresses=bindings(self.archive,event)
        require(event['quote_mint']==WSOL,'unsupported_quote_currency')
        pair=(WSOL,event['base_mint']) if side=='BUY' else (event['base_mint'],WSOL)
        forward=self.quotes.get(*pair,amount);q=quote(self.archive,forward)
        units=min(q['minimum_output_raw'],q['output_raw']*(10000-model.adverse_bps)//10000)
        reverse=self.quotes.get(pair[1],pair[0],units)
        accounts=self.rpc.accounts(addresses,max(event['slot'],q['slot']))
        return {'forward_seq':forward,'reverse_seq':reverse,'accounts_seq':accounts}

class Bridge:
    """Plans are archived before ledger writes. Recovery uses their original time.
    Network acquisition is synchronous/bounded for this first vertical, not HFT.
    """
    def __init__(self,archive,directory,collector=None,policy=POLICY,model=MODEL,initial=1_000_000_000,size=10_000_000):
        require(archive.network=='mainnet','bridge_mainnet_required');self.a=archive;self.collector=collector
        self.policy=policy;self.model=model;self.size=size;self.initial=initial;self.directory=Path(directory);self.directory.mkdir(parents=True,exist_ok=True)
        self.cfg={'code':fingerprint(),'policy':policy.document(),'model':model.document(),'initial':initial,'size':size,'strategy':'bounded-observed-swap-v1','hold_rule':'next_distinct_observed_swap_after_entry','assurance':'CONDITIONAL_PAPER_SCENARIO'}
        archive.audit();configs=[];self.plans={};self.results={};self.kill=False
        for seq,doc in archive.db.execute('SELECT seq,document FROM frames ORDER BY seq'):
            f=json.loads(doc);m=f['metadata']
            if f['kind']=='bridge_config':configs.append(m)
            if f['kind']=='bridge_operator':self.kill=m['kill']
            if f['kind']=='bridge_plan':require(m['id'] not in self.plans,'duplicate_bridge_plan');self.plans[m['id']]=(seq,m)
            if f['kind']=='bridge_result':require(m['id'] not in self.results,'duplicate_bridge_result');self.results[m['id']]=m['result']
        require(all(c==self.cfg for c in configs),'immutable_bridge_configuration')
        if not configs:archive.append('bridge_config',None,self.cfg)
        self.engine=Engine(self.directory/'engine.sqlite','mainnet')
        try:self.paper=Paper(self.directory/'paper.sqlite',WSOL,initial,policy,model,archive)
        except BaseException:self.engine.close();raise
    def set_kill(self,value):
        require(type(value)==bool,'invalid_kill');self.a.append('bridge_operator',None,{'kill':value});self.kill=value
    def close(self):self.paper.close();self.engine.close()
    def latencies(self):return self.engine.latencies()
    def _apply(self,plan):
        e=plan['event'];self.engine.ingest(self.a,e['provenance']['frame_sequence'],e['provenance']['genesis_sequence'])
        if plan.get('rejection'):return {'kind':'reject','id':plan['id'],'code':plan['rejection'],'event_id':e['id'],'live_execution':False}
        op=opportunity(self.a,e,plan['side'],plan['amount'],**plan['evidence'],now=plan['now'],policy=self.policy,model=self.model)
        # Features are the immutable event-time snapshot, never the current pool row.
        row=self.engine.db.execute('SELECT document FROM decisions WHERE event_id=?',(e['id'],)).fetchone()
        op['observed_features']=json.loads(row[0])['opportunity'] if row else None
        if plan['action']=='settle':return self.paper.settle(self.a,plan['intent_id'],plan['evidence']['forward_seq'],op,plan['now'],kill=plan['kill'])
        return self.paper.submit(plan['id'],plan['side'],e['base_mint'],plan['amount'],op,plan['now'],kill=plan['kill'])
    def finish(self,ident,hook=None):
        if ident in self.results:return self.results[ident]
        _,plan=self.plans[ident]
        try:result=self._apply(plan)
        except (ValueError,KeyError,TypeError) as exc:
            # A failed fill leaves inventory untouched; the pending intent can retry.
            diagnostic=diagnose(exc,'apply_evidence')
            if diagnostic['category'] not in ('EVIDENCE_REJECT','SOURCE_FAILURE','OPERATIONAL_FAILURE'):raise
            result={'kind':'reject','id':ident,'code':reason(exc),'event_id':plan['event']['id'],'live_execution':False}
        if hook:hook('ledger_committed')
        self.a.append('bridge_result',None,{'id':ident,'result':result});self.results[ident]=result
        return result
    def recover(self):
        for ident in list(self.plans):self.finish(ident)
        # A crash before preparation is an explicit missed decision, never a
        # retroactive trade based on data acquired after the original event.
        for doc, in self.engine.db.execute('SELECT document FROM events ORDER BY seq'):
            event=json.loads(doc);ident=sha(['bridge-v1',event['id']])
            if event['kind']!='swap' or ident in self.plans:continue
            plan={'id':ident,'event':event,'rejection':'interrupted_before_evidence_plan','now':event['availability_ns']}
            n=self.a.append('bridge_plan',None,plan);self.plans[ident]=(n,plan);self.finish(ident)
    def ingest(self,archive,seq,genesis_seq,hook=None):
        require(archive is self.a,'bridge_archive_mismatch');self.recover()
        # Canonical source proof matches the unchanged Observer replay: last
        # verified identity preceding THIS raw transaction, never a later proof.
        for n,doc in archive.db.execute('SELECT seq,document FROM frames WHERE seq<? ORDER BY seq',(seq,)):
            frame=json.loads(doc)
            if frame['metadata'].get('method')=='getGenesisHash' and frame['raw']:
                verified,_=archive.frame(n);require(result(base64.b64decode(verified['raw']))==NETWORKS['mainnet'],'genesis_mismatch');genesis_seq=n
        decoded=self.engine.ingest(archive,seq,genesis_seq)
        for event in decoded['events']:
            if event['kind']!='swap':continue
            ident=sha(['bridge-v1',event['id']])
            if ident in self.plans:continue
            state=self.paper.state();pending=next(iter(state['pending'].values()),None);pos=state['positions'].get(event['base_mint']);side='SELL' if pos else 'BUY';amount=pos['units'] if pos else self.size
            action='submit';rejection=None
            if pending:
                if pending['mint']!=event['base_mint']:rejection='pending_other_token'
                else:side=pending['side'];amount=pending['amount'];action='settle'
            started=time.perf_counter_ns();refs={}
            try:
                require(not rejection,rejection or 'blocked')
                require(self.collector is not None,'collector_unavailable')
                refs=self.collector.collect(event,side,amount,self.model)
            except (ValueError,KeyError,TypeError,OSError) as exc:
                diagnostic=diagnose(exc,'collect_evidence')
                if diagnostic['category'] not in ('EVIDENCE_REJECT','SOURCE_FAILURE','OPERATIONAL_FAILURE'):raise
                rejection=reason(exc) if not rejection else rejection
            now=time.time_ns();kill=self.kill
            plan={'id':ident,'event':event,'side':side,'amount':amount,'action':action,'intent_id':pending['id'] if pending else None,'evidence':refs,'now':now,'kill':kill,'rejection':rejection,'acquisition_ns':time.perf_counter_ns()-started}
            n=archive.append('bridge_plan',None,plan);self.plans[ident]=(n,plan)
            if hook:hook('prepared')
            self.finish(ident,hook)
        return decoded
    def outcome_links(self):
        rows=self.paper.export()['ledger'];intents={r['id']:r for r in rows if r['kind']=='intent'};open_positions={};closed=[]
        for r in rows:
            if r['kind']!='settlement':continue
            intent=intents[r['intent_id']];mint=intent['mint']
            if intent['side']=='BUY':open_positions[mint]=(intent,r)
            else:
                entry,buy=open_positions.pop(mint)
                closed.append({'entry_decision':entry['id'],'entry_event':entry['opportunity']['event_id'],'entry_fill_scenario':buy['id'],
                    'exit_decision':intent['id'],'exit_event':intent['opportunity']['event_id'],'exit_fill_scenario':r['id'],
                    'pool':intent['opportunity']['pool'],'mint':mint,'quote_mint':WSOL,'realized_scenario_pnl_quote_raw':r['quote_received']-buy['quote_spent'],
                    'entry_quote':buy['quote_evidence']['provenance'],'exit_quote':r['quote_evidence']['provenance'],'assurance':'CONDITIONAL_PAPER_SCENARIO'})
        decisions=[{'decision_id':ident,'event_id':plan['event']['id'],'pool':plan['event']['pool'],'result_kind':self.results.get(ident,{}).get('kind','pending'),
            'outcome_scope':'pool_observed_marks_in_observatory_outcomes','realized_pnl_available':any(ident in (t['entry_decision'],t['exit_decision']) for t in closed)} for ident,(_,plan) in self.plans.items()]
        return {'closed_scenarios':closed,'decision_census':decisions}
    def export(self):
        return {'configuration':self.cfg,'plans':[p for _,p in self.plans.values()],'results':self.results,'paper':self.paper.export(),'outcome_links':self.outcome_links(),'observatory':self.engine.export(),'coverage':'OBSERVED_SUBSET','real_execution':'DISABLED'}
    def verify_replay(self):
        """Recompute every decision from raw evidence into fresh DBs, no I/O."""
        self.a.audit()
        with tempfile.TemporaryDirectory(prefix='astra-bridge-replay-') as tmp:
            other=Bridge(self.a,tmp,None,self.policy,self.model,self.initial,self.size)
            try:
                expected=dict(self.results);other.results={}
                genesis=None
                for seq,doc in self.a.db.execute('SELECT seq,document FROM frames ORDER BY seq'):
                    frame=json.loads(doc);method=frame['metadata'].get('method')
                    if method=='getGenesisHash' and frame['raw'] and result(base64.b64decode(frame['raw']))==NETWORKS['mainnet']:genesis=seq
                    if method=='getTransaction' and frame['raw'] and 'error' not in strict(base64.b64decode(frame['raw'])):other.engine.ingest(self.a,seq,genesis)
                    if frame['kind']!='bridge_plan':continue
                    plan=frame['metadata'];ident=plan['id']
                    try:actual=other._apply(plan)
                    except (ValueError,KeyError,TypeError) as exc:actual={'kind':'reject','id':ident,'code':reason(exc),'event_id':plan['event']['id'],'live_execution':False}
                    require(actual==expected.get(ident),'bridge_decision_replay_mismatch')
                require(other.paper.export()==self.paper.export(),'bridge_portfolio_replay_mismatch')
            finally:other.close()
        self.engine.verify_reconstruction(self.a)
        return {'status':'PASS','plans':len(self.plans),'results':len(self.results),'network_used':False}
