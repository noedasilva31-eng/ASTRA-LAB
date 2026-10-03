"""Paper-only Brain session CLI; mainnet credentials are read from environment."""
import argparse,json,os,sys
from pathlib import Path
from astra_bridge.__main__ import writer_lock
from astra_bridge.runtime import Collector
from astra_bridge.diagnostics import diagnose
from astra_observer.spine import Archive
from astra_observer.engine import replay
from astra_multicycle.session import run
from astra_bridge.session import metrics
from astra_measure.report import generate,write_report
from .runtime import BrainBridge
from .dataset import build,freeze

def execute(folder,seconds=180,max_cycles=3,offline=False):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True);a=b=None;result={'status':'NOT_EXECUTED','code':'brain_mainnet_configuration_missing'}
    try:
        with writer_lock(folder):
            try:
                a=Archive(folder/'raw.sqlite','mainnet');b=BrainBridge(a,folder/'state');b.recover();replay(a,b.engine);b.recover()
                endpoint=os.environ.get('ASTRA_OBSERVER_RPC_URL');ws=os.environ.get('ASTRA_OBSERVER_WS_URL')
                if offline:result={'status':'PASS','code':'brain_offline_reconstruction'}
                elif endpoint and ws and os.environ.get('ASTRA_OBSERVER_NETWORK')=='mainnet':
                    b.collector=Collector(a,endpoint,os.environ.get('JUPITER_API_KEY'));session=run(a,b,endpoint,ws,seconds,max_cycles)
                    observed=len(b.brain_records)
                    result={'status':'PASS' if observed else 'NOT_EXECUTED','code':'real_brain_observations_audited' if observed else 'no_brain_opportunity_observed','session':session,'evaluated_opportunities':observed,'roundtrip_qualification':'OBSERVED' if session['closed_cycles'] else 'NOT_EXECUTED','assurance':'OBSERVATION_AND_CONDITIONAL_PAPER_NO_REAL_ORDERS'}
                result.update(reconstruction=b.verify_replay(),archive=a.audit())
            except Exception as exc:result={'status':'FAIL',**diagnose(exc,'brain_session')}
            finally:
                if b:
                    try:result['portfolio']=b.paper.state();result.setdefault('session',metrics(b,None))
                    finally:b.close()
                if a:a.close()
            # Keep exclusive writer lock through snapshot + freeze.
            write_report(folder,generate(folder));dataset=build(folder)
            (folder/'session-dataset.json').write_text(json.dumps(dataset,indent=2),encoding='utf-8')
            result['freeze']=freeze(folder,folder/'freezes')
    except Exception as exc:
        result={'status':'FAIL',**diagnose(exc,'brain_report_or_freeze')}
    (folder/'brain-report.json').write_text(json.dumps(result,indent=2),encoding='utf-8');return result

def main():
    p=argparse.ArgumentParser();p.add_argument('--directory',required=True);p.add_argument('--seconds',type=int,default=180);p.add_argument('--max-cycles',type=int,default=3);p.add_argument('--offline',action='store_true');a=p.parse_args()
    r=execute(a.directory,a.seconds,a.max_cycles,a.offline);print(r['status']+' | '+r['code']);return 0 if r['status']=='PASS' else 1
if __name__=='__main__':sys.exit(main())
