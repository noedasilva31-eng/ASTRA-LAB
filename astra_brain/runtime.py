"""Additive strategy gate; the qualified Bridge and ledger still own Evidence/Risk/fills."""
import base64,json,tempfile,time
from pathlib import Path
from fractions import Fraction
from astra_bridge.runtime import Bridge,reason
from astra_bridge.evidence import opportunity
from astra_bridge.diagnostics import diagnose
from astra_execution.paper import replay_rows
from astra_execution.quotes import quote
from astra_observer.risk import evaluate
from astra_observer.spine import sha,require,result,strict,NETWORKS
from .core import DEFAULT,VERSION,NAMESPACES,datum,market,regime,scores,entry,position,meta_state

def code_hash():
    return sha([(p.name,p.read_text(encoding='utf-8')) for p in sorted(Path(__file__).parent.glob('*.py'))])

class BrainBridge(Bridge):
    def __init__(self,*args,brain_config=None,replaying=False,**kwargs):
        archive=args[0] if args else kwargs['archive'];self.brain_config=dict(DEFAULT if brain_config is None else brain_config);self.replaying=replaying
        require(set(self.brain_config)==set(DEFAULT) and self.brain_config['version']==VERSION,'invalid_brain_configuration')
        require(all(type(v)==int and (v<0 if k=='thesis_momentum_bps' else v>0) for k,v in self.brain_config.items() if k!='version'),'invalid_brain_configuration')
        self.brain_version={'config':self.brain_config,'code':code_hash(),'promotion':'OPERATOR_INSTALLED_PAPER_ONLY','live_execution':False}
        self.brain_records={};configs=[]
        for _,doc in archive.db.execute('SELECT seq,document FROM frames ORDER BY seq'):
            f=json.loads(doc)
            if f['kind']=='brain_config':configs.append(f['metadata'])
            if f['kind']=='brain_decision':
                r=f['metadata'];require(r['plan_id'] not in self.brain_records,'duplicate_brain_decision');self.brain_records[r['plan_id']]=r
        require(not configs or configs==[self.brain_version],'immutable_brain_configuration')
        if not configs:
            require(not archive.db.execute("SELECT 1 FROM frames WHERE json_extract(document,'$.kind')='bridge_plan' LIMIT 1").fetchone(),'brain_requires_separate_session')
            archive.append('brain_config',None,self.brain_version)
        super().__init__(*args,**kwargs)
    def _history(self,event):
        row=self.engine.db.execute('SELECT seq FROM events WHERE id=?',(event['id'],)).fetchone();require(row is not None,'brain_event_missing')
        # Bounded pool window, ordered by actual availability/materialization.
        rows=self.engine.db.execute("SELECT document FROM events WHERE seq<=? AND json_extract(document,'$.pool')=? ORDER BY seq DESC LIMIT 64",(row[0],event['pool'])).fetchall()
        return [json.loads(d) for d, in reversed(rows)]
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
        begin=time.perf_counter_ns();agent=market(self._history(e),e,op,now,self.brain_config)
        agent['features']['quote_impact_bps']=datum(int(Fraction(q['impact'])*10000) if q else None,now,q['observed_ns'] if q else None,'provider_quote',q['slot'] if q else None,q['provenance'] if q else None,'bps',classification='PROVEN')
        timings['market_agent_ns']=time.perf_counter_ns()-begin
        begin=time.perf_counter_ns();reg=regime(agent['features'],self.brain_config);timings['regime_ns']=time.perf_counter_ns()-begin
        begin=time.perf_counter_ns();sc=scores(agent['features'],now,self.brain_config);timings['scoring_ns']=time.perf_counter_ns()-begin
        risk_account={'exposure':sum(p['cost'] for p in account['positions'].values()) if plan.get('side')=='BUY' else 0,'positions':len(account['positions']) if plan.get('side')=='BUY' else 0,'loss':account['loss_quote_raw'] if plan.get('side')=='BUY' else 0}
        begin=time.perf_counter_ns();risk=evaluate(op or {},risk_account,plan.get('amount',self.size),now,self.policy,plan.get('kill',False));timings['risk_diagnostic_ns']=time.perf_counter_ns()-begin
        begin=time.perf_counter_ns()
        state={'version':'OpportunityStateV1','identity':{'event_id':e['id'],'token':e['base_mint'],'pool':e['pool'],'quote':e['quote_mint'],'network':e['network'],'signature':e['signature']},'clock':{'slot':e['slot'],'event_time':e['event_time'],'availability_time':e['availability_ns'],'decision_time':now},'market':agent['features'],'execution':op['execution_quote'] if op else {'status':'UNKNOWN'},'evidence':{'refs':plan.get('evidence',{}),'status':'PROVEN' if op else 'MISSING','failure':evidence_error},'risk':risk,'coverage':{'scope':'OBSERVED_SUBSET','window_events':agent['sample_event_ids'],'complete_market':False},'provenance':e['provenance'],'market_agent':agent,'scores':sc,'regime':reg,'decision_context':{'plan_id':plan['id'],'action':plan.get('action'),'side':plan.get('side'),'ledger_before_head':account['head']}}
        state.update({n:{'version':n+'-interface-v0','status':'UNKNOWN','value':None,'available_at':None,'provenance':None} for n in NAMESPACES});state['meta']=meta_state(now)
        timings['opportunity_state_ns']=time.perf_counter_ns()-begin
        begin=time.perf_counter_ns();en=entry(state,self.brain_config);timings['entry_arbiter_ns']=time.perf_counter_ns()-begin;ps=None
        existing=account['positions'].get(e['base_mint'])
        if existing:
            documents={json.loads(r[1])['id']:json.loads(r[1]) for r in ledger[:prefix]};fill=documents[existing['entry_id']];entry_record=self.brain_records.get(fill['intent_id']);require(entry_record is not None,'brain_entry_snapshot_missing')
            begin=time.perf_counter_ns();ps=position(entry_record,existing,fill,state,q,now,self.brain_config,self.model.fee_quote_raw,self.model.adverse_bps);timings['position_health_exit_ns']=time.perf_counter_ns()-begin
        action='REJECT' if evidence_error else 'SETTLE_PENDING' if plan.get('action')=='settle' else ps['exit']['action'] if ps else en['action']
        r={'version':VERSION,'plan_id':plan['id'],'state':state,'entry':en,'position':ps,'action':action,'ledger_before_sequence':prefix,'assurance':'CANDIDATE_REQUIRES_QUALIFIED_RISK_AND_POST_DECISION_QUOTE'};r['id']=sha(r)
        timings['brain_total_ns']=time.perf_counter_ns()-start
        if old:require(old==r,'brain_snapshot_replay_mismatch')
        else:
            require(not self.replaying,'brain_snapshot_missing');self.a.append('brain_decision',None,r,observed_ns=now);self.a.append('brain_latency',None,{'plan_id':plan['id'],'clock':'host_monotonic','stages':timings,'acquisition_ns':plan.get('acquisition_ns')},observed_ns=now);self.brain_records[plan['id']]=r
        return r
    def _apply(self,plan):
        e=plan['event'];self.engine.ingest(self.a,e['provenance']['frame_sequence'],e['provenance']['genesis_sequence']);r=self._record(plan)
        if r['action'] in ('HOLD','NO_TRADE','REDUCE_CANDIDATE'):
            return {'kind':r['action'].lower(),'id':plan['id'],'event_id':e['id'],'brain_snapshot':r['id'],'code':'partial_exit_not_supported' if r['action']=='REDUCE_CANDIDATE' else 'brain_arbiter_'+r['action'].lower(),'live_execution':False}
        # All actual intents/settlements still pass through qualified Evidence + Risk.
        started=time.perf_counter_ns();result_=super()._apply(plan)
        if not self.replaying:
            exists=self.a.db.execute("SELECT 1 FROM frames WHERE json_extract(document,'$.kind')='brain_execution_latency' AND json_extract(document,'$.metadata.plan_id')=? LIMIT 1",(plan['id'],)).fetchone()
            if not exists:self.a.append('brain_execution_latency',None,{'plan_id':plan['id'],'stage':'qualified_settlement_path_ns' if plan.get('action')=='settle' else 'qualified_intent_path_ns','duration_ns':time.perf_counter_ns()-started,'scope':'Evidence + enforced Risk + idempotent ledger operation; combined measurement'},observed_ns=plan['now'])
        return result_
    def verify_replay(self):
        self.a.audit()
        with tempfile.TemporaryDirectory(prefix='astra-brain-replay-') as tmp:
            other=BrainBridge(self.a,tmp,None,self.policy,self.model,self.initial,self.size,brain_config=self.brain_config,replaying=True)
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
