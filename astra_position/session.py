"""Position-only polling, persistent caps, one new transaction per poll."""
import time,json
from astra_bridge.session import target,attempted,metrics
from astra_observer.spine import require,ReadOnlyRpc
from astra_bridge.runtime import Collector
from astra_bridge.diagnostics import diagnose

class TargetCollector:
    def __init__(self,collector,pool,mint):self.collector=collector;self.pool=pool;self.mint=mint
    def collect(self,event,side,amount,model):
        require(event['pool']==self.pool and event['base_mint']==self.mint and side=='SELL','pending_other_token')
        return self.collector.collect(event,side,amount,model)

def records(a,kind):
    return [json.loads(d)['metadata'] for d, in a.db.execute("SELECT document FROM frames WHERE json_extract(document,'$.kind')=? ORDER BY seq",(kind,))]

def run(b,endpoint,key=None,seconds=120,max_polls=16,clock=time.monotonic,wall=time.time_ns,sleep=time.sleep,rpc=None):
    require(type(seconds)==int and 1<=seconds<=180 and type(max_polls)==int and 1<=max_polls<=32,'position_session_bounds')
    a=b.a;config={'seconds':seconds,'max_polls':max_polls,'budget':b.activation['budget'],'single_transaction_per_poll':True}
    old=records(a,'position_session_config');require(not old or old==[config],'immutable_position_session_bounds')
    if not old:a.append('position_session_config',None,config)
    starts=records(a,'position_window');now=wall()
    if starts:window=starts[0]
    else:window={'started_ns':now,'expires_ns':now+seconds*10**9};a.append('position_window',None,window,observed_ns=now)
    start=clock();deadline=start+max(0,(window['expires_ns']-now)/1e9);stop='bounded_window_ended'
    if not rpc:
        rpc=ReadOnlyRpc(a,endpoint,limit=config['budget']);c=Collector(a,endpoint,key,limit=config['budget']);b.collector=TargetCollector(c,b.activation['target']['pool'],b.activation['target']['mint'])
    base_budget=a.db.execute('SELECT used FROM rpc_budget').fetchone()[0];initial_events=b.engine.db.execute('SELECT count(*) FROM events').fetchone()[0]
    while clock()<deadline and wall()<window['expires_ns']:
        current=target(b)
        if current is None:stop='position_closed';break
        require(current['pool']==b.activation['target']['pool'] and current['mint']==b.activation['target']['mint'],'position_target_changed')
        polls=records(a,'position_poll_reserved')
        if len(polls)>=max_polls:stop='poll_budget';break
        if wall()<window['started_ns']:stop='clock_regression';break
        index=len(polls)+1;a.append('position_poll_reserved',None,{'index':index,'target':current},observed_ns=wall())
        stats={'index':index,'pool':current['pool'],'listed':0,'reused':0,'old':0,'failed':0,'hydrated':0,'new_matching_events':0}
        try:
            if not rpc.verified:rpc.identity()
            rows,seq=rpc.call('getSignaturesForAddress',[current['pool'],{'limit':8,'commitment':'confirmed'}]);require(type(rows)==list,'invalid_signature_listing');stats.update(listed=len(rows),listing_frame=seq)
            counts,complete=attempted(a)
            # Highest observed matching event slot, including inherited observations.
            watermark=max([current['after_slot']]+[json.loads(d)['slot'] for d, in b.engine.db.execute("SELECT document FROM events WHERE json_extract(document,'$.pool')=?",(current['pool'],))])
            for row in reversed(rows):
                require(type(row)==dict and type(row.get('slot'))==int and type(row.get('signature'))==str and 'err' in row,'invalid_signature_listing')
                if clock()>=deadline or wall()>=window['expires_ns']:break
                if row['err'] is not None:stats['failed']+=1;continue
                if row['signature'] in complete:stats['reused']+=1;continue
                if row['slot']<watermark or row['slot']<=current['after_slot']:stats['old']+=1;continue
                if counts[row['signature']]>=2:continue
                _,txseq=rpc.transaction(row['signature']);stats['hydrated']+=1
                if clock()>=deadline or wall()>=window['expires_ns']:
                    stats['expired_raw_frame']=txseq;stop='window_expired_after_raw'
                    collector=b.collector;b.collector=None
                    try:
                        decoded=b.ingest(a,txseq,rpc.genesis_seq);stats['new_matching_events']=sum(e['pool']==current['pool'] for e in decoded['events'])
                    finally:b.collector=collector
                    break
                decoded=b.ingest(a,txseq,rpc.genesis_seq);stats['new_matching_events']=sum(e['pool']==current['pool'] for e in decoded['events']);break
        except (ValueError,OSError) as exc:
            diagnostic=diagnose(exc,'position_follow');code=diagnostic['code'];stats['error']=code
            if code=='quota_exhausted':stop='rpc_budget';a.append('position_poll',None,stats);break
            if diagnostic['category'] not in ('SOURCE_FAILURE','OPERATIONAL_FAILURE','EVIDENCE_REJECT'):raise
        a.append('position_poll',None,stats)
        if target(b) is None:stop='position_closed';break
        remaining=min(deadline-clock(),(window['expires_ns']-wall())/1e9)
        if remaining>0:sleep(min(1,remaining))
    result=metrics(b,window['started_ns']);polls=records(a,'position_poll');result.update(stop_reason=stop,polls_reserved=len(records(a,'position_poll_reserved')),polls_completed=len(polls),rpc_calls_this_invocation=a.db.execute('SELECT used FROM rpc_budget').fetchone()[0]-base_budget,rpc_budget=dict(zip(('limit','used'),a.db.execute('SELECT limit_value,used FROM rpc_budget').fetchone())),hydrations=sum(x['hydrated'] for x in polls),observations_reused=sum(x['reused'] for x in polls),new_matching_observations=sum(x['new_matching_events'] for x in polls),new_decoded_events_this_invocation=b.engine.db.execute('SELECT count(*) FROM events').fetchone()[0]-initial_events,elapsed_monotonic_ns=int((clock()-start)*1e9),window=window)
    a.append('position_session_end',None,result);return result
