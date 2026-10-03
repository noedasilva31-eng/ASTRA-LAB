"""Bounded scheduling around the qualified Observer/Evidence/ledger components.
Discovery via WS; targeted read-only hydration while an intent/position is open.
No timer-generated fills, no refreshed event timestamps, no forced exit.
"""
import base64,json,time,hashlib
from pathlib import Path
from collections import Counter
from .diagnostics import diagnose
from astra_observer.spine import ReadOnlyRpc,require,strict
from astra_observer.source import stream

class FollowupReady(Exception):
    """Internal scheduling signal after an ingest has fully committed."""

def target(bridge):
    state=bridge.paper.state();pending=next(iter(state['pending'].values()),None)
    if pending:return {'phase':'PENDING_'+pending['side'],'pool':pending['opportunity']['pool'],'mint':pending['mint'],'after_slot':pending['decision_slot'],'intent_id':pending['id'],'decision_ns':pending['decision_ns']}
    if state['positions']:
        mint,position=next(iter(state['positions'].items()));rows=bridge.paper.export()['ledger'];by_id={row['id']:row for row in rows};fill=by_id[position['entry_id']];intent=by_id[fill['intent_id']]
        return {'phase':'OPEN_POSITION','pool':intent['opportunity']['pool'],'mint':mint,'after_slot':fill['quote_evidence']['slot'],'entry_id':fill['id'],'decision_ns':fill['availability_ns']}
    return None

class DiscoveryPort:
    def __init__(self,bridge):self.bridge=bridge
    def latencies(self):return self.bridge.latencies()
    def ingest(self,archive,seq,genesis_seq):
        result=self.bridge.ingest(archive,seq,genesis_seq)
        if target(self.bridge):
            archive.append('paper_session_transition',None,{'to':'TARGETED_FOLLOWUP','reason':'committed_intent_or_position'})
            raise FollowupReady()
        return result

def attempted(archive):
    counts=Counter();complete=set()
    for doc, in archive.db.execute('SELECT document FROM frames ORDER BY seq'):
        frame=json.loads(doc);m=frame['metadata']
        if m.get('method')!='getTransaction':continue
        sig=m['params'][0];counts[sig]+=1
        if frame['raw']:
            value=strict(base64.b64decode(frame['raw']))
            if isinstance(value.get('result'),dict):complete.add(sig)
    return counts,complete

def follow_once(archive,bridge,rpc,until,clock=time.monotonic):
    current=target(bridge);require(current is not None,'session_target_missing')
    if not rpc.verified:rpc.identity()
    rows,listing=rpc.call('getSignaturesForAddress',[current['pool'],{'limit':8,'commitment':'confirmed'}])
    require(type(rows)==list,'invalid_signature_listing');counts,complete=attempted(archive)
    stats={'phase':current['phase'],'pool':current['pool'],'listing_frame':listing,'listed':len(rows),'old':0,'failed':0,'already_processed':0,'retry_bound':0,'hydrated':0,'decoded':0,'matching_events':0}
    for row in reversed(rows):
        require(type(row)==dict and type(row.get('slot'))==int and type(row.get('signature'))==str and 'err' in row,'invalid_signature_listing')
        if clock()>=until:break
        if row['err'] is not None:stats['failed']+=1;continue
        if row['slot']<=current['after_slot']:stats['old']+=1;continue
        sig=row['signature']
        if sig in complete:stats['already_processed']+=1;continue
        if counts[sig]>=2:stats['retry_bound']+=1;continue
        _,seq=rpc.transaction(sig);counts[sig]+=1;result=bridge.ingest(archive,seq,rpc.genesis_seq);stats['hydrated']+=1;stats['decoded']+=len(result['events']);stats['matching_events']+=sum(e['pool']==current['pool'] and e['base_mint']==current['mint'] for e in result['events'])
        # Recompute size, side and minimum slot after EVERY state transition.
        if target(bridge)!=current:break
    archive.append('paper_session_tick',None,stats);return stats

def metrics(bridge,started_ns):
    state=bridge.paper.state();rows=bridge.paper.export()['ledger'];rejections=Counter()
    for r in bridge.results.values():
        if r['kind']=='reject':
            for code in r.get('risk',{}).get('reasons') or [r.get('code','risk_veto')]:rejections[code]+=1
    buys=sum(r['kind']=='settlement' and 'quote_spent' in r for r in rows);sells=sum(r['kind']=='settlement' and 'quote_received' in r for r in rows)
    current=target(bridge);state_name='ROUNDTRIP_OBSERVED' if sells and not current else current['phase'] if current else 'NO_TRADE'
    return {'state':state_name,'scope':'cumulative_persistent_session','started_ns':started_ns,'observed_ns':time.time_ns(),'intents':sum(r['kind']=='intent' for r in rows),'buy_scenarios':buys,'sell_scenarios':sells,'pending':len(state['pending']),'positions':len(state['positions']),'realized_scenario_pnl_quote_raw':state['realized_scenario_pnl_quote_raw'],'rejection_counts':dict(sorted(rejections.items())),'target':current,'assurance':'CONDITIONAL_PAPER_NOT_EXECUTED_TRADES','coverage':'OBSERVED_SUBSET'}

def run_session(archive,bridge,endpoint,ws_endpoint,seconds=120):
    require(type(seconds)==int and 1<=seconds<=300,'invalid_session_bounds')
    start=time.monotonic();until=start+seconds;started_ns=time.time_ns();ticks=[];rpc=ReadOnlyRpc(archive,endpoint,limit=200)
    archive.append('paper_session_start',None,{'scheduler_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'seconds':seconds,'budget':200,'poll_interval_seconds':1,'signatures_per_poll':8,'max_hydration_attempts_per_signature':2})
    while time.monotonic()<until:
        if target(bridge) is None:
            if bridge.outcome_links()['closed_scenarios']:break
            remaining=int(until-time.monotonic())
            if remaining<1:break
            try:stream(archive,DiscoveryPort(bridge),endpoint,ws_endpoint,seconds=remaining,max_messages=64,limit=200)
            except FollowupReady:pass
            if target(bridge) is None:break
        else:
            tick=follow_once(archive,bridge,rpc,until);ticks.append(tick)
            remaining=until-time.monotonic()
            if remaining>0:time.sleep(min(1,remaining))
    m=metrics(bridge,started_ns);m['polls']=len(ticks);m['followup_hydrations']=sum(t['hydrated'] for t in ticks);m['followup_decoded_events']=sum(t['decoded'] for t in ticks);m['stop_reason']='roundtrip_observed' if m['state']=='ROUNDTRIP_OBSERVED' else 'bounded_window_ended';m['elapsed_monotonic_ns']=int((time.monotonic()-start)*1e9)
    archive.append('paper_session_end',None,m)
    return {'status':'PASS','code':'bounded_session_observed','session':m}
