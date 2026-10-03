import argparse,json,sys
from .archive import capture_source
from .store import Journal,reconstruct

def main():
    p=argparse.ArgumentParser();s=p.add_subparsers(dest='command',required=True)
    i=s.add_parser('import');i.add_argument('--source',required=True);i.add_argument('--db',required=True);i.add_argument('--start',type=int);i.add_argument('--end',type=int);i.add_argument('--exclude',type=int,nargs='*',default=[])
    for name in ('recover','audit'):
        c=s.add_parser(name);c.add_argument('--db',required=True)
    e=s.add_parser('export');e.add_argument('--db',required=True);e.add_argument('--id',type=int,required=True);e.add_argument('--output',required=True)
    b=s.add_parser('reconstruct');b.add_argument('--source',required=True);b.add_argument('--output',required=True)
    a=p.parse_args();j=None
    try:
        if a.command=='reconstruct':result=reconstruct(a.source,a.output)
        else:
            j=Journal(a.db)
            if a.command=='import':
                ident=j.capture(capture_source(a.source,a.start,a.end,a.exclude));j.publish(ident);result=j.audit();result['capture_id']=ident
            elif a.command=='recover':result=j.recover()
            elif a.command=='audit':result=j.audit()
            else:j.export(a.id,a.output);result={'status':'PASS'}
        print(json.dumps(result));return 0 if result.get('healthy',True) else 1
    except Exception:print('{"status":"FAIL","code":"provenance_operation_failed"}');return 1
    finally:
        if j:j.close()
if __name__=='__main__':sys.exit(main())
