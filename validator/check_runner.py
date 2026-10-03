"""Regression checks for the validator. Requires the current ASTRA project."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import validate_v1b as v

PARSER = argparse.ArgumentParser()
PARSER.add_argument('--project', required=True, type=Path)
ARGS = PARSER.parse_args()

class RunnerChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='v1b-runner-check-')
        self.root = Path(self.temp.name)
        shutil.copytree(ARGS.project / 'astra', self.root / 'project' / 'astra',
                        ignore=shutil.ignore_patterns('__pycache__'))
        shutil.copyfile(Path(__file__).with_name('adapter_current.py'), self.root / 'adapter.py')
        raw = json.dumps({'jsonrpc':'2.0','id':1,'result':{'context':{'slot':100},
              'value':{'blockhash':'SYNTHETIC','lastValidBlockHeight':200}}}).encode()
        v.save(self.root / 'fixture.json', {'wire':v.blob(raw),'origin':'synthetic_fallback','document':'', 'provenance':{'network':'solana-devnet','provider':'fixture','endpoint':'https://fixture.invalid','rpc_method':'getLatestBlockhash','request_params':[{'commitment':'finalized'}]}})
    def tearDown(self):
        self.temp.cleanup()
    def case(self, name):
        dest = self.root / (name + '.json')
        rc = v.run_child(['--case', str(self.root), name, str(dest)], self.root)
        self.assertEqual(rc, 0)
        return json.loads(dest.read_text())
    def test_known_archive_results(self):
        for name in ('raw_bytes','replay','backup','before_normalize','before_publish','recover_twice','redelivery','conflict','continue','hashes'):
            with self.subTest(name=name): self.assertEqual(self.case(name)['status'], 'PASS')
        for name in ('live_rpc','after_outage'):
            with self.subTest(name=name): self.assertEqual(self.case(name)['status'], 'FAIL')
    def test_broken_recover_is_detected(self):
        p = self.root / 'project/astra/store.py'
        p.write_text(p.read_text().replace('    def recover(self):\n', '    def recover(self):\n        return self.health()\n'))
        self.assertEqual(self.case('before_normalize')['status'], 'FAIL')
        self.assertEqual(self.case('before_publish')['status'], 'FAIL')
    def check_backup_connection_closed(self, fail):
        code = r"""
import sqlite3
from unittest.mock import patch
from astra.store import Store
s = Store('source.sqlite')
original = s.db
connect = sqlite3.connect
connections = []
def tracked(*args, **kwargs):
    conn = connect(*args, **kwargs)
    connections.append(conn)  # Strong reference: no reliance on garbage collection.
    return conn
class BrokenSource:
    def backup(self, target):
        raise RuntimeError('intentional_backup_failure')
try:
    if FAIL:
        s.db = BrokenSource()
    with patch('astra.store.sqlite3.connect', side_effect=tracked):
        try:
            s.backup('backup.sqlite')
        except RuntimeError:
            assert FAIL
        else:
            assert not FAIL
    assert len(connections) == 1
    try:
        connections[0].execute('SELECT 1')
    except sqlite3.ProgrammingError:
        pass
    else:
        raise AssertionError('backup_connection_still_open')
finally:
    s.db = original
    s.close()
    for conn in connections:
        conn.close()
""".replace('FAIL', repr(fail))
        result = subprocess.run([sys.executable, '-B', '-c', code],
            cwd=self.root / 'project', env=v.child_env(),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        self.assertEqual(result.returncode, 0, 'Backup must explicitly close its target connection')
    def test_backup_closes_target_on_success(self):
        self.check_backup_connection_closed(False)
    def test_backup_closes_target_on_exception(self):
        self.check_backup_connection_closed(True)
    def test_broken_product_replay_is_detected(self):
        p = self.root / 'project/astra/store.py'
        p.write_text(p.read_text().replace('    def replay_rpc(self, capture_id):\n',
            '    def replay_rpc(self, capture_id):\n        return {"match": False}\n'))
        self.assertEqual(self.case('replay')['status'], 'FAIL')
    def test_missing_provenance_is_detected(self):
        p = self.root / 'adapter.py'
        p.write_text(p.read_text().replace('return store.capture_rpc(wire, PROVENANCE)', 'return store.capture(wire)'))
        self.assertEqual(self.case('raw_bytes')['status'], 'FAIL')
    def test_secret_echo_rejected(self):
        with self.assertRaises(v.CheckError):
            v.check_secret_echo(b'{"echo":"TEST-CREDENTIAL-MARKER"}', 'https://example.invalid/?key=TEST-CREDENTIAL-MARKER')
    def test_child_timeout_enforced(self):
        (self.root / 'adapter.py').write_text('import time\ntime.sleep(60)\n')
        rc = v.run_child(['--case', str(self.root),'raw_bytes',str(self.root / 'result.json')], self.root, timeout=0.3)
        self.assertEqual(rc, 124)

if __name__ == '__main__':
    unittest.main(argv=['check_runner'], verbosity=2)
