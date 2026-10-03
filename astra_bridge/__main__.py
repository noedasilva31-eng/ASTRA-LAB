"""Mainnet observation -> conditional paper. Endpoints only from environment."""
import argparse,json,os,sys
from pathlib import Path
from contextlib import contextmanager
from astra_observer.spine import Archive,require
from astra_observer.engine import replay
from astra_observer.source import stream,search,transport_latencies
from .runtime import Bridge,Collector,reason
from .diagnostics import diagnose
from .session import run_session,metrics

@contextmanager
def writer_lock(folder):
    f=open(Path(folder)/'session.lock','a+b');f.seek(0);f.write(b'0');f.flush();f.seek(0)
    try:
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(f.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:raise ValueError('session_writer_already_running') from None
        yield
    finally:f.close()

def run(folder,command='stream',seconds=30):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True);a=b=None
    with writer_lock(folder):
        stage='startup'
        try:
            a=Archive(folder/'raw.sqlite','mainnet');b=Bridge(a,folder/'state');b.recover();replay(a,b.engine);b.recover()
            if command=='audit':result={'status':'PASS','code':'offline_reconstruction'}
            elif command in ('kill','unkill'):b.set_kill(command=='kill');result={'status':'PASS','code':'operator_control_archived'}
            else:
                endpoint=os.environ.get('ASTRA_OBSERVER_RPC_URL');ws=os.environ.get('ASTRA_OBSERVER_WS_URL')
                if not endpoint or os.environ.get('ASTRA_OBSERVER_NETWORK')!='mainnet':result={'status':'NOT_EXECUTED','code':'observer_mainnet_configuration_missing'}
                elif command in ('stream','session') and not ws:result={'status':'NOT_EXECUTED','code':'observer_ws_endpoint_missing'}
                else:
                    b.collector=Collector(a,endpoint,os.environ.get('JUPITER_API_KEY'))
                    stage='stream_and_evidence'
                    result=run_session(a,b,endpoint,ws,seconds) if command=='session' else stream(a,b,endpoint,ws,seconds=seconds,max_messages=64,limit=200) if command=='stream' else search(a,b,endpoint,limit=200,max_signatures=20,seconds=seconds)
            stage='offline_reconstruction'
            result.update(reconstruction=b.verify_replay(),archive=a.audit(),state=b.export(),transport_latencies=transport_latencies(a))
        except Exception as exc:
            detail=diagnose(exc,stage);result={'status':'FAIL',**detail,'diagnostic':detail}
            if b:
                try:result['state']=b.export();result['session']=metrics(b,None)
                except Exception as export_error:result['state_export_error']=diagnose(export_error,'failure_state_export')
        finally:
            if b:b.close()
            if a:a.close()
    (folder/'bridge-report.json').write_text(json.dumps(result,indent=2,ensure_ascii=True),encoding='utf-8')
    return result

def main():
    p=argparse.ArgumentParser();p.add_argument('command',choices=('session','stream','search','audit','kill','unkill'));p.add_argument('--directory',required=True);p.add_argument('--seconds',type=int,default=30);args=p.parse_args()
    r=run(args.directory,args.command,args.seconds);print(r['status']+' | '+r.get('code',''));return 0 if r['status']=='PASS' else 1
if __name__=='__main__':sys.exit(main())
