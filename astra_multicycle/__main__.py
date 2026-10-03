"""Dedicated persistent session. Only Mainnet read-only and conditional paper."""
import argparse,json,os,sys
from pathlib import Path
from astra_bridge.__main__ import writer_lock
from astra_bridge.runtime import Bridge,Collector
from astra_bridge.diagnostics import diagnose
from astra_observer.spine import Archive
from astra_observer.engine import replay
from astra_measure.report import generate,write_report
from .session import run,census

def execute(folder,seconds=120,max_cycles=3,offline=False):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True);a=b=None
    result={'status':'NOT_EXECUTED','code':'multicycle_configuration_missing'}
    try:
        with writer_lock(folder):
            try:
                a=Archive(folder/'raw.sqlite','mainnet');b=Bridge(a,folder/'state');b.recover();replay(a,b.engine);b.recover();census(a,b)
                endpoint=os.environ.get('ASTRA_OBSERVER_RPC_URL');ws=os.environ.get('ASTRA_OBSERVER_WS_URL')
                if offline:result={'status':'PASS','code':'offline_reconstruction'}
                elif endpoint and ws and os.environ.get('ASTRA_OBSERVER_NETWORK')=='mainnet':
                    b.collector=Collector(a,endpoint,os.environ.get('JUPITER_API_KEY'))
                    m=run(a,b,endpoint,ws,seconds,max_cycles)
                    qualified=m['closed_cycles']>=2
                    result={'status':'PASS' if qualified else 'NOT_EXECUTED','code':'multiple_real_conditional_cycles' if qualified else 'multiple_real_cycles_not_qualified','session':m}
                result.update(reconstruction=b.verify_replay(),archive=a.audit())
            except Exception as exc:
                result={'status':'FAIL',**diagnose(exc,'multi_opportunity_session')}
            finally:
                if b:
                    try:result['portfolio']=b.paper.state()
                    finally:b.close()
                if a:a.close()
            # Still hold writer lock for coherent cross-database reporting.
            report=generate(folder);write_report(folder,report)
    except Exception as exc:result={'status':'FAIL',**diagnose(exc,'multi_session_or_measurement')}
    (folder/'session-report.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    return result

def main():
    p=argparse.ArgumentParser();p.add_argument('--directory',required=True);p.add_argument('--seconds',type=int,default=120);p.add_argument('--max-cycles',type=int,default=3);p.add_argument('--offline',action='store_true');a=p.parse_args()
    r=execute(a.directory,a.seconds,a.max_cycles,a.offline);print(r['status']+' | '+r['code']);return 0 if r['status']=='PASS' else 1
if __name__=='__main__':sys.exit(main())
