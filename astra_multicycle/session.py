import hashlib,json,time
from pathlib import Path
from astra_bridge.session import target,DiscoveryPort,FollowupReady,follow_once,metrics
from astra_observer.spine import ReadOnlyRpc,require
from astra_observer.source import stream
VERSION='multi-opportunity-v1'

def frames(archive,kind):
    return [(n,json.loads(d)['metadata']) for n,d in archive.db.execute('SELECT seq,document FROM frames ORDER BY seq') if json.loads(d)['kind']==kind]

def census(archive,bridge):
    """Rebuild missing census rows after crash; result IDs are immutable keys."""
    known={x['result_id'] for _,x in frames(archive,'multi_decision')}
    for plan_id,result in bridge.results.items():
        if result['id'] in known:continue
        plan_seq,plan=bridge.plans[plan_id]
        archive.append('multi_decision',None,{'plan_frame':plan_seq,'event_id':plan['event']['id'],'provenance':plan['event']['provenance'],'result_id':result['id'],'decision':result,'coverage':'OBSERVED_SUBSET','unobserved_opportunities':'UNKNOWN'})

def run(archive,bridge,endpoint,ws_endpoint,seconds=120,max_cycles=3,clock=time.monotonic,sleep=time.sleep,discover=None,follow=None,max_opportunities=50):
    archive.audit()
    require(type(seconds)==int and 1<=seconds<=300,'invalid_session_bounds')
    require(type(max_cycles)==int and 1<=max_cycles<=100,'invalid_cycle_bound')
    require(type(max_opportunities)==int and 1<=max_opportunities<=1000,'invalid_opportunity_bound')
    config={'version':VERSION,'scheduler_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'max_opportunities_lifetime':max_opportunities,'max_cycles_lifetime':max_cycles,'rpc_budget_lifetime':200,'coverage':'OBSERVED_SUBSET'}
    old=frames(archive,'multi_config')
    require(not old or (len(old)==1 and old[0][1]==config),'immutable_multicycle_configuration')
    if not old:archive.append('multi_config',None,config)
    bridge.recover();census(archive,bridge)
    rpc=ReadOnlyRpc(archive,endpoint,limit=200)
    start=clock();until=start+seconds;started=time.time_ns();polls=0;hydrated=0;discoveries=0
    # A crash/resume never resets RPC attempts, portfolio, loss or lifetime cycle cap.
    archive.append('multi_start',None,{'seconds':seconds,'started_ns':started,'resume_state':bridge.paper.state(),'target':target(bridge)})
    stop='bounded_window_ended'
    while clock()<until:
        if len(bridge.plans)>=max_opportunities:stop='opportunity_cap_reached';break
        if len(bridge.outcome_links()['closed_scenarios'])>=max_cycles and target(bridge) is None:stop='cycle_cap_reached';break
        used=archive.db.execute('SELECT used FROM rpc_budget WHERE id=1').fetchone()[0]
        if used>=200:stop='rpc_budget_exhausted';break
        before=archive.db.execute('SELECT COALESCE(MAX(seq),0) FROM frames').fetchone()[0];begin=time.time_ns()
        if target(bridge) is None:
            remaining=min(15,int(until-clock()))
            if remaining<1:break
            discoveries+=1;outcome=None
            try:
                if discover is not None:outcome=discover()
                else:outcome=stream(archive,DiscoveryPort(bridge),endpoint,ws_endpoint,seconds=remaining,max_messages=64,limit=200)
            except FollowupReady:outcome={'status':'HANDOFF','code':'intent_persisted'}
            census(archive,bridge)
            after=archive.db.execute('SELECT COALESCE(MAX(seq),0) FROM frames').fetchone()[0]
            archive.append('multi_discovery',None,{'from_frame_exclusive':before,'through_frame':after,'started_ns':begin,'ended_ns':time.time_ns(),'result':outcome,'state':target(bridge),'decision':'FOLLOW' if target(bridge) else 'NO_TRADE','coverage':'OBSERVED_SUBSET','false_negative_evaluation':'NOT_SUPPORTED_WITHOUT_OBSERVATION_COVERAGE'})
            if outcome and outcome.get('status')=='FAIL' and outcome.get('code')!='no_supported_event_observed':raise ValueError('discovery_failed')
        else:
            tick=follow() if follow is not None else follow_once(archive,bridge,rpc,until,clock=clock)
            polls+=1;hydrated+=tick['hydrated'];census(archive,bridge)
            archive.append('multi_follow',None,{'tick':tick,'remaining':target(bridge),'portfolio':bridge.paper.state()})
        remaining=until-clock()
        if remaining>0:sleep(min(1,remaining))
    census(archive,bridge);result=metrics(bridge,started)
    result.update(stop_reason=stop,polls=polls,followup_hydrations=hydrated,discovery_windows=discoveries,closed_cycles=len(bridge.outcome_links()['closed_scenarios']),rpc_budget=dict(zip(('limit','used'),archive.db.execute('SELECT limit_value,used FROM rpc_budget WHERE id=1').fetchone())),elapsed_monotonic_ns=int((clock()-start)*1e9))
    archive.append('multi_end',None,result)
    return result
