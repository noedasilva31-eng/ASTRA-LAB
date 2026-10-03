"""V1e gate; temporary data only; real prerequisites never simulated."""
import argparse,contextlib,hashlib,io,json,os,subprocess,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from astra_provenance.archive import capture_source,bundle,verify,require
from astra_provenance.store import Journal,reconstruct
from astra_blocks.store import BlockStore
from block_validation.run import network_off
from memory_validation.run import run_phase as blocks_phase

def save(path,value):Path(path).write_text(json.dumps(value,indent=2),encoding='utf-8')
def pipeline(folder,source):
    """Capture then resume publication in a new offline process."""
    folder=Path(folder);network_off();j=Journal(folder/'journal.sqlite')
    try:ident=j.capture(capture_source(source))
    finally:j.close()
    env={k:v for k,v in os.environ.items() if k!='SOLANA_RPC_URL'}
    script="from block_validation.run import network_off;network_off();from astra_provenance.__main__ import main;import sys;sys.exit(main())"
    p=subprocess.run([sys.executable,'-B','-c',script,'recover','--db',str(folder/'journal.sqlite')],env=env,cwd=ROOT,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=90)
    require(p.returncode==0,'offline_resume_failed');j=Journal(folder/'journal.sqlite')
    try:
        before=list(j.db.execute('SELECT * FROM provenance_events'));j.recover();j.publish(j.capture(capture_source(source)))
        require(before==list(j.db.execute('SELECT * FROM provenance_events')),'event_republication')
        export=folder/'dataset.json';j.export(ident,export);reconstruct(export,folder/'rebuilt.json')
        require(export.read_bytes()==(folder/'rebuilt.json').read_bytes(),'rebuild_not_identical')
        audit=j.audit();require(audit['healthy'],'journal_unhealthy')
        return {'status':'PASS','evidence':{'journal':audit,'dataset_sha256':json.loads(export.read_text(encoding='utf-8'))['dataset_sha256'],'offline_reconstruction_identical':True,'resume_new_process':True}}
    finally:j.close()

def worker(phase,folder):
    folder=Path(folder)
    if phase=='unit':
        network_off()
        class Result(unittest.TestResult):
            def __init__(self):super().__init__();self.rows=[]
            def addSuccess(self,t):super().addSuccess(t);self.rows.append({'test':t.id(),'status':'PASS'})
            def addFailure(self,t,e):super().addFailure(t,e);self.rows.append({'test':t.id(),'status':'FAIL','exception_type':e[0].__name__})
            def addError(self,t,e):super().addError(t,e);self.rows.append({'test':t.id(),'status':'FAIL','exception_type':e[0].__name__})
        suite=unittest.defaultTestLoader.discover(str(ROOT/'provenance_tests'));r=Result()
        with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):suite.run(r)
        return {'status':'PASS' if r.wasSuccessful() and r.testsRun else 'FAIL','count':r.testsRun,'tests':r.rows}
    if phase=='deterministic':
        network_off();from provenance_tests.test_provenance import fixture
        source=folder/'blocks.sqlite';fixture(source);r=pipeline(folder,source)
        c=r['evidence']['journal']['coverage_versions'][0]
        require(c['counts']==dict(archived=3,skipped=1,unresolved=1,error=1,excluded=0) and not c['source_complete'],'false_complete')
        from block_tests.test_blocks import context,block
        from memory_tests.test_memory import tx,b58
        from astra_blocks.rpc import canonical
        s=BlockStore(source)
        try:
            sid=s.session(context())
            for slot,parent in ((103,102),(104,103)):
                obj=json.loads(block(slot,parent));t=tx(amount=slot);t['transaction']['signatures']=[b58(bytes([slot])*64)];obj['result']['transactions']=[t]
                s.apply(s.capture(slot,sid,canonical(obj).encode()))
        finally:s.close()
        j=Journal(folder/'journal.sqlite')
        try:
            ident=j.capture(capture_source(source));v=j.publish(ident);j.recover()
            after=j.audit();require(after['datasets']==2 and after['unique_event_publications']==5,'retry_republication')
            coverage=v['payload']['derived']['coverage'];require(coverage['source_complete'] and coverage['historical_error_attempts']==1,'lost_error_history')
            j.export(ident,folder/'retry-dataset.json');reconstruct(folder/'retry-dataset.json',folder/'retry-rebuilt.json')
            require((folder/'retry-dataset.json').read_bytes()==(folder/'retry-rebuilt.json').read_bytes(),'retry_rebuild_mismatch')
            r['evidence']['after_retry']=after
        finally:j.close()
        return r
    if phase=='live_provenance':
        r=pipeline(folder,folder/'blocks.sqlite');c=r['evidence']['journal']['coverage_versions'][0]
        if not c['source_complete'] or not c['events'] or c['decoder_errors']:r.update(status='FAIL',code='live_coverage_or_supported_events_missing')
        return r
    raise ValueError('unknown_phase')
def run_phase(phase,folder):
    env={k:os.environ[k] for k in ('PATH','SystemRoot','WINDIR','TEMP','TMP','TMPDIR','LANG') if k in os.environ}
    try:
        p=subprocess.run([sys.executable,'-B',str(Path(__file__).resolve()),'--worker',phase,'--folder',str(folder)],cwd=ROOT,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=150)
        path=Path(folder)/(phase+'.json')
        require(p.returncode==0 and path.exists(),'worker_failed');r=json.loads(path.read_text(encoding='utf-8'));require(r.get('status') in ('PASS','FAIL'),'bad_report');return r
    except subprocess.TimeoutExpired:return {'status':'FAIL','code':'worker_timeout'}
    except Exception:return {'status':'FAIL','code':'worker_or_report_failure'}
def reference():
    refs=json.loads((ROOT/'V1D_REFERENCE.json').read_text(encoding='utf-8'));changed=[n for n,h in refs.items() if not (ROOT/n).is_file() or hashlib.sha256((ROOT/n).read_bytes()).hexdigest()!=h]
    return {'id':'v1d_reference_unchanged','status':'FAIL' if changed else 'PASS','files_checked':len(refs),'changed_files':changed}
def validate(self_test=False):
    checks=[reference()]
    with tempfile.TemporaryDirectory(prefix='astra-provenance-validation-') as tmp:
        base=Path(tmp)
        for phase in ('unit','deterministic'):
            d=base/phase;d.mkdir();checks.append(dict(run_phase(phase,d),id=phase))
        live=base/'live';live.mkdir();proceed=True
        for phase in ('first','resume','retry','offline_replay','live_provenance'):
            if self_test or not os.environ.get('SOLANA_RPC_URL'):r={'status':'FAIL','code':'live_endpoint_not_used'}
            elif not proceed:r={'status':'FAIL','code':'previous_phase_failed'}
            else:r=run_phase(phase,live) if phase=='live_provenance' else blocks_phase(phase,live,block=True)
            proceed=r['status']=='PASS' or r.get('can_continue',False);checks.append(dict(r,id=phase))
    return {'overall':'PASS' if all(c['status']=='PASS' for c in checks) else 'FAIL','checks':checks}
def main():
    p=argparse.ArgumentParser();p.add_argument('--worker');p.add_argument('--folder');p.add_argument('--self-test',action='store_true');a=p.parse_args()
    if a.worker:
        try:r=worker(a.worker,a.folder)
        except Exception as exc:
            tb=exc.__traceback__
            while tb.tb_next:tb=tb.tb_next
            r={'status':'FAIL','code':'phase_exception','exception_type':type(exc).__name__,
               'location':{'file':Path(tb.tb_frame.f_code.co_filename).name,'function':tb.tb_frame.f_code.co_name,'line':tb.tb_lineno}}
        save(Path(a.folder)/(a.worker+'.json'),r);return 0
    dest=Path(tempfile.mkdtemp(prefix='provenance-report-',dir=ROOT/'provenance_validation'));r=validate(a.self_test);save(dest/'report.json',r);(dest/'report.txt').write_text(json.dumps(r,indent=2),encoding='utf-8');print(r['overall']+' — '+str(dest));return 0 if r['overall']=='PASS' else 1
if __name__=='__main__':sys.exit(main())
