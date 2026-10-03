import json,os,subprocess,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parent

def invoke(folder,*args,offline=False):
    env={k:os.environ[k] for k in ('PATH','SystemRoot','WINDIR','TEMP','TMP','TMPDIR','SSL_CERT_FILE','SSL_CERT_DIR') if k in os.environ}
    if not offline and os.environ.get('SOLANA_RPC_URL'):env['SOLANA_RPC_URL']=os.environ['SOLANA_RPC_URL']
    script="from block_validation.run import network_off;network_off();from astra_pipeline.__main__ import main;import sys;sys.exit(main())" if offline else "from astra_pipeline.__main__ import main;import sys;sys.exit(main())"
    try:
        p=subprocess.run([sys.executable,'-B','-c',script,*args],cwd=ROOT,env=env,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=180)
        r=json.loads(p.stdout.decode('utf-8'));return p.returncode,r
    except subprocess.TimeoutExpired:return 124,{'status':'FAIL','code':'process_timeout'}
    except Exception:return 1,{'status':'FAIL','code':'pipeline_report_unreadable'}

def validate(self_test=False):
    if self_test or not os.environ.get('SOLANA_RPC_URL'):return {'overall':'FAIL','checks':[{'id':'integrated_live_pipeline','status':'FAIL','code':'live_endpoint_not_used'}]}
    checks=[]
    with tempfile.TemporaryDirectory(prefix='astra-integrated-live-') as tmp:
        folder=Path(tmp);work=folder/'work'
        rc,first=invoke(folder,'run','--workdir',str(work),'--slots','12','--max-slots','3','--request-limit','100')
        good=rc==1 and first.get('code')=='range_incomplete_or_decoder_error' and first.get('blocks',{}).get('coverage',{}).get('attempted_slots')==3
        checks.append({'id':'interruption_checkpoint','status':'PASS' if good else 'FAIL','code':'' if good else first.get('code','unexpected_midrange'),'evidence':first,'exception_type':first.get('exception_type'),'location':first.get('location')})
        if good:
            rc,result=invoke(folder,'run','--workdir',str(work),'--request-limit','100')
            checks.append({'id':'integrated_resume','status':'PASS' if rc==0 and result.get('status')=='PASS' else 'FAIL','code':result.get('code',''),'evidence':result,'exception_type':result.get('exception_type'),'location':result.get('location')})
            if rc==0:
                business=result['business'];ident=business['dataset_id'];dataset=work/'business/datasets'/(ident+'.json')
                rc,replay=invoke(folder,'replay','--dataset',str(dataset),'--output',str(folder/'rebuilt'),offline=True)
                equal=rc==0 and dataset.read_bytes()==(folder/'rebuilt'/(ident+'.json')).read_bytes()
                checks.append({'id':'offline_business_reconstruction','status':'PASS' if equal else 'FAIL','code':'' if equal else 'business_replay_failed'})
                kinds=business['metrics']['event_kinds'];new=sum(v for k,v in kinds.items() if k in ('spl_transfer_checked','token_balance_change'))
                checks.append({'id':'real_token_business_data','status':'PASS' if new else 'FAIL','code':'' if new else 'no_real_token_event_observed','event_kinds':kinds})
                first_slot=result['blocks']['slots'][0]['slot']
                rc,coordinator=invoke(folder,'poll','--directory',str(folder/'poll'),'--range-size','2','--max-batches','1','--start',str(first_slot),'--request-limit','10')
                ok=rc==0 and coordinator.get('next_slot')==first_slot+2
                checks.append({'id':'real_range_coordinator','status':'PASS' if ok else 'FAIL','code':'' if ok else coordinator.get('code','coordinator_failed'),'evidence':coordinator,'exception_type':coordinator.get('exception_type'),'location':coordinator.get('location')})
    return {'overall':'PASS' if checks and all(x['status']=='PASS' for x in checks) else 'FAIL','checks':checks}
if __name__=='__main__':
    r=validate('--self-test' in sys.argv);Path(sys.argv[1]).write_text(json.dumps(r,indent=2),encoding='utf-8');sys.exit(0 if r['overall']=='PASS' else 1)
