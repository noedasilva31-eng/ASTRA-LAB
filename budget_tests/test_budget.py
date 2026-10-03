import tempfile,unittest,subprocess,sys
from pathlib import Path
from astra_budget.store import Budget
ROOT=Path(__file__).resolve().parents[1]
class BudgetTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'quota.sqlite';self.b=Budget(self.path,2,10)
    def tearDown(self):self.b.close();self.tmp.cleanup()
    def test_limit_rejects_without_write(self):
        self.b.reserve('one',8)
        with self.assertRaises(ValueError):self.b.reserve('two',3)
        self.assertEqual(self.b.audit()['requests'],1)
    def test_duplicate_is_not_authorization_to_resend(self):
        self.assertTrue(self.b.reserve('one',4)['authorized']);self.assertFalse(self.b.reserve('one',4)['authorized']);self.assertEqual(self.b.audit()['charged_units'],4)
    def test_conflicting_identity_rejected(self):
        self.b.reserve('one',4)
        with self.assertRaises(ValueError):self.b.reserve('one',5)
    def test_settlement_idempotent_and_request_limit_retained(self):
        self.b.reserve('one',8);self.b.settle('one',2);self.b.settle('one',2);self.b.reserve('two',8)
        with self.assertRaises(ValueError):self.b.reserve('three',0)
        self.assertEqual(self.b.audit()['charged_units'],10)
    def test_unknown_usage_remains_charged_after_crash(self):
        p=Path(self.tmp.name)/'crash.sqlite'
        code="import os,sys;from astra_budget.store import Budget;b=Budget(sys.argv[1],1,10);b.reserve('request',10);os._exit(73)"
        r=subprocess.run([sys.executable,'-B','-c',code,str(p)],cwd=ROOT,timeout=10,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);self.assertEqual(r.returncode,73)
        b=Budget(p)
        try:
            self.assertEqual(b.audit()['charged_units'],10);self.assertFalse(b.reserve('request',10)['authorized'])
            with self.assertRaises(ValueError):b.reserve('other',1)
        finally:b.close()
    def test_over_settlement_rejected(self):
        self.b.reserve('one',3)
        with self.assertRaises(ValueError):self.b.settle('one',4)
        self.assertEqual(self.b.audit()['charged_units'],3)
    def test_policy_immutable(self):
        with self.assertRaises(ValueError):Budget(self.path,3,10)
    def test_corruption_blocks_reservation(self):
        self.b.reserve('one',4);self.b.db.execute('DROP TRIGGER no_UPDATE_quota_reservations');self.b.db.execute('UPDATE quota_reservations SET units=0');self.b.db.commit()
        with self.assertRaises(ValueError):self.b.reserve('two',1)
    def test_two_connections_enforce_common_limit(self):
        other=Budget(self.path)
        try:
            self.b.reserve('one',6)
            with self.assertRaises(ValueError):other.reserve('two',5)
            self.assertEqual(other.audit()['requests'],1)
        finally:other.close()

    def test_snapshot_rebuild_identical(self):
        from astra_budget.store import rebuild
        self.b.reserve('a',8);self.b.settle('a',2);self.b.reserve('b',8)
        value=self.b.snapshot();p=Path(self.tmp.name)/'restored.sqlite';self.assertTrue(rebuild(value,p)['healthy'])
        other=Budget(p)
        try:self.assertEqual(value,other.snapshot());self.assertFalse(other.reserve('b',8)['authorized'])
        finally:other.close()
    def test_snapshot_corruption_rejected(self):
        from astra_budget.store import rebuild
        value=self.b.snapshot();value['payload']['policy'][0]=99
        with self.assertRaises(ValueError):rebuild(value,Path(self.tmp.name)/'bad.sqlite')

    def test_rebuild_preserves_reservation_order_not_key_order(self):
        from astra_budget.store import rebuild
        self.b.reserve('z',8);self.b.settle('z',2);self.b.reserve('a',8)
        value=self.b.snapshot();p=Path(self.tmp.name)/'ordered.sqlite';rebuild(value,p)
        other=Budget(p)
        try:self.assertEqual(other.snapshot(),value)
        finally:other.close()
