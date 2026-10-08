import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from astra_intelligence_lab.contracts import FORBIDDEN_DECISIONS
from astra_intelligence_lab.integrity import canonical, sha256_json
from astra_intelligence_lab.liquidity import (
    LiquidityConfigV0,
    analyze_dataset_decision,
    analyze_liquidity,
    history_as_of,
)
from astra_intelligence_lab.non_influence import attest_non_influence, capture_astra_baseline
from astra_intelligence_lab.session import replay_lab
from astra_intelligence_lab.store import LabStore


def observation(quote=1_000, base=500, at=10, slot=100):
    return {
        "quote_reserve_raw": quote,
        "base_reserve_raw": base,
        "observed_ns": at,
        "slot": slot,
        "provenance": {"frame": slot},
    }


def quote(impact=25, size=100, at=10, slot=100):
    return {
        "quote_impact_bps": impact,
        "quote_size_raw": size,
        "observed_ns": at,
        "slot": slot,
        "provenance": {"frame": slot + 1},
    }


def analyze(observations=(), quote_value=None, cutoff=20):
    return analyze_liquidity(
        event_id="event-1",
        pool="pool-1",
        mint="mint-1",
        cutoff_ns=cutoff,
        observations=observations,
        quote=quote_value,
    ).document()


class LiquidityFeatureTests(unittest.TestCase):
    def test_known_reserves_produce_exact_features(self):
        result = analyze([observation()], quote(), 20)["result"]
        features = result["features"]
        self.assertEqual(features["quote_reserve_raw"]["value"], 1_000)
        self.assertEqual(features["base_reserve_raw"]["value"], 500)
        self.assertEqual(features["reserve_ratio"]["value"], {"numerator": 2, "denominator": 1})
        self.assertEqual(features["quote_impact_bps"]["value"], 25)
        self.assertEqual(features["quote_size_raw"]["value"], 100)
        self.assertEqual(features["quote_age_ns"]["value"], 10)
        self.assertEqual(features["observations_count"]["value"], 1)
        self.assertEqual(result["decision_effect"], "NONE")

    def test_missing_reserves_remain_unknown(self):
        row = {"observed_ns": 10, "slot": 100, "provenance": {"frame": 1}}
        document = analyze([row], quote())
        features = document["result"]["features"]
        self.assertEqual(features["quote_reserve_raw"]["status"], "UNKNOWN")
        self.assertIsNone(features["quote_reserve_raw"]["value"])
        self.assertEqual(features["base_reserve_raw"]["status"], "UNKNOWN")
        self.assertIsNone(features["reserve_ratio"]["value"])

    def test_missing_quote_is_unknown_not_zero(self):
        document = analyze([observation()])
        features = document["result"]["features"]
        self.assertIsNone(features["quote_impact_bps"]["value"])
        self.assertEqual(features["quote_impact_bps"]["status"], "UNKNOWN")
        self.assertIsNone(features["quote_size_raw"]["value"])
        self.assertIsNone(features["quote_age_ns"]["value"])
        self.assertIn("quote", document["missing"])

    def test_no_inputs_produce_unknown_null_result(self):
        document = analyze()
        self.assertEqual(document["classification"], "UNKNOWN")
        self.assertIsNone(document["result"])
        self.assertTrue(document["missing"])

    def test_future_observation_and_quote_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "shadow_future_information"):
            analyze([observation(at=21)], cutoff=20)
        with self.assertRaisesRegex(ValueError, "shadow_future_information"):
            analyze([observation()], quote(at=21), cutoff=20)

    def test_future_history_is_not_selected_and_old_analysis_is_stable(self):
        rows = [observation(at=10), observation(1_500, 600, at=30, slot=101)]
        prefix = history_as_of(rows, 20)
        self.assertEqual(len(prefix), 1)
        before = analyze(prefix, quote(), 20)
        after = analyze(history_as_of(rows + [observation(2_000, 700, at=40, slot=102)], 20), quote(), 20)
        self.assertEqual(before, after)

    def test_reserve_changes_span_and_gap_are_exact(self):
        rows = [observation(1_000, 500, 10, 100), observation(1_250, 400, 16, 101)]
        features = analyze(rows, quote(at=16), 20)["result"]["features"]
        self.assertEqual(features["quote_reserve_change_bps"]["value"], 2_500)
        self.assertEqual(features["base_reserve_change_bps"]["value"], -2_000)
        self.assertEqual(features["observation_span_ns"]["value"], 6)
        self.assertEqual(features["maximum_observed_gap_ns"]["value"], 6)

    def test_rational_arithmetic_is_canonical_and_no_float_is_emitted(self):
        value = analyze([observation(10, 3)], quote())
        ratio = value["result"]["features"]["reserve_ratio"]["value"]
        self.assertEqual(ratio, {"numerator": 10, "denominator": 3})

        def walk(item):
            if isinstance(item, dict):
                for child in item.values():
                    yield from walk(child)
            elif isinstance(item, list):
                for child in item:
                    yield from walk(child)
            else:
                yield item

        self.assertFalse(any(isinstance(item, float) for item in walk(value)))

    def test_executable_depth_is_always_unknown_without_curve(self):
        depth = analyze([observation()], quote())["result"]["features"]["executable_depth"]
        self.assertEqual(depth["status"], "UNKNOWN")
        self.assertIsNone(depth["value"])
        self.assertIn("multi-size", depth["reason"])

    def test_stale_and_elevated_impact_are_descriptive_versioned_labels(self):
        config = LiquidityConfigV0(freshness_ns=5, impact_elevated_bps=100)
        document = analyze_liquidity(
            event_id="e",
            pool="p",
            mint="m",
            cutoff_ns=20,
            observations=[observation(at=10)],
            quote=quote(impact=100, at=10),
            config=config,
        ).document()
        self.assertIn("STALE", document["result"]["labels"])
        self.assertIn("IMPACT_ELEVATED", document["result"]["labels"])
        self.assertEqual(document["result"]["features"]["quote_reserve_raw"]["status"], "STALE")
        self.assertEqual(document["result"]["features"]["quote_impact_bps"]["status"], "STALE")
        self.assertEqual(document["result"]["configuration"]["version"], "LiquidityConfigV0")
        self.assertIn("NOT_DECISION_THRESHOLDS", document["result"]["configuration"]["semantics"])

    def test_outputs_contain_no_forbidden_decision(self):
        encoded = json.dumps(analyze([observation()], quote())).upper()
        for action in FORBIDDEN_DECISIONS | {"ENTER", "EXIT", "ALLOW", "DENY"}:
            self.assertNotIn(f'"{action}"', encoded)


class LiquidityDatasetAndPersistenceTests(unittest.TestCase):
    def decision(self, event_id, at, quote_reserve, base_reserve):
        def datum(value, name):
            return {
                "value": value,
                "status": "FRESH",
                "available_at": at,
                "slot": at,
                "provenance": {"field": name, "event": event_id},
            }

        return {
            "id": "decision-" + event_id,
            "state": {
                "identity": {"event_id": event_id, "pool": "pool", "token": "mint"},
                "clock": {"availability_time": at, "decision_time": at},
                "coverage": {"scope": "OBSERVED_SUBSET"},
                "market": {
                    "quote_reserve": datum(quote_reserve, "quote"),
                    "base_reserve": datum(base_reserve, "base"),
                    "quote_impact_bps": datum(20, "impact"),
                    "size_raw": datum(100, "size"),
                },
            },
        }

    def test_dataset_adapter_does_not_use_future_decisions(self):
        target = self.decision("target", 20, 1_100, 500)
        future = self.decision("future", 30, 9_999, 1)
        prior = self.decision("prior", 10, 1_000, 500)
        before = analyze_dataset_decision({"decisions": [prior, target]}, "target").document()
        after = analyze_dataset_decision({"decisions": [prior, target, future]}, "target").document()
        self.assertEqual(before, after)
        self.assertEqual(before["result"]["features"]["quote_reserve_change_bps"]["value"], 1_000)

    def test_store_redelivery_and_offline_replay_are_identical(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "lab.sqlite"
            store = LabStore(path)
            envelope = analyze_liquidity(
                event_id="e", pool="p", mint="m", cutoff_ns=20,
                observations=[observation()], quote=quote(),
            )
            self.assertTrue(store.append(envelope))
            self.assertFalse(store.append(envelope))
            expected = store.replay()
            store.close()
            self.assertEqual(replay_lab(path)["records"], expected)

    def test_liquidity_run_does_not_modify_astra_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "state").mkdir()
            raw = sqlite3.connect(root / "raw.sqlite")
            raw.execute("CREATE TABLE frames(seq INTEGER PRIMARY KEY,document TEXT,previous TEXT,hash TEXT)")
            for seq, kind in enumerate(("brain_decision", "position_health"), 1):
                document = canonical({"kind": kind, "metadata": {"id": kind}})
                raw.execute("INSERT INTO frames VALUES(?,?,?,?)", (seq, document, "0" * 64, sha256_json(document)))
            raw.commit(); raw.close()
            paper = sqlite3.connect(root / "state" / "paper.sqlite")
            paper.execute("CREATE TABLE ledger(seq INTEGER PRIMARY KEY,id TEXT,doc TEXT,prev TEXT,hash TEXT)")
            paper.commit(); paper.close()
            before = capture_astra_baseline(root)
            store = LabStore(root.parent / "lab.sqlite")
            store.append(analyze_liquidity(event_id="e", pool="p", mint="m", cutoff_ns=20, observations=[observation()], quote=quote()))
            store.close()
            after = capture_astra_baseline(root)
            attestation = attest_non_influence(before, after)
            self.assertTrue(attestation["unchanged"])
            self.assertTrue(attestation["archive_unchanged"])
            self.assertTrue(attestation["ledger_unchanged"])
            self.assertTrue(attestation["brain_decisions_unchanged"])
            self.assertTrue(attestation["position_health_unchanged"])


if __name__ == "__main__":
    unittest.main()
