"""All tests use disposable databases; reports never contain endpoints/payloads."""
import argparse,contextlib,hashlib,io,json,os,shutil,socket,subprocess,sys,tempfile,time,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from astra_blocks.store import BlockStore
from astra_blocks.rpc import Rpc,tip_from_context

def save(p,obj):Path(p).write_text(json.dumps(obj,indent=2,ensure_ascii=True),encoding='utf-8')
def require(value,code):
    if not value:raise AssertionError(code)
def network_off():
    def denied(*a,**kw):raise RuntimeError('offline_network_access')
    socket.socket.connect=denied;socket.socket.connect_ex=denied;socket.create_connection=denied

def worker(phase,folder):
    folder=Path(folder);s=None
    try:
        if phase=='unit':
            network_off()
            class Results(unittest.TestResult):
                def __init__(self):super().__init__();self.rows=[]
                def addSuccess(self,t):super().addSuccess(t);self.rows.append({'test':t.id(),'status':'PASS'})
                def addFailure(self,t,e):super().addFailure(t,e);self.rows.append({'test':t.id(),'status':'FAIL'})
                def addError(self,t,e):
                    super().addError(t,e)
                    tb=e[2];frames=[]
                    while tb:
                        frames.append({'file':Path(tb.tb_frame.f_code.co_filename).name,'function':tb.tb_frame.f_code.co_name,'line':tb.tb_lineno});tb=tb.tb_next
                    self.rows.append({'test':t.id(),'status':'FAIL','exception_type':e[0].__name__,'winerror':getattr(e[1],'winerror',None),'frames':frames})
            suite=unittest.defaultTestLoader.discover(str(ROOT/'block_tests'));r=Results()
            with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):suite.run(r)
            save(folder/'unit.json',{'status':'PASS' if r.wasSuccessful() and r.testsRun else 'FAIL','tests':r.rows,'count':r.testsRun})
            return
        if phase=='deterministic':
            network_off()
            from block_tests.test_blocks import Fixture
            path=folder/'deterministic.sqlite'
            s=BlockStore(path,100,105);middle=s.collect(Fixture(),max_slots=3)
            s.close();s=BlockStore(path)
            initial=s.collect(Fixture());final=s.collect(Fixture(True),retry=True)
            require(initial['counts']=={'archived':3,'skipped':1,'unavailable':1,'error':1},'initial_counts')
            require(final['healthy'] and final['publications']==5 and final['unresolved']==0,'retry_counts')
            save(folder/'deterministic.json',{'status':'PASS','evidence':{'middle':middle,'before_retry':initial,'after_retry':final}})
            return
        path=folder/'blocks.sqlite'
        if phase=='first':
            rpc=Rpc();tip=tip_from_context(rpc.context());end=tip-8;start=end-5
            s=BlockStore(path,start,end);data=s.collect(rpc,max_slots=3)
            require(data['next_slot']==start+3,'checkpoint_not_midrange')
            save(folder/'first_publications.json',[[r['slot'],r['document_hash'],r['published_at']] for r in s.db.execute('SELECT * FROM publications ORDER BY slot')])
        elif phase in ('resume','retry'):
            s=BlockStore(path)
            if phase=='retry':
                rounds=[]
                for number in range(1,4):
                    before=s.audit()['coverage']['attempts']
                    data=s.collect(Rpc(),retry=True,retry_round=number)
                    rounds.append({'round':number,'attempts_added':data['coverage']['attempts']-before,'remaining_errors':data['counts']['error'],'remaining_unresolved':data['unresolved']})
                    if not data['unresolved'] or data['coverage']['attempts']==before: break
                data['retry_rounds']=rounds
            else:
                data=s.collect(Rpc())
            require(data['first_pass_complete'],'range_incomplete')
            previous=json.loads((folder/'first_publications.json').read_text())
            for slot,h,at in previous:
                p=s.db.execute('SELECT * FROM publications WHERE slot=?',(slot,)).fetchone()
                require(p and p['document_hash']==h and p['published_at']==at,'published_block_changed')
        elif phase=='offline_replay':
            network_off();s=BlockStore(path)
            before=[tuple(r) for r in s.db.execute('SELECT * FROM publications ORDER BY slot')]
            s.recover();s.recover();data=s.audit()
            require(before==[tuple(r) for r in s.db.execute('SELECT * FROM publications ORDER BY slot')],'recover_changed_publications')
            replays=[]
            for ident, in s.db.execute('SELECT id FROM attempts ORDER BY id'):
                r=s.replay(ident);replays.append({'attempt_id':ident,'status':r['status'],'document_hash':r['document_hash']})
            data['replays']=replays
            require(data['first_pass_complete'],'range_incomplete')
        else:raise ValueError('unknown_phase')
        require(data['healthy'] and data['accounting_ok'],'integrity_or_accounting_failure')
        passed=data['publications']>0 and (phase in ('first','resume') or data['counts']['error']==0)
        result={'status':'PASS' if passed else 'FAIL','can_continue':True,'evidence':data}
        if not passed:result['code']='no_real_block_archived' if data['publications']==0 else 'unresolved_rpc_errors'
        save(folder/(phase+'.json'),result)
    except Exception as exc:
        safe={'checkpoint_not_midrange','range_incomplete','published_block_changed',
              'recover_changed_publications','no_real_block_archived','integrity_or_accounting_failure',
              'devnet_identity_not_verified','finalized_tip_unavailable','https_endpoint_required',
              'range_not_finalized','hash_mismatch','finalized_block_conflict','finalized_parent_hash_conflict',
              'finalized_chain_conflict','integrity_check_failed_before_collection'}
        code=str(exc) if str(exc) in safe else 'phase_failed_details_suppressed'
        save(folder/(phase+'.json'),{'status':'FAIL','code':code})
    finally:
        if s:s.close()

def main():
    p=argparse.ArgumentParser();p.add_argument('--worker');p.add_argument('--folder');p.add_argument('--self-test',action='store_true')
    a=p.parse_args()
    if a.worker:worker(a.worker,a.folder);return 0
    reports=Path(tempfile.mkdtemp(prefix='blocks-report-',dir=ROOT/'block_validation'))
    baseline=json.loads((ROOT/'V1B_REFERENCE.json').read_text())
    changed=[n for n,h in baseline.items() if not (ROOT/n).is_file() or hashlib.sha256((ROOT/n).read_bytes()).hexdigest()!=h]
    checks=[{'id':'v1b_reference_unchanged','status':'FAIL' if changed else 'PASS','changed_files':changed}]
    with tempfile.TemporaryDirectory(prefix='astra-blocks-validation-') as folder:
        for phase in ('unit','deterministic','first','resume','retry','offline_replay'):
            if phase not in ('unit','deterministic') and (a.self_test or not os.environ.get('SOLANA_RPC_URL')):
                checks.append({'id':phase,'status':'FAIL','code':'live_endpoint_not_used'});continue
            if phase not in ('unit','deterministic','first') and checks[-1]['status']!='PASS' and not checks[-1].get('can_continue',False):
                checks.append({'id':phase,'status':'FAIL','code':'previous_phase_failed'});continue
            allowed=('PATH','SystemRoot','WINDIR','TEMP','TMP','TMPDIR','LANG','SSL_CERT_FILE','SSL_CERT_DIR')
            env={k:os.environ[k] for k in allowed if k in os.environ};env['PYTHONDONTWRITEBYTECODE']='1'
            if phase not in ('unit','deterministic','offline_replay'):env['SOLANA_RPC_URL']=os.environ['SOLANA_RPC_URL']
            start=time.monotonic()
            try:
                rc=subprocess.run([sys.executable,'-B',str(Path(__file__).resolve()),'--worker',phase,'--folder',folder],
                    cwd=ROOT,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=90).returncode
                path=Path(folder)/(phase+'.json')
                result=json.loads(path.read_text()) if rc==0 and path.exists() else {'status':'FAIL','code':'worker_failed'}
            except subprocess.TimeoutExpired:result={'status':'FAIL','code':'worker_deadline_exceeded'}
            result.update(id=phase,seconds=round(time.monotonic()-start,3));checks.append(result)
            print(result['status']+' | '+phase,flush=True)
    overall='PASS' if all(x['status']=='PASS' for x in checks) else 'FAIL'
    report={'overall':overall,'scope':'V1c blocks; V1b gate runs separately via unchanged validate-windows.cmd','checks':checks}
    save(reports/'report.json',report)
    (reports/'report.txt').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print('Rapports blocs: '+str(reports));return 0 if overall=='PASS' else 1
if __name__=='__main__':sys.exit(main())
