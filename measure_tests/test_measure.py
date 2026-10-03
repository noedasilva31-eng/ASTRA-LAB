import copy,hashlib,json,shutil,sqlite3,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from astra_measure.costs import row,separate_total,CATEGORIES
from astra_measure.report import generate
from v1e_preserve import preserve
ROOT=Path(__file__).resolve().parents[1]
FIXTURE=ROOT/'measure_tests/fixtures/vsof'
class MeasureTests(unittest.TestCase):
    def test_real_vsof_exact_regression(self):
        r=generate(FIXTURE);self.assertEqual(r['audit']['status'],'PASS');self.assertEqual(len(r['cycles']),1);c=r['cycles'][0]
        for k,v in {'buy_notional_quote_raw':10000000,'base_quantity_raw':406739,'holding_duration_ns':8210169200,'gross_before_fixed_fees_quote_raw':-158759,'fixed_simulated_fees_quote_raw':4200000,'net_quote_raw':-4358759}.items():self.assertEqual(c[k],v,k)
        self.assertEqual(c['base_decimals']['value'],6);self.assertEqual(r['portfolio']['cash_quote_raw'],995641241);self.assertEqual(c['MAE']['classification'],'UNKNOWN');self.assertFalse(c['real_execution'])
        for side in ('buy','sell'):
            d=c[side];self.assertGreater(d['settlement_quote']['observed_ns'],d['decision_ns']);self.assertLessEqual(d['decision_quote']['observed_ns'],d['decision_ns']);self.assertTrue(d['risk_decision']['allowed']);self.assertTrue(d['risk_settlement']['allowed'])
    def test_report_deterministic_sources_unchanged(self):
        before={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in FIXTURE.iterdir() if p.is_file()};a=generate(FIXTURE);b=generate(FIXTURE)
        self.assertEqual(a,b);self.assertEqual(before,{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in FIXTURE.iterdir() if p.is_file()})
    def test_corrupt_archive_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            for p in FIXTURE.glob('*.sqlite'):shutil.copyfile(p,Path(tmp)/p.name)
            db=sqlite3.connect(Path(tmp)/'raw.sqlite')
            try:db.execute('DROP TRIGGER no_UPDATE_frames');db.execute("UPDATE frames SET hash='bad' WHERE seq=1");db.commit()
            finally:db.close()
            with self.assertRaises(ValueError):generate(tmp)
    def test_unknown_is_not_zero(self):
        self.assertIsNone(row('network')['amount'])
        with self.assertRaisesRegex(ValueError,'unknown_is_not_zero'):row('network',0)
        self.assertIsNone(separate_total([row('network',included='separate',key='a')]))
    def test_duplicate_and_aggregate_allocation_rejected(self):
        a=row('other',10,source='ledger',available_at=1,mode='SIMULATED',included='separate',key='aggregate',components=['network'])
        b=row('network',3,source='proof',available_at=1,mode='PROVEN',included='separate',key='network')
        for rows in ([a,a],[a,b],[b,a]):
            with self.assertRaisesRegex(ValueError,'duplicate'):separate_total(rows)
    def test_unknown_does_not_hide_duplicate(self):
        u=row('network',included='separate',key='a')
        with self.assertRaises(ValueError):separate_total([u,u])
    def test_costs_temporal_and_units(self):
        r=row('other',10,source='ledger',available_at=5,mode='SIMULATED',included='separate',key='one')
        with self.assertRaisesRegex(ValueError,'not_yet_available'):separate_total([r],as_of=4)
        with self.assertRaisesRegex(ValueError,'units'):separate_total([r],unit='USDC')
        self.assertEqual(separate_total([r],as_of=5),10)
    def test_no_double_subtraction_quote_haircut(self):
        c=generate(FIXTURE)['cycles'][0]
        for side in ('buy','sell'):
            costs=c[side]['costs'];self.assertEqual(costs['separate_total_lamports'],2100000);self.assertEqual(set(r['category'] for r in costs['rows']),set(CATEGORIES))
            haircut=next(r for r in costs['rows'] if r['category']=='paper-slippage');self.assertTrue(haircut['already_applied_in_ledger']);self.assertEqual(haircut['included_in_quote_or_separate'],'descriptive_only')
    def test_preservation_all_associated_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            src=Path(tmp)/'source';src.mkdir()
            names=['blocks.sqlite','blocks.sqlite-wal','journal.sqlite','dataset.json','rebuilt.json','first.json']
            for n in names:(src/n).write_bytes(n.encode())
            out=Path(tmp)/'saved';r=preserve(src,out);shutil.rmtree(src);self.assertEqual(set(r['files']),set(names));self.assertFalse(r['criteria_changed'])
            for n in names:self.assertEqual((out/n).read_bytes(),n.encode())
    def test_preservation_does_not_overwrite_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileExistsError):preserve(tmp,tmp)
    def test_protected_components_unchanged(self):
        manifest=json.loads((ROOT/'PROTECTED_COMPONENTS.json').read_text())
        for p,h in manifest.items():self.assertEqual(hashlib.sha256((ROOT/p).read_bytes()).hexdigest(),h,p)
    def test_v1e_zero_events_still_fail(self):
        from provenance_validation import run
        c={'source_complete':True,'events':0,'decoder_errors':0}
        with patch.object(run,'pipeline',return_value={'status':'PASS','evidence':{'journal':{'coverage_versions':[c]}}}):
            r=run.worker('live_provenance',Path('unused'));self.assertEqual(r['status'],'FAIL');self.assertEqual(r['code'],'live_coverage_or_supported_events_missing')
    def test_cli_offline_empty_session_no_fabricated_cycle(self):
        from astra_multicycle.__main__ import execute
        with tempfile.TemporaryDirectory() as tmp:
            r=execute(tmp,offline=True);self.assertEqual(r['status'],'PASS')
            report=json.loads((Path(tmp)/'cycle-report.json').read_text(encoding='utf-8'));self.assertEqual(report['cycles'],[]);self.assertEqual(report['portfolio']['sequence'],0)
    def test_live_configuration_absent_not_pass(self):
        from astra_multicycle.__main__ import execute
        with tempfile.TemporaryDirectory() as tmp,patch.dict('os.environ',{},clear=True):
            r=execute(tmp);self.assertEqual(r['status'],'NOT_EXECUTED');self.assertEqual(r['code'],'multicycle_configuration_missing')
