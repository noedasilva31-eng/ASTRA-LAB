"""Independent context adapter. Qualified components and Brain V0 remain byte-identical."""
import base64,json,tempfile,time
from pathlib import Path
from astra_brain.runtime import BrainBridge
from astra_brain.core import NAMESPACES,meta_state,position
from astra_bridge.evidence import opportunity
from astra_bridge.runtime import reason
from astra_bridge.diagnostics import diagnose
from astra_execution.paper import replay_rows
from astra_execution.quotes import quote
from astra_observer.risk import evaluate
from astra_observer.spine import sha,require,result,strict,NETWORKS
from .model import VERSION,CONFIG,build,classify,score,arbitrate

def fingerprint():
    return sha([(p.name,p.read_text(encoding='utf-8')) for p in sorted(Path(__file__).parent.glob('*.py'))])

class ContextBridge(BrainBridge):
    def __init__(self,*args,context_config=None,**kwargs):
        a=args[0] if args else kwargs['archive'];self.context_config=dict(CONFIG if context_config is None else context_config)
        require(set(self.context_config)==set(CONFIG) and all(type(v)==int and v>0 for v in self.context_config.values()),'invalid_context_configuration')
        cfg={'version':VERSION,'config':self.context_config,'code':fingerprint(),'economic_threshold_changes':False}
        old=[json.loads(d)['metadata'] for d, in a.db.execute("SELECT document FROM frames WHERE json_extract(document,'$.kind')='context_config'")]
        require(not old or old==[cfg],'immutable_context_configuration')
        if not old:
            require(not a.db.execute("SELECT 1 FROM frames WHERE json_extract(document,'$.kind')='bridge_plan'").fetchone(),'context_requires_new_session')
            a.append('context_config',None,cfg)
        super().__init__(*args,**kwargs)
    def _account_history(self,event,now):
        values={}
        for r in self.brain_records.values():
            s=r['state']
            if s['identity']['pool']!=event['pool'] or s['clock']['decision_time']>=now or s['provenance']['frame_sequence']>=event['provenance']['frame_sequence']:continue
            f=s['market'];q=f.get('quote_reserve',{});b=f.get('base_reserve',{})
            if q.get('value') is None or b.get('value') is None:continue
            values[q['provenance']['frame']]={'quote_reserve_raw':q['value'],'base_reserve_raw':b['value'],'observed_ns':q['available_at'],'slot':q['slot'],'provenance':q['provenance']}
        return sorted(values.values(),key=lambda x:x['observed_ns'])
    def _watch_at_plan(self,plan):
        cutoff=self.plans[plan['id']][0];active={}
        for d, in self.a.db.execute('SELECT document FROM frames WHERE seq<? ORDER BY seq',(cutoff,)):
            f=json.loads(d);m=f['metadata']
            if f['kind']=='context_watch':active[m['watch_id']]=m
            if f['kind']=='context_watch_end':active.pop(m['watch_id'],None)
        return next((w for w in active.values() if w['pool']==plan['event']['pool']),None)
    def _record(self,plan):
        start=time.perf_counter_ns();timings={};e=plan['event'];now=plan['now'];old=self.brain_records.get(plan['id'])
        ledger=self.paper.rows();prefix=old['ledger_before_sequence'] if old else len(ledger)
        require(prefix<=len(ledger),'brain_ledger_prefix_missing');account=replay_rows(ledger[:prefix],self.initial)
        begin=time.perf_counter_ns();op=None;q=None;evidence_error=plan.get('rejection')
        if not evidence_error:
            try:
                op=opportunity(self.a,e,plan['side'],plan['amount'],**plan['evidence'],now=now,policy=self.policy,model=self.model)
                q=quote(self.a,plan['evidence']['forward_seq'])
            except (ValueError,KeyError,TypeError) as exc:
                detail=diagnose(exc,'brain_evidence')
                if detail['category'] not in ('EVIDENCE_REJECT','SOURCE_FAILURE','OPERATIONAL_FAILURE'):raise
                evidence_error=detail['code']
        timings['evidence_validation_ns']=time.perf_counter_ns()-begin
        begin=time.perf_counter_ns();agent=build(self._history(e),e,op,q,now,self.brain_config,self.context_config,self._account_history(e,now))
        timings['market_agent_ns']=time.perf_counter_ns()-begin
        begin=time.perf_counter_ns();reg=classify(agent,self.brain_config);timings['regime_ns']=time.perf_counter_ns()-begin
        begin=time.perf_counter_ns();sc=score(agent,now,self.brain_config);timings['scoring_ns']=time.perf_counter_ns()-begin
        risk_account={'exposure':sum(p['cost'] for p in account['positions'].values()) if plan.get('side')=='BUY' else 0,'positions':len(account['positions']) if plan.get('side')=='BUY' else 0,'loss':account['loss_quote_raw'] if plan.get('side')=='BUY' else 0}
        begin=time.perf_counter_ns();risk=evaluate(op or {},risk_account,plan.get('amount',self.size),now,self.policy,plan.get('kill',False));timings['risk_diagnostic_ns']=time.perf_counter_ns()-begin
        begin=time.perf_counter_ns()
        state={'version':'OpportunityStateV1','identity':{'event_id':e['id'],'token':e['base_mint'],'pool':e['pool'],'quote':e['quote_mint'],'network':e['network'],'signature':e['signature']},'clock':{'slot':e['slot'],'event_time':e['event_time'],'availability_time':e['availability_ns'],'decision_time':now},'market':agent['features'],'execution':op['execution_quote'] if op else {'status':'UNKNOWN'},'evidence':{'refs':plan.get('evidence',{}),'status':'PROVEN' if op else 'MISSING','failure':evidence_error},'risk':risk,'coverage':{'scope':'OBSERVED_SUBSET','window_events':agent['sample_event_ids'],'complete_market':False},'provenance':e['provenance'],'market_agent':agent,'scores':sc,'regime':reg,'decision_context':{'plan_id':plan['id'],'action':plan.get('action'),'side':plan.get('side'),'ledger_before_head':account['head']}}
        state.update({n:{'version':n+'-interface-v0','status':'UNKNOWN','value':None,'available_at':None,'provenance':None} for n in NAMESPACES});state['meta']=meta_state(now)
        timings['opportunity_state_ns']=time.perf_counter_ns()-begin
        begin=time.perf_counter_ns();en=arbitrate(state,self.brain_config);timings['entry_arbiter_ns']=time.perf_counter_ns()-begin;ps=None
        existing=account['positions'].get(e['base_mint'])
        if existing:
            documents={json.loads(r[1])['id']:json.loads(r[1]) for r in ledger[:prefix]};fill=documents[existing['entry_id']];entry_record=self.brain_records.get(fill['intent_id']);require(entry_record is not None,'brain_entry_snapshot_missing')
            begin=time.perf_counter_ns();ps=position(entry_record,existing,fill,state,q,now,self.brain_config,self.model.fee_quote_raw,self.model.adverse_bps);timings['position_health_exit_ns']=time.perf_counter_ns()-begin
        watch=self._watch_at_plan(plan)
        if watch and plan.get('action')=='submit' and plan.get('side')=='BUY':
            within=watch['started_ns']<=now<watch['expires_ns'];en['conditions']['hydration_not_expired']=within
            if not within:en['action']='NO_TRADE';en['reasons'].append('hydration_expired_during_acquisition')
        state['decision_context']['hydration_watch']=watch
        action='REJECT' if evidence_error else 'SETTLE_PENDING' if plan.get('action')=='settle' else ps['exit']['action'] if ps else en['action']
        r={'version':VERSION,'plan_id':plan['id'],'state':state,'entry':en,'position':ps,'action':action,'ledger_before_sequence':prefix,'assurance':'CANDIDATE_REQUIRES_QUALIFIED_RISK_AND_POST_DECISION_QUOTE'};r['id']=sha(r)
        timings['brain_total_ns']=time.perf_counter_ns()-start
        if old:require(old==r,'brain_snapshot_replay_mismatch')
        else:
            require(not self.replaying,'brain_snapshot_missing');self.a.append('brain_decision',None,r,observed_ns=now);self.a.append('brain_latency',None,{'plan_id':plan['id'],'clock':'host_monotonic','stages':timings,'acquisition_ns':plan.get('acquisition_ns')},observed_ns=now);self.brain_records[plan['id']]=r
        return r
    def verify_replay(self):
        self.a.audit()
        with tempfile.TemporaryDirectory(prefix='astra-brain-replay-') as tmp:
            other=ContextBridge(self.a,tmp,None,self.policy,self.model,self.initial,self.size,brain_config=self.brain_config,context_config=self.context_config,replaying=True)
            try:
                expected=dict(self.results);other.results={};genesis=None
                for seq,doc in self.a.db.execute('SELECT seq,document FROM frames ORDER BY seq'):
                    f=json.loads(doc);method=f['metadata'].get('method')
                    if method=='getGenesisHash' and f['raw'] and result(base64.b64decode(f['raw']))==NETWORKS['mainnet']:genesis=seq
                    if method=='getTransaction' and f['raw'] and 'error' not in strict(base64.b64decode(f['raw'])):other.engine.ingest(self.a,seq,genesis)
                    if f['kind']!='bridge_plan':continue
                    plan=f['metadata'];ident=plan['id']
                    try:actual=other._apply(plan)
                    except (ValueError,KeyError,TypeError) as exc:
                        if diagnose(exc,'replay')['category'] not in ('EVIDENCE_REJECT','SOURCE_FAILURE','OPERATIONAL_FAILURE'):raise
                        actual={'kind':'reject','id':ident,'code':reason(exc),'event_id':plan['event']['id'],'live_execution':False}
                    require(actual==expected.get(ident),'brain_decision_replay_mismatch')
                require(other.paper.export()==self.paper.export(),'brain_portfolio_replay_mismatch')
            finally:other.close()
        self.engine.verify_reconstruction(self.a)
        return {'status':'PASS','plans':len(self.plans),'snapshots':len(self.brain_records),'results':len(self.results),'network_used':False}
