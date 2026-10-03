import argparse,json,os,sys,tempfile
from pathlib import Path
from validate_all import launch,newest_new
ROOT=Path(__file__).resolve().parent

def main():
    p=argparse.ArgumentParser();p.add_argument('--self-test',action='store_true');a=p.parse_args();flags=['--self-test'] if a.self_test else []
    dest=Path(tempfile.mkdtemp(prefix='provenance-validation-',dir=ROOT));old=set((ROOT/'provenance_validation').glob('provenance-report-*'));old_base=set(ROOT.glob('memory-validation-*'))
    print('Validation provenance/couverture...',flush=True);rc,_=launch([sys.executable,'-B','provenance_validation/run.py',*flags],timeout=900)
    print('Non-regression V1d + V1c + V1b...',flush=True)
    cmd=['cmd','/d','/c','validate-memory-windows.cmd',*flags] if os.name=='nt' else [sys.executable,'-B','validate_memory_all.py',*flags]
    brc,_=launch(cmd,timeout=2000)
    def read(folder,prefix,old):
        try:return newest_new(folder,prefix,old)
        except Exception:return {'overall':'FAIL','code':'report_unreadable'}
    current=read(ROOT/'provenance_validation','provenance-report-',old);baseline=read(ROOT,'memory-validation-',old_base)
    passed=rc==brc==0 and current.get('overall')==baseline.get('overall')=='PASS'
    report={'overall':'PASS' if passed else 'FAIL','platform':sys.platform,'windows_executed':os.name=='nt','rpc_configured':bool(os.environ.get('SOLANA_RPC_URL')),
      'baseline_windows_evidence':'baseline_windows_evidence/report.json; supplied Windows PASS, distinct from current local execution','provenance':current,'non_regression':baseline}
    (dest/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    lines=['ASTRA V1e: '+report['overall'],'Platform: '+sys.platform]
    for c in current.get('checks',[]):lines.append(c['status']+' | '+c['id']+' | '+c.get('code',''))
    lines+=['Non-regression V1d/V1c/V1b: '+baseline.get('overall','FAIL'),'','Full evidence:',json.dumps(report,indent=2)]
    (dest/'report.txt').write_text('\n'.join(lines),encoding='utf-8');print(report['overall']+' — '+str(dest));return 0 if passed else 1
if __name__=='__main__':sys.exit(main())
