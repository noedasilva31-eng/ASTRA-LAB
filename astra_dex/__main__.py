import argparse,json,sys
from pathlib import Path
from astra_blocks.rpc import canonical
from astra_pipeline.store import atomic_file
from .decode import decode

def main():
    p=argparse.ArgumentParser();p.add_argument('--dataset',required=True);p.add_argument('--output',required=True);p.add_argument('--require-event',action='store_true');a=p.parse_args()
    try:
        result=decode(json.loads(Path(a.dataset).read_text(encoding='utf-8')));atomic_file(a.output,canonical(result));m=result['payload']['metrics']
        failed=m['transaction_errors'] or m['instruction_states']['error'] or (a.require_event and not m['events'])
        r={'status':'FAIL' if failed else 'PASS','code':'dex_evidence_insufficient' if failed else 'archive_replayed','metrics':m,'sha256':result['sha256']}
    except Exception as exc:r={'status':'FAIL','code':'dex_replay_failed','exception_type':type(exc).__name__}
    print(json.dumps(r,ensure_ascii=True));return 0 if r['status']=='PASS' else 1
if __name__=='__main__':sys.exit(main())
