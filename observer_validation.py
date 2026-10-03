"""Real qualification is separate from deterministic tests; no synthetic fallback."""
import json,os,sys,tempfile
from pathlib import Path
from astra_observer.spine import Archive
from astra_observer.engine import Engine
from astra_observer.source import search,stream

def main(path):
    target=Path(path);proofs=target.parent/'observer-proofs';proofs.mkdir(exist_ok=True);checks=[]
    network=os.environ.get('ASTRA_OBSERVER_NETWORK');endpoint=os.environ.get('ASTRA_OBSERVER_RPC_URL');ws=os.environ.get('ASTRA_OBSERVER_WS_URL')
    if '--self-test' in sys.argv:network=None;endpoint=None;ws=None
    for ident in ('real_pumpswap_events','real_websocket_spine'):
        if not endpoint or network!='mainnet':checks.append({'id':ident,'status':'NOT_EXECUTED','code':'observer_mainnet_configuration_missing'});continue
        if ident=='real_websocket_spine' and not ws:checks.append({'id':ident,'status':'NOT_EXECUTED','code':'observer_ws_endpoint_missing'});continue
        a=e=None
        try:
            folder=proofs/ident;folder.mkdir(exist_ok=True);a=Archive(folder/'raw.sqlite','mainnet');e=Engine(folder/'engine.sqlite','mainnet')
            result=search(a,e,endpoint,seconds=60) if ident=='real_pumpswap_events' else stream(a,e,endpoint,ws,seconds=20,max_messages=4,limit=10)
            result.update(id=ident,archive=a.audit(),reconstruction=e.verify_reconstruction(a));checks.append(result)
        except Exception as exc:
            safe={'genesis_mismatch','quota_exhausted','rpc_transport_failure','rpc_error','websocket_client_not_installed','credential_echo_rejected'}
            checks.append({'id':ident,'status':'FAIL','code':str(exc) if str(exc) in safe else 'observer_phase_exception','exception_type':type(exc).__name__})
        finally:
            if e:e.close()
            if a:a.close()
    report={'overall':'PASS' if all(c['status']=='PASS' for c in checks) else 'FAIL','checks':checks,'proofs':str(proofs.name)}
    target.write_text(json.dumps(report,indent=2,ensure_ascii=True),encoding='utf-8');return 0 if report['overall']=='PASS' else 1
if __name__=='__main__':sys.exit(main(sys.argv[1]))
