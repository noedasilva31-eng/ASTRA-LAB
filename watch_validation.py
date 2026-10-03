import argparse,json,os
from pathlib import Path
from astra_watch.__main__ import execute

def main():
    p=argparse.ArgumentParser();p.add_argument('report');p.add_argument('--self-test',action='store_true');args=p.parse_args();path=Path(args.report)
    configured=os.environ.get('ASTRA_OBSERVER_RPC_URL') and os.environ.get('ASTRA_OBSERVER_NETWORK')=='mainnet'
    if args.self_test or not configured:r={'status':'NOT_EXECUTED','code':'watch_mainnet_configuration_missing'}
    else:r=execute(Path(__file__).parent/'position_reference/all-validation-jyqge_an/context-proofs',path.parent/'watch-proofs',live=True)
    report={'overall':'PASS' if r['status']=='PASS' else 'FAIL','checks':[dict(r,id='real_position_watch',proof_directory='watch-proofs')]}
    path.write_text(json.dumps(report,indent=2),encoding='utf-8');return 0 if report['overall']=='PASS' else 1
if __name__=='__main__':raise SystemExit(main())
