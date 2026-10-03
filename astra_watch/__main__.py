import argparse,json,os,sys
from urllib.parse import urlsplit
from pathlib import Path
from astra_observer.spine import Archive,require
from astra_bridge.__main__ import writer_lock
from astra_bridge.diagnostics import diagnose
from astra_position.resume import prepare
from astra_position.runtime import PositionBridge
from .report import build
from .runtime import activate,WatchBridge
from .session import begin,monitor,cursor

def endpoint_label(endpoint):
    try:host=urlsplit(endpoint or '').hostname
    except ValueError:return 'INVALID_OR_REDACTED'
    return host if host in ('mainnet.helius-rpc.com','api.mainnet-beta.solana.com') else 'CUSTOM_HOST_REDACTED'

def execute(source,directory,live=False,window_id=None,seconds=120,budget=80,max_polls=30,poll_seconds=2):
    folder=Path(directory)
    if not folder.exists():prepare(source,folder)
    a=b=None;r={};d={'position_loaded':False,'pool':None,'mint':None,'cursor_slot':None,'network_attempted':False,'signatures_found':0,'transactions_hydrated':0,'position_observations':0,'latest_slot_seen':None,'stop_reason':'setup_not_completed','stage':'NO_NETWORK_CALL','endpoint_env':'ASTRA_OBSERVER_RPC_URL'}
    with writer_lock(folder):
        try:
            a=Archive(folder/'raw.sqlite','mainnet')
            has_watch=a.db.execute("SELECT 1 FROM frames WHERE json_extract(document,'$.kind')='watch_activation'").fetchone()
            if not has_watch:
                prior=PositionBridge(a,folder/'state')
                try:prior.recover();prior.verify_replay()
                finally:prior.close()
                activate(a)
            b=WatchBridge(a,folder/'state');b.recover()
            c=cursor(b)
            d.update(position_loaded=c is not None,pool=c['pool'] if c else None,mint=c['mint'] if c else None,cursor_slot=c['cursor_slot'] if c else None,cursor_signature=c['cursor_signature'] if c else None,stop_reason='offline_only')
            r={'status':'PASS','code':'watch_offline_resume','position_loaded':c is not None,'cursor':c,'network_attempted':False}
            if live:
                endpoint=os.environ.get('ASTRA_OBSERVER_RPC_URL')
                d.update(endpoint_configured=bool(endpoint),rpc_host_label=endpoint_label(endpoint),expected_network='mainnet')
                if not endpoint or os.environ.get('ASTRA_OBSERVER_NETWORK')!='mainnet':
                    d['stop_reason']='mainnet_configuration_missing'
                    r.update(status='NOT_EXECUTED',code='watch_mainnet_configuration_missing',stage='NO_NETWORK_CALL',endpoint_env='ASTRA_OBSERVER_RPC_URL',endpoint_configured=bool(endpoint),network_matches=os.environ.get('ASTRA_OBSERVER_NETWORK')=='mainnet')
                elif c is None:r.update(status='NOT_EXECUTED',code='watch_position_closed',stage='NO_NETWORK_CALL')
                else:
                    w=begin(b,window_id,seconds,budget,max_polls,poll_seconds);monitor(b,w,endpoint,os.environ.get('JUPITER_API_KEY'),diagnostic=d)
                    r={'status':'FAIL' if d['errors'] else 'PASS' if d['stage']=='NEW_POSITION_OBSERVATION' else 'NOT_EXECUTED','code':d['stage'],'diagnostic':d}
            r['replay']=b.verify_replay();r['portfolio']=b.paper.state()
        except Exception as exc:
            d['stop_reason']='exception';r={'status':'FAIL',**diagnose(exc,'watch_session')}
        finally:
            if b:b.close()
            if a:a.close()
        try:(folder/'watch-review.json').write_text(json.dumps(build(folder),indent=2),encoding='utf-8')
        except Exception as exc:r.update(status='FAIL',report_error=diagnose(exc,'watch_report'))
        r['diagnostic']=d
        (folder/'watch-report.json').write_text(json.dumps(r,indent=2),encoding='utf-8')
    return r

def main():
    p=argparse.ArgumentParser();p.add_argument('--source',default='position_reference/all-validation-jyqge_an/context-proofs');p.add_argument('--directory',default='position-continuation');p.add_argument('--live',action='store_true');p.add_argument('--window-id');p.add_argument('--seconds',type=int,default=120);p.add_argument('--budget',type=int,default=80);p.add_argument('--max-polls',type=int,default=30);p.add_argument('--poll-seconds',type=int,default=2);a=p.parse_args();r=execute(a.source,a.directory,a.live,a.window_id,a.seconds,a.budget,a.max_polls,a.poll_seconds)
    print(r['status']+' | '+r['code'])
    print(json.dumps(r.get('diagnostic',{k:r[k] for k in ('position_loaded','cursor','network_attempted','stage','endpoint_env','endpoint_configured','network_matches') if k in r}),ensure_ascii=True))
    return 0 if r['status']=='PASS' else 1
if __name__=='__main__':sys.exit(main())
