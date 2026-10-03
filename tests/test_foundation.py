import ast
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from astra.contracts import canonical, validate
from astra.store import Store

class Clock:
    def __init__(self): self.value = 100_000_000
    def __call__(self):
        self.value += 100
        return self.value

def record(**changes):
    obj = dict(schema_version=1,source='fixture',source_id='s0',logical_id='token:a',kind='token_creation',event_time=10,slot=1,blockhash='fixture-block',commitment='finalized',revision=0,supersedes=None,retracted=False,payload={'symbol':'SYNTHETIC'})
    obj.update(changes)
    return obj

def raw(**changes): return canonical(record(**changes)).encode()

class FoundationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name)/'db.sqlite'
        self.clock = Clock()
        self.store = Store(self.path, self.clock)
    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()
    def test_valid_contract(self): self.assertEqual(validate(record())['schema_version'],1)
    def test_missing_field(self):
        obj=record(); del obj['slot']
        with self.assertRaises(ValueError): validate(obj)
    def test_unknown_field(self):
        self.assertEqual(self.store.ingest(raw(available_to_strategy_at=1))['status'],'quarantined')
    def test_bool_time_rejected(self):
        self.assertEqual(self.store.ingest(raw(event_time=True))['status'],'quarantined')
    def test_nonfinite_rejected(self):
        self.assertEqual(self.store.ingest(b'{"x":NaN}')['status'],'quarantined')
    def test_duplicate_json_keys(self):
        self.assertEqual(self.store.ingest(b'{"x":1,"x":2}')['status'],'quarantined')
    def test_future_clock_quarantine(self):
        self.assertEqual(self.store.ingest(raw(event_time=999_000_000))['status'],'quarantined')
    def test_null_event_time(self):
        self.assertEqual(self.store.ingest(raw(event_time=None))['status'],'accepted')
    def test_old_event_not_backdated(self):
        self.store.ingest(raw())
        self.assertEqual(self.store.as_of(99_000_000),[])
        result=self.store.as_of(self.clock.value)[0]
        self.assertLessEqual(result['observed_at'],result['processed_at'])
        self.assertLessEqual(result['processed_at'],result['available_to_strategy_at'])
    def test_boundary(self):
        self.store.ingest(raw()); at=self.clock.value
        self.assertEqual(len(self.store.as_of(at)),1)
        self.assertEqual(len(self.store.as_of(at-1)),0)
    def test_duplicate_idempotent(self):
        self.store.ingest(raw()); before=self.store.snapshot(self.clock.value)
        self.assertEqual(self.store.ingest(raw())['status'],'duplicate')
        self.assertEqual(len(self.store.as_of(self.clock.value)),1)
        self.assertEqual(self.store.snapshot(before['manifest']['cutoff']),before)
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM raw_capture').fetchone()[0],2)
    def test_conflicting_id_preserves_raw(self):
        self.store.ingest(raw())
        self.assertEqual(self.store.ingest(raw(payload={'symbol':'BAD'}))['status'],'quarantined')
        self.assertEqual(len(self.store.as_of(self.clock.value)),1)
    def test_correction_does_not_rewrite_past(self):
        self.store.ingest(raw()); before=self.clock.value
        self.store.ingest(raw(source_id='s1',revision=1,supersedes='s0',payload={'symbol':'FIX'}))
        self.assertEqual(self.store.as_of(before,latest=True)[0]['record']['payload']['symbol'],'SYNTHETIC')
        self.assertEqual(self.store.as_of(self.clock.value,latest=True)[0]['record']['payload']['symbol'],'FIX')
    def test_retraction(self):
        self.store.ingest(raw()); before=self.clock.value
        self.store.ingest(raw(source_id='s1',revision=1,supersedes='s0',retracted=True))
        self.assertEqual(len(self.store.as_of(before,latest=True)),1)
        self.assertEqual(self.store.as_of(self.clock.value,latest=True),[])
        self.assertEqual(len(self.store.as_of(self.clock.value)),2)
    def test_missing_revision_parent(self):
        self.assertEqual(self.store.ingest(raw(source_id='s1',revision=1,supersedes='s0'))['status'],'quarantined')
    def test_revision_collision(self):
        self.store.ingest(raw())
        self.assertEqual(self.store.ingest(raw(source_id='s2'))['status'],'quarantined')
    def test_providers_not_silently_merged(self):
        self.store.ingest(raw()); self.store.ingest(raw(source='other'))
        self.assertEqual(len(self.store.as_of(self.clock.value,latest=True)),2)
    def test_out_of_order_event_time(self):
        self.store.ingest(raw(event_time=90))
        self.store.ingest(raw(source_id='s2',logical_id='token:b',event_time=5))
        self.assertEqual([x['record']['event_time'] for x in self.store.as_of(self.clock.value)],[90,5])
    def test_crash_after_capture_recovery(self):
        self.store.capture(raw()); self.store.close()
        self.store=Store(self.path,self.clock)
        self.assertEqual(self.store.health()['pending'],1)
        self.assertTrue(self.store.recover()['healthy'])
        self.assertEqual(len(self.store.as_of(self.clock.value)),1)
    def test_crash_after_normalization_recovery(self):
        ident=self.store.capture(raw()); self.store.normalize(ident); cutoff=self.clock.value
        self.assertEqual(self.store.as_of(cutoff),[])
        self.store.close(); self.store=Store(self.path,self.clock)
        self.store.recover()
        self.assertEqual(self.store.as_of(cutoff),[])
        self.assertEqual(len(self.store.as_of(self.clock.value)),1)
    def test_recovery_idempotent(self):
        self.store.ingest(raw()); cutoff=self.clock.value; before=self.store.snapshot(cutoff)
        self.store.recover(); self.store.recover()
        self.assertEqual(self.store.snapshot(cutoff),before)
    def test_append_only(self):
        self.store.ingest(raw())
        for table in ('raw_capture','normalization','publication'):
            with self.subTest(table=table):
                with self.assertRaises(sqlite3.IntegrityError):
                    self.store.db.execute(f'DELETE FROM {table}')
                self.store.db.rollback()
    def test_backup_restore(self):
        self.store.ingest(raw()); at=self.clock.value
        path=Path(self.tmp.name)/'backup.sqlite'; self.store.backup(path)
        other=Store(path,self.clock)
        try:
            self.assertEqual(other.snapshot(at),self.store.snapshot(at))
            self.assertTrue(other.health()['healthy'])
        finally: other.close()
    def test_backup_no_overwrite(self):
        with self.assertRaises(ValueError): self.store.backup(self.path)
    def test_clock_regression_fail_closed(self):
        ident=self.store.capture(raw()); self.store.normalize(ident)
        self.clock.value=1
        with self.assertRaises(ValueError): self.store.publish(ident)
        self.assertEqual(self.store.as_of(999_999_999),[])
    def test_unknown_schema(self):
        self.assertEqual(self.store.ingest(raw(schema_version=2))['status'],'quarantined')
    def test_invalid_utf8(self):
        self.assertEqual(self.store.ingest(b'\xff')['status'],'quarantined')
    def test_health_detects_quarantine(self):
        self.store.ingest(b'bad')
        self.assertFalse(self.store.health()['healthy'])
    def test_repeatable_snapshot(self):
        self.store.ingest(raw()); at=self.clock.value
        self.assertEqual(self.store.snapshot(at),self.store.snapshot(at))
    def test_raw_corruption_detected(self):
        self.store.ingest(raw())
        # Simulate a privileged/offline alteration beyond append-only permissions.
        self.store.db.execute('DROP TRIGGER no_UPDATE_raw_capture')
        self.store.db.execute("UPDATE raw_capture SET raw=?",(b'corrupt',))
        self.store.db.commit()
        self.assertEqual(self.store.health()['raw_hash_errors'],1)
        self.assertFalse(self.store.health()['healthy'])
    def test_normalized_corruption_blocks_replay(self):
        self.store.ingest(raw())
        self.store.db.execute('DROP TRIGGER no_UPDATE_normalization')
        self.store.db.execute("UPDATE normalization SET document='{}'")
        self.store.db.commit()
        self.assertEqual(self.store.health()['document_hash_errors'],1)
        with self.assertRaises(ValueError): self.store.as_of(self.clock.value)
    def test_core_has_no_llm_network_imports(self):
        tree=ast.parse(Path('astra/store.py').read_text())
        imported=[]
        for node in ast.walk(tree):
            if isinstance(node,ast.Import): imported.extend(x.name for x in node.names)
            elif isinstance(node,ast.ImportFrom): imported.append(node.module)
        self.assertEqual(set(imported),{'sqlite3','time','pathlib','contracts'})

if __name__ == '__main__': unittest.main()
