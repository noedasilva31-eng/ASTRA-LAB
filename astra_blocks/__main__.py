import argparse,json,sys
from .rpc import Rpc
from .store import BlockStore

def main():
    p=argparse.ArgumentParser(description='Isolated finalized Devnet chronology');p.add_argument('--db',required=True)
    sub=p.add_subparsers(dest='command',required=True)
    c=sub.add_parser('collect');c.add_argument('--start',type=int);c.add_argument('--end',type=int)
    c.add_argument('--max-slots',type=int);c.add_argument('--retry-unresolved',action='store_true')
    sub.add_parser('audit');sub.add_parser('recover');r=sub.add_parser('replay');r.add_argument('attempt_id',type=int)
    a=p.parse_args();store=None
    try:
        store=BlockStore(a.db,getattr(a,'start',None),getattr(a,'end',None))
        if a.command=='collect':data=store.collect(Rpc(),a.max_slots,a.retry_unresolved)
        elif a.command=='recover':data=store.recover()
        elif a.command=='audit':data=store.audit()
        else:data={k:v for k,v in store.replay(a.attempt_id).items() if k!='document'}
        print(json.dumps(data,sort_keys=True));return 0 if data.get('healthy',True) else 1
    except Exception:
        print('{"status":"FAIL","code":"collector_error_details_suppressed"}');return 2
    finally:
        if store:store.close()
if __name__=='__main__':sys.exit(main())
