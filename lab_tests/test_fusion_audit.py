import copy
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from astra_intelligence_lab.fusion import create_fusion_record, validate_fusion_record
from astra_intelligence_lab.integrity import sha256_json
from astra_intelligence_lab.launch import analyze_launch
from astra_intelligence_lab.liquidity import analyze_liquidity
from astra_intelligence_lab.store import LabStore


def launch(event="event", cutoff=20, marker=1):
    return analyze_launch(
        event_id=event,
        pool="pool",
        mint="mint",
        cutoff_ns=cutoff,
        observations=[{"observed_ns": 10, "kind": "swap", "provenance": {"marker": marker}}],
    )


def liquidity(event="event", cutoff=20, marker=2):
    return analyze_liquidity(
        event_id=event,
        pool="pool",
        mint="mint",
        cutoff_ns=cutoff,
        observations=[{
            "quote_reserve_raw": 1_000,
            "base_reserve_raw": 500,
            "observed_ns": 10,
            "provenance": {"marker": marker},
        }],
    )


def rehash(record):
    value = copy.deepcopy(record)
    value.pop("fusion_id", None)
    value["fusion_id"] = sha256_json(value)
    return value


class FusionIdentityAuditTests(unittest.TestCase):
    def test_every_semantic_identity_component_is_covered_by_fusion_id(self):
        original = create_fusion_record([launch(), liquidity()]).document()
        mutations = {
            "pool": lambda value: value.__setitem__("pool", "other-pool"),
            "mint": lambda value: value.__setitem__("mint", "other-mint"),
            "event_id": lambda value: value.__setitem__("event_id", "other-event"),
            "cutoff": lambda value: value.__setitem__("cutoff_ns", 21),
            "analysis_id": lambda value: value["agents"]["LaunchAgentV0"].__setitem__("analysis_id", "a" * 64),
            "agent_version": lambda value: value["agents"]["LaunchAgentV0"].__setitem__("agent_version", "LaunchAgentV0.1"),
            "input_hashes": lambda value: value["agents"]["LaunchAgentV0"].__setitem__("input_hashes", ["b" * 64]),
            "provenance": lambda value: value["agents"]["LaunchAgentV0"].__setitem__("provenance", [{"observed_ns": 9}]),
            "coverage": lambda value: value["agents"]["LaunchAgentV0"].__setitem__("coverage", "PARTIAL_TEST"),
            "missing": lambda value: value["agents"]["LaunchAgentV0"].__setitem__("missing", ["new_dimension"]),
            "classification": lambda value: value["agents"]["LaunchAgentV0"].__setitem__("classification", "OBSERVED"),
            "supported_producers": lambda value: value.__setitem__("supported_producers", ["LaunchAgentV0"]),
            "temporal_rule": lambda value: value.__setitem__("temporal_rule", "OTHER_RULE"),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                changed = copy.deepcopy(original)
                changed.pop("fusion_id")
                mutate(changed)
                self.assertNotEqual(original["fusion_id"], sha256_json(changed))

    def test_json_key_order_has_no_effect(self):
        record = create_fusion_record([launch(), liquidity()]).document()
        shuffled = {key: record[key] for key in reversed(list(record))}
        shuffled["agents"] = {
            name: {key: reference[key] for key in reversed(list(reference))}
            for name, reference in reversed(list(record["agents"].items()))
        }
        self.assertEqual(validate_fusion_record(shuffled)["fusion_id"], record["fusion_id"])

    def test_unexpected_or_malformed_present_reference_fields_are_rejected(self):
        base = create_fusion_record([launch(), liquidity()]).document()
        unexpected = copy.deepcopy(base)
        unexpected["agents"]["LaunchAgentV0"]["unexpected"] = "field"
        with self.assertRaisesRegex(ValueError, "invalid_fusion_agent_reference_fields"):
            validate_fusion_record(rehash(unexpected))
        cases = {
            "invalid_fusion_agent_version": ("agent_version", None),
            "invalid_fusion_analysis_id": ("analysis_id", "g" * 64),
            "invalid_fusion_input_hashes": ("input_hashes", []),
            "invalid_fusion_provenance": ("provenance", "not-a-list"),
            "invalid_fusion_coverage": ("coverage", ""),
            "invalid_fusion_missing_dimensions": ("missing", [0]),
        }
        for error, (field, value) in cases.items():
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, error):
                changed = copy.deepcopy(base)
                changed["agents"]["LaunchAgentV0"][field] = value
                validate_fusion_record(rehash(changed))

    def test_timezone_and_c_locale_do_not_change_identity_in_new_process(self):
        script = """
from astra_intelligence_lab.launch import analyze_launch
from astra_intelligence_lab.liquidity import analyze_liquidity
from astra_intelligence_lab.fusion import create_fusion_record
l=analyze_launch(event_id='e',pool='p',mint='m',cutoff_ns=20,observations=[{'observed_ns':10,'provenance':{'x':1}}])
q=analyze_liquidity(event_id='e',pool='p',mint='m',cutoff_ns=20,observations=[{'quote_reserve_raw':1000,'base_reserve_raw':500,'observed_ns':10,'provenance':{'x':2}}])
print(create_fusion_record([l,q]).document()['fusion_id'])
"""
        values = []
        for timezone in ("UTC", "Pacific/Honolulu"):
            env = dict(os.environ, TZ=timezone, LC_ALL="C", PYTHONDONTWRITEBYTECODE="1")
            result = subprocess.run(
                [sys.executable, "-B", "-c", script],
                cwd=Path(__file__).resolve().parents[1],
                env=env,
                text=True,
                capture_output=True,
                timeout=20,
                check=True,
            )
            values.append(result.stdout.strip())
        self.assertEqual(values[0], values[1])

    def test_fusion_contains_no_future_outcome_payload(self):
        record = create_fusion_record([launch(), liquidity()]).document()
        self.assertNotIn("result", record)
        self.assertNotIn("outcome", json.dumps(record).lower())
        self.assertNotIn("future", json.dumps(record).lower())


class FusionStoreAuditTests(unittest.TestCase):
    def test_update_and_delete_are_both_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = LabStore(Path(tmp) / "lab.sqlite")
            store.append(launch())
            with self.assertRaises(sqlite3.IntegrityError):
                store.db.execute("UPDATE lab_records SET document='{}'")
            store.db.rollback()
            with self.assertRaises(sqlite3.IntegrityError):
                store.db.execute("DELETE FROM lab_records")
            store.db.rollback()
            self.assertEqual(len(store.replay()), 1)
            store.close()

    def test_interrupted_insert_rolls_back_and_reopens_cleanly(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "lab.sqlite"
            store = LabStore(path)
            source = launch()
            store.append(source)
            store.db.execute(
                "CREATE TRIGGER abort_second BEFORE INSERT ON lab_records "
                "WHEN NEW.seq=2 BEGIN SELECT RAISE(ABORT,'simulated interruption'); END"
            )
            store.db.commit()
            with self.assertRaises(sqlite3.IntegrityError):
                store.append(create_fusion_record([source]))
            self.assertEqual(len(store.replay()), 1)
            store.close()
            reopened = LabStore(path)
            self.assertEqual(len(reopened.replay()), 1)
            reopened.close()

    def test_moderate_record_volume_replays_and_unique_identity_is_indexed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "lab.sqlite"
            store = LabStore(path)
            total_fusions = 100
            for number in range(total_fusions):
                event = f"event-{number}"
                source = launch(event=event, marker=number)
                store.append(source)
                store.append(create_fusion_record([source]))
            replayed = store.replay()
            self.assertEqual(len(replayed), total_fusions * 2)
            indexes = store.db.execute("PRAGMA index_list('lab_records')").fetchall()
            self.assertTrue(any(row[2] for row in indexes), indexes)
            plan = store.db.execute(
                "EXPLAIN QUERY PLAN SELECT document FROM lab_records WHERE analysis_id=?",
                (replayed[-1]["fusion_id"],),
            ).fetchall()
            self.assertTrue(any("INDEX" in row[-1].upper() for row in plan), plan)
            self.assertGreater(path.stat().st_size, 0)
            store.close()


if __name__ == "__main__":
    unittest.main()
