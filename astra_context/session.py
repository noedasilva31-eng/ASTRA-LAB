"""Durable, bounded pre-entry hydration; existing position follow-up is reused."""
import json,time,hashlib
from pathlib import Path
from astra_observer.spine import ReadOnlyRpc,require,sha
from astra_observer.source import stream
from astra_bridge.session import target,follow_once,attempted,FollowupReady,metrics
from astra_multicycle.session import frames,census

def eligible(bridge,now):
    watched={r['pool'] for _,r in frames(bridge.a,'context_watch')}
    for r in reversed(list(bridge.brain_records.values())):
        s=r['state'];c=s['market_agent']['context'];pool=s['identity']['pool'];missing=c['required_missing']
        if pool in watched or r['action']!='NO_TRADE' or s['evidence']['status']!='PROVEN' or not s['risk']['allowed']:continue
        if now-s['clock']['decision_time']>bridge.context_config['fresh_ns'] or now<s['clock']['decision_time']:continue
        if not missing or any(k not in ('history.minimum_samples','history.minimum_span','history.continuity','momentum_bps') for k in missing):continue
        if not r['entry']['conditions']['nonnegative_flow']:continue
        return r
    return None

def current_watch(bridge):
    closed={r['watch_id'] for _,r in frames(bridge.a,'context_watch_end')}
    return next((r for _,r in reversed(frames(bridge.a,'context_watch')) if r['watch_id'] not in closed),None)

def start_watch(bridge,record):
    s=record['state'];watch={'watch_id':sha(['context-watch-v0.1',record['id']]),'snapshot':record['id'],'pool':s['identity']['pool'],'mint':s['identity']['token'],'after_slot':s['clock']['slot'],'started_ns':s['clock']['decision_time'],'expires_ns':s['clock']['decision_time']+bridge.context_config['hydration_ns'],'coverage':'TARGETED_OBSERVED_SUBSET'}
    previous=[r for _,r in frames(bridge.a,'context_watch') if r['watch_id']==watch['watch_id']]
    require(not previous or previous==[watch],'context_watch_identity_conflict')
    if not previous:bridge.a.append('context_watch',None,watch)
    return watch

def end_watch(bridge,watch,reason):
    if not any(r['watch_id']==watch['watch_id'] for _,r in frames(bridge.a,'context_watch_end')):bridge.a.append('context_watch_end',None,{'watch_id':watch['watch_id'],'reason':reason})

def hydration_tick(bridge,rpc,watch,now_ns=time.time_ns):
    a=bridge.a;cfg=bridge.context_config;now=now_ns()
    if any(r['watch_id']==watch['watch_id'] for _,r in frames(a,'context_watch_end')):return {'hydrated':0,'stopped':'closed'}
    polls=[r for _,r in frames(a,'context_poll') if r['watch_id']==watch['watch_id']];receipts=[r for _,r in frames(a,'context_receipt') if r['watch_id']==watch['watch_id']]
    if now<watch['started_ns'] or now>=watch['expires_ns']:end_watch(bridge,watch,'expired_or_clock_regression');return {'hydrated':0,'stopped':'expired'}
    if len(polls)>=cfg['max_polls'] or len(receipts)>=cfg['max_hydrated_transactions']:end_watch(bridge,watch,'hydration_budget_exhausted');return {'hydrated':0,'stopped':'budget'}
    # Reserve before I/O; restart cannot reset poll count.
    a.append('context_poll',None,{'watch_id':watch['watch_id'],'ordinal':len(polls)+1})
    if not rpc.verified:rpc.identity()
    rows,listing=rpc.call('getSignaturesForAddress',[watch['pool'],{'limit':8,'commitment':'confirmed'}]);require(type(rows)==list,'invalid_signature_listing')
    counts,complete=attempted(a);stats={'hydrated':0,'listed':len(rows),'listing_frame':listing,'watch_id':watch['watch_id']}
    for row in reversed(rows):
        require(type(row)==dict and type(row.get('slot'))==int and type(row.get('signature'))==str and 'err' in row,'invalid_signature_listing')
        if now_ns()>=watch['expires_ns']:end_watch(bridge,watch,'expired');break
        if len(receipts)+stats['hydrated']>=cfg['max_hydrated_transactions']:end_watch(bridge,watch,'hydration_budget_exhausted');break
        if row['err'] is not None or row['slot']<=watch['after_slot'] or row['signature'] in complete or counts[row['signature']]>=2:continue
        _,seq=rpc.transaction(row['signature']);expired=now_ns()>=watch['expires_ns'];a.append('context_receipt',None,{'watch_id':watch['watch_id'],'raw_frame':seq,'expired':expired});stats['hydrated']+=1
        collector=bridge.collector
        try:
            if expired:bridge.collector=None
            bridge.ingest(a,seq,rpc.genesis_seq)
        finally:bridge.collector=collector
        census(a,bridge)
        if expired:end_watch(bridge,watch,'expired_receipt_no_evidence_acquisition');break
        if now_ns()>=watch['expires_ns']:end_watch(bridge,watch,'expired_during_evidence');break
        if target(bridge):end_watch(bridge,watch,'handed_to_qualified_paper_follow');break
        relevant=[r for r in bridge.brain_records.values() if r['state']['identity']['pool']==watch['pool'] and r['state']['provenance']['frame_sequence']==seq]
        if relevant:
            latest=relevant[-1];s=latest['state'];f=s['market'];c=s['market_agent']['context']
            if latest['action']=='REJECT' or not s['risk']['allowed'] or (f['imbalance_bps']['value'] is not None and f['imbalance_bps']['value']<0) or (f['momentum_bps']['value'] is not None and f['momentum_bps']['value']<0):end_watch(bridge,watch,'evidence_risk_or_market_deterioration');break
            if c['complete_for_model']:end_watch(bridge,watch,'context_ready_no_forced_trade');break
        # One new transaction per tick keeps decisions tied to fresh subsequent data.
        break
    a.append('context_poll_result',None,stats);return stats

class Port:
    def __init__(self,bridge,clock):self.bridge=bridge;self.clock=clock
    def latencies(self):return self.bridge.latencies()
    def ingest(self,a,seq,g):
        r=self.bridge.ingest(a,seq,g)
        if target(self.bridge) or eligible(self.bridge,self.clock()):raise FollowupReady()
        return r

def run(archive,bridge,endpoint,ws_endpoint,seconds=180,max_cycles=3,clock=time.monotonic,sleep=time.sleep,wall=time.time_ns):
    require(type(seconds)==int and 1<=seconds<=300 and type(max_cycles)==int and 1<=max_cycles<=100,'invalid_session_bounds')
    cfg={'version':'context-session-v0.1','scheduler':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'max_cycles':max_cycles,'max_plans':50,'rpc_budget':200}
    old=frames(archive,'context_session_config');require(not old or old==[(old[0][0],cfg)],'immutable_context_session')
    if not old:archive.append('context_session_config',None,cfg)
    bridge.recover();archive.audit();census(archive,bridge);rpc=ReadOnlyRpc(archive,endpoint,limit=200);start=clock();until=start+seconds;started=wall();stop='bounded_window_ended';polls=0;hydrated=0
    while clock()<until:
        if len(bridge.plans)>=50:stop='plan_bound_after_atomic_transaction';break
        if len(bridge.outcome_links()['closed_scenarios'])>=max_cycles and not target(bridge):stop='cycle_cap';break
        if archive.db.execute('SELECT used FROM rpc_budget WHERE id=1').fetchone()[0]>=200:stop='rpc_budget_exhausted';break
        if target(bridge):
            w=current_watch(bridge)
            if w:end_watch(bridge,w,'handed_to_qualified_paper_follow')
            r=follow_once(archive,bridge,rpc,until,clock=clock);polls+=1;hydrated+=r['hydrated']
        else:
            w=current_watch(bridge);candidate=eligible(bridge,wall()) if not w else None
            if candidate:w=start_watch(bridge,candidate)
            if w:r=hydration_tick(bridge,rpc,w,wall);polls+=1;hydrated+=r['hydrated']
            else:
                remaining=min(15,int(until-clock()))
                if remaining<1:break
                before=archive.audit()['frames'];result_=None
                try:result_=stream(archive,Port(bridge,wall),endpoint,ws_endpoint,seconds=remaining,max_messages=32,limit=200)
                except FollowupReady:result_={'status':'HANDOFF'}
                archive.append('multi_discovery',None,{'from_frame_exclusive':before,'through_frame':archive.audit()['frames'],'coverage':'OBSERVED_SUBSET','result':result_})
                if result_.get('status')=='FAIL' and result_.get('code')!='no_supported_event_observed':raise ValueError('context_discovery_failed')
        census(archive,bridge);remaining=until-clock()
        if remaining>0:sleep(min(1,remaining))
    m=metrics(bridge,started);m.update(stop_reason=stop,polls=polls,followup_hydrations=hydrated,closed_cycles=len(bridge.outcome_links()['closed_scenarios']),context_watch=current_watch(bridge),rpc_budget=dict(zip(('limit','used'),archive.db.execute('SELECT limit_value,used FROM rpc_budget WHERE id=1').fetchone())))
    archive.append('multi_end',None,m);return m
