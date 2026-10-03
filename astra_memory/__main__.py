import argparse,json,sys
from .store import Memory,rebuild
from .import_blocks import import_blocks

def main():
    p=argparse.ArgumentParser();p.add_argument('--db',required=True)
    sub=p.add_subparsers(dest='command',required=True)
    i=sub.add_parser('import');i.add_argument('--blocks-db',required=True);i.add_argument('--limit',type=int)
    sub.add_parser('recover');sub.add_parser('audit')
    e=sub.add_parser('export');e.add_argument('destination')
    r=sub.add_parser('rebuild');r.add_argument('archive')
    args=p.parse_args();m=None
    try:
        if args.command=='rebuild':result=rebuild(args.archive,args.db)
        else:
            m=Memory(args.db)
            if args.command=='import':result=import_blocks(args.blocks_db,m,args.limit)
            elif args.command=='recover':result=m.recover()
            elif args.command=='audit':result=m.audit()
            else:result={'dataset_sha256':m.export(args.destination)}
        print(json.dumps(result,sort_keys=True));return 0 if result.get('healthy',True) else 1
    except Exception:print('{"status":"FAIL","code":"memory_operation_failed"}');return 2
    finally:
        if m:m.close()
if __name__=='__main__':sys.exit(main())
