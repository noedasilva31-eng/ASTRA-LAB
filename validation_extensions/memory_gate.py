"""Keep immutable V1d checks; replace only the random live sample selection."""
import json,os,shutil,sqlite3,subprocess,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from memory_validation import run as original

def main():
    if '--probe-worker' in sys.argv:
        from validation_extensions.sol_probe import search
        folder=Path(sys.argv[2])
        try:r=search(folder/'blocks.sqlite',folder)
        except Exception as exc:r={'status':'FAIL','code':'sol_probe_exception','exception_type':type(exc).__name__}
        (folder/'probe.json').write_text(json.dumps(r,indent=2),encoding='utf-8');return 0
    if '--offline-worker' in sys.argv:
        folder=Path(sys.argv[2])
        try:
            e=original.decode_dataset(folder,folder/'proof.sqlite')
            r={'status':'PASS' if e['final']['events']>0 else 'FAIL','code':'real_transfer_decoded' if e['final']['events'] else 'sol_proof_has_no_transfer','evidence':e}
        except Exception as exc:r={'status':'FAIL','code':'sol_proof_replay_failed','exception_type':type(exc).__name__}
        (folder/'proof-result.json').write_text(json.dumps(r,indent=2),encoding='utf-8');return 0
    dest=Path(tempfile.mkdtemp(prefix='memory-report-',dir=ROOT/'memory_validation'));old=original.run_phase
    def phase(name,folder,block=False):
        if name!='live_memory':return old(name,folder,block)
        folder=Path(folder)
        env={k:os.environ[k] for k in ('PATH','SystemRoot','WINDIR','TEMP','TMP','TMPDIR','SSL_CERT_FILE','SSL_CERT_DIR','SOLANA_RPC_URL') if k in os.environ}
        try:
            p=subprocess.run([sys.executable,'-B',str(Path(__file__).resolve()),'--probe-worker',str(folder)],cwd=ROOT,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=120)
            r=json.loads((folder/'probe.json').read_text(encoding='utf-8')) if p.returncode==0 else {'status':'FAIL','code':'probe_worker_failed'}
            if r['status']=='PASS':
                env.pop('SOLANA_RPC_URL',None)
                p=subprocess.run([sys.executable,'-B',str(Path(__file__).resolve()),'--offline-worker',str(folder)],cwd=ROOT,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=100)
                result=json.loads((folder/'proof-result.json').read_text(encoding='utf-8')) if p.returncode==0 else {'status':'FAIL','code':'proof_worker_failed'}
                result['selection']=r['evidence'];r=result
        except subprocess.TimeoutExpired:r={'status':'FAIL','code':'sol_probe_worker_timeout'}
        except Exception as exc:r={'status':'FAIL','code':'sol_probe_report_failure','exception_type':type(exc).__name__}
        # Preserve exact closed capture journals and exported raw dataset for review.
        for name in ('probe.json','search.sqlite','proof.sqlite','probe-quota.sqlite','dataset.json','proof-result.json'):
            if (folder/name).exists():
                if name.endswith('.sqlite'):
                    src=sqlite3.connect((folder/name).resolve().as_uri()+'?mode=ro',uri=True)
                    try:
                        target=sqlite3.connect(dest/name)
                        try:src.backup(target)
                        finally:target.close()
                    finally:src.close()
                else:shutil.copyfile(folder/name,dest/name)
        return r
    original.run_phase=phase
    report=original.validate('--self-test' in sys.argv)
    report['proof_artifacts_directory']=dest.relative_to(ROOT).as_posix()
    (dest/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8');(dest/'report.txt').write_text(json.dumps(report,indent=2),encoding='utf-8')
    return 0 if report['overall']=='PASS' else 1
if __name__=='__main__':sys.exit(main())
