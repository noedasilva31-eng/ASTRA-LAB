import argparse,json,sys
from pathlib import Path
from astra_blocks.rpc import strict
from .run import run,offline
from .decode import verify_dataset
from .store import export

def main():
    p=argparse.ArgumentParser();sub=p.add_subparsers(dest='cmd',required=True)
    c=sub.add_parser('run');c.add_argument('--workdir',required=True);c.add_argument('--request-limit',type=int,default=300);c.add_argument('--slots',type=int,default=6);c.add_argument('--start',type=int);c.add_argument('--end',type=int);c.add_argument('--max-slots',type=int);c.add_argument('--retry',action='store_true');c.add_argument('--budget-db')
    o=sub.add_parser('offline');o.add_argument('--source',required=True);o.add_argument('--output',required=True)
    q=sub.add_parser('replay');q.add_argument('--dataset',required=True);q.add_argument('--output')
    cmp=sub.add_parser('compare');cmp.add_argument('--left',required=True);cmp.add_argument('--right',required=True)
    w=sub.add_parser('poll');w.add_argument('--directory',required=True);w.add_argument('--range-size',type=int,default=12);w.add_argument('--max-batches',type=int,default=1);w.add_argument('--request-limit',type=int,default=300);w.add_argument('--start',type=int)
    a=p.parse_args()
    try:
        if a.cmd=='run':r=run(a.workdir,limit=a.request_limit,slots=a.slots,start=a.start,end=a.end,max_slots=a.max_slots,retry=a.retry,budget_path=a.budget_db)
        elif a.cmd=='poll':
            from .coordinator import poll
            r=poll(a.directory,a.range_size,a.max_batches,a.request_limit,a.start)
        elif a.cmd=='offline':r=offline(a.source,a.output)
        elif a.cmd=='compare':
            from .compare import compare
            r=compare(strict(Path(a.left).read_bytes()),strict(Path(a.right).read_bytes()));r['status']='PASS' if r['consistent_over_union'] else 'FAIL'
        else:
            value=strict(Path(a.dataset).read_bytes());m=verify_dataset(value)
            if a.output:export(value,a.output)
            r={'status':'PASS','dataset_id':value['dataset_sha256'],'metrics':m}
    except Exception as exc:
        safe={'immutable_policy','quota_exhausted','existing_export_corrupt','source_integrity_failure','business_integrity_failure','existing_range_mismatch','budget_integrity_failure'}
        tb=exc.__traceback__
        while tb.tb_next:tb=tb.tb_next
        r={'status':'FAIL','code':str(exc) if str(exc) in safe else 'pipeline_exception','exception_type':type(exc).__name__,
           'location':{'file':Path(tb.tb_frame.f_code.co_filename).name,'line':tb.tb_lineno,'function':tb.tb_frame.f_code.co_name}}
    if a.cmd in ('run','poll'):
        from astra_operations.alerts import Alerts
        folder=Path(a.workdir if a.cmd=='run' else a.directory)
        alerts=None
        try:
            alerts=Alerts(folder/'alerts.sqlite');r['operational_alerts']=alerts.record('pipeline',r)
        except Exception as exc:r={'status':'FAIL','code':'alert_journal_failure','exception_type':type(exc).__name__}
        finally:
            if alerts:alerts.close()
    text=json.dumps(r,indent=2,ensure_ascii=True);print(text)
    if a.cmd in ('run','poll'):
        folder=Path(a.workdir if a.cmd=='run' else a.directory)
        if folder.exists():(folder/'pipeline-report.json').write_text(text,encoding='utf-8')
    return 0 if r['status']=='PASS' else 1
if __name__=='__main__':sys.exit(main())
