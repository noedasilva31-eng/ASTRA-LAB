"""Distinct Lab manifests and deterministic offline replay receipts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from .integrity import canonical, sha256_file, sha256_json
from .store import LabStore


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise ValueError(code)


def replay_lab(store_path: str | Path) -> dict[str, Any]:
    store = LabStore(store_path, readonly=True)
    try:
        records = store.replay()
        audit = store.audit()
    finally:
        store.close()
    return {
        "schema": "LabReplayV0",
        "records": records,
        "records_sha256": sha256_json(records),
        "store": audit,
        "network_used": False,
    }


def build_session_manifest(
    output: str | Path,
    store_path: str | Path,
    source_identity: str,
    non_influence: dict[str, Any],
    extra_files: Iterable[str | Path] = (),
) -> dict[str, Any]:
    """Write a Lab-only manifest; source ASTRA paths are read but never modified."""
    target = Path(output)
    store = Path(store_path)
    _require(non_influence.get("unchanged") is True, "non_influence_not_proven")
    files = {store.name: sha256_file(store)}
    for item in extra_files:
        path = Path(item)
        files[path.name] = sha256_file(path)
    manifest = {
        "schema": "IntelligenceLabSessionManifestV0",
        "shadow_only": True,
        "source_identity": source_identity,
        "lab_files": dict(sorted(files.items())),
        "non_influence_sha256": sha256_json(non_influence),
        "network_used": False,
        "promotion_allowed": False,
    }
    manifest["session_id"] = sha256_json(manifest)
    encoded = canonical(manifest)
    if target.exists():
        _require(json.loads(target.read_text(encoding="utf-8")) == manifest, "lab_manifest_identity_conflict")
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(encoded, encoding="utf-8")
    return manifest


def verify_session_manifest(path: str | Path, directory: str | Path | None = None) -> dict[str, Any]:
    manifest_path = Path(path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    _require(manifest.get("schema") == "IntelligenceLabSessionManifestV0", "invalid_lab_manifest")
    session_id = manifest.pop("session_id", None)
    _require(sha256_json(manifest) == session_id, "lab_manifest_hash_mismatch")
    root = Path(directory) if directory is not None else manifest_path.parent
    for name, digest in manifest["lab_files"].items():
        relative = Path(name)
        _require(not relative.is_absolute() and ".." not in relative.parts, "lab_manifest_path_invalid")
        _require(sha256_file(root / relative) == digest, "lab_manifest_file_hash_mismatch")
    return {"status": "PASS", "session_id": session_id, "network_used": False}
