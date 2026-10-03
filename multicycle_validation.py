"""Additive qualification: no live proof is replaced by a fixture."""
import argparse,json,os
from pathlib import Path
from astra_multicycle.__main__ import execute

def main():
    p=argparse.ArgumentParser();p.add_argument('report');p.add_argument('--self-test',action='store_true');args=p.parse_args();path=Path(args.report)
    configured=all(os.environ.get(n) for n in ('ASTRA_OBSERVER_RPC_URL','ASTRA_OBSERVER_WS_URL')) and os.environ.get('ASTRA_OBSERVER_NETWORK')=='mainnet'
    if args.self_test or not configured:
        check={'id':'real_multi_opportunity','status':'NOT_EXECUTED','code':'multicycle_configuration_missing'}
    else:
        result=execute(path.parent/'multi-proofs',seconds=120,max_cycles=3)
        check=dict(result,id='real_multi_opportunity',proof_directory='multi-proofs',assurance='CONDITIONAL_PAPER_NO_REAL_ORDERS')
    report={'overall':'PASS' if check['status']=='PASS' else 'FAIL','checks':[check]}
    path.write_text(json.dumps(report,indent=2),encoding='utf-8');return 0 if report['overall']=='PASS' else 1
if __name__=='__main__':raise SystemExit(main())
