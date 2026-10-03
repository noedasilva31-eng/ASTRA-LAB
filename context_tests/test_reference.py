import unittest
from pathlib import Path
from astra_context.audit import audit
ROOT=Path(__file__).resolve().parents[1]
class ReferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.r=audit(ROOT/'context_reference/all-validation-3qductr2')
    def test_actual_windows_replayed_offline(self):
        self.assertEqual(self.r['replay']['status'],'PASS');self.assertEqual(self.r['freeze_verification']['status'],'PASS');self.assertEqual(self.r['decisions'],51);self.assertEqual(self.r['portfolio']['sequence'],0)
    def test_four_null_scores_exact_cause(self):
        r=self.r['evidence_proven_candidates'];self.assertEqual(len(r),4)
        for x in r:self.assertIsNone(x['score']);self.assertEqual(x['observations'],1);self.assertEqual(x['missing'],['momentum_bps']);self.assertLess(x['quote_age_ns'],5000000000)
    def test_quote_orientation_not_silently_supported(self):
        currencies=self.r['quote_currency_audit'];rejected=[x for x in currencies if x['runtime_support']=='REJECT_UNCHANGED']
        self.assertEqual(sum(x['frequency'] for x in rejected),23);self.assertEqual(sum(x['frequency'] for x in rejected if x['classification']=='POTENTIALLY_SUPPORTABLE'),21);self.assertEqual(sum(x['frequency'] for x in rejected if x['classification']=='REJECT'),2)
    def test_other_real_failures_retained(self):
        self.assertTrue(any(x['code']=='devnet_identity_not_verified' for x in self.r['historical_failures_preserved']));self.assertEqual(self.r['result_counts']['price_impact_limit'],24)
