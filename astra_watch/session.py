"""No WS/discovery. Exact diagnostics, bounded newest-head query, durable epochs."""
import json,time,re,uuid
from astra_observer.spine import ReadOnlyRpc,require
from astra_bridge.runtime import Collector
from astra_bridge.session import target,attempted,metrics
from astra_bridge.diagnostics import diagnose
from astra_position.session import records,TargetCollector

def cursor(b):
    current=target(b)
    if not current:return None
    found=[json.loads(d) for d, in b.engine.db.execute("SELECT document FROM events WHERE json_extract(document,'$.pool')=? AND json_extract(document,'$.base_mint')=? ORDER BY seq",(current['pool'],current['mint']))]
    latest=max(found,key=lambda e:(e['slot'],e['availability_ns'])) if found else None
    return dict(current,cursor_slot=max(current['after_slot'],latest['slot'] if latest else 0),cursor_signature=latest['signature'] if latest else None,cursor_signature_slot=latest['slot'] if latest else None,cursor_availability_ns=latest['availability_ns'] if latest else current['decision_ns'])

def begin(b,window_id=None,seconds=120,budget=80,max_polls=30,poll_seconds=2,now=None):
    require(type(seconds)==int and 1<=seconds<=900 and type(budget)==int and 8<=budget<=200 and type(max_polls)==int and 1<=max_polls<=300 and type(poll_seconds)==int and 1<=poll_seconds<=30,'watch_bounds')
    ident=window_id or uuid.uuid4().hex;require(bool(re.fullmatch('[A-Za-z0-9_-]{1,64}',ident)),'invalid_watch_id')
    config={'seconds':seconds,'budget':budget,'max_polls':max_polls,'poll_seconds':poll_seconds,'signature_limit':32}
    old=records(b.a,'watch_window');matching=[x for x in old if x['window_id']==ident]
    if matching:
        require(matching[0]['config']==config,'immutable_watch_bounds');require(old[-1]['window_id']==ident,'watch_window_superseded');return matching[0]
    current=cursor(b);require(current is not None,'watch_position_closed')
    require(current['pool']==b.activation['target']['pool'] and current['mint']==b.activation['target']['mint'],'watch_target_mismatch')
    now=time.time_ns() if now is None else now
    previous=b.a.db.execute('SELECT limit_value,used FROM rpc_budget').fetchone();require(previous is not None,'watch_budget_missing')
    ordinal=len(old)+1;table='watch_previous_budget_'+str(ordinal)
    w={'window_id':ident,'config':config,'started_ns':now,'expires_ns':now+seconds*10**9,'cursor':current,'previous_budget':dict(zip(('limit','used'),previous)),'previous_budget_table':table,'supersedes_window_id':old[-1]['window_id'] if old else None,'allocation':'EXPLICIT_NEW_WINDOW_NOT_LEDGER_RESET','coverage':'LATEST_32_SIGNATURES_OBSERVED_SUBSET_NO_FULL_CATCHUP'}
    # One SQLite transaction reserves the new epoch and its chained control frame.
    from astra_observer.spine import canonical,sha
    with b.a.db:
        b.a.db.execute('BEGIN IMMEDIATE');b.a.db.execute('ALTER TABLE rpc_budget RENAME TO '+table)
        b.a.db.execute('CREATE TABLE rpc_budget(id INTEGER PRIMARY KEY CHECK(id=1),limit_value INTEGER,used INTEGER)');b.a.db.execute('INSERT INTO rpc_budget VALUES(1,?,0)',(budget,))
        doc=canonical({'kind':'watch_window','network':b.a.network,'raw':None,'metadata':w,'observed_ns':now});last=b.a.db.execute('SELECT seq,hash FROM frames ORDER BY seq DESC LIMIT 1').fetchone();seq=last[0]+1;prev=last[1]
        b.a.db.execute('INSERT INTO frames VALUES(?,?,?,?)',(seq,doc,prev,sha([seq,doc,prev])))
    return w

def stage(d):
    if not d['network_attempted']:return 'NO_NETWORK_CALL'
    if d['position_observations']:
        return 'NEW_OBSERVATION_REJECTED' if d['observations_accepted']==0 else 'NEW_POSITION_OBSERVATION'
    if d['transactions_hydrated']:return 'NEW_TRANSACTION_UNSUPPORTED'
    if d['new_signatures_found']:return 'NEW_SIGNATURE_NOT_HYDRATED'
    return 'NO_NEW_SIGNATURE'

def monitor(b,w,endpoint=None,key=None,clock=time.monotonic,wall=time.time_ns,sleep=time.sleep,rpc=None,diagnostic=None):
    a=b.a;c=w['config'];cur=cursor(b);base_used=a.db.execute('SELECT used FROM rpc_budget').fetchone()[0];start=clock();until=start+max(0,(w['expires_ns']-wall())/1e9)
    info={'window_id':w['window_id'],'position_loaded':cur is not None,'pool':w['cursor']['pool'],'mint':w['cursor']['mint'],'cursor_slot':w['cursor']['cursor_slot'],'cursor_signature':w['cursor']['cursor_signature'],'cursor_availability_ns':w['cursor']['cursor_availability_ns'],'cursor_signature_slot':w['cursor']['cursor_signature_slot'],'network_attempted':False,'endpoint_env':'ASTRA_OBSERVER_RPC_URL','endpoint_configured':bool(endpoint) or rpc is not None,'network':'mainnet','signature_search_completed':False,'signature_rows_seen':0,'signatures_found':0,'new_signatures_found':0,'transactions_hydrated':0,'hydration_attempts':0,'position_observations':0,'observations_accepted':0,'observations_rejected':0,'rejection_reasons':{},'latest_slot_seen':None,'polls':0,'already_processed':0,'below_cursor':0,'failed_transactions':0,'retry_exhausted':0,'unsupported_transactions':0,'missing_transactions':0,'rpc_calls':0,'errors':[],'stop_reason':'window_expired','coverage':w['coverage']}
    d={} if diagnostic is None else diagnostic;d.update(info)
    seen=set();eligible_seen=set()
    # No client construction or network identity request when window is already closed.
    if cur is None:d['stop_reason']='position_closed'
    elif wall()<w['started_ns']:d['stop_reason']='clock_regression'
    elif wall()<w['expires_ns']:
        if rpc is None:
            rpc=ReadOnlyRpc(a,endpoint,limit=c['budget']);collector=Collector(a,endpoint,key,limit=c['budget']);b.collector=TargetCollector(collector,d['pool'],d['mint'])
        try:
            while clock()<until and wall()<w['expires_ns']:
                if target(b) is None:d['stop_reason']='position_closed';break
                require(target(b)['pool']==d['pool'] and target(b)['mint']==d['mint'],'watch_target_mismatch')
                count=sum(x['window_id']==w['window_id'] for x in records(a,'watch_poll_reserved'))
                if count>=c['max_polls']:d['stop_reason']='poll_budget';break
                if a.db.execute('SELECT used FROM rpc_budget').fetchone()[0]>=c['budget']:d['stop_reason']='rpc_budget';break
                if wall()<w['started_ns']:d['stop_reason']='clock_regression';break
                a.append('watch_poll_reserved',None,{'window_id':w['window_id'],'index':count+1},observed_ns=wall());d['polls']+=1
                tick={'window_id':w['window_id'],'index':count+1,'at_ns':wall()}
                try:
                    d['network_attempted']=True
                    if not rpc.verified:rpc.identity()
                    d['genesis_verified']=rpc.verified;d['genesis_frame']=rpc.genesis_seq
                    rows,seq=rpc.call('getSignaturesForAddress',[d['pool'],{'limit':c['signature_limit'],'commitment':'confirmed'}]);require(type(rows)==list,'invalid_signature_listing');d['signature_rows_seen']+=len(rows);d['signature_search_completed']=True;tick['listing_frame']=seq
                    counts,complete=attempted(a);candidates=[]
                    for row in rows:
                        require(type(row)==dict and type(row.get('slot'))==int and type(row.get('signature'))==str and 'err' in row,'invalid_signature_listing')
                        seen.add(row['signature']);d['signatures_found']=len(seen)
                        d['latest_slot_seen']=max(d['latest_slot_seen'] or 0,row['slot'])
                        if row['err'] is not None:d['failed_transactions']+=1;continue
                        if row['signature'] in complete:d['already_processed']+=1;continue
                        if row['slot']<d['cursor_slot'] or row['slot']<=w['cursor']['after_slot']:d['below_cursor']+=1;continue
                        eligible_seen.add(row['signature']);d['new_signatures_found']=len(eligible_seen)
                        if counts[row['signature']]>=2:d['retry_exhausted']+=1;continue
                        candidates.append(row)
                    # Prefer the freshest candidate. No before/until; fixed per-window lower bound.
                    candidates.sort(key=lambda x:x['slot'],reverse=True)
                    if candidates and clock()<until and wall()<w['expires_ns']:
                        row=candidates[0];tick['signature']=row['signature'];d['hydration_attempts']+=1
                        tx,txseq=rpc.transaction(row['signature']);tick['transaction_frame']=txseq
                        if tx is None:d['missing_transactions']+=1
                        else:d['transactions_hydrated']+=1
                        expired=clock()>=until or wall()>=w['expires_ns'];collector=b.collector
                        if expired:b.collector=None
                        old=len(b.health_records)
                        try:decoded=b.ingest(a,txseq,rpc.genesis_seq)
                        finally:b.collector=collector
                        added=list(b.health_records.values())[old:];d['position_observations']+=len(added)
                        for h in added:
                            res=b.results.get(h['plan_id'],{});rejected=res.get('kind')=='reject' or h['health']['evidence']['status']!='PROVEN' or not h['health']['risk'].get('allowed',False)
                            d['observations_rejected' if rejected else 'observations_accepted']+=1
                            if rejected:
                                for reason in set(h['health']['reasons']+[res.get('code','rejected')]):d['rejection_reasons'][reason]=d['rejection_reasons'].get(reason,0)+1
                        if tx is not None and not added:d['unsupported_transactions']+=1
                        tick.update(decoded_events=len(decoded['events']),position_observations=len(added),decoder_states=decoded.get('states',[]))
                        if expired:d['stop_reason']='window_expired_after_raw'
                    a.append('watch_poll',None,tick)
                except (ValueError,OSError) as exc:
                    diagnostic=diagnose(exc,'watch_poll');code=diagnostic['code'];tick['error']=code;a.append('watch_poll',None,tick)
                    if code=='quota_exhausted':d['stop_reason']='rpc_budget';break
                    d['errors'].append(code)
                    if diagnostic['category'] not in ('SOURCE_FAILURE','OPERATIONAL_FAILURE','EVIDENCE_REJECT'):raise
                if target(b) is None:d['stop_reason']='position_closed';break
                rest=min(until-clock(),(w['expires_ns']-wall())/1e9)
                if rest>0:sleep(min(c['poll_seconds'],rest))
        except KeyboardInterrupt:
            d['stop_reason']='operator_interrupted'
            from astra_observer.engine import replay
            replay(a,b.engine);b.recover()
    d['rpc_calls']=a.db.execute('SELECT used FROM rpc_budget').fetchone()[0]-base_used;d['network_attempted']=d['rpc_calls']>0
    d['stage']=stage(d);d['state']=metrics(b,None)['state'];d['elapsed_monotonic_ns']=int((clock()-start)*1e9);d['remaining_budget']=c['budget']-a.db.execute('SELECT used FROM rpc_budget').fetchone()[0];d['position_health_total']=len(b.health_records)
    a.append('watch_diagnostic',None,d);return d
