import argparse,json,os,sys
from pathlib import Path
from .spine import Archive
from .engine import Engine,replay
from .source import search,stream

def main():
    p=argparse.ArgumentParser();p.add_argument('command',choices=('search','stream','replay'));p.add_argument('--network',choices=('devnet','mainnet'),required=True);p.add_argument('--directory',required=True);p.add_argument('--source');p.add_argument('--seconds',type=int,default=30);a=p.parse_args();folder=Path(a.directory);folder.mkdir(parents=True,exist_ok=True);arc=None;engine=None
    try:
        arc=Archive(a.source if a.command=='replay' else folder/'raw.sqlite',a.network);arc.audit();engine=Engine(folder/'observer.sqlite',a.network)
        if a.command=='replay':r={'status':'PASS','result':replay(arc,engine)}
        else:
            replay(arc,engine)  # startup recovery only; never a per-event history scan
            endpoint=os.environ.get('ASTRA_OBSERVER_RPC_URL',os.environ.get('SOLANA_RPC_URL',''))
            if not endpoint:r={'status':'NOT_EXECUTED','code':'observer_endpoint_missing'}
            elif a.command=='search':r=search(arc,engine,endpoint,seconds=a.seconds)
            else:
                ws=os.environ.get('ASTRA_OBSERVER_WS_URL','')
                r=stream(arc,engine,endpoint,ws,seconds=a.seconds) if ws else {'status':'NOT_EXECUTED','code':'observer_ws_endpoint_missing'}
        r['archive']=arc.audit();r['engine']=engine.verify();r['reconstruction']=engine.verify_reconstruction(arc);r['latencies']=engine.latencies()
    except Exception as exc:
        codes={'genesis_mismatch','read_only_method_refused','quota_exhausted','immutable_budget','immutable_engine_configuration','network_mismatch','websocket_client_not_installed','credential_echo_rejected','rpc_transport_failure','rpc_error'}
        r={'status':'FAIL','code':str(exc) if str(exc) in codes else 'observer_exception','exception_type':type(exc).__name__}
    finally:
        if engine:engine.close()
        if arc:arc.close()
    (folder/'observer-report.json').write_text(json.dumps(r,indent=2,ensure_ascii=True),encoding='utf-8');print(json.dumps(r,ensure_ascii=True));return 0 if r['status']=='PASS' else 1
if __name__=='__main__':sys.exit(main())
