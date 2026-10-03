import argparse,json,os
from pathlib import Path
from astra_context.__main__ import execute

def main():
    p=argparse.ArgumentParser();p.add_argument('report');p.add_argument('--self-test',action='store_true');args=p.parse_args();path=Path(args.report)
    configured=all(os.environ.get(n) for n in ('ASTRA_OBSERVER_RPC_URL','ASTRA_OBSERVER_WS_URL')) and os.environ.get('ASTRA_OBSERVER_NETWORK')=='mainnet'
    if args.self_test or not configured:r={'status':'NOT_EXECUTED','code':'context_mainnet_configuration_missing'}
    else:r=execute(path.parent/'context-proofs',seconds=180,max_cycles=3)
    checks=[dict(r,id='real_context_session',proof_directory='context-proofs')]
    # Round-trips are observations, NOT a success quota for the strategy.
    report={'overall':'PASS' if r['status']=='PASS' else 'FAIL','checks':checks}
    path.write_text(json.dumps(report,indent=2),encoding='utf-8');return 0 if report['overall']=='PASS' else 1
if __name__=='__main__':raise SystemExit(main())
