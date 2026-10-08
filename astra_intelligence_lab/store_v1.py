"""Incremental Lab store prototype; V1 is separate and never migrates V0."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Mapping

from .contracts import SCHEMA as ENVELOPE_SCHEMA, validate_envelope
from .flow import SCHEMA as FLOW_SCHEMA, validate_flow_observation
from .fusion import SCHEMA as FUSION_SCHEMA, validate_fusion_record
from .integrity import canonical, sha256_json
from .outcome import SCHEMA as OUTCOME_SCHEMA, validate_outcome_record

STORE_SCHEMA = "AstraIntelligenceLabStoreV1"
GENESIS_HASH = "0" * 64


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise ValueError(code)


def _identity(document: Mapping[str, Any]) -> str:
    fields = {
        ENVELOPE_SCHEMA: "analysis_id",
        FUSION_SCHEMA: "fusion_id",
        OUTCOME_SCHEMA: "outcome_id",
        FLOW_SCHEMA: "observation_id",
    }
    _require(document.get("schema") in fields, "unsupported_lab_v1_record_schema")
    return document[fields[document["schema"]]]


class IncrementalLabStoreV1:
    """O(1)-ish append validation plus an explicitly separate full audit."""

    def __init__(self, path: str | Path, readonly: bool = False):
        target = Path(path)
        self.path = target
        self.readonly = readonly
        if readonly:
            _require(target.is_file(), "lab_v1_store_missing")
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and target.stat().st_size > 0:
            probe = sqlite3.connect(target.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)
            try:
                config = probe.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='lab_config'"
                ).fetchone()
                _require(config is not None, "foreign_lab_v1_database")
                row = probe.execute("SELECT schema FROM lab_config").fetchone()
                _require(row is not None and row[0] == STORE_SCHEMA, "lab_v1_migration_forbidden")
            finally:
                probe.close()
        self.db = sqlite3.connect(
            target.resolve().as_uri() + "?mode=ro&immutable=1" if readonly else target,
            uri=readonly,
        )
        try:
            if readonly:
                self.db.execute("PRAGMA query_only=ON")
                self._validate_schema()
                return
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("PRAGMA synchronous=FULL")
            self.db.executescript(
                """
                CREATE TABLE IF NOT EXISTS lab_config(schema TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS lab_head(
                    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                    seq INTEGER NOT NULL,
                    hash TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS lab_records(
                    seq INTEGER PRIMARY KEY,
                    identity TEXT NOT NULL UNIQUE,
                    schema TEXT NOT NULL,
                    document TEXT NOT NULL,
                    previous TEXT NOT NULL,
                    hash TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS lab_records_schema ON lab_records(schema);
                """
            )
            row = self.db.execute("SELECT schema FROM lab_config").fetchone()
            if row is None:
                self.db.execute("INSERT INTO lab_config VALUES(?)", (STORE_SCHEMA,))
                self.db.execute("INSERT INTO lab_head VALUES(1,0,?)", (GENESIS_HASH,))
            else:
                _require(row[0] == STORE_SCHEMA, "lab_v1_migration_forbidden")
            for operation in ("UPDATE", "DELETE"):
                self.db.execute(
                    f"CREATE TRIGGER IF NOT EXISTS no_{operation}_lab_records "
                    f"BEFORE {operation} ON lab_records BEGIN SELECT RAISE(ABORT,'immutable'); END"
                )
            self.db.commit()
            self._validate_schema()
        except BaseException:
            self.db.close()
            raise

    def _validate_schema(self) -> None:
        row = self.db.execute("SELECT schema FROM lab_config").fetchone()
        _require(row is not None and row[0] == STORE_SCHEMA, "immutable_lab_v1_store_schema")
        head = self.db.execute("SELECT seq,hash FROM lab_head WHERE singleton=1").fetchone()
        _require(head is not None, "lab_v1_head_missing")

    def close(self) -> None:
        self.db.close()

    def _source(self, identity: str) -> dict[str, Any] | None:
        row = self.db.execute(
            "SELECT document FROM lab_records WHERE identity=?", (identity,)
        ).fetchone()
        return json.loads(row[0]) if row else None

    def _validate_new(self, document: Mapping[str, Any]) -> dict[str, Any]:
        schema = document.get("schema")
        if schema == ENVELOPE_SCHEMA:
            return validate_envelope(document)
        if schema == FLOW_SCHEMA:
            return validate_flow_observation(document)
        if schema == FUSION_SCHEMA:
            identifiers = [
                reference["analysis_id"]
                for reference in document.get("agents", {}).values()
                if reference.get("status") == "PRESENT"
            ]
            sources = {identity: source for identity in identifiers if (source := self._source(identity))}
            return validate_fusion_record(document, sources)
        if schema == OUTCOME_SCHEMA:
            identity = document.get("source_fusion_id")
            source = self._source(identity) if isinstance(identity, str) else None
            return validate_outcome_record(document, {identity: source} if source else {})
        raise ValueError("unsupported_lab_v1_record_schema")

    def _verified_head(self) -> tuple[int, str]:
        head = self.db.execute("SELECT seq,hash FROM lab_head WHERE singleton=1").fetchone()
        _require(head is not None, "lab_v1_head_missing")
        tail = self.db.execute(
            "SELECT seq,document,previous,hash FROM lab_records ORDER BY seq DESC LIMIT 2"
        ).fetchall()
        if not tail:
            _require(tuple(head) == (0, GENESIS_HASH), "lab_v1_head_mismatch")
            return head[0], head[1]
        last = tail[0]
        prior_seq, prior_hash = (tail[1][0], tail[1][3]) if len(tail) == 2 else (0, GENESIS_HASH)
        _require(last[0] == prior_seq + 1, "lab_v1_sequence_mismatch")
        _require(last[2] == prior_hash, "lab_v1_previous_hash_mismatch")
        _require(sha256_json([last[0], last[1], last[2]]) == last[3], "lab_v1_chain_hash_mismatch")
        _require(tuple(head) == (last[0], last[3]), "lab_v1_head_mismatch")
        return head[0], head[1]

    def append(self, value: Mapping[str, Any] | Any) -> bool:
        _require(not self.readonly, "readonly_lab_v1_store")
        document = value.document() if hasattr(value, "document") else dict(value)
        try:
            self.db.execute("BEGIN IMMEDIATE")
            seq, previous = self._verified_head()
            document = self._validate_new(document)
            identity = _identity(document)
            encoded = canonical(document)
            old = self.db.execute(
                "SELECT document FROM lab_records WHERE identity=?", (identity,)
            ).fetchone()
            if old:
                _require(old[0] == encoded, "lab_v1_identity_conflict")
                self.db.commit()
                return False
            next_seq = seq + 1
            digest = sha256_json([next_seq, encoded, previous])
            self.db.execute(
                "INSERT INTO lab_records VALUES(?,?,?,?,?,?)",
                (next_seq, identity, document["schema"], encoded, previous, digest),
            )
            self.db.execute(
                "UPDATE lab_head SET seq=?,hash=? WHERE singleton=1",
                (next_seq, digest),
            )
            self.db.commit()
            return True
        except BaseException:
            self.db.rollback()
            raise

    def replay(self) -> list[dict[str, Any]]:
        """Full offline validation; incremental append is not a substitute for this."""
        previous = GENESIS_HASH
        expected_seq = 1
        result: list[dict[str, Any]] = []
        analyses: dict[str, dict[str, Any]] = {}
        fusions: dict[str, dict[str, Any]] = {}
        for seq, identity, schema, encoded, prior, digest in self.db.execute(
            "SELECT seq,identity,schema,document,previous,hash FROM lab_records ORDER BY seq"
        ):
            _require(seq == expected_seq, "lab_v1_sequence_mismatch")
            _require(prior == previous, "lab_v1_previous_hash_mismatch")
            _require(sha256_json([seq, encoded, prior]) == digest, "lab_v1_chain_hash_mismatch")
            document = json.loads(encoded)
            _require(document.get("schema") == schema, "lab_v1_schema_index_mismatch")
            if schema == ENVELOPE_SCHEMA:
                document = validate_envelope(document)
                analyses[identity] = document
            elif schema == FLOW_SCHEMA:
                document = validate_flow_observation(document)
            elif schema == FUSION_SCHEMA:
                document = validate_fusion_record(document, analyses)
                fusions[identity] = document
            elif schema == OUTCOME_SCHEMA:
                document = validate_outcome_record(document, fusions)
            else:
                raise ValueError("unsupported_lab_v1_record_schema")
            _require(_identity(document) == identity, "lab_v1_record_identity_mismatch")
            result.append(document)
            previous = digest
            expected_seq += 1
        head = self._verified_head()
        _require(head == (expected_seq - 1, previous), "lab_v1_head_mismatch")
        _require(self.db.execute("PRAGMA integrity_check").fetchone()[0] == "ok", "lab_v1_sqlite_integrity")
        return result

    def audit(self) -> dict[str, Any]:
        records = self.replay()
        seq, head = self._verified_head()
        return {
            "schema": STORE_SCHEMA,
            "records": len(records),
            "sequence": seq,
            "head": head,
            "network_used": False,
        }
