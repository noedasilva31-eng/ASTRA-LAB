"""Offline audit/reconstruction only; positive PAPER scenarios are not live orders."""
import argparse,json,sys,sqlite3
from pathlib import Path
from .paper import replay_rows,fingerprint
from astra_observer.spine import sha

def main():
    p=argparse.ArgumentParser();p.add_argument('--ledger',required=True);p.add_argument('--output',required=True);a=p.parse_args();db=None
    try:
        db=sqlite3.connect(Path(a.ledger).resolve().as_uri()+'?mode=ro',uri=True);cfg=json.loads(db.execute('SELECT doc FROM config').fetchone()[0]);
        if cfg['code_sha256']!=fingerprint():raise ValueError('paper_code_version_mismatch')
        rows=db.execute('SELECT seq,doc,prev,hash FROM ledger ORDER BY seq').fetchall();state=replay_rows(rows,cfg['initial']);result={'status':'PASS','assurance':'CONDITIONAL_PAPER_NOT_EXECUTED_TRADES','state':state,'ledger_sha256':sha(rows)}
        with Path(a.output).open('x',encoding='utf-8') as f:json.dump(result,f,indent=2,ensure_ascii=True)
    except Exception as exc:result={'status':'FAIL','code':'paper_audit_failed','exception_type':type(exc).__name__}
    finally:
        if db:db.close()
    print(json.dumps(result));return 0 if result['status']=='PASS' else 1
if __name__=='__main__':sys.exit(main())
