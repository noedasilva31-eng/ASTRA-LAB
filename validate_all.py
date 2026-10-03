"""Unified validation; preserves and invokes the immutable V1b Windows gate."""
import argparse,json,os,re,subprocess,sys,tempfile,time
from pathlib import Path
ROOT=Path(__file__).resolve().parent

def launch(cmd,timeout=450):
    try:
        p=subprocess.run(cmd,cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                         text=True,encoding='utf-8',errors='replace',timeout=timeout)
        return p.returncode,p.stdout
    except subprocess.TimeoutExpired:return 124,'deadline_exceeded'

def newest_new(folder,prefix,old):
    fresh=[p for p in folder.glob(prefix+'*') if p not in old]
    if not fresh:return {'overall':'FAIL','code':'report_missing'}
    return json.loads((max(fresh,key=lambda p:p.stat().st_mtime)/'report.json').read_text())

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--self-test',action='store_true');a=ap.parse_args()
    flags=['--self-test'] if a.self_test else []
    dest=Path(tempfile.mkdtemp(prefix='validation-',dir=ROOT))
    old_blocks=set((ROOT/'block_validation').glob('blocks-report-*'))
    old_base=set((ROOT/'validator').glob('v1b-report-*'))
    print('Validation blocs...',flush=True)
    block_rc,_=launch([sys.executable,'-B','block_validation/run.py',*flags])
    print('Non-regression V1b...',flush=True)
    if os.name=='nt':
        gate_rc,output=launch(['cmd','/d','/c','validate-windows.cmd',*flags])
        runner_ok=bool(re.search(r'Ran 8 tests[^\n]*\n\s*\nOK\b',output))
        gate_mode='unchanged validate-windows.cmd'
    else:
        runner_rc,_=launch([sys.executable,'-B','validator/check_runner.py','--project','.'])
        runner_ok=runner_rc==0
        gate_rc,_=launch([sys.executable,'-B','validator/validate_v1b.py','--project','.',*flags])
        gate_mode='Linux equivalents; Windows not executed'
    blocks=newest_new(ROOT/'block_validation','blocks-report-',old_blocks)
    baseline=newest_new(ROOT/'validator','v1b-report-',old_base)
    passed=block_rc==gate_rc==0 and runner_ok and blocks.get('overall')=='PASS' and baseline.get('overall')=='PASS'
    report={'overall':'PASS' if passed else 'FAIL','platform':sys.platform,'v1b_gate':gate_mode,
            'rpc_configured':bool(os.environ.get('SOLANA_RPC_URL')),'runner_tests':{'status':'PASS' if runner_ok else 'FAIL','expected_count':8},
            'blocks':blocks,'v1b':baseline,'baseline_immutable':any(c.get('id')=='v1b_reference_unchanged' and c.get('status')=='PASS' for c in blocks.get('checks',[]))}
    (dest/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    lines=['ASTRA V1c — '+report['overall'],'Platform: '+sys.platform,'V1b gate: '+gate_mode,
           'Runner: '+report['runner_tests']['status'],'']
    for row in blocks.get('checks',[]):lines.append(row['status']+' | blocs | '+row['id']+' | '+row.get('code',''))
    for row in baseline.get('criteria',[]):lines.append(row['status']+' | V1b | '+row['criterion']+' | '+row.get('code',''))
    lines+=['','Full evidence:',json.dumps(report,indent=2)]
    (dest/'report.txt').write_text('\n'.join(lines),encoding='utf-8')
    print(report['overall']+' — rapports: '+str(dest));return 0 if passed else 1
if __name__=='__main__':sys.exit(main())
