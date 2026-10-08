"""Dedicated append-only, hash-chained store for Lab outputs only."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Mapping

from .contracts import SCHEMA as ENVELOPE_SCHEMA, validate_envelope
from .integrity import canonical, sha256_json

STORE_SCHEMA = "AstraIntelligenceLabStoreV0"


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise ValueError(code)


def _validate_document(
    document: Mapping[str, Any],
    analyses_by_id: Mapping[str, Mapping[str, Any]] | None = None,
    fusions_by_id: Mapping[str, Mapping[str, Any]] | None = None,
) -> tuple[dict[str, Any], str]:
    if document.get("schema") == ENVELOPE_SCHEMA:
        value = validate_envelope(document)
        return value, value["analysis_id"]
    from .fusion import SCHEMA as FUSION_SCHEMA, validate_fusion_record
    if document.get("schema") == FUSION_SCHEMA:
        value = validate_fusion_record(document, analyses_by_id)
        return value, value["fusion_id"]
    from .outcome import SCHEMA as OUTCOME_SCHEMA, validate_outcome_record
    if document.get("schema") == OUTCOME_SCHEMA:
        value = validate_outcome_record(document, fusions_by_id)
        return value, value["outcome_id"]
    raise ValueError("unsupported_lab_record_schema")


class LabStore:
    def __init__(self, path: str | Path, readonly: bool = False):
        target = Path(path)
        self.readonly = readonly
        if readonly:
            _require(target.is_file(), "lab_store_missing")
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            probe = sqlite3.connect(target.resolve().as_uri() + "?mode=ro", uri=True)
            try:
                _require(
                    probe.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='lab_records'").fetchone()
                    is not None,
                    "foreign_database",
                )
            finally:
                probe.close()
        self.path = target
        self.db = sqlite3.connect(
            target.resolve().as_uri() + "?mode=ro" if readonly else target,
            uri=readonly,
        )
        try:
            if readonly:
                self.db.execute("PRAGMA query_only=ON")
                row = self.db.execute("SELECT schema FROM lab_config").fetchone()
                _require(row is not None and row[0] == STORE_SCHEMA, "immutable_lab_store_schema")
                return
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("PRAGMA synchronous=FULL")
            self.db.executescript(
                """
                CREATE TABLE IF NOT EXISTS lab_config(schema TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS lab_records(
                    seq INTEGER PRIMARY KEY,
                    analysis_id TEXT NOT NULL UNIQUE,
                    document TEXT NOT NULL,
                    previous TEXT NOT NULL,
                    hash TEXT NOT NULL
                );
                """
            )
            row = self.db.execute("SELECT schema FROM lab_config").fetchone()
            if row:
                _require(row[0] == STORE_SCHEMA, "immutable_lab_store_schema")
            else:
                self.db.execute("INSERT INTO lab_config VALUES(?)", (STORE_SCHEMA,))
            for table in ("lab_config", "lab_records"):
                for operation in ("UPDATE", "DELETE"):
                    self.db.execute(
                        f"CREATE TRIGGER IF NOT EXISTS no_{operation}_{table} "
                        f"BEFORE {operation} ON {table} BEGIN SELECT RAISE(ABORT,'immutable'); END"
                    )
            self.db.commit()
        except BaseException:
            self.db.close()
            raise

    def close(self) -> None:
        self.db.close()

    def append(self, envelope: Mapping[str, Any] | Any) -> bool:
        _require(not self.readonly, "readonly_lab_store")
        document = envelope.document() if hasattr(envelope, "document") else dict(envelope)
        from .fusion import SCHEMA as FUSION_SCHEMA
        existing = self.replay()
        known = {
            parsed["analysis_id"]: parsed
            for parsed in existing
            if parsed.get("schema") == ENVELOPE_SCHEMA
        }
        fusions = {
            parsed["fusion_id"]: parsed
            for parsed in existing
            if parsed.get("schema") == FUSION_SCHEMA
        }
        document, analysis_id = _validate_document(document, known, fusions)
        encoded = canonical(document)
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            old = self.db.execute(
                "SELECT document FROM lab_records WHERE analysis_id=?", (analysis_id,)
            ).fetchone()
            if old:
                _require(old[0] == encoded, "lab_identity_conflict")
                return False
            last = self.db.execute("SELECT seq,hash FROM lab_records ORDER BY seq DESC LIMIT 1").fetchone()
            seq = last[0] + 1 if last else 1
            previous = last[1] if last else "0" * 64
            digest = sha256_json([seq, encoded, previous])
            self.db.execute(
                "INSERT INTO lab_records VALUES(?,?,?,?,?)",
                (seq, analysis_id, encoded, previous, digest),
            )
        return True

    def replay(self) -> list[dict[str, Any]]:
        previous = "0" * 64
        expected_seq = 1
        result = []
        known = {}
        fusions = {}
        from .fusion import SCHEMA as FUSION_SCHEMA
        for seq, analysis_id, encoded, prior, digest in self.db.execute(
            "SELECT seq,analysis_id,document,previous,hash FROM lab_records ORDER BY seq"
        ):
            _require(seq == expected_seq and prior == previous, "lab_chain_sequence_mismatch")
            _require(sha256_json([seq, encoded, prior]) == digest, "lab_chain_hash_mismatch")
            document = json.loads(encoded)
            document, identity = _validate_document(document, known, fusions)
            _require(identity == analysis_id, "lab_record_identity_mismatch")
            if document.get("schema") == ENVELOPE_SCHEMA:
                known[identity] = document
            elif document.get("schema") == FUSION_SCHEMA:
                fusions[identity] = document
            result.append(document)
            previous = digest
            expected_seq += 1
        _require(self.db.execute("PRAGMA integrity_check").fetchone()[0] == "ok", "lab_store_integrity")
        return result

    def audit(self) -> dict[str, Any]:
        records = self.replay()
        head = self.db.execute("SELECT hash FROM lab_records ORDER BY seq DESC LIMIT 1").fetchone()
        return {
            "schema": STORE_SCHEMA,
            "records": len(records),
            "head": head[0] if head else "0" * 64,
            "network_used": False,
        }
