"""Exercise real CLI subprocesses with a disposable database."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time

root = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory() as tmp:
    database = str(Path(tmp)/'data.sqlite')
    def call(*args, db=database):
        result = subprocess.run([sys.executable,'-m','astra','--db',db,*args],cwd=root,text=True,capture_output=True,check=True)
        return [json.loads(line) for line in result.stdout.splitlines()]
    receipts = call('ingest','fixtures/events.jsonl')
    assert [r['status'] for r in receipts] == ['accepted','duplicate']
    assert call('health')[0]['healthy']
    assert call('as-of','--at','0') == [[]]
    at = str(time.time_ns()//1000)
    snapshot = call('snapshot','--at',at)[0]
    assert len(snapshot['manifest']['events']) == 1
    assert call('recover')[0]['healthy']
    assert call('snapshot','--at',at)[0] == snapshot
    backup = str(Path(tmp)/'backup.sqlite')
    call('backup',backup)
    assert call('snapshot','--at',at,db=backup)[0] == snapshot
    print(json.dumps({'status':'PASS','fixture':'synthetic','commands':['ingest','health','as-of','snapshot','recover','backup'],'accepted':1,'duplicate':1,'restored_snapshot_identical':True,'cutoff':int(at),'dataset_sha256':snapshot['dataset_sha256']},indent=2))
