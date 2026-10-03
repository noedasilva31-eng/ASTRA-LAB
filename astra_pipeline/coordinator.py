"""Sequential bounded range scheduler: durable receipts, no speculative advance."""
import json,sqlite3
from pathlib import Path
from astra_blocks.rpc import canonical,digest,tip_from_context,strict
from astra_budget.store import Budget
from astra_provenance.archive import require
from .rpc import BudgetRpc,QuotaExceeded
from .run import run
from .decode import verify_dataset

def poll(directory,range_size=12,max_batches=1,limit=300,start=None,client_factory=BudgetRpc,hook=None):
    require(type(range_size)==int and 1<=range_size<=1000 and type(max_batches)==int and 1<=max_batches<=100,'invalid_poll_bounds')
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True);path=directory/'coordinator.sqlite';quota=directory/'shared-quota.sqlite'
    if path.exists():
        probe=sqlite3.connect(path)
        try:require(probe.execute("SELECT 1 FROM sqlite_master WHERE name='range_config'").fetchone(),'foreign_database')
        finally:probe.close()
    db=sqlite3.connect(path,timeout=5)
    try:
        db.execute('PRAGMA journal_mode=WAL');db.execute('PRAGMA synchronous=FULL')
        db.executescript('CREATE TABLE IF NOT EXISTS range_config(id INTEGER PRIMARY KEY CHECK(id=1),start INTEGER,size INTEGER,hash TEXT);CREATE TABLE IF NOT EXISTS range_receipts(start INTEGER PRIMARY KEY,end INTEGER,report TEXT,hash TEXT);')
        for table in ('range_config','range_receipts'):
            for op in ('UPDATE','DELETE'):db.execute(f"CREATE TRIGGER IF NOT EXISTS no_{op}_{table} BEFORE {op} ON {table} BEGIN SELECT RAISE(ABORT,'append only'); END")
        db.commit();meta=db.execute('SELECT start,size,hash FROM range_config').fetchone()
        if meta is None:
            if start is None:
                b=Budget(quota,limit,limit)
                try:start=tip_from_context(client_factory(b).context())-8-range_size+1
                finally:b.close()
            require(type(start)==int and start>=1,'invalid_start')
            with db:db.execute('INSERT INTO range_config VALUES(1,?,?,?)',(start,range_size,digest(canonical([start,range_size]).encode())))
            meta=(start,range_size,digest(canonical([start,range_size]).encode()))
        require(meta[1]==range_size and (start is None or start==meta[0]) and meta[2]==digest(canonical(list(meta[:2])).encode()),'coordinator_config_mismatch')
        cursor=meta[0]
        # Verify receipts and their actual output files before trusting the cursor.
        for first,last,raw,h in db.execute('SELECT * FROM range_receipts ORDER BY start'):
            require(first==cursor and last==cursor+range_size-1 and digest(raw.encode())==h,'coordinator_receipt_mismatch')
            report=strict(raw);require(report['status']=='PASS','receipt_not_complete');ident=report['business']['dataset_id']
            dataset=strict((directory/('range-'+str(first))/'business/datasets'/(ident+'.json')).read_bytes());verify_dataset(dataset)
            require(dataset['dataset_sha256']==ident,'receipt_dataset_mismatch');cursor=last+1
        initial=cursor;completed=[]
        for _ in range(max_batches):
            first=cursor;last=first+range_size-1
            try:report=run(directory/('range-'+str(first)),start=first,end=last,limit=limit,budget_path=quota,client_factory=client_factory)
            except ValueError as exc:
                if str(exc)=='range_not_finalized':return {'status':'WAIT','code':'waiting_for_finality','next_slot':cursor,'completed':completed}
                raise
            except QuotaExceeded:return {'status':'FAIL','code':'quota_exhausted','next_slot':cursor,'completed':completed}
            if report['status']!='PASS':return {'status':'FAIL','code':report.get('code','range_failed'),'next_slot':cursor,'completed':completed,'range_report':report}
            if hook:hook('range_ready')
            raw=canonical(report)
            with db:
                db.execute('BEGIN IMMEDIATE')
                old=db.execute('SELECT report FROM range_receipts WHERE start=?',(first,)).fetchone()
                if old:
                    # Concurrent workers may observe different quota counters; the
                    # accepted dataset identity must still be identical.
                    require(strict(old[0])['business']['dataset_id']==report['business']['dataset_id'],'coordinator_publication_conflict')
                else:db.execute('INSERT INTO range_receipts VALUES(?,?,?,?)',(first,last,raw,digest(raw.encode())))
            if hook:hook('receipt_committed')
            completed.append({'start':first,'end':last,'dataset_id':report['business']['dataset_id']});cursor=last+1
        return {'status':'PASS','start_cursor':initial,'next_slot':cursor,'completed':completed,'mode':'sequential_bounded_poll'}
    finally:db.close()
