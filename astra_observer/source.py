"""Bounded logs subscription + HTTP hydration. No completeness claim on reconnect."""
import json,os,time,urllib.parse
from .spine import ReadOnlyRpc,require,strict
from astra_dex.pumpswap import PROGRAM

def safe_frame(raw,endpoint):
    p=urllib.parse.urlsplit(endpoint);parts=[endpoint,p.username,p.password]+[v for _,v in urllib.parse.parse_qsl(p.query)]+[v for v in p.path.split('/') if len(v)>=12]
    text=raw.decode('utf-8');obj=strict(raw);decoded=json.dumps(obj,ensure_ascii=False)
    require(not any(s and len(s)>=4 and (s in text or s in decoded or urllib.parse.quote(s,safe='') in text) for s in parts),'credential_echo_rejected');return obj

def stream(archive,engine,http_endpoint,ws_endpoint,seconds=30,max_messages=20,limit=40,connect=None):
    require(type(seconds)==int and 1<=seconds<=300 and type(max_messages)==int and 1<=max_messages<=1000,'invalid_stream_bounds')
    require(urllib.parse.urlsplit(ws_endpoint).scheme=='wss','wss_required')
    rpc=ReadOnlyRpc(archive,http_endpoint,limit=limit);g=rpc.identity();archive.append('feed_control',None,{'status':'PARTIAL','reason':'subscription_started_no_backfill'})
    if connect is None:
        try:from websocket import create_connection
        except ImportError:raise ValueError('websocket_client_not_installed')
        connect=create_connection
    ws=connect(ws_endpoint,timeout=5);deadline=time.monotonic()+seconds;messages=0;decoded=0;subscription=None
    try:
        ws.send(json.dumps({'jsonrpc':'2.0','id':1,'method':'logsSubscribe','params':[{'mentions':[PROGRAM]},{'commitment':'confirmed'}]}))
        while time.monotonic()<deadline and messages<max_messages:
            ws.settimeout(min(5,max(.001,deadline-time.monotonic())))
            raw=ws.recv();received_mono=time.perf_counter_ns();raw=raw.encode() if isinstance(raw,str) else raw
            require(len(raw)<=2*1024*1024,'notification_too_large');obj=safe_frame(raw,ws_endpoint)
            archive.append('notification',raw,{'coverage':'PARTIAL'})
            if obj.get('id')==1:
                require(type(obj.get('result'))==int,'subscription_rejected');subscription=obj['result'];continue
            require(subscription is not None and obj.get('method')=='logsNotification' and obj['params']['subscription']==subscription,'invalid_notification')
            messages+=1;signature=obj['params']['result']['value']['signature']
            value,seq=rpc.transaction(signature)
            result=engine.ingest(archive,seq,g);decoded+=len(result['events'])
            archive.append('latency',None,{'signature':signature,'notification_to_processing_ns':time.perf_counter_ns()-received_mono,'decoded_events':len(result['events']),'clock':'host_monotonic','provider_emission_time_known':False})
            # Null hydration is archived unresolved. A later bounded search/replay may recover it.
    finally:
        ws.close();archive.append('feed_control',None,{'status':'PARTIAL','reason':'subscription_stopped_reconciliation_required'})
    return {'status':'PASS' if decoded else 'FAIL','code':'real_events_decoded' if decoded else 'no_supported_event_observed','notifications':messages,'events':decoded,'coverage':'PARTIAL','latencies':engine.latencies(),'transport_latencies':transport_latencies(archive)}

def search(archive,engine,endpoint,limit=24,max_signatures=20,seconds=90):
    require(type(max_signatures)==int and 1<=max_signatures<=100 and type(seconds)==int and 1<=seconds<=300,'invalid_search_bounds')
    rpc=ReadOnlyRpc(archive,endpoint,limit=limit);g=rpc.identity();deadline=time.monotonic()+seconds
    rows,_=rpc.call('getSignaturesForAddress',[PROGRAM,{'limit':max_signatures,'commitment':'confirmed'}]);events=0;states=[]
    for row in rows:
        if time.monotonic()>deadline:break
        if row['err'] is not None:continue
        _,seq=rpc.transaction(row['signature']);r=engine.ingest(archive,seq,g);events+=len(r['events']);states.extend(r['states'])
        if events:break
    return {'status':'PASS' if events else 'FAIL','code':'real_events_decoded' if events else 'bounded_search_no_supported_event','events':events,'states':states,'coverage':'PARTIAL','latencies':engine.latencies(),'transport_latencies':transport_latencies(archive)}


def transport_latencies(archive):
    samples={'http_roundtrip_ns':[],'notification_to_processing_ns':[]}
    for doc, in archive.db.execute('SELECT document FROM frames ORDER BY seq'):
        f=json.loads(doc);m=f['metadata']
        if f['kind']=='rpc' and type(m.get('transport_ns'))==int:samples['http_roundtrip_ns'].append(m['transport_ns'])
        if f['kind']=='latency':samples['notification_to_processing_ns'].append(m['notification_to_processing_ns'])
    out={}
    for key,values in samples.items():
        values.sort();n=len(values);out[key]={'samples':n,'p95':values[(95*n+99)//100-1] if n else None,'p99':values[(99*n+99)//100-1] if n else None}
    out['provider_emission_latency']='NOT_MEASURED';return out
