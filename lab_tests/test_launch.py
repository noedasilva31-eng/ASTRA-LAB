import ast
import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from astra_intelligence_lab.integrity import canonical, sha256_json
from astra_intelligence_lab.launch import (
    BLOCKED_DIMENSION,
    LaunchConfigV0,
    analyze_dataset_decision,
    analyze_launch,
    history_as_of,
)
from astra_intelligence_lab.liquidity import analyze_liquidity
from astra_intelligence_lab.non_influence import attest_non_influence, capture_astra_baseline
from astra_intelligence_lab.session import replay_lab
from astra_intelligence_lab.store import LabStore


def observation(
    at=10,
    slot=100,
    kind="swap",
    pool_age=None,
    quote_reserve=None,
    base_reserve=None,
    volume=None,
    swaps=None,
):
    return {
        "observed_ns": at,
        "slot": slot,
        "kind": kind,
        "pool_age_seconds": pool_age,
        "quote_reserve_raw": quote_reserve,
        "base_reserve_raw": base_reserve,
        "volume_quote_raw": volume,
        "swaps_observed": swaps,
        "provenance": {"frame": slot, "event": f"event-{slot}"},
    }


def analyze(rows=(), cutoff=20, config=LaunchConfigV0()):
    return analyze_launch(
        event_id="event-target",
        pool="pool-1",
        mint="mint-1",
        cutoff_ns=cutoff,
        observations=rows,
        config=config,
    ).document()


class LaunchFeatureTests(unittest.TestCase):
    def test_determinism_and_content_addressed_identity(self):
        rows = [observation(10), observation(15, slot=101), observation(20, slot=102)]
        first = analyze(rows, 20)
        second = analyze(list(reversed(rows)), 20)
        self.assertEqual(first, second)
        self.assertEqual(first["analysis_id"], second["analysis_id"])
        unsigned = {key: value for key, value in first.items() if key != "analysis_id"}
        self.assertEqual(first["analysis_id"], sha256_json(unsigned))
        self.assertTrue(first["shadow_only"])
        self.assertEqual(first["agent"], "LaunchAgentV0")

    def test_observable_age_creation_and_arrival_features(self):
        rows = [
            observation(10, 100, "pool_created", pool_age=0),
            observation(14, 101, pool_age=4),
            observation(20, 102, pool_age=10),
        ]
        features = analyze(rows, 20)["result"]["features"]
        self.assertEqual(features["first_observed_ns"]["value"], 10)
        self.assertEqual(features["time_since_first_observation_ns"]["value"], 10)
        self.assertEqual(features["observations_count"]["value"], 3)
        self.assertEqual(features["observation_span_ns"]["value"], 10)
        self.assertEqual(features["maximum_observed_gap_ns"]["value"], 6)
        self.assertEqual(features["observed_pool_age_seconds"]["value"], 10)
        self.assertEqual(features["observed_pool_creation_ns"]["value"], 10)
        self.assertEqual(features["time_since_observed_pool_creation_ns"]["value"], 10)

    def test_exact_reserve_volume_and_window_transaction_evolution(self):
        rows = [
            observation(10, 100, quote_reserve=1_000, base_reserve=500, volume=100, swaps=2),
            observation(20, 101, quote_reserve=1_250, base_reserve=400, volume=160, swaps=5),
        ]
        features = analyze(rows, 20)["result"]["features"]
        self.assertEqual(features["quote_reserve_change_bps"]["value"], 2_500)
        self.assertEqual(features["base_reserve_change_bps"]["value"], -2_000)
        self.assertEqual(features["observed_window_volume_change_raw"]["value"], 60)
        self.assertEqual(features["observed_window_swaps_change"]["value"], 3)

    def test_activity_direction_uses_equal_time_halves_without_threshold(self):
        rows = [observation(10), observation(18, slot=101), observation(19, slot=102), observation(20, slot=103)]
        result = analyze(rows, 20)["result"]
        self.assertIn("ACTIVITY_INCREASING", result["labels"])
        self.assertEqual(result["configuration"]["semantics"], "DESCRIPTIVE_V0_NOT_A_DECISION_THRESHOLD")
        self.assertIsNotNone(result["features"]["arrival_velocity"]["value"])
        self.assertIsNotNone(result["features"]["activity_acceleration"]["value"])

    def test_unknown_is_null_and_insufficient_data_is_explicit(self):
        document = analyze([observation()])
        result = document["result"]
        self.assertIn("INSUFFICIENT_DATA", result["labels"])
        self.assertIsNone(result["features"]["activity_acceleration"]["value"])
        self.assertIsNone(result["features"]["quote_reserve_change_bps"]["value"])
        self.assertIsNone(result["features"]["buy_count"]["value"])
        self.assertNotEqual(result["features"]["buy_count"]["value"], 0)

    def test_no_observations_produce_unknown_null_result(self):
        document = analyze()
        self.assertEqual(document["classification"], "UNKNOWN")
        self.assertIsNone(document["result"])
        self.assertTrue(document["missing"])

    def test_blocked_layout_dimensions_remain_unknown(self):
        features = analyze([observation()])["result"]["features"]
        for key in ("token_deployment_time", "bonding_curve_phase", "migration_status", "deployed_layout_extensions"):
            self.assertEqual(features[key]["status"], "UNKNOWN")
            self.assertIsNone(features[key]["value"])
            self.assertIn(BLOCKED_DIMENSION, features[key]["reason"])

    def test_stale_is_explicit_without_substitution(self):
        document = analyze([observation(at=10)], cutoff=20, config=LaunchConfigV0(freshness_ns=5))
        self.assertIn("STALE", document["result"]["labels"])
        self.assertEqual(document["result"]["features"]["latest_observed_ns"]["status"], "STALE")
        self.assertEqual(document["result"]["features"]["freshness_age_ns"]["value"], 10)

    def test_provenance_and_all_available_times_are_retained(self):
        row = observation()
        row.update(availability_ns=9, available_at=8, decision_time=10, as_of=10)
        document = analyze([row])
        self.assertEqual(document["provenance"][0]["ref"], row["provenance"])
        self.assertEqual(document["result"]["features"]["first_observed_ns"]["provenance"], row["provenance"])

    def test_outputs_have_no_trading_judgment_or_decision(self):
        document = analyze([observation()])
        self.assertEqual(document["result"]["decision_effect"], "NONE")
        encoded = json.dumps(document).upper()
        for forbidden in (
            "BUY", "SELL", "HOLD", "CANDIDATE_BUY", "EXIT_CANDIDATE",
            "GOOD_LAUNCH", "BAD_LAUNCH", "AVOID", "PROMISING", "HIGH_POTENTIAL",
        ):
            self.assertNotIn(f'"{forbidden}"', encoded)


class LaunchTemporalAndPersistenceTests(unittest.TestCase):
    def test_future_information_is_rejected_for_every_supported_time_key(self):
        for key in ("observed_ns", "availability_ns", "available_at", "decision_time", "as_of"):
            row = observation(at=10)
            row[key] = 21
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "shadow_future_information"):
                analyze([row], cutoff=20)

    def test_future_history_is_excluded_and_old_analysis_never_changes(self):
        prefix = [observation(10), observation(15, slot=101), observation(20, slot=102)]
        future = observation(30, slot=103, quote_reserve=9_999)
        before = analyze(history_as_of(prefix, 20), 20)
        after = analyze(history_as_of(prefix + [future], 20), 20)
        self.assertEqual(before, after)

    def test_dataset_adapter_ignores_future_decisions(self):
        def decision(event_id, at, volume):
            def datum(value, name):
                return {"value": value, "available_at": at, "status": "FRESH", "provenance": {"field": name}}
            return {
                "id": "decision-" + event_id,
                "state": {
                    "identity": {"event_id": event_id, "pool": "pool", "token": "mint"},
                    "clock": {"availability_time": at, "decision_time": at, "slot": at},
                    "coverage": {"scope": "OBSERVED_SUBSET"},
                    "market": {
                        "pool_age_seconds": datum(at, "age"),
                        "quote_reserve": datum(1_000 + at, "quote"),
                        "base_reserve": datum(500, "base"),
                        "volume": datum(volume, "volume"),
                        "swaps": datum(3, "swaps"),
                    },
                },
            }
        prior = decision("prior", 10, 100)
        target = decision("target", 20, 150)
        future = decision("future", 30, 9_999)
        before = analyze_dataset_decision({"decisions": [prior, target]}, "target").document()
        after = analyze_dataset_decision({"decisions": [prior, target, future]}, "target").document()
        self.assertEqual(before, after)

    def test_replay_offline_and_redelivery_are_identical(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "lab.sqlite"
            store = LabStore(path)
            envelope = analyze_launch(event_id="e", pool="p", mint="m", cutoff_ns=20, observations=[observation()])
            self.assertTrue(store.append(envelope))
            self.assertFalse(store.append(envelope))
            expected = store.replay()
            store.close()
            before = path.read_bytes()
            self.assertEqual(replay_lab(path)["records"], expected)
            self.assertEqual(path.read_bytes(), before)

    def test_launch_and_liquidity_coexist_without_agent_dependency(self):
        launch = analyze([observation()])
        liquidity = analyze_liquidity(
            event_id="event-target", pool="pool-1", mint="mint-1", cutoff_ns=20,
            observations=[{"quote_reserve_raw": 1_000, "base_reserve_raw": 500, "observed_ns": 10, "provenance": {"frame": 1}}],
        ).document()
        self.assertEqual(launch["agent"], "LaunchAgentV0")
        self.assertEqual(liquidity["agent"], "LiquidityAgentV0")
        self.assertNotEqual(launch["analysis_id"], liquidity["analysis_id"])
        launch_tree = ast.parse(Path("astra_intelligence_lab/launch.py").read_text())
        imported = {node.module for node in ast.walk(launch_tree) if isinstance(node, ast.ImportFrom)}
        self.assertNotIn(".liquidity", imported)

    def test_launch_run_does_not_modify_astra_files_or_semantic_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "astra"
            (root / "state").mkdir(parents=True)
            raw = sqlite3.connect(root / "raw.sqlite")
            raw.execute("CREATE TABLE frames(seq INTEGER PRIMARY KEY,document TEXT,previous TEXT,hash TEXT)")
            for seq, kind in enumerate(("brain_decision", "position_health"), 1):
                document = canonical({"kind": kind, "metadata": {"id": kind}})
                raw.execute("INSERT INTO frames VALUES(?,?,?,?)", (seq, document, "0" * 64, sha256_json(document)))
            raw.commit(); raw.close()
            paper = sqlite3.connect(root / "state" / "paper.sqlite")
            paper.execute("CREATE TABLE ledger(seq INTEGER PRIMARY KEY,id TEXT,doc TEXT,prev TEXT,hash TEXT)")
            paper.commit(); paper.close()
            before_files = {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in root.rglob("*") if path.is_file()}
            before = capture_astra_baseline(root)
            store = LabStore(Path(tmp) / "lab.sqlite")
            store.append(analyze_launch(event_id="e", pool="p", mint="m", cutoff_ns=20, observations=[observation()]))
            store.close()
            after = capture_astra_baseline(root)
            after_files = {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in root.rglob("*") if path.is_file()}
            self.assertEqual(before_files, after_files)
            self.assertTrue(attest_non_influence(before, after)["unchanged"])


if __name__ == "__main__":
    unittest.main()
