import argparse,json,sys
from pathlib import Path
from .store import Timeline,restore

def main():
    p=argparse.ArgumentParser();sub=p.add_subparsers(dest='cmd',required=True)
    for name in ('ingest','query','snapshot','restore'):
        c=sub.add_parser(name);c.add_argument('--db',required=True)
        if name in ('ingest','restore'):c.add_argument('--input',required=True)
        if name in ('query','snapshot'):c.add_argument('--output',required=True)
        if name=='query':
            c.add_argument('--start',type=int,required=True);c.add_argument('--end',type=int,required=True);c.add_argument('--sequence',type=int);c.add_argument('--as-of-ns',type=int)
    a=p.parse_args();t=None
    try:
        if a.cmd=='restore':restore(json.loads(Path(a.input).read_text(encoding='utf-8')),a.db);r={'status':'PASS'}
        else:
            t=Timeline(a.db)
            if a.cmd=='ingest':r={'status':'PASS','receipt':t.ingest(json.loads(Path(a.input).read_text(encoding='utf-8')))}
            else:
                value=t.snapshot() if a.cmd=='snapshot' else t.query(a.start,a.end,a.sequence,a.as_of_ns)
                with Path(a.output).open('x',encoding='utf-8') as f:json.dump(value,f,ensure_ascii=True,sort_keys=True)
                r={'status':'PASS','sha256':value['sha256']}
    except Exception as exc:r={'status':'FAIL','code':'timeline_failure','exception_type':type(exc).__name__}
    finally:
        if t:t.close()
    print(json.dumps(r));return 0 if r['status']=='PASS' else 1
if __name__=='__main__':sys.exit(main())
