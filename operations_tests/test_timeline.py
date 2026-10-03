import copy,json,os,subprocess,sys,tempfile,unittest
from pathlib import Path
from astra_blocks.store import BlockStore
from astra_blocks.rpc import canonical
from astra_pipeline.decode import enrich
from astra_pipeline.run import offline
from astra_provenance.archive import bundle,capture_source
from astra_timeline.store import Timeline,restore
from block_tests.test_blocks import context,response
from pipeline_tests.test_pipeline import rich_block
ROOT=Path(__file__).resolve().parents[1]
class TimelineTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()
    def dataset(self,second=False):
        p=self.root/'blocks.sqlite';s=BlockStore(p,100,101)
        try:
            session=s.session(context())
            if not s.db.execute('SELECT 1 FROM publications WHERE slot=100').fetchone():s.apply(s.capture(100,session,rich_block()))
            if second:s.apply(s.capture(101,session,rich_block(101,100)))
        finally:s.close()
        return enrich(bundle(capture_source(p)))
    def test_cutoff_and_future_retry(self):
        a=self.dataset();b=self.dataset(True);t=Timeline(self.root/'t',clock=iter([1000,2000]).__next__)
        try:
            t.ingest(a);before=t.query(100,102,sequence=1);t.ingest(b)
            self.assertEqual(t.query(100,102,sequence=1),before)
            self.assertEqual(before['payload']['counts']['unresolved'],1);self.assertEqual(before['payload']['counts']['not_observed'],1)
            self.assertEqual(t.query(100,101,as_of_ns=1999)['payload']['counts']['unresolved'],1)
            self.assertTrue(t.query(100,101,as_of_ns=2000)['payload']['source_complete'])
            self.assertFalse(t.query(100,101)['payload']['market_coverage_complete'])
        finally:t.close()
    def test_empty_knowledge_not_zero_activity_proof(self):
        t=Timeline(self.root/'t')
        try:
            r=t.query(100,101,sequence=0)['payload'];self.assertEqual(r['counts']['not_observed'],2);self.assertFalse(r['source_complete']);self.assertEqual(r['social_coverage'],'not_collected')
        finally:t.close()
    def test_duplicate_receipt_not_retimed(self):
        v=self.dataset();t=Timeline(self.root/'t',clock=iter([1000]).__next__)
        try:
            a=t.ingest(v);b=t.ingest(v);self.assertEqual(a['sequence'],b['sequence']);self.assertEqual(a['recorded_ns'],b['recorded_ns']);self.assertTrue(b['duplicate']);self.assertEqual(len(t.rows()),1)
        finally:t.close()
    def test_clock_regression_rejected_no_write(self):
        a=self.dataset();b=self.dataset(True);t=Timeline(self.root/'t',clock=iter([2000,1999]).__next__)
        try:
            t.ingest(a)
            with self.assertRaisesRegex(ValueError,'clock_regression'):t.ingest(b)
            self.assertEqual(len(t.rows()),1)
        finally:t.close()
    def test_features_exact_with_event_provenance(self):
        v=self.dataset();t=Timeline(self.root/'t')
        try:
            t.ingest(v);f=t.query(100,100)['payload']['slots'][0]['feature']
            self.assertEqual(f['event_counts'],{'spl_transfer_checked':1,'token_balance_change':2});self.assertEqual(sorted(x['delta_raw'] for x in f['token_changes']),['-12','12'])
            self.assertTrue(all(x['provenance']['raw_sha256'] for x in f['evidence']))
        finally:t.close()
    def test_snapshot_offline_restore_identical(self):
        v=self.dataset();t=Timeline(self.root/'t')
        try:t.ingest(v);snap=t.snapshot();before=t.query(100,101)
        finally:t.close()
        restore(snap,self.root/'restored');r=Timeline(self.root/'restored')
        try:self.assertEqual(before,r.query(100,101));self.assertEqual(snap,r.snapshot())
        finally:r.close()
        with self.assertRaises(ValueError):restore(snap,self.root/'restored')
    def test_dataset_corruption_rejected(self):
        v=self.dataset();v['payload']['events'][0]['event']['amount_raw']='999';t=Timeline(self.root/'t')
        try:
            with self.assertRaises(ValueError):t.ingest(v)
            self.assertEqual(t.rows(),[])
        finally:t.close()
    def test_receipt_corruption_fail_closed(self):
        t=Timeline(self.root/'t')
        try:
            t.ingest(self.dataset());t.db.execute('DROP TRIGGER no_UPDATE_knowledge');t.db.execute('UPDATE knowledge SET recorded_ns=1');t.db.commit()
            with self.assertRaisesRegex(ValueError,'chain_mismatch'):t.query(100,101)
        finally:t.close()
    def test_interruption_new_process_before_and_after_commit(self):
        value=self.dataset();p=self.root/'dataset.json';p.write_text(canonical(value),encoding='utf-8')
        code="import json,os,sys;from astra_timeline.store import Timeline\nt=Timeline(sys.argv[1])\ndef hook(stage):\n if stage==sys.argv[3]:os._exit(73)\nt.ingest(json.load(open(sys.argv[2],encoding='utf-8')),hook)"
        for stage in ('before_commit','committed'):
            db=self.root/stage
            r=subprocess.run([sys.executable,'-B','-c',code,str(db),str(p),stage],cwd=ROOT,timeout=20,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);self.assertEqual(r.returncode,73)
            t=Timeline(db)
            try:
                receipt=t.ingest(value);self.assertEqual(receipt['duplicate'],stage=='committed');self.assertEqual(len(t.rows()),1);t.verify()
            finally:t.close()
    def test_pipeline_restart_keeps_knowledge_receipt(self):
        self.dataset();a=offline(self.root/'blocks.sqlite',self.root/'business');b=offline(self.root/'blocks.sqlite',self.root/'business')
        self.assertEqual(a['knowledge_receipt']['sequence'],b['knowledge_receipt']['sequence']);self.assertEqual(a['knowledge_receipt']['recorded_ns'],b['knowledge_receipt']['recorded_ns']);self.assertTrue(b['knowledge_receipt']['duplicate'])
    def test_cli_replay_without_endpoint(self):
        v=self.dataset();p=self.root/'d.json';p.write_text(canonical(v),encoding='utf-8');db=self.root/'timeline.sqlite'
        for args in [('ingest','--input',str(p)),('query','--start','99','--end','101','--sequence','1','--output',str(self.root/'view.json'))]:
            r=subprocess.run([sys.executable,'-B','-m','astra_timeline',*args,'--db',str(db)],cwd=ROOT,env={k:v for k,v in os.environ.items() if k!='SOLANA_RPC_URL'},stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=20)
            self.assertEqual(r.returncode,0,r.stdout)
        self.assertEqual(json.loads((self.root/'view.json').read_text())['payload']['counts']['not_observed'],1)
