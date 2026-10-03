import argparse,json,os,sys
from pathlib import Path
from astra_bridge.__main__ import writer_lock
from astra_bridge.diagnostics import diagnose
from astra_observer.spine import Archive
from .resume import prepare
from .runtime import PositionBridge
from .session import run,records
from .report import build

def qualification(new_health,session,errors):
    errors=[x for x in errors if x!='quota_exhausted']
    if errors:return {'status':'FAIL','code':'position_source_error','source_error_codes':sorted(set(errors)),'session':session}
    if not new_health:return {'status':'NOT_EXECUTED','code':'no_new_position_observation','session':session}
    return {'status':'PASS','code':'position_bounded_observation','new_position_health':new_health,'session':session}

def execute(source,folder,offline=True):
    folder=Path(folder);prepare(source,folder);a=b=None;r={}
    with writer_lock(folder):
        try:
            a=Archive(folder/'raw.sqlite','mainnet');b=PositionBridge(a,folder/'state');b.recover()
            if offline:r={'status':'PASS','code':'position_resume_offline','network_used':False}
            elif os.environ.get('ASTRA_OBSERVER_NETWORK')=='mainnet' and os.environ.get('ASTRA_OBSERVER_RPC_URL'):
                before=len(b.health_records);old_polls=len(records(a,'position_poll'))
                session=run(b,os.environ['ASTRA_OBSERVER_RPC_URL'],os.environ.get('JUPITER_API_KEY'))
                errors=[x['error'] for x in records(a,'position_poll')[old_polls:] if x.get('error')]
                r=qualification(len(b.health_records)-before,session,errors)
            else:r={'status':'NOT_EXECUTED','code':'position_mainnet_configuration_missing'}
            r['replay']=b.verify_replay();r['portfolio']=b.paper.state()
        except Exception as exc:r={'status':'FAIL',**diagnose(exc,'position_session')}
        finally:
            if b:b.close()
            if a:a.close()
        try:
            report=build(folder);(folder/'position-review.json').write_text(json.dumps(report,indent=2),encoding='utf-8');r['review_hash']=report['dataset_sha256']
        except Exception as exc:r={'status':'FAIL',**diagnose(exc,'position_report')}
        (folder/'position-report.json').write_text(json.dumps(r,indent=2),encoding='utf-8')
    return r

def main():
    p=argparse.ArgumentParser();p.add_argument('--source',required=True);p.add_argument('--directory',required=True);p.add_argument('--live',action='store_true');args=p.parse_args();r=execute(args.source,args.directory,not args.live);print(r['status']+' | '+r['code']);return 0 if r['status']=='PASS' else 1
if __name__=='__main__':sys.exit(main())
