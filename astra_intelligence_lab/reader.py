"""Strict read-only readers for canonical datasets and SessionFreezeV0."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from .contracts import assert_cutoff, assert_unknown_is_not_zero
from .integrity import sha256_file, sha256_json


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise ValueError(code)


def _strict_json(path: Path) -> dict[str, Any]:
    _require(path.is_file(), "lab_input_missing")
    with path.open("r", encoding="utf-8") as stream:
        value = json.load(stream)
    _require(isinstance(value, dict), "lab_input_not_object")
    return value


@dataclass(frozen=True)
class LabInput:
    dataset: Mapping[str, Any]
    dataset_sha256: str
    source_kind: str
    source_identity: str
    network_used: bool = False


def _validate_dataset(value: dict[str, Any]) -> LabInput:
    digest = value.get("dataset_sha256")
    _require(isinstance(digest, str) and len(digest) == 64, "dataset_hash_missing")
    payload = dict(value)
    payload.pop("dataset_sha256")
    _require(sha256_json(payload) == digest, "dataset_hash_mismatch")
    _require(isinstance(value.get("schema"), str), "dataset_schema_missing")
    assert_unknown_is_not_zero(value)
    frozen = MappingProxyType(value)
    return LabInput(frozen, digest, "canonical_dataset", digest)


def read_canonical_dataset(path: str | Path) -> LabInput:
    """Read and verify a dataset without opening network or writable resources."""
    return _validate_dataset(_strict_json(Path(path)))


def read_session_freeze(folder: str | Path) -> LabInput:
    """Verify the content-addressed freeze and consume its canonical dataset read-only."""
    root = Path(folder)
    manifest = _strict_json(root / "manifest.json")
    _require(manifest.get("schema") == "SessionFreezeV0", "unsupported_freeze_schema")
    freeze_id = manifest.get("freeze_id")
    unsigned = dict(manifest)
    unsigned.pop("freeze_id", None)
    _require(isinstance(freeze_id, str) and sha256_json(unsigned) == freeze_id, "freeze_manifest_hash_mismatch")
    files = manifest.get("files")
    _require(isinstance(files, dict) and "dataset.json" in files, "freeze_files_missing")
    for name, digest in files.items():
        relative = Path(name)
        _require(not relative.is_absolute() and ".." not in relative.parts, "freeze_path_invalid")
        _require(isinstance(digest, str) and sha256_file(root / relative) == digest, "freeze_file_hash_mismatch")
    result = _validate_dataset(_strict_json(root / "dataset.json"))
    _require(result.dataset_sha256 == manifest.get("dataset_sha256"), "freeze_dataset_hash_mismatch")
    return LabInput(result.dataset, result.dataset_sha256, "session_freeze", freeze_id, False)


def validate_inputs_as_of(records: Any, cutoff_ns: int) -> None:
    """Public cutoff gate for any future shadow computation."""
    _require(type(cutoff_ns) is int and cutoff_ns >= 0, "invalid_cutoff")
    assert_cutoff(records, cutoff_ns)
