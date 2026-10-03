"""Isolated V1d validation. Only safe status codes/aggregate metrics are logged."""
import argparse,contextlib,hashlib,io,json,os,socket,subprocess,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from astra_memory.store import Memory,rebuild
from astra_memory.import_blocks import import_blocks
from block_validation.run import network_off

def save(path,value):Path(path).write_text(json.dumps(value,indent=2),encoding='utf-8')
def require(ok,code):
    if not ok:raise AssertionError(code)
def metrics(audit):
    result={k:v for k,v in audit.items() if k!='coverage'}
    result['transactions_expected']=sum(x['transactions_expected'] for x in audit['coverage'])
    for group in ('transactions','instructions'):
        result[group]={}
        for x in audit['coverage']:
            for key,value in x[group].items():result[group][key]=result[group].get(key,0)+value
    result['accounting_ok']=all(x['accounting_ok'] for x in audit['coverage'])
    result['inner_coverage_unavailable']=sum(x['inner_coverage_unavailable'] for x in audit['coverage'])
    return result

def decode_dataset(folder,source):
    """Exercises the same pipeline for simulated and live source blocks, offline."""
    network_off();folder=Path(folder);memory_path=folder/'memory.sqlite'
    m=Memory(memory_path)
    try:
        first=import_blocks(source,m,limit=1)
        before=[tuple(r) for r in m.db.execute('SELECT * FROM memory_events ORDER BY event_id')]
    finally:m.close()
    # Separate process, no endpoint, with OS process boundary and offline CLI.
    env={k:v for k,v in os.environ.items() if k!='SOLANA_RPC_URL'}
    code="from block_validation.run import network_off;network_off();from astra_memory.__main__ import main;import sys;sys.exit(main())"
    p=subprocess.run([sys.executable,'-B','-c',code,'--db',str(memory_path),'import','--blocks-db',str(source)],cwd=ROOT,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=60)
    require(p.returncode==0,'resume_process_failed')
    m=Memory(memory_path)
    try:
        for old in before:require(tuple(m.db.execute('SELECT * FROM memory_events WHERE event_id=?',(old[0],)).fetchone())==old,'event_republished')
        m.recover();full_before=[tuple(r) for r in m.db.execute('SELECT * FROM memory_events ORDER BY event_id')]
        import_blocks(source,m);m.recover()
        require(full_before==[tuple(r) for r in m.db.execute('SELECT * FROM memory_events ORDER BY event_id')],'duplicate_publication')
        audit=m.audit();require(audit['healthy'],'memory_integrity_failure')
        require(all(c['accounting_ok'] for c in audit['coverage']),'coverage_accounting_failure')
        archive=folder/'dataset.json';root=m.export(archive)
        rebuilt=folder/'rebuilt.sqlite';rebuilt_audit=rebuild(archive,rebuilt)
        other=Memory(rebuilt)
        try:require(other.dataset()==m.dataset(),'dataset_rebuild_mismatch')
        finally:other.close()
        evidence={'first_import':metrics(first),'final':metrics(audit),'dataset_sha256':root,
                  'rebuild':metrics(rebuilt_audit),'resume_new_process':True,'source_read_only':True,'offline':True}
        # Unsupported programs remain explicit; malformed supported decoding fails gate.
        require(not evidence['final']['transactions'].get('error',0) and not evidence['final']['instructions'].get('error',0),'decoder_errors_present')
        return evidence
    finally:m.close()

def worker(phase,folder):
    folder=Path(folder)
    if phase=='unit':
        network_off()
        class Result(unittest.TestResult):
            def __init__(self):super().__init__();self.rows=[]
            def addSuccess(self,t):super().addSuccess(t);self.rows.append({'test':t.id(),'status':'PASS'})
            def addFailure(self,t,e):super().addFailure(t,e);self.rows.append({'test':t.id(),'status':'FAIL','type':e[0].__name__})
            def addError(self,t,e):super().addError(t,e);self.rows.append({'test':t.id(),'status':'FAIL','type':e[0].__name__})
        suite=unittest.defaultTestLoader.discover(str(ROOT/'memory_tests'));r=Result()
        with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):suite.run(r)
        return {'status':'PASS' if r.wasSuccessful() and r.testsRun else 'FAIL','count':r.testsRun,'tests':r.rows}
    if phase=='deterministic':
        network_off()
        from memory_tests.test_memory import raw_block,tx,b58,context
        from astra_blocks.store import BlockStore
        from astra_blocks.rpc import canonical
        path=folder/'simulated.sqlite';s=BlockStore(path,100,101)
        try:
            sid=s.session(context())
            for slot in (100,101):
                t=tx(amount=slot);t['transaction']['signatures']=[b58(bytes([slot])*64)]
                obj=json.loads(raw_block([t]));obj['result']['blockhash']='h'+str(slot);obj['result']['previousBlockhash']='h'+str(slot-1);obj['result']['parentSlot']=slot-1
                s.apply(s.capture(slot,sid,canonical(obj).encode()))
        finally:s.close()
        evidence=decode_dataset(folder,path)
        require(evidence['final']['events']==2 and evidence['final']['decoded']==2,'deterministic_counts')
        return {'status':'PASS','evidence':evidence}
    if phase=='live_memory':
        evidence=decode_dataset(folder,folder/'blocks.sqlite')
        # A small range without any supported instruction is not evidence of real decoding.
        return {'status':'PASS' if evidence['final']['events']>0 else 'FAIL',
                'code':'real_transfer_decoded' if evidence['final']['events']>0 else 'no_supported_transfer_observed','evidence':evidence}
    raise ValueError('unknown_phase')

def run_phase(phase,folder,block=False):
    allowed=('PATH','SystemRoot','WINDIR','TEMP','TMP','TMPDIR','LANG','SSL_CERT_FILE','SSL_CERT_DIR')
    env={k:os.environ[k] for k in allowed if k in os.environ};env['PYTHONDONTWRITEBYTECODE']='1'
    if block and phase in ('first','resume','retry') and os.environ.get('SOLANA_RPC_URL'):env['SOLANA_RPC_URL']=os.environ['SOLANA_RPC_URL']
    script=ROOT/'block_validation/run.py' if block else Path(__file__).resolve()
    try:
        p=subprocess.run([sys.executable,'-B',str(script),'--worker',phase,'--folder',str(folder)],cwd=ROOT,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=100)
        path=Path(folder)/(phase+'.json')
        if p.returncode!=0 or not path.exists():return {'status':'FAIL','code':'worker_failed'}
        value=json.loads(path.read_text(encoding='utf-8'))
        if value.get('status') not in ('PASS','FAIL'):return {'status':'FAIL','code':'invalid_worker_report'}
        return value
    except subprocess.TimeoutExpired:return {'status':'FAIL','code':'worker_timeout'}
    except (ValueError,OSError):return {'status':'FAIL','code':'worker_report_unavailable'}

def reference_check():
    refs=json.loads((ROOT/'V1C_REFERENCE.json').read_text())
    changed=[n for n,h in refs.items() if not (ROOT/n).is_file() or hashlib.sha256((ROOT/n).read_bytes()).hexdigest()!=h]
    return {'id':'v1c_reference_unchanged','status':'FAIL' if changed else 'PASS','changed_files':changed,'files_checked':len(refs)}
def validate(self_test=False):
    checks=[reference_check()]
    with tempfile.TemporaryDirectory(prefix='astra-memory-validation-') as tmp:
        base=Path(tmp)
        for phase in ('unit','deterministic'):
            folder=base/phase;folder.mkdir();r=run_phase(phase,folder);checks.append(dict(r,id=phase))
        live=base/'live';live.mkdir();proceed=True
        for phase in ('first','resume','retry','offline_replay','live_memory'):
            if self_test or not os.environ.get('SOLANA_RPC_URL'):r={'status':'FAIL','code':'live_endpoint_not_used'}
            elif not proceed:r={'status':'FAIL','code':'previous_phase_failed'}
            else:r=run_phase(phase,live,block=phase!='live_memory')
            proceed=r['status']=='PASS' or r.get('can_continue',False)
            checks.append(dict(r,id=phase))
    return {'overall':'PASS' if all(r['status']=='PASS' for r in checks) else 'FAIL','checks':checks}

def main():
    p=argparse.ArgumentParser();p.add_argument('--worker');p.add_argument('--folder');p.add_argument('--self-test',action='store_true');a=p.parse_args()
    if a.worker:
        try:value=worker(a.worker,a.folder)
        except Exception as exc:value={'status':'FAIL','code':'worker_exception','exception_type':type(exc).__name__}
        save(Path(a.folder)/(a.worker+'.json'),value);return 0
    dest=Path(tempfile.mkdtemp(prefix='memory-report-',dir=ROOT/'memory_validation'));r=validate(a.self_test)
    save(dest/'report.json',r);(dest/'report.txt').write_text(json.dumps(r,indent=2),encoding='utf-8')
    print(r['overall']+' — '+str(dest));return 0 if r['overall']=='PASS' else 1
if __name__=='__main__':sys.exit(main())
