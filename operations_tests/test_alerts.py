import tempfile,unittest
from pathlib import Path
from astra_operations.alerts import Alerts
class AlertTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'a.sqlite';self.a=Alerts(self.path)
    def tearDown(self):self.a.close();self.tmp.cleanup()
    def test_lifecycle_and_dedup(self):
        r={'status':'FAIL','code':'quota_exhausted'};a=self.a.record('feed',r);self.assertEqual(a,self.a.record('feed',r))
        b=self.a.record('feed',{'status':'PASS','business':{'alerts':[],'metrics':{}}});self.assertEqual(b['active']['feed'],[]);self.assertEqual(b['transitions'][-1]['state'],'RESOLVED')
    def test_incomplete_report_never_clears(self):
        self.a.record('feed',{'status':'FAIL','code':'quota_exhausted'});r=self.a.record('feed',{'status':'PASS'});self.assertEqual(r['active']['feed'],['quota_exhausted'])
    def test_restart_replay(self):
        r=self.a.record('feed',{'status':'WAIT','code':'waiting_for_finality'});self.a.close();self.a=Alerts(self.path);self.assertEqual(self.a.replay(),r)
    def test_secrets_not_recorded(self):
        self.a.record('feed',{'status':'FAIL','message':'SECRET_API_URL'});self.assertNotIn('SECRET_API_URL',str(list(self.a.db.execute('SELECT * FROM alert_observations'))))
    def test_corruption_fails_closed(self):
        self.a.record('feed',{'status':'FAIL'});self.a.db.execute('DROP TRIGGER no_UPDATE_alerts');self.a.db.execute("UPDATE alert_observations SET document='{}'");self.a.db.commit()
        with self.assertRaises(ValueError):self.a.replay()

    def test_snapshot_rebuild_preserves_lifecycle(self):
        from astra_operations.alerts import restore
        expected=self.a.record('feed',{'status':'FAIL','code':'quota_exhausted'})
        self.assertEqual(restore(self.a.snapshot(),Path(self.tmp.name)/'rebuilt.sqlite'),expected)
    def test_full_budget_remains_alert_on_success(self):
        r=self.a.record('feed',{'status':'PASS','business':{'alerts':[],'metrics':{}},'quota':{'requests':1,'request_limit':1,'charged_units':1,'unit_limit':1}})
        self.assertEqual(r['active']['feed'],['quota_exhausted'])
