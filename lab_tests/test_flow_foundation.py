import copy
import hashlib
import json
import socket
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from astra_intelligence_lab.flow import FlowObservationV0, observations_available_at, validate_flow_observation
from astra_intelligence_lab.integrity import canonical, sha256_json
from astra_intelligence_lab.store import LabStore
from astra_intelligence_lab.store_v1 import IncrementalLabStoreV1
from lab_tests.test_outcome import fusion, outcome, sources


def flow(available=20, observed=18, event="event", amount=100):
    return FlowObservationV0(
        observation_type="SWAP",
        pool="pool",
        mint="mint",
        wallets={"user": "wallet"},
        signature="signature",
        slot=123,
        event_id=event,
        instruction_index=4,
        inner_instruction_index=1,
        event_time=10,
        observed_ns=observed,
        availability_ns=available,
        source_hashes=("a" * 64,),
        provenance={"archive": "fixture", "raw_sha256": "a" * 64},
        values={"input_amount_raw": amount, "unit": "raw"},
        coverage="OBSERVED_SUBSET",
        missing_dimensions=(),
    )


class FlowObservationContractTests(unittest.TestCase):
    def test_content_identity_determinism_and_mapping_order(self):
        first = flow().document()
        second = flow().document()
        reordered = {key: first[key] for key in reversed(first)}
        reordered["wallets"] = {key: first["wallets"][key] for key in reversed(first["wallets"])}
        reordered["values"] = {key: first["values"][key] for key in reversed(first["values"])}
        self.assertEqual(first, second)
        self.assertEqual(validate_flow_observation(reordered)["observation_id"], first["observation_id"])
        self.assertNotEqual(first["observation_id"], flow(amount=101).document()["observation_id"])

    def test_unknown_is_null_and_declared_never_zero(self):
        unknown = FlowObservationV0(
            observation_type="TRANSFER_IN", pool=None, mint=None, wallets={}, signature=None,
            slot=None, event_id=None, instruction_index=None, inner_instruction_index=None,
            event_time=None, observed_ns=10, availability_ns=11,
            source_hashes=("b" * 64,), provenance={"archive": "partial"},
            values={"amount": {"status": "UNKNOWN", "value": None}}, coverage="PARTIAL",
            missing_dimensions=("pool", "mint", "wallets", "signature", "slot", "event_id",
                                "instruction_index", "inner_instruction_index", "event_time", "amount"),
        ).document()
        self.assertIsNone(unknown["values"]["amount"]["value"])
        changed = copy.deepcopy(unknown); changed.pop("observation_id")
        changed["values"]["amount"]["value"] = 0
        with self.assertRaisesRegex(ValueError, "unknown_must_be_null"):
            validate_flow_observation(changed)

    def test_late_arrival_and_future_cutoff_use_availability_only(self):
        late = flow(observed=100, available=110)
        early_chain_event = late.document()
        self.assertEqual(early_chain_event["event_time"], 10)
        self.assertEqual(observations_available_at([late], 109), [])
        self.assertEqual(observations_available_at([late], 110), [early_chain_event])
        future = flow(observed=120, available=119)
        with self.assertRaisesRegex(ValueError, "invalid_flow_availability_time"):
            future.document()
        future_knowledge = flow().document(); future_knowledge.pop("observation_id")
        future_knowledge["values"]["available_at"] = 21
        with self.assertRaisesRegex(ValueError, "flow_future_information"):
            validate_flow_observation(future_knowledge)

    def test_provenance_and_redelivery_are_preserved(self):
        document = flow().document()
        self.assertEqual(document["provenance"]["raw_sha256"], "a" * 64)
        self.assertEqual(document["source_hashes"], ["a" * 64])
        self.assertEqual(
            observations_available_at([document, document], 20),
            [document, document],
        )

    def test_wallet_judgments_scores_and_decisions_are_forbidden(self):
        for values, error in (
            ({"wallet_label": "SMART_MONEY"}, "flow_wallet_judgment_forbidden"),
            ({"flow_score": 10}, "flow_evaluation_field_forbidden"),
            ({"recommendation": "observe"}, "flow_evaluation_field_forbidden"),
            ({"action": "BUY"}, "flow_evaluation_field_forbidden"),
        ):
            with self.subTest(values=values), self.assertRaisesRegex(ValueError, error):
                changed = flow().document()
                changed.pop("observation_id")
                changed["values"] = values
                validate_flow_observation(changed)
        for key in (" Action ", "trade-action", "DECISION", "nested score", "Ranking", "Recommendation"):
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "flow_evaluation_field_forbidden"):
                changed = flow().document(); changed.pop("observation_id")
                changed["values"] = {"nested": [{key: "BUY"}]}
                validate_flow_observation(changed)


class ExistingOfflineFlowInventoryTests(unittest.TestCase):
    def test_canonical_swap_and_raw_archives_are_read_only_and_hashed(self):
        engine = Path("position_handoff/offline-resume/state/engine.sqlite")
        raw = Path("position_handoff/offline-resume/raw.sqlite")
        hashes = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in (engine, raw)}
        self.assertEqual(hashes[engine], "d61646d3c37a9a60af10b65ffab3c6aa512bef1ab188d4ef1d8675e7fc597b7f")
        self.assertEqual(hashes[raw], "93795169b1ec65058b572b19762e3a0dcfc280b64ec15f7141f7cf2dcd500562")
        database = sqlite3.connect(engine.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            events = [json.loads(row[0]) for row in database.execute("SELECT document FROM events")]
        finally:
            database.close()
        self.assertEqual(len(events), 51)
        required = {"id", "signature", "slot", "instruction_index", "pool", "base_mint",
                    "wallet", "availability_ns", "event_time", "event_data_sha256", "provenance"}
        self.assertTrue(all(event["kind"] == "swap" and required <= set(event) for event in events))
        database = sqlite3.connect(raw.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            kinds = {}
            for document, in database.execute("SELECT document FROM frames"):
                kind = json.loads(document)["kind"]
                kinds[kind] = kinds.get(kind, 0) + 1
        finally:
            database.close()
        self.assertEqual(kinds["rpc"], 112)
        self.assertEqual(kinds["notification"], 52)
        self.assertEqual(kinds["quote"], 76)
        self.assertEqual({path: hashlib.sha256(path.read_bytes()).hexdigest() for path in hashes}, hashes)


class IncrementalStoreV1Tests(unittest.TestCase):
    def test_append_redelivery_offline_replay_and_full_audit(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "lab-v1.sqlite"
            store = IncrementalLabStoreV1(path)
            self.assertTrue(store.append(flow()))
            self.assertFalse(store.append(flow()))
            expected = store.replay()
            self.assertEqual(store.audit()["records"], 1)
            store.close(); before = path.read_bytes()
            with patch.object(socket, "create_connection", side_effect=AssertionError("network used")):
                readonly = IncrementalLabStoreV1(path, readonly=True)
                self.assertEqual(readonly.replay(), expected)
                self.assertFalse(readonly.audit()["network_used"])
                readonly.close()
            self.assertEqual(path.read_bytes(), before)

    def test_existing_lab_record_families_coexist(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = IncrementalLabStoreV1(Path(tmp) / "lab-v1.sqlite")
            launch, liquidity = sources(); source = __import__(
                "astra_intelligence_lab.fusion", fromlist=["create_fusion_record"]
            ).create_fusion_record([launch, liquidity])
            for record in (launch, liquidity, source, outcome(source.document()), flow()):
                store.append(record)
            self.assertEqual(
                [record["schema"] for record in store.replay()],
                ["ShadowAnalysisEnvelopeV0", "ShadowAnalysisEnvelopeV0", "AgentFusionRecordV0",
                 "OutcomeRecordV0", "FlowObservationV0"],
            )
            store.close()

    def test_v0_is_still_readable_and_v1_refuses_silent_migration(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "lab.sqlite"; old = LabStore(path); old.append(sources()[0]); old.close()
            before = hashlib.sha256(path.read_bytes()).hexdigest()
            check = LabStore(path, readonly=True); self.assertEqual(len(check.replay()), 1); check.close()
            with self.assertRaisesRegex(ValueError, "lab_v1_migration_forbidden"):
                IncrementalLabStoreV1(path)
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before)

    def test_simulated_crash_is_atomic(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "lab-v1.sqlite"; store = IncrementalLabStoreV1(path); store.append(flow())
            store.db.execute(
                "CREATE TRIGGER abort_insert BEFORE INSERT ON lab_records "
                "BEGIN SELECT RAISE(ABORT,'simulated crash'); END"
            ); store.db.commit()
            with self.assertRaises(sqlite3.IntegrityError):
                store.append(flow(event="other"))
            self.assertEqual(len(store.replay()), 1)
            store.close(); reopened = IncrementalLabStoreV1(path); self.assertEqual(len(reopened.replay()), 1); reopened.close()

    def test_corruption_bad_previous_sequence_and_head_are_detected(self):
        def corrupted(field, expression, error):
            with tempfile.TemporaryDirectory() as tmp:
                store = IncrementalLabStoreV1(Path(tmp) / "lab-v1.sqlite")
                store.append(flow()); store.append(flow(event="second"))
                store.db.execute("DROP TRIGGER no_UPDATE_lab_records")
                store.db.execute(f"UPDATE lab_records SET {field}={expression} WHERE seq=2")
                store.db.commit()
                with self.assertRaisesRegex(ValueError, error): store.replay()
                with self.assertRaisesRegex(ValueError, error): store.append(flow(event="third"))
                store.close()
        corrupted("previous", "'" + "f" * 64 + "'", "lab_v1_previous_hash_mismatch")
        corrupted("seq", "3", "lab_v1_sequence_mismatch")
        with tempfile.TemporaryDirectory() as tmp:
            store = IncrementalLabStoreV1(Path(tmp) / "lab-v1.sqlite"); store.append(flow())
            store.db.execute("UPDATE lab_head SET hash=?", ("e" * 64,)); store.db.commit()
            with self.assertRaisesRegex(ValueError, "lab_v1_head_mismatch"): store.append(flow(event="other"))
            store.close()

    def test_interior_corruption_requires_and_fails_full_audit(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = IncrementalLabStoreV1(Path(tmp) / "lab-v1.sqlite")
            for number in range(3): store.append(flow(event=f"event-{number}"))
            store.db.execute("DROP TRIGGER no_UPDATE_lab_records")
            store.db.execute("UPDATE lab_records SET document='{}' WHERE seq=1"); store.db.commit()
            self.assertTrue(store.append(flow(event="event-after-old-corruption")))
            with self.assertRaisesRegex(ValueError, "lab_v1_chain_hash_mismatch"): store.replay()
            store.close()


if __name__ == "__main__":
    unittest.main()
