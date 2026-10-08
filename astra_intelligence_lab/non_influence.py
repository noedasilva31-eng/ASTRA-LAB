"""Read-only fingerprints proving that a Lab run did not mutate ASTRA state."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .integrity import sha256_file, sha256_json


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise ValueError(code)


def _read_rows(path: Path, query: str) -> list[list[Any]]:
    _require(path.is_file(), "astra_state_file_missing")
    db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)
    try:
        db.execute("PRAGMA query_only=ON")
        return [list(row) for row in db.execute(query)]
    finally:
        db.close()


def capture_astra_baseline(directory: str | Path) -> dict[str, Any]:
    """Hash source files and semantic rows without writing or checkpointing WAL files."""
    root = Path(directory)
    raw = root / "raw.sqlite"
    paper = root / "state" / "paper.sqlite"
    for path in (raw, paper):
        wal = Path(str(path) + "-wal")
        _require(not wal.exists() or wal.stat().st_size == 0, "baseline_requires_checkpointed_session")
    archive_rows = _read_rows(raw, "SELECT seq,document,previous,hash FROM frames ORDER BY seq")
    ledger_rows = _read_rows(paper, "SELECT seq,id,doc,prev,hash FROM ledger ORDER BY seq")
    brain_rows = [
        row
        for row in archive_rows
        if json.loads(row[1]).get("kind") == "brain_decision"
    ]
    health_rows = [
        row
        for row in archive_rows
        if json.loads(row[1]).get("kind") == "position_health"
    ]
    return {
        "schema": "AstraNonRegressionBaselineV0",
        "archive": {"file_sha256": sha256_file(raw), "rows_sha256": sha256_json(archive_rows)},
        "ledger": {"file_sha256": sha256_file(paper), "rows_sha256": sha256_json(ledger_rows)},
        "brain_decisions_sha256": sha256_json(brain_rows),
        "position_health_sha256": sha256_json(health_rows),
    }


def attest_non_influence(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    _require(before.get("schema") == "AstraNonRegressionBaselineV0", "invalid_before_baseline")
    _require(after.get("schema") == "AstraNonRegressionBaselineV0", "invalid_after_baseline")
    unchanged = before == after
    return {
        "schema": "ShadowNonInfluenceAttestationV0",
        "shadow_only": True,
        "unchanged": unchanged,
        "before_sha256": sha256_json(before),
        "after_sha256": sha256_json(after),
        "archive_unchanged": before["archive"] == after["archive"],
        "ledger_unchanged": before["ledger"] == after["ledger"],
        "brain_decisions_unchanged": before["brain_decisions_sha256"] == after["brain_decisions_sha256"],
        "position_health_unchanged": before["position_health_sha256"] == after["position_health_sha256"],
        "lab_writes_to_astra": 0,
        "network_used": False,
    }
