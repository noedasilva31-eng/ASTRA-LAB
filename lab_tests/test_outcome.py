import ast
import copy
import hashlib
import json
import socket
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from astra_intelligence_lab.fusion import create_fusion_record, validate_fusion_record
from astra_intelligence_lab.integrity import canonical, sha256_json
from astra_intelligence_lab.launch import analyze_launch
from astra_intelligence_lab.liquidity import analyze_liquidity
from astra_intelligence_lab.non_influence import attest_non_influence, capture_astra_baseline
from astra_intelligence_lab.outcome import create_outcome_record, validate_outcome_record
from astra_intelligence_lab.session import replay_lab
from astra_intelligence_lab.store import LabStore


def sources(event="event", cutoff=20):
    launch = analyze_launch(
        event_id=event, pool="pool", mint="mint", cutoff_ns=cutoff,
        observations=[{"observed_ns": 10, "kind": "swap", "provenance": {"frame": 1}}],
    )
    liquidity = analyze_liquidity(
        event_id=event, pool="pool", mint="mint", cutoff_ns=cutoff,
        observations=[{"quote_reserve_raw": 1_000, "base_reserve_raw": 500,
                       "observed_ns": 10, "provenance": {"frame": 2}}],
    )
    return launch, liquidity


def fusion(event="event", cutoff=20):
    launch, liquidity = sources(event, cutoff)
    return create_fusion_record([launch, liquidity]).document()


def outcome(source=None, duration=10, result=None, status="OBSERVED", provenance=None):
    source = source or fusion()
    end = source["cutoff_ns"] + duration
    if result is None and status in {"OBSERVED", "INCOMPLETE_COVERAGE"}:
        result = {"future_snapshot": {"quote_reserve_raw": 1_200, "observed_ns": end}}
    missing = ["price"] if status != "OBSERVED" else []
    return create_outcome_record(
        source, horizon_duration_ns=duration, assessment_ns=end + 2,
        outcome_observed_ns=end if status in {"OBSERVED", "INCOMPLETE_COVERAGE"} else None,
        outcome_available_ns=end + 1 if status in {"OBSERVED", "INCOMPLETE_COVERAGE"} else None,
        input_hashes=["a" * 64],
        provenance=provenance if provenance is not None else [{"observed_ns": end, "availability_ns": end + 1}],
        coverage="COMPLETE" if status == "OBSERVED" else "PARTIAL",
        status=status, missing=missing, result=result,
    )


class OutcomeContractTests(unittest.TestCase):
    def test_valid_fusion_produces_valid_deterministic_outcome(self):
        first = outcome().document()
        second = outcome().document()
        self.assertEqual(first, second)
        self.assertEqual(validate_outcome_record(first), first)
        self.assertTrue(first["shadow_only"])
        self.assertEqual(first["decision_effect"], "NONE")

    def test_horizon_result_and_provenance_change_identity(self):
        baseline = outcome().document()
        self.assertNotEqual(baseline["outcome_id"], outcome(duration=11).document()["outcome_id"])
        changed_result = outcome(result={"future_snapshot": {"quote_reserve_raw": 1_201, "observed_ns": 30}}).document()
        self.assertNotEqual(baseline["outcome_id"], changed_result["outcome_id"])
        changed_provenance = outcome(provenance=[{"observed_ns": 30, "availability_ns": 31, "source": "archive-b"}]).document()
        self.assertNotEqual(baseline["outcome_id"], changed_provenance["outcome_id"])

    def test_json_key_order_does_not_change_identity(self):
        record = outcome().document()
        shuffled = {key: record[key] for key in reversed(record)}
        shuffled["horizon"] = {key: record["horizon"][key] for key in reversed(record["horizon"])}
        self.assertEqual(validate_outcome_record(shuffled)["outcome_id"], record["outcome_id"])

    def test_invalid_temporal_values_and_context_are_refused(self):
        record = outcome().document()
        for field, value, error in (
            ("outcome_observed_ns", 20, "outcome_observed_before_horizon"),
            ("outcome_available_ns", 20, "invalid_outcome_availability"),
            ("assessment_ns", 20, "outcome_assessment_not_future"),
        ):
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, error):
                changed = copy.deepcopy(record); changed.pop("outcome_id"); changed[field] = value
                validate_outcome_record(changed)
        with self.assertRaisesRegex(ValueError, "invalid_outcome_horizon"):
            create_outcome_record(fusion(), horizon_duration_ns=0, assessment_ns=22,
                                  outcome_observed_ns=21, outcome_available_ns=22,
                                  input_hashes=["a" * 64], provenance=[], coverage="COMPLETE",
                                  status="OBSERVED", missing=[], result={"value": 1}).document()
        changed = copy.deepcopy(record); changed.pop("outcome_id"); changed["pool"] = "other"
        changed["outcome_id"] = sha256_json(changed)
        with self.assertRaisesRegex(ValueError, "outcome_fusion_context_mismatch"):
            validate_outcome_record(changed, {fusion()["fusion_id"]: fusion()})

    def test_statuses_preserve_unknown_missing_incomplete_and_not_yet(self):
        unknown = outcome(status="UNKNOWN", result=None, provenance=[]).document()
        missing = outcome(status="MISSING", result=None, provenance=[]).document()
        incomplete = outcome(status="INCOMPLETE_COVERAGE").document()
        source = fusion()
        not_yet = create_outcome_record(
            source, horizon_duration_ns=10, assessment_ns=25,
            outcome_observed_ns=None, outcome_available_ns=None,
            input_hashes=["b" * 64], provenance=[], coverage="NONE",
            status="NOT_AVAILABLE_YET", missing=["horizon_not_complete"], result=None,
        ).document()
        self.assertIsNone(unknown["result"])
        self.assertIsNone(missing["result"])
        self.assertNotEqual(missing["result"], 0)
        self.assertEqual(not_yet["status"], "NOT_AVAILABLE_YET")
        self.assertEqual(incomplete["status"], "INCOMPLETE_COVERAGE")
        self.assertNotEqual({unknown["status"], missing["status"], not_yet["status"]}, {"OBSERVED"})

    def test_actions_are_forbidden(self):
        with self.assertRaisesRegex(ValueError, "shadow_decision_forbidden"):
            outcome(result={"recommendation": "BUY", "observed_ns": 30}).document()


class OutcomeStoreTests(unittest.TestCase):
    def append_sources(self, store):
        launch, liquidity = sources()
        source_fusion = create_fusion_record([launch, liquidity])
        store.append(launch); store.append(liquidity); store.append(source_fusion)
        return launch, liquidity, source_fusion.document()

    def test_source_must_exist_and_multiple_horizons_are_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = LabStore(Path(tmp) / "lab.sqlite")
            with self.assertRaisesRegex(ValueError, "outcome_fusion_not_in_store"):
                store.append(outcome())
            launch, liquidity, source = self.append_sources(store)
            first, second = outcome(source), outcome(source, duration=20)
            old_ids = (launch.document()["analysis_id"], liquidity.document()["analysis_id"], source["fusion_id"])
            self.assertTrue(store.append(first)); self.assertFalse(store.append(first)); self.assertTrue(store.append(second))
            replayed = store.replay()
            self.assertEqual(old_ids, (replayed[0]["analysis_id"], replayed[1]["analysis_id"], replayed[2]["fusion_id"]))
            self.assertNotEqual(replayed[3]["outcome_id"], replayed[4]["outcome_id"])
            store.close()

    def test_offline_readonly_replay_and_legacy_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "lab.sqlite"; store = LabStore(path)
            _, _, source = self.append_sources(store); store.append(outcome(source)); expected = store.replay(); store.close()
            before = path.read_bytes()
            with patch.object(socket, "create_connection", side_effect=AssertionError("network used")):
                receipt = replay_lab(path)
            self.assertEqual(receipt["records"], expected); self.assertFalse(receipt["network_used"])
            self.assertEqual(path.read_bytes(), before)

    def test_corrupt_fusion_and_rehashed_outcome_tampering_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = LabStore(Path(tmp) / "lab.sqlite"); _, _, source = self.append_sources(store); store.append(outcome(source))
            store.db.execute("DROP TRIGGER no_UPDATE_lab_records")
            # Change the outcome source and recompute the chain hash, but not a valid source relationship.
            row = store.db.execute("SELECT document,previous FROM lab_records WHERE seq=4").fetchone()
            document = json.loads(row[0]); document["source_fusion_id"] = "f" * 64
            document.pop("outcome_id"); document["outcome_id"] = sha256_json(document)
            encoded = canonical(document); digest = sha256_json([4, encoded, row[1]])
            store.db.execute("UPDATE lab_records SET analysis_id=?,document=?,hash=? WHERE seq=4",
                             (document["outcome_id"], encoded, digest)); store.db.commit()
            with self.assertRaisesRegex(ValueError, "outcome_fusion_not_in_store"):
                store.replay()
            store.close()

        with tempfile.TemporaryDirectory() as tmp:
            store = LabStore(Path(tmp) / "lab.sqlite"); _, _, source = self.append_sources(store)
            store.db.execute("DROP TRIGGER no_UPDATE_lab_records")
            row = store.db.execute("SELECT document,previous FROM lab_records WHERE seq=3").fetchone()
            corrupted = json.loads(row[0])
            corrupted["agents"]["LaunchAgentV0"]["analysis_id"] = "e" * 64
            corrupted.pop("fusion_id"); corrupted["fusion_id"] = sha256_json(corrupted)
            encoded = canonical(corrupted); digest = sha256_json([3, encoded, row[1]])
            store.db.execute("UPDATE lab_records SET analysis_id=?,document=?,hash=? WHERE seq=3",
                             (corrupted["fusion_id"], encoded, digest)); store.db.commit()
            with self.assertRaisesRegex(ValueError, "fusion_analysis_not_in_store"):
                store.append(outcome(source))
            store.close()

    def test_update_delete_refused_and_scale(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = LabStore(Path(tmp) / "lab.sqlite"); _, _, source = self.append_sources(store)
            for duration in range(1, 51):
                store.append(outcome(source, duration=duration))
            self.assertEqual(len(store.replay()), 53)
            with self.assertRaises(sqlite3.IntegrityError): store.db.execute("UPDATE lab_records SET document='{}'")
            store.db.rollback()
            with self.assertRaises(sqlite3.IntegrityError): store.db.execute("DELETE FROM lab_records")
            store.db.rollback(); store.close()


class OutcomeLeakageAndIsolationTests(unittest.TestCase):
    def test_outcome_cannot_be_injected_into_fusion_or_historical_analysis(self):
        launch, liquidity = sources(); source = create_fusion_record([launch, liquidity]).document()
        future = outcome(source).document()
        original_ids = (launch.document()["analysis_id"], liquidity.document()["analysis_id"], source["fusion_id"])
        injected = copy.deepcopy(source); injected["outcome"] = future
        with self.assertRaisesRegex(ValueError, "invalid_fusion_record_fields"):
            validate_fusion_record(injected)
        historical = launch.document(); historical["input_hashes"] = [future["outcome_id"]]
        with self.assertRaisesRegex(ValueError, "shadow_analysis_hash_mismatch"):
            from astra_intelligence_lab.contracts import validate_envelope
            validate_envelope(historical)
        changed_classification = launch.document(); changed_classification["classification"] = "UNKNOWN"
        with self.assertRaises(ValueError):
            from astra_intelligence_lab.contracts import validate_envelope
            validate_envelope(changed_classification)
        self.assertEqual(original_ids, (launch.document()["analysis_id"], liquidity.document()["analysis_id"], source["fusion_id"]))

    def test_outcome_run_does_not_modify_astra_state_or_import_runtime(self):
        for path in Path("astra_intelligence_lab").glob("*.py"):
            tree = ast.parse(path.read_text())
            modules = {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
            self.assertFalse(any(name == "astra" or name.startswith("astra_") for name in modules), path)
        for base in [Path("astra"), *[p for p in Path(".").glob("astra_*") if p.is_dir() and p.name != "astra_intelligence_lab"]]:
            for path in base.glob("*.py"):
                self.assertNotIn("astra_intelligence_lab", path.read_text())
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "astra"; (root / "state").mkdir(parents=True)
            raw = sqlite3.connect(root / "raw.sqlite")
            raw.execute("CREATE TABLE frames(seq INTEGER PRIMARY KEY,document TEXT,previous TEXT,hash TEXT)")
            for seq, kind in enumerate(("brain_decision", "position_health"), 1):
                doc = canonical({"kind": kind, "metadata": {"id": kind}})
                raw.execute("INSERT INTO frames VALUES(?,?,?,?)", (seq, doc, "0" * 64, sha256_json(doc)))
            raw.commit(); raw.close()
            paper = sqlite3.connect(root / "state" / "paper.sqlite")
            paper.execute("CREATE TABLE ledger(seq INTEGER PRIMARY KEY,id TEXT,doc TEXT,prev TEXT,hash TEXT)")
            paper.commit(); paper.close()
            before_files = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob("*") if p.is_file()}
            before = capture_astra_baseline(root)
            store = LabStore(Path(tmp) / "lab.sqlite"); launch, liquidity = sources()
            source = create_fusion_record([launch, liquidity]); store.append(launch); store.append(liquidity); store.append(source)
            store.append(outcome(source.document())); store.close()
            after = capture_astra_baseline(root)
            after_files = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob("*") if p.is_file()}
            attestation = attest_non_influence(before, after)
            self.assertEqual(before_files, after_files); self.assertTrue(attestation["unchanged"])
            self.assertEqual(attestation["lab_writes_to_astra"], 0); self.assertFalse(attestation["network_used"])


if __name__ == "__main__":
    unittest.main()
