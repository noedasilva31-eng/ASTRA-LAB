"""V1d gate + unchanged V1c/V1b gate. Missing prerequisites remain FAIL."""
import argparse,json,os,subprocess,sys,tempfile
from pathlib import Path
from validate_all import launch,newest_new
ROOT=Path(__file__).resolve().parent

def main():
    p=argparse.ArgumentParser();p.add_argument('--self-test',action='store_true');a=p.parse_args();flags=['--self-test'] if a.self_test else []
    dest=Path(tempfile.mkdtemp(prefix='memory-validation-',dir=ROOT))
    old_memory=set((ROOT/'memory_validation').glob('memory-report-*'));old_baseline=set(ROOT.glob('validation-*'))
    print('Validation memoire/dataset...',flush=True)
    memory_rc,_=launch([sys.executable,'-B','memory_validation/run.py',*flags],timeout=780)
    print('Non-regression V1c + V1b...',flush=True)
    cmd=['cmd','/d','/c','validate-blocks-windows.cmd',*flags] if os.name=='nt' else [sys.executable,'-B','validate_all.py',*flags]
    baseline_rc,_=launch(cmd,timeout=1100)
    memory=newest_new(ROOT/'memory_validation','memory-report-',old_memory)
    baseline=newest_new(ROOT,'validation-',old_baseline)
    passed=memory_rc==baseline_rc==0 and memory.get('overall')==baseline.get('overall')=='PASS'
    report={'overall':'PASS' if passed else 'FAIL','platform':sys.platform,
            'windows_executed':os.name=='nt','rpc_configured':bool(os.environ.get('SOLANA_RPC_URL')),
            'baseline_status':json.loads((ROOT/'BASELINE_STATUS.json').read_text()),
            'memory':memory,'non_regression':baseline,
            'scope':'Native top-level System Transfer; local reconstructible dataset. Full V1 not qualified.'}
    (dest/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    lines=['ASTRA V1d: '+report['overall'],'Platform: '+sys.platform,'Windows executed: '+str(report['windows_executed'])]
    for c in memory.get('checks',[]):lines.append(c['status']+' | memory | '+c['id']+' | '+c.get('code',''))
    lines.append('Non-regression V1c/V1b: '+baseline.get('overall','FAIL'))
    lines+=['','Full evidence:',json.dumps(report,indent=2)]
    (dest/'report.txt').write_text('\n'.join(lines),encoding='utf-8')
    print(report['overall']+' — rapports: '+str(dest));return 0 if passed else 1
if __name__=='__main__':sys.exit(main())
