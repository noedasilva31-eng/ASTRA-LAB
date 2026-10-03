import sqlite3,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from astra_blocks.rpc import Rpc
from astra_pipeline.coordinator import poll
from pipeline_tests.test_pipeline import factory,fake_call
class CoordinatorTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()
    def test_successive_ranges_no_holes(self):
        with patch.object(Rpc,'call',fake_call):r=poll(self.root,2,2,20,100,factory)
        self.assertEqual(r['next_slot'],104);self.assertEqual([(x['start'],x['end']) for x in r['completed']],[(100,101),(102,103)])
    def test_restart_after_output_before_receipt(self):
        def crash(stage):
            if stage=='range_ready':raise RuntimeError('interrupted')
        with patch.object(Rpc,'call',fake_call):
            with self.assertRaises(RuntimeError):poll(self.root,2,1,20,100,factory,crash)
            r=poll(self.root,2,1,20,None,factory)
        self.assertEqual(r['next_slot'],102)
        db=sqlite3.connect(self.root/'shared-quota.sqlite')
        try:self.assertEqual(db.execute('SELECT COUNT(*) FROM quota_reservations').fetchone()[0],4)
        finally:db.close()
    def test_quota_exhaustion_does_not_advance(self):
        with patch.object(Rpc,'call',fake_call):r=poll(self.root,2,1,3,100,factory)
        self.assertEqual(r['code'],'quota_exhausted');self.assertEqual(r['next_slot'],100)
    def test_wait_for_finality_no_receipt(self):
        with patch.object(Rpc,'call',fake_call):r=poll(self.root,2,1,10,200,factory)
        self.assertEqual(r['status'],'WAIT');self.assertEqual(r['next_slot'],200)
    def test_receipt_corruption_stops_recovery(self):
        with patch.object(Rpc,'call',fake_call):poll(self.root,2,1,20,100,factory)
        db=sqlite3.connect(self.root/'coordinator.sqlite')
        try:db.execute('DROP TRIGGER no_UPDATE_range_receipts');db.execute("UPDATE range_receipts SET report='{}'");db.commit()
        finally:db.close()
        with self.assertRaises(ValueError):poll(self.root,2,1,20,None,factory)
