import copy
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from astra_intelligence_lab.integrity import sha256_json
from astra_intelligence_lab.outcome import MAX_TIMESTAMP_NS, create_outcome_record, validate_outcome_record
from astra_intelligence_lab.store import LabStore
from lab_tests.test_outcome import fusion, outcome, sources


def without_identity(document):
    value = copy.deepcopy(document)
    value.pop("outcome_id", None)
    return value


class OutcomeIdentityAuditTests(unittest.TestCase):
    def test_every_semantic_field_changes_content_identity(self):
        original = outcome().document()
        mutations = {
            "source_fusion_id": lambda value: value.__setitem__("source_fusion_id", "b" * 64),
            "pool": lambda value: value.__setitem__("pool", "other-pool"),
            "mint": lambda value: value.__setitem__("mint", "other-mint"),
            "event_id": lambda value: value.__setitem__("event_id", "other-event"),
            "source_cutoff_ns": lambda value: value.__setitem__("source_cutoff_ns", 19),
            "horizon": lambda value: value["horizon"].__setitem__("duration_ns", 11),
            "ends_at_ns": lambda value: value["horizon"].__setitem__("ends_at_ns", 31),
            "assessment_ns": lambda value: value.__setitem__("assessment_ns", 33),
            "outcome_observed_ns": lambda value: value.__setitem__("outcome_observed_ns", 31),
            "outcome_available_ns": lambda value: value.__setitem__("outcome_available_ns", 32),
            "input_hashes": lambda value: value.__setitem__("input_hashes", ["c" * 64]),
            "provenance": lambda value: value["provenance"][0].__setitem__("source", "other"),
            "coverage": lambda value: value.__setitem__("coverage", "PARTIAL"),
            "status": lambda value: value.__setitem__("status", "INCOMPLETE_COVERAGE"),
            "missing": lambda value: value.__setitem__("missing", ["price"]),
            "result": lambda value: value["result"].__setitem__("extra", "different"),
            "version": lambda value: value.__setitem__("outcome_version", "OutcomeRecordV1"),
            "shadow_only": lambda value: value.__setitem__("shadow_only", False),
            "decision_effect": lambda value: value.__setitem__("decision_effect", "OTHER"),
        }
        original_body = without_identity(original)
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                changed = copy.deepcopy(original_body)
                mutate(changed)
                self.assertNotEqual(original["outcome_id"], sha256_json(changed))

    def test_mapping_order_and_new_process_timezone_locale_are_stable(self):
        record = outcome().document()
        reordered = {key: record[key] for key in reversed(record)}
        reordered["result"] = {
            key: record["result"][key] for key in reversed(record["result"])
        }
        reordered["provenance"] = [
            {key: record["provenance"][0][key] for key in reversed(record["provenance"][0])}
        ]
        self.assertEqual(validate_outcome_record(reordered)["outcome_id"], record["outcome_id"])
        script = "from lab_tests.test_outcome import outcome; print(outcome().document()['outcome_id'])"
        identities = []
        for timezone in ("UTC", "Pacific/Honolulu"):
            run = subprocess.run(
                [sys.executable, "-B", "-c", script],
                cwd=Path(__file__).resolve().parents[1],
                env=dict(os.environ, TZ=timezone, LC_ALL="C", PYTHONDONTWRITEBYTECODE="1"),
                check=True, capture_output=True, text=True, timeout=20,
            )
            identities.append(run.stdout.strip())
        self.assertEqual(identities, [record["outcome_id"], record["outcome_id"]])


class XYBoundaryAndHorizonAuditTests(unittest.TestCase):
    def assert_invalid(self, mutate, error):
        record = without_identity(outcome().document())
        mutate(record)
        with self.assertRaisesRegex(ValueError, error):
            validate_outcome_record(record)

    def test_all_temporal_boundary_violations_are_rejected(self):
        self.assert_invalid(lambda d: d["provenance"][0].__setitem__("availability_ns", 20),
                            "outcome_information_not_future")
        self.assert_invalid(lambda d: d.__setitem__("outcome_observed_ns", 29),
                            "outcome_observed_before_horizon")
        self.assert_invalid(lambda d: d.__setitem__("outcome_available_ns", 29),
                            "invalid_outcome_availability")
        self.assert_invalid(lambda d: d.__setitem__("assessment_ns", 30),
                            "invalid_outcome_availability")
        self.assert_invalid(lambda d: d["provenance"][0].__setitem__("observed_ns", 33),
                            "outcome_information_after_availability")
        source = fusion()
        falsified = without_identity(outcome(source).document())
        falsified["source_cutoff_ns"] = source["cutoff_ns"] - 1
        falsified["horizon"]["ends_at_ns"] -= 1
        with self.assertRaisesRegex(ValueError, "outcome_fusion_context_mismatch"):
            validate_outcome_record(falsified, {source["fusion_id"]: source})

    def test_positive_exact_and_extreme_horizons(self):
        with self.assertRaisesRegex(ValueError, "invalid_outcome_horizon"):
            outcome(duration=0).document()
        source = fusion(cutoff=MAX_TIMESTAMP_NS - 2)
        extreme = create_outcome_record(
            source, horizon_duration_ns=1, assessment_ns=MAX_TIMESTAMP_NS,
            outcome_observed_ns=MAX_TIMESTAMP_NS - 1, outcome_available_ns=MAX_TIMESTAMP_NS,
            input_hashes=["d" * 64],
            provenance=[{"observed_ns": MAX_TIMESTAMP_NS - 1, "availability_ns": MAX_TIMESTAMP_NS}],
            coverage="COMPLETE", status="OBSERVED", missing=[], result={"value": 1},
        ).document()
        self.assertEqual(extreme["horizon"]["ends_at_ns"], MAX_TIMESTAMP_NS - 1)
        with self.assertRaisesRegex(ValueError, "outcome_horizon_overflow"):
            create_outcome_record(
                source, horizon_duration_ns=3, assessment_ns=MAX_TIMESTAMP_NS,
                outcome_observed_ns=MAX_TIMESTAMP_NS, outcome_available_ns=MAX_TIMESTAMP_NS,
                input_hashes=["d" * 64], provenance=[], coverage="COMPLETE",
                status="OBSERVED", missing=[], result={"value": 1},
            ).document()

    def test_not_available_and_observed_are_separated_by_horizon_end(self):
        source = fusion()
        pending = create_outcome_record(
            source, horizon_duration_ns=10, assessment_ns=29,
            outcome_observed_ns=None, outcome_available_ns=None,
            input_hashes=["e" * 64], provenance=[], coverage="NONE",
            status="NOT_AVAILABLE_YET", missing=["horizon_not_complete"], result=None,
        ).document()
        self.assertEqual(pending["status"], "NOT_AVAILABLE_YET")
        changed = without_identity(pending); changed["assessment_ns"] = 30
        with self.assertRaisesRegex(ValueError, "outcome_horizon_already_elapsed"):
            validate_outcome_record(changed)


class OutcomeStatusAuditTests(unittest.TestCase):
    def test_valid_statuses_remain_distinct(self):
        documents = {
            "OBSERVED": outcome().document(),
            "UNKNOWN": outcome(status="UNKNOWN", result=None, provenance=[]).document(),
            "MISSING": outcome(status="MISSING", result=None, provenance=[]).document(),
            "INCOMPLETE_COVERAGE": outcome(status="INCOMPLETE_COVERAGE").document(),
        }
        documents["NOT_AVAILABLE_YET"] = create_outcome_record(
            fusion(), horizon_duration_ns=10, assessment_ns=29,
            outcome_observed_ns=None, outcome_available_ns=None,
            input_hashes=["f" * 64], provenance=[], coverage="NONE",
            status="NOT_AVAILABLE_YET", missing=["horizon_not_complete"], result=None,
        ).document()
        self.assertEqual(set(documents), {value["status"] for value in documents.values()})
        for name in ("UNKNOWN", "MISSING", "NOT_AVAILABLE_YET"):
            self.assertIsNone(documents[name]["result"])
            self.assertNotEqual(documents[name]["result"], 0)
        self.assertTrue(documents["INCOMPLETE_COVERAGE"]["missing"])
        self.assertNotEqual(documents["INCOMPLETE_COVERAGE"]["coverage"], "COMPLETE")

    def test_invalid_status_result_missing_timestamp_and_coverage_combinations(self):
        cases = []
        observed_missing = without_identity(outcome().document())
        observed_missing["missing"] = ["price"]
        cases.append((observed_missing, "observed_outcome_must_be_complete"))
        observed_partial = without_identity(outcome().document())
        observed_partial["coverage"] = "PARTIAL"
        cases.append((observed_partial, "observed_outcome_must_be_complete"))
        observed_no_provenance = without_identity(outcome().document())
        observed_no_provenance["provenance"] = []
        cases.append((observed_no_provenance, "observed_outcome_requires_provenance"))
        incomplete_complete = without_identity(outcome(status="INCOMPLETE_COVERAGE").document())
        incomplete_complete["coverage"] = "COMPLETE"
        cases.append((incomplete_complete, "non_observed_outcome_cannot_be_complete"))
        missing_result = without_identity(outcome(status="MISSING", result=None, provenance=[]).document())
        missing_result["result"] = {"value": -1}
        cases.append((missing_result, "absent_outcome_requires_null"))
        unknown_timestamp = without_identity(outcome(status="UNKNOWN", result=None, provenance=[]).document())
        unknown_timestamp["outcome_observed_ns"] = 30
        cases.append((unknown_timestamp, "absent_outcome_requires_null"))
        for document, error in cases:
            with self.subTest(error=error), self.assertRaisesRegex(ValueError, error):
                validate_outcome_record(document)


class StoreCompatibilityAuditTests(unittest.TestCase):
    def test_envelope_only_fusion_and_outcome_prefixes_all_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            launch, liquidity = sources()
            store = LabStore(Path(tmp) / "lab.sqlite")
            store.append(launch)
            self.assertEqual([r["schema"] for r in store.replay()], ["ShadowAnalysisEnvelopeV0"])
            store.append(liquidity)
            source = __import__("astra_intelligence_lab.fusion", fromlist=["create_fusion_record"]).create_fusion_record([launch, liquidity])
            store.append(source)
            self.assertEqual(store.replay()[-1]["schema"], "AgentFusionRecordV0")
            store.append(outcome(source.document()))
            self.assertEqual(store.replay()[-1]["schema"], "OutcomeRecordV0")
            store.close()


class RealOfflineCorpusAuditTests(unittest.TestCase):
    def test_archived_outcome_candidate_is_hashed_but_not_contract_complete(self):
        path = Path("position_handoff/offline-resume/state/engine.sqlite")
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        self.assertEqual(before, "d61646d3c37a9a60af10b65ffab3c6aa512bef1ab188d4ef1d8675e7fc597b7f")
        database = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            total, populated, pools, horizons = database.execute(
                "SELECT count(*),sum(document is not null),count(distinct pool),"
                "count(distinct horizon) FROM outcomes"
            ).fetchone()
            candidate = json.loads(database.execute(
                "SELECT document FROM outcomes WHERE document is not null"
            ).fetchone()[0])
        finally:
            database.close()
        self.assertEqual((total, populated, pools, horizons), (95, 1, 19, 5))
        self.assertIn("observed_ns", candidate)
        self.assertNotIn("availability_ns", candidate)
        self.assertNotIn("available_at", candidate)
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before)


if __name__ == "__main__":
    unittest.main()
