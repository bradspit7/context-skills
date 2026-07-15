#!/usr/bin/env python
"""Build and verify complete exact-content sanction packets.

This helper is intentionally evidence-only.  It freezes a declared scope,
derives filesystem/Git evidence, renders the full review artifacts, and verifies
that the reviewed state remains current.  It NEVER applies target bytes, stages,
rolls back, commits, or authenticates that an owner actually approved anything.

Its strongest claim is deliberately narrow:

    mechanically complete for owner-approved declared scope

CLI:
    sanction-packet.py build SPEC.json --out ABSOLUTE_DIR [--hmac-key-file FILE]
    sanction-packet.py decision LOCK.json --verdict approved|rejected
        --evidence-file FILE [--hmac-key-file FILE]
    sanction-packet.py verify LOCK.json --phase pre-decision|pre-apply|
        post-apply|pre-commit|post-commit [--commits FILE]
        [--hmac-key-file FILE]
    sanction-packet.py receipt LOCK.json --out RECEIPT.md
        --failure-point TEXT [--hmac-key-file FILE]
"""

from __future__ import annotations

import argparse
import datetime as dt
import difflib
import hashlib
import hmac
import json
import os
import platform
import secrets
import shutil
import stat
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import Any


VERSION = "1.0.0"
SCHEMA = "sanction-packet/v1"
CLAIM = "mechanically complete for owner-approved declared scope"
EXIT_INVALID = 2
EXIT_INCOMPLETE = 3


class SanctionError(RuntimeError):
    """A fail-closed manifest, evidence, freshness, or decision error."""


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read(path: Path, label: str) -> bytes:
    try:
        if not path.is_file():
            raise SanctionError(f"{label} is not an accessible regular file: {path}")
        return path.read_bytes()
    except OSError as exc:
        raise SanctionError(f"cannot read {label} {path}: {exc}") from exc


def _write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="")


def _json_load(path: Path, label: str) -> Any:
    try:
        return json.loads(_read(path, label).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SanctionError(f"invalid UTF-8 JSON in {label} {path}: {exc}") from exc


def _json_write(path: Path, value: Any) -> None:
    _write_text(path, json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def _expect_object(value: Any, where: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SanctionError(f"{where} must be an object")
    return value


def _expect_list(value: Any, where: str) -> list[Any]:
    if not isinstance(value, list):
        raise SanctionError(f"{where} must be a list")
    return value


def _keys(obj: dict[str, Any], required: set[str], allowed: set[str], where: str) -> None:
    missing = sorted(required - obj.keys())
    unknown = sorted(obj.keys() - allowed)
    if missing:
        raise SanctionError(f"{where} missing required fields: {', '.join(missing)}")
    if unknown:
        raise SanctionError(f"{where} has unknown fields: {', '.join(unknown)}")


def _nonempty(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SanctionError(f"{where} must be a non-empty string")
    return value.strip()


def _choice(value: Any, choices: set[str], where: str) -> str:
    text = _nonempty(value, where)
    if text not in choices:
        raise SanctionError(f"{where} must be one of {sorted(choices)}, got {text!r}")
    return text


def _absolute(value: Any, where: str, *, must_exist: bool = True) -> Path:
    path = Path(_nonempty(value, where)).expanduser()
    if not path.is_absolute():
        raise SanctionError(f"{where} must be absolute: {path}")
    if must_exist and not path.exists():
        raise SanctionError(f"{where} does not exist: {path}")
    return path.resolve(strict=must_exist)


def _relative(value: Any, where: str) -> str:
    text = _nonempty(value, where).replace("\\", "/")
    pure = PurePosixPath(text)
    if pure.is_absolute() or any(part in ("", ".", "..") for part in pure.parts):
        raise SanctionError(f"{where} must be a lexical root-relative path without traversal: {text}")
    return pure.as_posix()


def _within(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=True))
        return True
    except (ValueError, OSError):
        return False


def _is_reparse_or_symlink(path: Path) -> bool:
    try:
        if path.is_symlink():
            return True
        attrs = getattr(path.lstat(), "st_file_attributes", 0)
        flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        return bool(attrs & flag)
    except OSError:
        return False


def _safe_component(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in value)
    return cleaned or "item"


def _identity(data: bytes) -> dict[str, Any]:
    return {"algorithm": "sha256", "value": _sha(data), "bytes": len(data)}


def _hmac_identity(data: bytes, key: bytes, nonce: str, target_id: str, role: str) -> dict[str, Any]:
    # The tag must compare the same bytes across base/target/current roles, so the
    # domain binds packet + target but deliberately not the observation role.
    domain = f"sanction-packet/v1\0{nonce}\0{target_id}\0content\0".encode("utf-8")
    tag = hmac.new(key, domain + data, hashlib.sha256).hexdigest()
    # Length is deliberately withheld for low-entropy sensitive material.
    return {"algorithm": "hmac-sha256", "value": tag, "bytes": "withheld"}


def _key(path_value: str | None, required: bool) -> bytes | None:
    if not path_value:
        if required:
            raise SanctionError("sensitive targets require --hmac-key-file")
        return None
    path = _absolute(path_value, "--hmac-key-file")
    data = _read(path, "HMAC key")
    if len(data) < 32:
        raise SanctionError("HMAC key must contain at least 32 random bytes")
    return data


def _helper_path() -> Path:
    return Path(__file__).resolve()


def _helper_sha() -> str:
    return _sha(_read(_helper_path(), "helper"))


def _git_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_TERMINAL_PROMPT="0",
    )
    if extra:
        env.update(extra)
    return env


def _git(
    root: Path,
    *args: str,
    input_bytes: bytes | None = None,
    extra_env: dict[str, str] | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[bytes]:
    cp = subprocess.run(
        ["git", "-c", "commit.gpgsign=false", "-c", f"core.hooksPath={os.devnull}", *args],
        cwd=root,
        env=_git_env(extra_env),
        input=input_bytes,
        capture_output=True,
    )
    if check and cp.returncode:
        err = cp.stderr.decode("utf-8", "replace").strip()
        raise SanctionError(f"git {' '.join(args)} failed in {root}: {err}")
    return cp


def _zpaths(raw: bytes) -> set[str]:
    return {part.decode("utf-8", "surrogateescape") for part in raw.split(b"\0") if part}


def _git_status(root: Path) -> dict[str, list[str]]:
    return {
        "staged": sorted(_zpaths(_git(root, "diff", "--cached", "--name-only", "-z").stdout)),
        "unstaged": sorted(_zpaths(_git(root, "diff", "--name-only", "-z").stdout)),
        "untracked": sorted(_zpaths(_git(root, "ls-files", "--others", "--exclude-standard", "-z").stdout)),
    }


def _index_snapshot(root: Path) -> dict[str, Any]:
    raw = _git(root, "ls-files", "--stage", "-z").stdout
    entries: list[dict[str, str]] = []
    for record in raw.split(b"\0"):
        if not record:
            continue
        meta, sep, path = record.partition(b"\t")
        if not sep:
            raise SanctionError(f"cannot parse index entry in {root}")
        bits = meta.decode("ascii", "strict").split()
        if len(bits) != 3:
            raise SanctionError(f"cannot parse index metadata in {root}: {meta!r}")
        mode, oid, stage = bits
        entries.append(
            {
                "path": path.decode("utf-8", "surrogateescape"),
                "mode": mode,
                "oid": oid,
                "stage": stage,
            }
        )
    return {"sha256": _sha(raw), "entries": entries}


def _tree_entries(root: Path, revision: str) -> list[dict[str, str]]:
    raw = _git(root, "ls-tree", "-r", "-z", "--full-tree", revision).stdout
    entries: list[dict[str, str]] = []
    for record in raw.split(b"\0"):
        if not record:
            continue
        meta, sep, path = record.partition(b"\t")
        if not sep:
            raise SanctionError(f"cannot parse tree entry in {root}")
        bits = meta.decode("ascii", "strict").split()
        if len(bits) != 3:
            raise SanctionError(f"cannot parse tree metadata in {root}: {meta!r}")
        mode, _kind, oid = bits
        entries.append(
            {
                "path": path.decode("utf-8", "surrogateescape"),
                "mode": mode,
                "oid": oid,
                "stage": "0",
            }
        )
    return entries


def _git_blob_at(root: Path, revision: str, path: str) -> tuple[bytes | None, str]:
    probe = _git(root, "cat-file", "-e", f"{revision}:{path}", check=False)
    if probe.returncode:
        return None, "absent"
    data = _git(root, "show", f"{revision}:{path}").stdout
    raw = _git(root, "ls-tree", "-z", revision, "--", path).stdout
    if not raw:
        raise SanctionError(f"cannot derive mode for {revision}:{path}")
    first = raw.split(b"\0", 1)[0]
    meta = first.split(b"\t", 1)[0].decode("ascii", "strict").split()
    if len(meta) < 1:
        raise SanctionError(f"cannot parse mode for {revision}:{path}")
    mode = meta[0]
    if mode == "160000":
        raise SanctionError(f"submodule target is unsupported in v1: {path}")
    return data, mode


def _decode_text(data: bytes, encoding: str, where: str) -> str:
    try:
        return data.decode(encoding, "strict")
    except (LookupError, UnicodeDecodeError) as exc:
        raise SanctionError(f"{where} is not strict {encoding} text: {exc}") from exc


def _inventory(root: Path) -> dict[str, dict[str, Any]]:
    if not root.is_dir():
        raise SanctionError(f"generated-run root is not a directory: {root}")
    result: dict[str, dict[str, Any]] = {}
    for path in sorted(root.rglob("*")):
        if path.is_dir():
            continue
        if _is_reparse_or_symlink(path):
            raise SanctionError(f"generated inventory rejects reparse/symlink: {path}")
        rel = path.relative_to(root).as_posix()
        result[rel] = _identity(_read(path, "generated output"))
    return result


def _artifact(path: Path) -> dict[str, Any]:
    data = _read(path, "packet artifact")
    return {
        "path": str(path.resolve()),
        "sha256": _sha(data),
        "bytes": len(data),
        "lines": data.count(b"\n") + (1 if data and not data.endswith(b"\n") else 0),
        "hunks": sum(1 for line in data.splitlines() if line.startswith(b"@@ ")),
    }


def _validate_manifest(raw: Any) -> dict[str, Any]:
    spec = _expect_object(raw, "manifest")
    _keys(spec, {"schema", "decision", "roots", "targets", "residue", "generated_groups"}, {"schema", "decision", "roots", "targets", "residue", "generated_groups"}, "manifest")
    if spec["schema"] != SCHEMA:
        raise SanctionError(f"manifest.schema must be {SCHEMA!r}")

    decision = _expect_object(spec["decision"], "decision")
    _keys(decision, {"gate", "actions", "scope", "root_ids", "target_ids"}, {"gate", "actions", "scope", "root_ids", "target_ids"}, "decision")
    gate = _expect_object(decision["gate"], "decision.gate")
    _keys(gate, {"kind", "locator"}, {"kind", "locator"}, "decision.gate")
    _choice(gate["kind"], {"explicit-user", "project-rule", "built-in-stop"}, "decision.gate.kind")
    _nonempty(gate["locator"], "decision.gate.locator")
    actions = [_choice(v, {"apply", "adopt", "commit", "publish", "canonicalize"}, "decision.actions[]") for v in _expect_list(decision["actions"], "decision.actions")]
    if not actions or len(actions) != len(set(actions)):
        raise SanctionError("decision.actions must be non-empty and unique")
    if decision["scope"] != "exact-bytes":
        raise SanctionError("decision.scope must be exact-bytes")

    roots: dict[str, dict[str, Any]] = {}
    for i, value in enumerate(_expect_list(spec["roots"], "roots")):
        root = _expect_object(value, f"roots[{i}]")
        _keys(root, {"id", "kind", "path"}, {"id", "kind", "path", "base_revision"}, f"roots[{i}]")
        ident = _nonempty(root["id"], f"roots[{i}].id")
        if ident in roots:
            raise SanctionError(f"duplicate root id: {ident}")
        kind = _choice(root["kind"], {"git", "filesystem"}, f"roots[{i}].kind")
        path = _absolute(root["path"], f"roots[{i}].path")
        if not path.is_dir() or _is_reparse_or_symlink(path):
            raise SanctionError(f"root must be a physical directory, not reparse/symlink: {path}")
        if kind == "git":
            _nonempty(root.get("base_revision"), f"roots[{i}].base_revision")
        elif "base_revision" in root:
            raise SanctionError(f"filesystem root {ident} cannot declare base_revision")
        root["_path"] = path
        roots[ident] = root

    declared_roots = [_nonempty(v, "decision.root_ids[]") for v in _expect_list(decision["root_ids"], "decision.root_ids")]
    if len(declared_roots) != len(set(declared_roots)) or set(declared_roots) != set(roots):
        raise SanctionError("decision.root_ids must exactly equal the unique roots denominator")

    targets: dict[str, dict[str, Any]] = {}
    path_keys: set[tuple[str, str]] = set()
    sensitive = False
    for i, value in enumerate(_expect_list(spec["targets"], "targets")):
        target = _expect_object(value, f"targets[{i}]")
        allowed = {"id", "root", "path", "entry", "operation", "base_authority", "content", "commit", "relationship", "target_source", "base_source", "old_path", "target_mode"}
        _keys(target, {"id", "root", "path", "entry", "operation", "base_authority", "content", "commit", "relationship"}, allowed, f"targets[{i}]")
        ident = _nonempty(target["id"], f"targets[{i}].id")
        if ident in targets:
            raise SanctionError(f"duplicate target id: {ident}")
        root_id = _nonempty(target["root"], f"targets[{i}].root")
        if root_id not in roots:
            raise SanctionError(f"target {ident} names unknown root {root_id}")
        rel = _relative(target["path"], f"targets[{i}].path")
        key = (root_id, rel.casefold() if os.name == "nt" else rel)
        if key in path_keys:
            raise SanctionError(f"duplicate target path in root {root_id}: {rel}")
        path_keys.add(key)
        entry = _choice(target["entry"], {"pre-apply", "already-applied"}, f"targets[{i}].entry")
        operation = _choice(target["operation"], {"add", "modify", "delete", "rename", "mode-change"}, f"targets[{i}].operation")
        _nonempty(target["base_authority"], f"targets[{i}].base_authority")
        if not isinstance(target["commit"], bool):
            raise SanctionError(f"targets[{i}].commit must be boolean")
        if roots[root_id]["kind"] == "filesystem" and target["commit"]:
            raise SanctionError(f"filesystem target {ident} cannot be marked commit=true")
        if operation == "delete":
            if "target_source" in target:
                raise SanctionError(f"delete target {ident} cannot have target_source")
        else:
            target["_target_source"] = _absolute(target.get("target_source"), f"targets[{i}].target_source")
            if not target["_target_source"].is_file():
                raise SanctionError(f"target source is not a file: {target['_target_source']}")
        if roots[root_id]["kind"] == "filesystem" and operation != "add":
            target["_base_source"] = _absolute(target.get("base_source"), f"targets[{i}].base_source")
            if not target["_base_source"].is_file():
                raise SanctionError(f"base source is not a file: {target['_base_source']}")
        elif "base_source" in target:
            raise SanctionError(f"target {ident} may not declare base_source for this root/operation")
        if operation == "rename":
            target["old_path"] = _relative(target.get("old_path"), f"targets[{i}].old_path")
        elif "old_path" in target:
            raise SanctionError(f"non-rename target {ident} cannot declare old_path")
        if "target_mode" in target:
            mode = _choice(target["target_mode"], {"100644", "100755"}, f"targets[{i}].target_mode")
            target["target_mode"] = mode

        content = _expect_object(target["content"], f"targets[{i}].content")
        kind = _choice(content.get("kind"), {"text", "binary", "generated", "sensitive"}, f"targets[{i}].content.kind")
        if kind == "text":
            _keys(content, {"kind", "encoding"}, {"kind", "encoding"}, f"targets[{i}].content")
            _nonempty(content["encoding"], f"targets[{i}].content.encoding")
        elif kind == "binary":
            _keys(content, {"kind", "owner_access", "inspector"}, {"kind", "owner_access", "inspector"}, f"targets[{i}].content")
            _nonempty(content["owner_access"], f"targets[{i}].content.owner_access")
            inspector = _expect_object(content["inspector"], f"targets[{i}].content.inspector")
            _keys(inspector, {"tool", "scope", "limitations", "result_locator"}, {"tool", "scope", "limitations", "result_locator"}, f"targets[{i}].content.inspector")
            for name in ("tool", "scope", "limitations", "result_locator"):
                _nonempty(inspector[name], f"targets[{i}].content.inspector.{name}")
        elif kind == "generated":
            _keys(content, {"kind", "group", "relative_output"}, {"kind", "group", "relative_output"}, f"targets[{i}].content")
            _nonempty(content["group"], f"targets[{i}].content.group")
            _relative(content["relative_output"], f"targets[{i}].content.relative_output")
        else:
            sensitive = True
            _keys(content, {"kind", "binding", "key_ref", "owner_access"}, {"kind", "binding", "key_ref", "owner_access"}, f"targets[{i}].content")
            if content["binding"] != "hmac-sha256":
                raise SanctionError(f"sensitive target {ident} requires hmac-sha256 binding")
            _nonempty(content["key_ref"], f"targets[{i}].content.key_ref")
            _nonempty(content["owner_access"], f"targets[{i}].content.owner_access")
            if roots[root_id]["kind"] == "git" and target["commit"]:
                raise SanctionError(f"sensitive Git commit target {ident} is unsupported by default")

        relation = _expect_object(target["relationship"], f"targets[{i}].relationship")
        _keys(relation, {"kind"}, {"kind", "group"}, f"targets[{i}].relationship")
        relation_kind = _choice(relation["kind"], {"canonical", "exact-mirror", "adaptation", "independent"}, f"targets[{i}].relationship.kind")
        if relation_kind in {"exact-mirror", "adaptation"}:
            _nonempty(relation.get("group"), f"targets[{i}].relationship.group")
        elif "group" in relation:
            raise SanctionError(f"relationship.group only applies to mirror/adaptation target {ident}")

        target["path"] = rel
        target["_entry"] = entry
        target["_operation"] = operation
        target["_content_kind"] = kind
        targets[ident] = target

    declared_targets = [_nonempty(v, "decision.target_ids[]") for v in _expect_list(decision["target_ids"], "decision.target_ids")]
    if len(declared_targets) != len(set(declared_targets)) or set(declared_targets) != set(targets):
        raise SanctionError("decision.target_ids must exactly equal the unique targets denominator")

    residue: list[dict[str, Any]] = []
    for i, value in enumerate(_expect_list(spec["residue"], "residue")):
        row = _expect_object(value, f"residue[{i}]")
        _keys(row, {"root", "path", "states", "disposition", "reason"}, {"root", "path", "states", "disposition", "reason"}, f"residue[{i}]")
        root_id = _nonempty(row["root"], f"residue[{i}].root")
        if root_id not in roots or roots[root_id]["kind"] != "git":
            raise SanctionError(f"residue[{i}] must name a Git root")
        row["path"] = _relative(row["path"], f"residue[{i}].path")
        states = [_choice(v, {"staged", "unstaged", "untracked"}, f"residue[{i}].states[]") for v in _expect_list(row["states"], f"residue[{i}].states")]
        if not states or len(states) != len(set(states)):
            raise SanctionError(f"residue[{i}].states must be non-empty and unique")
        row["states"] = sorted(states)
        _choice(row["disposition"], {"excluded", "preserve", "leave"}, f"residue[{i}].disposition")
        _nonempty(row["reason"], f"residue[{i}].reason")
        residue.append(row)

    groups: dict[str, dict[str, Any]] = {}
    for i, value in enumerate(_expect_list(spec["generated_groups"], "generated_groups")):
        group = _expect_object(value, f"generated_groups[{i}]")
        _keys(group, {"id", "generator", "command_display", "tool_versions", "inputs", "outputs", "determinism"}, {"id", "generator", "command_display", "tool_versions", "inputs", "outputs", "determinism"}, f"generated_groups[{i}]")
        ident = _nonempty(group["id"], f"generated_groups[{i}].id")
        if ident in groups:
            raise SanctionError(f"duplicate generated group: {ident}")
        _nonempty(group["generator"], f"generated_groups[{i}].generator")
        _nonempty(group["command_display"], f"generated_groups[{i}].command_display")
        versions = [_nonempty(v, f"generated_groups[{i}].tool_versions[]") for v in _expect_list(group["tool_versions"], f"generated_groups[{i}].tool_versions")]
        if not versions:
            raise SanctionError(f"generated_groups[{i}].tool_versions cannot be empty")
        group["_inputs"] = [_absolute(v, f"generated_groups[{i}].inputs[]") for v in _expect_list(group["inputs"], f"generated_groups[{i}].inputs")]
        outputs = [_nonempty(v, f"generated_groups[{i}].outputs[]") for v in _expect_list(group["outputs"], f"generated_groups[{i}].outputs")]
        if not outputs or len(outputs) != len(set(outputs)):
            raise SanctionError(f"generated_groups[{i}].outputs must be non-empty and unique")
        det = _expect_object(group["determinism"], f"generated_groups[{i}].determinism")
        _keys(
            det,
            {"promised", "run_a"},
            {"promised", "run_a", "run_b", "reason"},
            f"generated_groups[{i}].determinism",
        )
        if not isinstance(det["promised"], bool):
            raise SanctionError(f"generated_groups[{i}].determinism.promised must be boolean")
        group["_run_a"] = _absolute(det["run_a"], f"generated_groups[{i}].determinism.run_a")
        if det["promised"]:
            if "run_b" not in det:
                raise SanctionError(f"generated group {ident} promises determinism but omits run_b")
            if "reason" in det:
                raise SanctionError(f"generated group {ident} promises determinism and cannot include a no-promise reason")
            group["_run_b"] = _absolute(det["run_b"], f"generated_groups[{i}].determinism.run_b")
        else:
            if "run_b" in det:
                raise SanctionError(f"generated group {ident} does not promise determinism and cannot claim a second-run comparison")
            group["_determinism_reason"] = _nonempty(
                det.get("reason"), f"generated_groups[{i}].determinism.reason"
            )
        groups[ident] = group

    generated_targets = {tid for tid, target in targets.items() if target["_content_kind"] == "generated"}
    group_outputs = {tid for group in groups.values() for tid in group["outputs"]}
    if generated_targets != group_outputs:
        raise SanctionError("generated group outputs must exactly enumerate every generated target")
    for tid in generated_targets:
        group_id = targets[tid]["content"]["group"]
        if group_id not in groups or tid not in groups[group_id]["outputs"]:
            raise SanctionError(f"generated target {tid} is not owned by its declared group {group_id}")

    spec["_roots"] = roots
    spec["_targets"] = targets
    spec["_residue"] = residue
    spec["_groups"] = groups
    spec["_sensitive"] = sensitive
    return spec


def _mode_for_file(path: Path) -> str:
    if not path.exists():
        return "absent"
    return "100755" if path.stat().st_mode & stat.S_IXUSR else "100644"


def _path_identity(path: Path, *, sensitive: bool, key: bytes | None, nonce: str, target_id: str, role: str) -> dict[str, Any]:
    if not path.exists():
        return {"algorithm": "absent"}
    if not path.is_file() or _is_reparse_or_symlink(path):
        raise SanctionError(f"target path is not a regular physical file: {path}")
    data = _read(path, f"target {target_id} {role}")
    if sensitive:
        if key is None:
            raise SanctionError("sensitive identity requested without HMAC key")
        return _hmac_identity(data, key, nonce, target_id, role)
    return _identity(data)


def _same_identity(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return left.get("algorithm") == right.get("algorithm") and left.get("value") == right.get("value") and left.get("bytes") == right.get("bytes")


def _freeze(path: Path, data: bytes, *, sensitive: bool) -> str | None:
    if sensitive:
        return None
    _write_bytes(path, data)
    return str(path.resolve())


def _target_bytes_and_modes(
    spec: dict[str, Any],
    target: dict[str, Any],
    root_obs: dict[str, Any],
) -> tuple[bytes | None, str, bytes | None, str]:
    root = spec["_roots"][target["root"]]
    op = target["_operation"]
    base_path = target.get("old_path", target["path"])
    if root["kind"] == "git":
        base, base_mode = _git_blob_at(root["_path"], root["base_revision"], base_path)
    elif op == "add":
        base, base_mode = None, "absent"
    else:
        base = _read(target["_base_source"], f"target {target['id']} base source")
        base_mode = _mode_for_file(target["_base_source"])

    if op == "add" and base is not None:
        raise SanctionError(f"add target {target['id']} already exists in its declared base")
    if op != "add" and base is None:
        raise SanctionError(f"{op} target {target['id']} is absent from its declared base")

    if op == "delete":
        target_bytes, target_mode = None, "absent"
    else:
        target_bytes = _read(target["_target_source"], f"target {target['id']} source")
        if "target_mode" in target:
            target_mode = target["target_mode"]
        elif op == "add":
            target_mode = "100644"
        else:
            target_mode = base_mode
    if target_mode == "160000" or base_mode == "160000":
        raise SanctionError(f"submodule mode is unsupported for target {target['id']}")
    return base, base_mode, target_bytes, target_mode


def _current_state(
    spec: dict[str, Any],
    target: dict[str, Any],
    key: bytes | None,
    nonce: str,
) -> dict[str, Any]:
    root = spec["_roots"][target["root"]]
    current = root["_path"] / PurePosixPath(target["path"])
    sensitive = target["_content_kind"] == "sensitive"
    result: dict[str, Any] = {
        "path": str(current.resolve(strict=False)),
        "identity": _path_identity(current, sensitive=sensitive, key=key, nonce=nonce, target_id=target["id"], role="current"),
        "mode": _mode_for_file(current),
    }
    if target["_operation"] == "rename":
        old = root["_path"] / PurePosixPath(target["old_path"])
        result["old_path"] = str(old.resolve(strict=False))
        result["old_identity"] = _path_identity(old, sensitive=sensitive, key=key, nonce=nonce, target_id=target["id"], role="old-current")
        result["old_mode"] = _mode_for_file(old)
    return result


def _freshness_state(target: dict[str, Any], observation: dict[str, Any]) -> str:
    op = target["_operation"]
    entry = target["_entry"]
    current = observation["current"]
    base = observation["base"]
    proposed = observation["target"]
    if entry == "pre-apply":
        if op == "rename":
            good = (
                _same_identity(current["old_identity"], base)
                and current["old_mode"] == observation["base_mode"]
                and current["identity"]["algorithm"] == "absent"
            )
        else:
            good = _same_identity(current["identity"], base) and current["mode"] == observation["base_mode"]
        return "BASE" if good else "DRIFT"
    if op == "delete":
        good = current["identity"]["algorithm"] == "absent" and current["mode"] == "absent"
    elif op == "rename":
        good = (
            _same_identity(current["identity"], proposed)
            and current["mode"] == observation["target_mode"]
            and current["old_identity"]["algorithm"] == "absent"
        )
    else:
        good = _same_identity(current["identity"], proposed) and current["mode"] == observation["target_mode"]
    return "TARGET" if good else "DRIFT"


def _observe_roots(spec: dict[str, Any]) -> dict[str, Any]:
    observed: dict[str, Any] = {}
    for root_id, root in spec["_roots"].items():
        path = root["_path"]
        st = path.stat()
        row: dict[str, Any] = {
            "id": root_id,
            "kind": root["kind"],
            "path": str(path),
            "physical": {"device": st.st_dev, "inode": st.st_ino},
        }
        if root["kind"] == "git":
            inside = _git(path, "rev-parse", "--is-inside-work-tree").stdout.decode().strip()
            if inside != "true":
                raise SanctionError(f"Git root is not a work tree: {path}")
            head = _git(path, "rev-parse", "HEAD").stdout.decode().strip()
            declared = _git(path, "rev-parse", root["base_revision"]).stdout.decode().strip()
            if len(declared) != 40 or head != declared:
                raise SanctionError(f"Git root {root_id} HEAD/base drift: declared {declared}, current {head}")
            branch_cp = _git(path, "symbolic-ref", "--quiet", "--short", "HEAD", check=False)
            branch = branch_cp.stdout.decode().strip() if branch_cp.returncode == 0 else "DETACHED"
            git_dir_text = _git(path, "rev-parse", "--absolute-git-dir").stdout.decode().strip()
            object_text = _git(path, "rev-parse", "--git-path", "objects").stdout.decode().strip()
            object_path = Path(object_text)
            if not object_path.is_absolute():
                object_path = path / object_path
            row.update(
                head=head,
                branch=branch,
                git_dir=str(Path(git_dir_text).resolve()),
                object_dir=str(object_path.resolve()),
                status=_git_status(path),
                index=_index_snapshot(path),
            )
        observed[root_id] = row
    return observed


def _validate_residue(
    spec: dict[str, Any],
    roots_obs: dict[str, Any],
    *,
    allow_all_targets: bool = False,
) -> None:
    expected: dict[tuple[str, str], set[str]] = {}
    for row in spec["_residue"]:
        key = (row["root"], row["path"])
        if key in expected:
            raise SanctionError(f"duplicate residue declaration: {row['root']}:{row['path']}")
        expected[key] = set(row["states"])

    covered: dict[str, set[str]] = {root_id: set() for root_id in spec["_roots"]}
    for target in spec["_targets"].values():
        if spec["_roots"][target["root"]]["kind"] != "git":
            continue
        if allow_all_targets or target["_entry"] == "already-applied":
            covered[target["root"]].add(target["path"])
            if target["_operation"] == "rename":
                covered[target["root"]].add(target["old_path"])

    actual: dict[tuple[str, str], set[str]] = {}
    for root_id, root in spec["_roots"].items():
        if root["kind"] != "git":
            continue
        for state, paths in roots_obs[root_id]["status"].items():
            for path in paths:
                if path in covered[root_id]:
                    continue
                # A pre-apply target already dirty is a base conflict, not residue.
                matching = [
                    target for target in spec["_targets"].values()
                    if target["root"] == root_id and target["_entry"] == "pre-apply"
                    and path in {target["path"], target.get("old_path")}
                ]
                if matching:
                    raise SanctionError(f"pre-apply target already has Git {state} state: {root_id}:{path}")
                actual.setdefault((root_id, path), set()).add(state)
    if actual != expected:
        def show(value: dict[tuple[str, str], set[str]]) -> dict[str, list[str]]:
            return {f"{root}:{path}": sorted(states) for (root, path), states in sorted(value.items())}
        raise SanctionError(f"Git residue denominator mismatch; declared={show(expected)} actual={show(actual)}")


def _observe_generated(spec: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for group_id, group in spec["_groups"].items():
        inv_a = _inventory(group["_run_a"])
        promised = group["determinism"]["promised"]
        if promised:
            inv_b = _inventory(group["_run_b"])
            if inv_a != inv_b:
                raise SanctionError(f"generated group {group_id} promised determinism but run inventories differ")
        inputs = []
        for path in group["_inputs"]:
            inputs.append({"path": str(path), "identity": _identity(_read(path, "generator input"))})
        for target_id in group["outputs"]:
            target = spec["_targets"][target_id]
            rel = _relative(target["content"]["relative_output"], f"target {target_id} generated relative_output")
            if rel not in inv_a:
                raise SanctionError(f"generated target {target_id} output {rel} missing from captured generator run")
            source_id = _identity(_read(target["_target_source"], f"generated target {target_id}"))
            if source_id != inv_a[rel]:
                raise SanctionError(f"generated target {target_id} does not match captured generator output {rel}")
        row = {
            "generator": group["generator"],
            "command_display": group["command_display"],
            "tool_versions": group["tool_versions"],
            "inputs": inputs,
            "outputs": group["outputs"],
            "inventory": inv_a,
            "determinism": "MATCH" if promised else "NOT_PROMISED",
        }
        if not promised:
            row["determinism_reason"] = group["_determinism_reason"]
        result[group_id] = row
    return result


def _observe_targets(
    spec: dict[str, Any],
    roots_obs: dict[str, Any],
    out: Path,
    key: bytes | None,
    nonce: str,
) -> dict[str, Any]:
    observed: dict[str, Any] = {}
    for target_id in spec["decision"]["target_ids"]:
        target = spec["_targets"][target_id]
        base_bytes, base_mode, target_bytes, target_mode = _target_bytes_and_modes(spec, target, roots_obs[target["root"]])
        sensitive = target["_content_kind"] == "sensitive"
        if sensitive:
            assert key is not None
            base_ident = {"algorithm": "absent"} if base_bytes is None else _hmac_identity(base_bytes, key, nonce, target_id, "base")
            target_ident = {"algorithm": "absent"} if target_bytes is None else _hmac_identity(target_bytes, key, nonce, target_id, "target")
        else:
            base_ident = {"algorithm": "absent"} if base_bytes is None else _identity(base_bytes)
            target_ident = {"algorithm": "absent"} if target_bytes is None else _identity(target_bytes)

        suffix = Path(target["path"]).suffix or ".bin"
        base_frozen = None if base_bytes is None else _freeze(out / "bases" / f"{_safe_component(target_id)}{suffix}", base_bytes, sensitive=sensitive)
        target_frozen = None if target_bytes is None else _freeze(out / "targets" / f"{_safe_component(target_id)}{suffix}", target_bytes, sensitive=sensitive)
        current = _current_state(spec, target, key, nonce)
        row: dict[str, Any] = {
            "id": target_id,
            "root": target["root"],
            "path": target["path"],
            "old_path": target.get("old_path"),
            "entry": target["_entry"],
            "operation": target["_operation"],
            "content_kind": target["_content_kind"],
            "commit": target["commit"],
            "relationship": target["relationship"],
            "base_authority": target["base_authority"],
            "base": base_ident,
            "target": target_ident,
            "base_mode": base_mode,
            "target_mode": target_mode,
            "base_frozen": base_frozen,
            "target_frozen": target_frozen,
            "base_source": str(target.get("_base_source", "")) or None,
            "target_source": str(target.get("_target_source", "")) or None,
            "current": current,
            "content": {k: v for k, v in target["content"].items()},
        }
        row["freshness"] = _freshness_state(target, row)
        if row["freshness"] == "DRIFT":
            raise SanctionError(f"target {target_id} is not at its declared {target['_entry']} state")
        observed[target_id] = row
    return observed


def _review_patch_for_root(
    spec: dict[str, Any],
    target_obs: dict[str, Any],
    root_id: str,
    out: Path,
) -> dict[str, Any] | None:
    chunks: list[str] = []
    for target_id in spec["decision"]["target_ids"]:
        target = spec["_targets"][target_id]
        obs = target_obs[target_id]
        if target["root"] != root_id or target["_content_kind"] != "text":
            continue
        encoding = target["content"]["encoding"]
        base_bytes = b"" if obs["base_frozen"] is None else _read(Path(obs["base_frozen"]), f"target {target_id} frozen base")
        target_bytes = b"" if obs["target_frozen"] is None else _read(Path(obs["target_frozen"]), f"target {target_id} frozen target")
        base_text = _decode_text(base_bytes, encoding, f"target {target_id} base")
        target_text = _decode_text(target_bytes, encoding, f"target {target_id} target")
        old_name = target.get("old_path", target["path"])
        chunks.append(f"diff --sanction a/{old_name} b/{target['path']}\n")
        if obs["base_mode"] != obs["target_mode"]:
            chunks.append(f"old mode {obs['base_mode']}\nnew mode {obs['target_mode']}\n")
        if target["_operation"] == "rename":
            chunks.append(f"rename from {target['old_path']}\nrename to {target['path']}\n")
        if base_bytes != target_bytes or target["_operation"] in {"add", "delete"}:
            chunks.extend(
                difflib.unified_diff(
                    base_text.splitlines(keepends=True),
                    target_text.splitlines(keepends=True),
                    fromfile=f"a/{old_name}" if base_bytes else "/dev/null",
                    tofile=f"b/{target['path']}" if target_bytes else "/dev/null",
                    n=3,
                )
            )
        chunks.append("\n")
    if not chunks:
        return None
    path = out / "repos" / _safe_component(root_id) / "review.patch"
    _write_text(path, "".join(chunks))
    return _artifact(path)


def _candidate_for_root(
    spec: dict[str, Any],
    roots_obs: dict[str, Any],
    target_obs: dict[str, Any],
    root_id: str,
    out: Path,
) -> dict[str, Any] | None:
    root = spec["_roots"][root_id]
    commit_targets = [
        spec["_targets"][target_id]
        for target_id in spec["decision"]["target_ids"]
        if spec["_targets"][target_id]["root"] == root_id and spec["_targets"][target_id]["commit"]
    ]
    if root["kind"] != "git" or not commit_targets:
        return None
    for target in commit_targets:
        if target["path"] in {".gitattributes", ".gitmodules"} or target.get("old_path") in {".gitattributes", ".gitmodules"}:
            raise SanctionError("v1 fails closed when the sanction transaction changes Git transformation/submodule configuration")

    repo_out = out / "repos" / _safe_component(root_id)
    object_dir = repo_out / "objects"
    object_dir.mkdir(parents=True, exist_ok=True)
    index_path = repo_out / "candidate.index"
    if index_path.exists():
        index_path.unlink()
    real_objects = Path(roots_obs[root_id]["object_dir"])
    env = {
        "GIT_INDEX_FILE": str(index_path.resolve()),
        "GIT_OBJECT_DIRECTORY": str(object_dir.resolve()),
        "GIT_ALTERNATE_OBJECT_DIRECTORIES": str(real_objects.resolve()),
    }
    base = roots_obs[root_id]["head"]
    _git(root["_path"], "read-tree", base, extra_env=env)

    entries: list[dict[str, Any]] = []
    for target in commit_targets:
        target_id = target["id"]
        obs = target_obs[target_id]
        op = target["_operation"]
        if op in {"delete", "rename"}:
            remove_path = target.get("old_path", target["path"])
            _git(root["_path"], "update-index", "--force-remove", "--", remove_path, extra_env=env)
        if op == "delete":
            entries.append(
                {
                    "target": target_id,
                    "operation": op,
                    "path": target["path"],
                    "old_path": target.get("old_path"),
                    "mode": "absent",
                    "blob_oid": "absent",
                    "committed_identity": {"algorithm": "absent"},
                    "committed_artifact": None,
                }
            )
            continue

        frozen = Path(obs["target_frozen"])
        raw = _read(frozen, f"target {target_id} frozen target")
        oid = _git(
            root["_path"],
            "hash-object",
            "-w",
            f"--path={target['path']}",
            "--stdin",
            input_bytes=raw,
            extra_env=env,
        ).stdout.decode().strip()
        committed = _git(root["_path"], "cat-file", "blob", oid, extra_env=env).stdout
        committed_path = repo_out / "committed" / f"{_safe_component(target_id)}.blob"
        _write_bytes(committed_path, committed)
        mode = obs["target_mode"]
        _git(
            root["_path"],
            "update-index",
            "--add",
            "--cacheinfo",
            mode,
            oid,
            target["path"],
            extra_env=env,
        )
        entries.append(
            {
                "target": target_id,
                "operation": op,
                "path": target["path"],
                "old_path": target.get("old_path"),
                "mode": mode,
                "blob_oid": oid,
                "raw_identity": obs["target"],
                "committed_identity": _identity(committed),
                "committed_artifact": str(committed_path.resolve()),
                "filter_changed_bytes": committed != raw,
            }
        )

    tree = _git(root["_path"], "write-tree", extra_env=env).stdout.decode().strip()
    patch_bytes = _git(
        root["_path"],
        "diff",
        "--cached",
        "--binary",
        "--full-index",
        "--find-renames",
        base,
        extra_env=env,
    ).stdout
    patch_path = repo_out / "commit.patch"
    _write_bytes(patch_path, patch_bytes)
    changed_paths = sorted(
        _zpaths(
            _git(
                root["_path"],
                "diff",
                "--cached",
                "--name-only",
                "-z",
                "--find-renames",
                base,
                extra_env=env,
            ).stdout
        )
    )
    if not changed_paths:
        raise SanctionError(f"Git candidate for {root_id} has no effective changes")
    return {
        "root": root_id,
        "base_revision": base,
        "candidate_tree": tree,
        "entries": entries,
        "changed_paths": changed_paths,
        "patch": _artifact(patch_path),
        "temp_index": str(index_path.resolve()),
        "temp_object_dir": str(object_dir.resolve()),
    }


def _packet_id_payload(lock: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in lock.items() if k not in {"packet_id", "packet_artifact"}}


def _id_short(identity: dict[str, Any]) -> str:
    algorithm = identity.get("algorithm", "unknown")
    if algorithm == "absent":
        return "ABSENT"
    value = str(identity.get("value", ""))
    size = identity.get("bytes", "withheld")
    return f"{algorithm}:{value} bytes={size}"


def _md_path(path: str) -> str:
    # Angle brackets preserve spaces in local Markdown link targets.
    return f"<{path}>"


def _render_packet(spec: dict[str, Any], lock: dict[str, Any]) -> str:
    decision = spec["decision"]
    lines = [
        "# Complete sanction packet\n",
        "\n",
        f"**Packet ID:** `{lock['packet_id']}`  \n",
        f"**Claim:** {CLAIM}  \n",
        "**State:** READY FOR OWNER DECISION — NOT APPROVED  \n",
        f"**Built:** {lock['created_at']} on `{lock['machine']}` with helper `{lock['helper']['sha256']}`\n",
        "\n",
        "> This packet does not authenticate the owner, choose the denominator, judge semantic adequacy, or mutate any target. Approval/rejection must cite this exact packet ID.\n",
        "\n",
        "## Decision boundary\n",
        "\n",
        f"- Gate: `{decision['gate']['kind']}` — {decision['gate']['locator']}\n",
        f"- Actions gated: {', '.join(f'`{a}`' for a in decision['actions'])}\n",
        f"- Declared roots: {', '.join(f'`{v}`' for v in decision['root_ids'])}\n",
        f"- Declared targets: {', '.join(f'`{v}`' for v in decision['target_ids'])}\n",
        "\n",
        "## Repository and filesystem roots\n",
        "\n",
        "| Root | Ownership | Physical path | Base / state |\n",
        "|---|---|---|---|\n",
    ]
    for root_id in decision["root_ids"]:
        root = lock["roots"][root_id]
        state = f"HEAD `{root['head']}` · branch `{root['branch']}`" if root["kind"] == "git" else "direct filesystem"
        lines.append(f"| `{root_id}` | `{root['kind']}` | `{root['path']}` | {state} |\n")

    lines.extend(
        [
            "\n",
            "## Complete target denominator\n",
            "\n",
            "Every target is listed separately. No mirror/adaptation row is silently deduplicated.\n",
            "\n",
            "| Target | Root/path | Entry | Operation/mode | Kind/relationship | Base | Proposed target | Presented state |\n",
            "|---|---|---|---|---|---|---|---|\n",
        ]
    )
    for target_id in decision["target_ids"]:
        target = lock["targets"][target_id]
        relation = target["relationship"]["kind"]
        if target["relationship"].get("group"):
            relation += f":{target['relationship']['group']}"
        path = target["path"]
        if target.get("old_path"):
            path = f"{target['old_path']} → {path}"
        lines.append(
            f"| `{target_id}` | `{target['root']}:{path}` | `{target['entry']}` | "
            f"`{target['operation']}` `{target['base_mode']}→{target['target_mode']}` | "
            f"`{target['content_kind']}` / `{relation}` | `{_id_short(target['base'])}` | "
            f"`{_id_short(target['target'])}` | `{target['freshness']}` |\n"
        )

    lines.extend(["\n", "## Full review artifacts\n", "\n", "These files are mechanically generated and never ellipsized. Literal `...`/`…` from source content is preserved. Every link is identity-bound and must reopen unchanged at each phase.\n", "\n"])
    for root_id, artifact in lock["artifacts"]["review_patches"].items():
        lines.append(
            f"- `{root_id}` raw review patch: [open the complete patch]({_md_path(artifact['path'])}) — "
            f"SHA-256 `{artifact['sha256']}`, {artifact['bytes']} bytes, {artifact['lines']} lines, {artifact['hunks']} hunks.\n"
        )
    for root_id, candidate in lock["candidates"].items():
        artifact = candidate["patch"]
        lines.append(
            f"- `{root_id}` exact Git candidate patch (binary/full-index): [open the complete patch]({_md_path(artifact['path'])}) — "
            f"SHA-256 `{artifact['sha256']}`, {artifact['bytes']} bytes; candidate tree `{candidate['candidate_tree']}`.\n"
        )

    lines.extend(["\n", "## Binary, generated, and sensitive evidence\n", "\n"])
    special = False
    for target_id in decision["target_ids"]:
        target = lock["targets"][target_id]
        kind = target["content_kind"]
        if kind == "binary":
            special = True
            inspector = target["content"]["inspector"]
            lines.append(
                f"- `{target_id}` binary exact source `{target['target_source']}`; frozen exact artifact "
                f"[open]({_md_path(target['target_frozen'])}); identity `{_id_short(target['target'])}`. "
                f"Inspector `{inspector['tool']}` scope: {inspector['scope']}; limitations: {inspector['limitations']}; result: {inspector['result_locator']}. "
                "Inspector adequacy remains owner judgment.\n"
            )
        elif kind == "generated":
            special = True
            group = lock["generated_groups"][target["content"]["group"]]
            if group["determinism"] == "MATCH":
                determinism = "deterministic MATCH across complete inventories"
            else:
                determinism = f"determinism NOT PROMISED ({group['determinism_reason']})"
            lines.append(
                f"- `{target_id}` generated by `{group['generator']}` (`{group['command_display']}`); "
                f"{determinism}; exact target `{_id_short(target['target'])}`. "
                "The helper verifies supplied artifacts, not that the named command produced them.\n"
            )
        elif kind == "sensitive":
            special = True
            lines.append(
                f"- `{target_id}` sensitive exact access: {target['content']['owner_access']}; binding `HMAC-SHA-256` "
                f"with separately held key `{target['content']['key_ref']}`; base `{_id_short(target['base'])}`; target `{_id_short(target['target'])}`. "
                "Raw bytes, raw digest, and byte length are not persisted in this packet.\n"
            )
    if not special:
        lines.append("- No binary, generated, or sensitive targets in this packet.\n")
    for group_id, group in lock["generated_groups"].items():
        if group["determinism"] == "MATCH":
            det_note = "deterministic match"
        else:
            det_note = f"determinism not promised: {group['determinism_reason']}"
        lines.append(f"- Generated group `{group_id}` tool versions: {', '.join(group['tool_versions'])}; outputs: {', '.join(group['outputs'])}; {det_note}.\n")

    lines.extend(["\n", "## Staged / unstaged / untracked residue and exclusions\n", "\n"])
    if not lock["residue"]:
        lines.append("No out-of-transaction Git residue was present at build time.\n")
    else:
        lines.extend(["| Root/path | State layers | Disposition | Reason |\n", "|---|---|---|---|\n"])
        for row in lock["residue"]:
            lines.append(f"| `{row['root']}:{row['path']}` | `{','.join(row['states'])}` | `{row['disposition']}` | {row['reason']} |\n")

    lines.extend(["\n", "## Exact Git commit manifests\n", "\n"])
    if not lock["candidates"]:
        lines.append("No Git commit is part of the declared decision.\n")
    for root_id, candidate in lock["candidates"].items():
        lines.append(f"### `{root_id}`\n\nExpected parent `{candidate['base_revision']}`; candidate tree `{candidate['candidate_tree']}`; exact changed path set: {', '.join(f'`{p}`' for p in candidate['changed_paths'])}.\n\n")
        lines.append("| Target/path | Operation | Mode | Candidate blob | Raw vs committed bytes |\n|---|---|---|---|---|\n")
        for entry in candidate["entries"]:
            changed = entry.get("filter_changed_bytes", False)
            lines.append(f"| `{entry['target']}:{entry['path']}` | `{entry['operation']}` | `{entry['mode']}` | `{entry['blob_oid']}` | `{'DIFFER' if changed else 'MATCH'}` |\n")

    lines.extend(
        [
            "\n",
            "## Decision protocol\n",
            "\n",
            f"Approve or reject **packet `{lock['packet_id']}`** only after opening every applicable full artifact above. "
            "Any base, target, artifact, helper, repository HEAD/index/residue, mirror/adaptation, or evidence change invalidates the decision. "
            "Rejection permanently blocks apply/adopt/commit for this packet.\n",
        ]
    )
    return "".join(lines)


def build_packet(spec_path: Path, out: Path, key_path: str | None) -> dict[str, Any]:
    raw = _json_load(spec_path, "manifest")
    snapshot = json.loads(json.dumps(raw))
    spec = _validate_manifest(raw)
    key = _key(key_path, spec["_sensitive"])
    out = out.expanduser()
    if not out.is_absolute():
        raise SanctionError("--out must be an absolute directory")
    out = out.resolve(strict=False)
    for root in spec["_roots"].values():
        if _within(out, root["_path"]):
            raise SanctionError(f"packet output must be outside every declared root: {out} is under {root['_path']}")
    if out.exists() and any(out.iterdir()):
        raise SanctionError(f"packet output directory must be absent or empty: {out}")
    out.mkdir(parents=True, exist_ok=True)

    nonce = secrets.token_hex(32)
    spec_copy = out / "spec.json"
    _json_write(spec_copy, snapshot)
    roots_obs = _observe_roots(spec)
    target_obs = _observe_targets(spec, roots_obs, out, key, nonce)
    _validate_residue(spec, roots_obs)
    generated_obs = _observe_generated(spec)

    review_patches: dict[str, Any] = {}
    candidates: dict[str, Any] = {}
    for root_id in spec["decision"]["root_ids"]:
        review = _review_patch_for_root(spec, target_obs, root_id, out)
        if review is not None:
            review_patches[root_id] = review
        candidate = _candidate_for_root(spec, roots_obs, target_obs, root_id, out)
        if candidate is not None:
            candidates[root_id] = candidate

    lock: dict[str, Any] = {
        "schema": SCHEMA,
        "version": VERSION,
        "claim": CLAIM,
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "machine": platform.node() or "unknown",
        "helper": {"path": str(_helper_path()), "sha256": _helper_sha()},
        "nonce": nonce,
        "manifest": {"path": str(spec_copy.resolve()), "sha256": _sha(_read(spec_copy, "frozen manifest"))},
        "decision": snapshot["decision"],
        "roots": roots_obs,
        "targets": target_obs,
        "residue": snapshot["residue"],
        "generated_groups": generated_obs,
        "candidates": candidates,
        "artifacts": {"review_patches": review_patches},
    }
    lock["packet_id"] = _sha(_canonical(_packet_id_payload(lock)))
    packet_path = out / "packet.md"
    _write_text(packet_path, _render_packet(spec, lock))
    lock["packet_artifact"] = _artifact(packet_path)
    lock_path = out / "packet.lock.json"
    _json_write(lock_path, lock)
    print(f"READY FOR OWNER DECISION {lock['packet_id']} {lock_path}")
    return lock


def _verify_file_artifact(artifact: dict[str, Any], label: str) -> None:
    path = Path(_nonempty(artifact.get("path"), f"{label}.path"))
    data = _read(path, label)
    if _sha(data) != artifact.get("sha256") or len(data) != artifact.get("bytes"):
        raise SanctionError(f"{label} changed or was replaced: {path}")
    lines = data.count(b"\n") + (1 if data and not data.endswith(b"\n") else 0)
    hunks = sum(1 for line in data.splitlines() if line.startswith(b"@@ "))
    if lines != artifact.get("lines") or hunks != artifact.get("hunks"):
        raise SanctionError(f"{label} structure changed: {path}")


def _load_lock(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    lock = _expect_object(_json_load(path, "packet lock"), "packet lock")
    required = {
        "schema", "version", "claim", "created_at", "machine", "helper", "nonce",
        "manifest", "decision", "roots", "targets", "residue", "generated_groups",
        "candidates", "artifacts", "packet_id", "packet_artifact",
    }
    _keys(lock, required, required, "packet lock")
    if lock["schema"] != SCHEMA or lock["claim"] != CLAIM:
        raise SanctionError("packet lock schema/claim mismatch")
    helper = _expect_object(lock["helper"], "packet lock.helper")
    if helper.get("sha256") != _helper_sha():
        raise SanctionError("helper bytes changed since packet build; rebuild and re-present")
    expected_id = _sha(_canonical(_packet_id_payload(lock)))
    if not hmac.compare_digest(str(lock["packet_id"]), expected_id):
        raise SanctionError("packet lock content does not match packet_id")
    manifest = _expect_object(lock["manifest"], "packet lock.manifest")
    manifest_path = Path(_nonempty(manifest.get("path"), "packet lock.manifest.path"))
    manifest_bytes = _read(manifest_path, "frozen manifest")
    if _sha(manifest_bytes) != manifest.get("sha256"):
        raise SanctionError("frozen manifest changed after packet build")
    spec = _validate_manifest(json.loads(manifest_bytes.decode("utf-8")))
    if spec["decision"] != lock["decision"]:
        raise SanctionError("lock decision denominator differs from frozen manifest")

    _verify_file_artifact(lock["packet_artifact"], "rendered packet")
    packet_path = Path(_nonempty(lock["packet_artifact"].get("path"), "rendered packet.path"))
    expected_packet = _render_packet(spec, lock).encode("utf-8")
    if _read(packet_path, "rendered packet") != expected_packet:
        raise SanctionError("rendered packet does not match the packet-id-bound canonical rendering")
    for root_id, artifact in _expect_object(lock["artifacts"], "lock.artifacts").get("review_patches", {}).items():
        _verify_file_artifact(artifact, f"review patch {root_id}")
    for root_id, candidate in _expect_object(lock["candidates"], "lock.candidates").items():
        _verify_file_artifact(candidate["patch"], f"commit patch {root_id}")
        for entry in candidate["entries"]:
            artifact_path = entry.get("committed_artifact")
            if artifact_path:
                data = _read(Path(artifact_path), f"committed candidate {entry['target']}")
                if _identity(data) != entry.get("committed_identity"):
                    raise SanctionError(f"committed candidate artifact changed for {entry['target']}")
    for target_id, target in _expect_object(lock["targets"], "lock.targets").items():
        for role in ("base", "target"):
            frozen = target.get(f"{role}_frozen")
            if frozen:
                data = _read(Path(frozen), f"frozen {role} for {target_id}")
                if _identity(data) != target[role]:
                    raise SanctionError(f"frozen {role} artifact changed for {target_id}")
    return lock, spec


def _decision_path(lock_path: Path) -> Path:
    return lock_path.resolve().parent / "decision.json"


def _load_decision(lock_path: Path, lock: dict[str, Any], *, required: bool) -> dict[str, Any] | None:
    path = _decision_path(lock_path)
    if not path.is_file():
        if required:
            raise SanctionError("owner decision is missing; packet is not approved")
        return None
    decision = _expect_object(_json_load(path, "decision record"), "decision record")
    fields = {"schema", "packet_id", "helper_sha256", "nonce", "verdict", "evidence", "recorded_at", "warning"}
    _keys(decision, fields, fields, "decision record")
    if decision["schema"] != SCHEMA or decision["packet_id"] != lock["packet_id"]:
        raise SanctionError("decision record is bound to a different packet")
    if decision["helper_sha256"] != lock["helper"]["sha256"] or decision["nonce"] != lock["nonce"]:
        raise SanctionError("decision helper/nonce binding mismatch")
    evidence = _expect_object(decision["evidence"], "decision.evidence")
    _keys(evidence, {"path", "sha256"}, {"path", "sha256"}, "decision.evidence")
    evidence_bytes = _read(Path(evidence["path"]), "owner-decision evidence")
    if _sha(evidence_bytes) != evidence["sha256"]:
        raise SanctionError("owner-decision evidence changed after recording")
    verdict = _choice(decision["verdict"], {"approved", "rejected"}, "decision.verdict")
    if required and verdict != "approved":
        raise SanctionError("packet was rejected; apply/adopt/commit is permanently blocked")
    return decision


def record_decision(lock_path: Path, verdict: str, evidence_file: Path, key_path: str | None) -> dict[str, Any]:
    lock, spec = _load_lock(lock_path)
    key = _key(key_path, spec["_sensitive"])
    _verify_phase(lock_path, lock, spec, "pre-decision", key, commits=None, semantic_review=None, write_receipt=False)
    path = _decision_path(lock_path)
    if path.exists():
        raise SanctionError(f"decision already exists and cannot be overwritten: {path}")
    evidence_file = _absolute(str(evidence_file), "--evidence-file")
    evidence = _read(evidence_file, "owner-decision evidence")
    record = {
        "schema": SCHEMA,
        "packet_id": lock["packet_id"],
        "helper_sha256": lock["helper"]["sha256"],
        "nonce": lock["nonce"],
        "verdict": _choice(verdict, {"approved", "rejected"}, "--verdict"),
        "evidence": {"path": str(evidence_file), "sha256": _sha(evidence)},
        "recorded_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "warning": "Agent-recorded attestation only; this helper does not authenticate the owner.",
    }
    _json_write(path, record)
    print(f"DECISION {record['verdict'].upper()} {lock['packet_id']} {path}")
    return record


def _verify_source_identities(lock: dict[str, Any], spec: dict[str, Any], key: bytes | None) -> None:
    nonce = lock["nonce"]
    for target_id in spec["decision"]["target_ids"]:
        target = spec["_targets"][target_id]
        locked = lock["targets"][target_id]
        base_bytes, base_mode, target_bytes, target_mode = _target_bytes_and_modes(spec, target, lock["roots"][target["root"]])
        sensitive = target["_content_kind"] == "sensitive"
        if sensitive:
            assert key is not None
            base_id = {"algorithm": "absent"} if base_bytes is None else _hmac_identity(base_bytes, key, nonce, target_id, "base")
            target_id_value = {"algorithm": "absent"} if target_bytes is None else _hmac_identity(target_bytes, key, nonce, target_id, "target")
        else:
            base_id = {"algorithm": "absent"} if base_bytes is None else _identity(base_bytes)
            target_id_value = {"algorithm": "absent"} if target_bytes is None else _identity(target_bytes)
        if base_id != locked["base"] or target_id_value != locked["target"]:
            raise SanctionError(f"base or proposed target source changed for {target_id}; rebuild and re-present")
        if base_mode != locked["base_mode"] or target_mode != locked["target_mode"]:
            raise SanctionError(f"mode changed for {target_id}; rebuild and re-present")


def _current_matches(lock: dict[str, Any], spec: dict[str, Any], key: bytes | None, *, desired: str) -> None:
    for target_id in spec["decision"]["target_ids"]:
        target = spec["_targets"][target_id]
        locked = lock["targets"][target_id]
        current = _current_state(spec, target, key, lock["nonce"])
        probe = dict(locked)
        probe["current"] = current
        if desired == "entry":
            state = _freshness_state(target, probe)
            expected = "BASE" if target["_entry"] == "pre-apply" else "TARGET"
        else:
            original = target["_entry"]
            target["_entry"] = "already-applied"
            try:
                state = _freshness_state(target, probe)
            finally:
                target["_entry"] = original
            expected = "TARGET"
        if state != expected:
            raise SanctionError(f"{target_id} current destination is {state}, expected {expected}")


def _verify_root_identity(lock: dict[str, Any], current: dict[str, Any], *, require_base_head: bool) -> None:
    for root_id, locked in lock["roots"].items():
        now = current[root_id]
        if now["path"] != locked["path"] or now["physical"] != locked["physical"]:
            raise SanctionError(f"physical root identity changed for {root_id}")
        if locked["kind"] == "git" and require_base_head and now["head"] != locked["head"]:
            raise SanctionError(f"Git HEAD changed for {root_id}; packet is stale")


def _candidate_real_patch(spec: dict[str, Any], root_id: str, candidate: dict[str, Any]) -> bytes:
    root = spec["_roots"][root_id]["_path"]
    return _git(root, "diff", "--cached", "--binary", "--full-index", "--find-renames", candidate["base_revision"]).stdout


def _semantic_evidence(path: Path | None) -> dict[str, str]:
    if path is None:
        raise SanctionError("pre-commit/post-commit requires --semantic-review-file (staged-byte semantic review evidence)")
    path = _absolute(str(path), "--semantic-review-file")
    data = _read(path, "semantic staged-byte review evidence")
    if not data.strip():
        raise SanctionError("semantic staged-byte review evidence is empty")
    return {"path": str(path), "sha256": _sha(data)}


def _verify_phase(
    lock_path: Path,
    lock: dict[str, Any],
    spec: dict[str, Any],
    phase: str,
    key: bytes | None,
    *,
    commits: Path | None,
    semantic_review: Path | None,
    write_receipt: bool,
) -> None:
    phase = _choice(phase, {"pre-decision", "pre-apply", "post-apply", "pre-commit", "post-commit"}, "--phase")
    requires_decision = phase != "pre-decision"
    _load_decision(lock_path, lock, required=requires_decision)
    _verify_source_identities(lock, spec, key)
    generated_now = _observe_generated(spec)
    if generated_now != lock["generated_groups"]:
        raise SanctionError("generated input/output evidence changed after packet build")

    if phase == "post-commit":
        current_roots = _observe_roots_allow_advanced(spec)
        _verify_root_identity(lock, current_roots, require_base_head=False)
    else:
        current_roots = _observe_roots(spec)
        _verify_root_identity(lock, current_roots, require_base_head=True)

    if phase in {"pre-decision", "pre-apply"}:
        _current_matches(lock, spec, key, desired="entry")
        _validate_residue(spec, current_roots)
        for root_id, current in current_roots.items():
            if current["kind"] == "git" and current["index"]["sha256"] != lock["roots"][root_id]["index"]["sha256"]:
                raise SanctionError(f"Git index changed for {root_id}; packet is stale")
            if current["kind"] == "git" and current["status"] != lock["roots"][root_id]["status"]:
                raise SanctionError(f"Git status changed for {root_id}; packet is stale")
    elif phase == "post-apply":
        _current_matches(lock, spec, key, desired="target")
        _validate_residue(spec, current_roots, allow_all_targets=True)
        for root_id, current in current_roots.items():
            if current["kind"] == "git" and current["index"]["sha256"] != lock["roots"][root_id]["index"]["sha256"]:
                raise SanctionError(f"post-apply phase found staged/index mutation before its gate in {root_id}")
    elif phase == "pre-commit":
        _current_matches(lock, spec, key, desired="target")
        _validate_residue(spec, current_roots, allow_all_targets=True)
        semantic = _semantic_evidence(semantic_review)
        for root_id, candidate in lock["candidates"].items():
            actual_patch = _candidate_real_patch(spec, root_id, candidate)
            expected_patch = _read(Path(candidate["patch"]["path"]), f"candidate patch {root_id}")
            if actual_patch != expected_patch:
                raise SanctionError(f"real staged bytes/path/modes differ from sanctioned candidate in {root_id}")
            staged = current_roots[root_id]["status"]["staged"]
            if staged != candidate["changed_paths"]:
                raise SanctionError(f"real staged path set differs in {root_id}: expected {candidate['changed_paths']}, got {staged}")
    else:
        semantic = _semantic_evidence(semantic_review)
        if commits is None:
            raise SanctionError("post-commit requires --commits JSON mapping root id to commit SHA")
        commit_map = _expect_object(_json_load(commits, "commit map"), "commit map")
        if set(commit_map) != set(lock["candidates"]):
            raise SanctionError("commit map root set must exactly equal candidate Git roots")
        _current_matches(lock, spec, key, desired="target")
        for root_id, candidate in lock["candidates"].items():
            root = spec["_roots"][root_id]["_path"]
            commit = _git(root, "rev-parse", str(commit_map[root_id])).stdout.decode().strip()
            if current_roots[root_id]["head"] != commit:
                raise SanctionError(f"current HEAD in {root_id} is not the sanctioned commit {commit}")
            parent_line = _git(root, "rev-list", "--parents", "-n", "1", commit).stdout.decode().strip().split()
            if len(parent_line) != 2 or parent_line[1] != candidate["base_revision"]:
                raise SanctionError(f"commit {commit} in {root_id} has wrong or non-single parent")
            tree = _git(root, "rev-parse", f"{commit}^{{tree}}").stdout.decode().strip()
            if tree != candidate["candidate_tree"]:
                raise SanctionError(f"commit tree differs from sanctioned candidate in {root_id}")
            actual_patch = _git(root, "diff", "--binary", "--full-index", "--find-renames", candidate["base_revision"], commit).stdout
            expected_patch = _read(Path(candidate["patch"]["path"]), f"candidate patch {root_id}")
            if actual_patch != expected_patch:
                raise SanctionError(f"committed patch differs from sanctioned candidate in {root_id}")
            if current_roots[root_id]["index"]["entries"] != _tree_entries(root, commit):
                raise SanctionError(f"current index in {root_id} does not exactly match the sanctioned commit")
            target_residue = set(candidate["changed_paths"]).intersection(
                set().union(*[set(paths) for paths in current_roots[root_id]["status"].values()])
            )
            if target_residue:
                raise SanctionError(f"sanctioned commit paths retain post-commit status in {root_id}: {sorted(target_residue)}")
        for root_id, current in current_roots.items():
            if current["kind"] != "git" or root_id in lock["candidates"]:
                continue
            if current["head"] != lock["roots"][root_id]["head"]:
                raise SanctionError(f"non-committing Git root {root_id} changed HEAD after sanction")
            if current["index"]["entries"] != lock["roots"][root_id]["index"]["entries"]:
                raise SanctionError(f"non-committing Git root {root_id} changed index after sanction")
        _validate_residue(spec, current_roots, allow_all_targets=True)

    if write_receipt:
        receipt = {
            "schema": SCHEMA,
            "packet_id": lock["packet_id"],
            "phase": phase,
            "verified_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        }
        if phase in {"pre-commit", "post-commit"}:
            receipt["semantic_review"] = semantic
        _json_write(lock_path.resolve().parent / f"verify-{phase}.json", receipt)
    print(f"VERIFIED {phase} {lock['packet_id']}")


def _observe_roots_allow_advanced(spec: dict[str, Any]) -> dict[str, Any]:
    observed: dict[str, Any] = {}
    for root_id, root in spec["_roots"].items():
        path = root["_path"]
        st = path.stat()
        row: dict[str, Any] = {"id": root_id, "kind": root["kind"], "path": str(path), "physical": {"device": st.st_dev, "inode": st.st_ino}}
        if root["kind"] == "git":
            head = _git(path, "rev-parse", "HEAD").stdout.decode().strip()
            branch_cp = _git(path, "symbolic-ref", "--quiet", "--short", "HEAD", check=False)
            row.update(
                head=head,
                branch=branch_cp.stdout.decode().strip() if branch_cp.returncode == 0 else "DETACHED",
                status=_git_status(path),
                index=_index_snapshot(path),
            )
        observed[root_id] = row
    return observed


def verify_packet(lock_path: Path, phase: str, key_path: str | None, commits: Path | None, semantic_review: Path | None) -> None:
    lock, spec = _load_lock(lock_path)
    key = _key(key_path, spec["_sensitive"])
    _verify_phase(lock_path, lock, spec, phase, key, commits=commits, semantic_review=semantic_review, write_receipt=True)


def _receipt_target_state(lock: dict[str, Any], spec: dict[str, Any], target_id: str, key: bytes | None) -> str:
    target = spec["_targets"][target_id]
    locked = lock["targets"][target_id]
    current = _current_state(spec, target, key, lock["nonce"])
    if target["_operation"] == "rename":
        at_target = _same_identity(current["identity"], locked["target"]) and current["old_identity"]["algorithm"] == "absent"
        at_base = _same_identity(current["old_identity"], locked["base"]) and current["identity"]["algorithm"] == "absent"
    elif target["_operation"] == "delete":
        at_target = current["identity"]["algorithm"] == "absent"
        at_base = _same_identity(current["identity"], locked["base"])
    else:
        at_target = _same_identity(current["identity"], locked["target"])
        at_base = _same_identity(current["identity"], locked["base"])
    if at_target:
        return "TARGET"
    if at_base:
        return "BASE"
    if current["identity"]["algorithm"] == "absent":
        return "ABSENT"
    return "DRIFT"


def _candidate_entry(lock: dict[str, Any], target_id: str) -> dict[str, Any] | None:
    for candidate in lock["candidates"].values():
        for entry in candidate["entries"]:
            if entry["target"] == target_id:
                return entry
    return None


def _index_blob(root: Path, path: str) -> tuple[bytes | None, str]:
    raw = _git(root, "ls-files", "--stage", "--", path).stdout
    records = [record for record in raw.splitlines() if record]
    if not records:
        return None, "absent"
    if len(records) != 1:
        return b"", "unmerged"
    meta, sep, _ = records[0].partition(b"\t")
    bits = meta.decode("ascii", "strict").split()
    if not sep or len(bits) != 3 or bits[2] != "0":
        return b"", "unmerged"
    data = _git(root, "show", f":{path}").stdout
    return data, bits[0]


def _classify_git_layer(
    lock: dict[str, Any],
    spec: dict[str, Any],
    target_id: str,
    layer: str,
) -> tuple[str, str]:
    target = spec["_targets"][target_id]
    locked = lock["targets"][target_id]
    root = spec["_roots"][target["root"]]["_path"]
    entry = _candidate_entry(lock, target_id)
    if entry is None:
        return "N/A", "N/A"

    def read_path(path: str) -> tuple[bytes | None, str]:
        if layer == "index":
            return _index_blob(root, path)
        return _git_blob_at(root, "HEAD", path)

    new_bytes, new_mode = read_path(target["path"])
    old_bytes: bytes | None = None
    old_mode = "absent"
    if target["_operation"] == "rename":
        old_bytes, old_mode = read_path(target["old_path"])

    candidate_identity = entry.get("committed_identity", {"algorithm": "absent"})
    new_identity = {"algorithm": "absent"} if new_bytes is None else _identity(new_bytes)
    old_identity = {"algorithm": "absent"} if old_bytes is None else _identity(old_bytes)
    op = target["_operation"]
    if op == "rename":
        target_match = new_identity == candidate_identity and new_mode == entry["mode"] and old_bytes is None
        base_match = old_identity == locked["base"] and old_mode == locked["base_mode"] and new_bytes is None
    elif op == "delete":
        target_match = new_bytes is None
        base_match = new_identity == locked["base"] and new_mode == locked["base_mode"]
    elif op == "add":
        target_match = new_identity == candidate_identity and new_mode == entry["mode"]
        base_match = new_bytes is None
    else:
        target_match = new_identity == candidate_identity and new_mode == entry["mode"]
        base_match = new_identity == locked["base"] and new_mode == locked["base_mode"]
    identity_text = _id_short(new_identity)
    if op == "rename":
        identity_text += f"; old={_id_short(old_identity)}"
    if target_match:
        return ("STAGED-TARGET" if layer == "index" else "COMMITTED-TARGET"), identity_text
    if base_match:
        return "BASE", identity_text
    if new_mode == "unmerged":
        return "UNKNOWN", identity_text
    return "DRIFT", identity_text


def write_partial_receipt(lock_path: Path, out: Path, failure_point: str, key_path: str | None) -> int:
    lock, spec = _load_lock(lock_path)
    key = _key(key_path, spec["_sensitive"])
    states = {target_id: _receipt_target_state(lock, spec, target_id, key) for target_id in spec["decision"]["target_ids"]}
    lines = ["# INCOMPLETE — NOT ADOPTED / NOT COMMITTED\n", "\n", f"**Packet:** `{lock['packet_id']}`  \n", f"**Failure point:** {_nonempty(failure_point, '--failure-point')}  \n"]
    lines.append("**PARTIAL LIVE / STAGED / COMMITTED STATE MAY BE PRESENT. No completion claim is permitted.**\n")
    lines.extend(["\n", "| Target | Live state / identity | Index state / identity | Commit state / identity | Compensation classification |\n", "|---|---|---|---|---|\n"])
    for target_id in spec["decision"]["target_ids"]:
        state = states[target_id]
        target = spec["_targets"][target_id]
        current = _current_state(spec, target, key, lock["nonce"])
        live_identity = _id_short(current["identity"])
        if target["_operation"] == "rename":
            live_identity += f"; old={_id_short(current['old_identity'])}"
        if spec["_roots"][target["root"]]["kind"] == "git" and target["commit"]:
            index_state, index_identity = _classify_git_layer(lock, spec, target_id, "index")
            commit_state, commit_identity = _classify_git_layer(lock, spec, target_id, "commit")
        else:
            index_state = index_identity = commit_state = commit_identity = "N/A"
        if state == "TARGET" and commit_state != "COMMITTED-TARGET":
            compensation = "candidate: transaction-owned target still exact; restore only from captured base after recheck"
        elif state == "BASE":
            compensation = "no live compensation needed"
        elif commit_state == "COMMITTED-TARGET":
            compensation = "unsafe for automatic compensation: target is committed; preserve and adjudicate"
        else:
            compensation = "unsafe for automatic compensation; preserve and adjudicate"
        lines.append(
            f"| `{target_id}` | `{state}` / `{live_identity}` | `{index_state}` / `{index_identity}` | "
            f"`{commit_state}` / `{commit_identity}` | {compensation} |\n"
        )
    lines.append("\nThe helper did not mutate, compensate, stage, unstage, commit, or clean any path. A failed/half-copied target must never become a propagation source.\n")
    out = out.expanduser().resolve(strict=False)
    _write_text(out, "".join(lines))
    print(f"INCOMPLETE {lock['packet_id']} {out}")
    return EXIT_INCOMPLETE


def _add_key_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--hmac-key-file", help="absolute path to separately held 32+ byte HMAC key")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build", help="freeze a declared scope and render the packet")
    build.add_argument("manifest")
    build.add_argument("--out", required=True)
    _add_key_arg(build)

    decision = sub.add_parser("decision", help="record an owner decision attestation")
    decision.add_argument("lock")
    decision.add_argument("--verdict", required=True, choices=("approved", "rejected"))
    decision.add_argument("--evidence-file", required=True)
    _add_key_arg(decision)

    verify = sub.add_parser("verify", help="re-derive evidence at a lifecycle phase")
    verify.add_argument("lock")
    verify.add_argument("--phase", required=True, choices=("pre-decision", "pre-apply", "post-apply", "pre-commit", "post-commit"))
    verify.add_argument("--commits")
    verify.add_argument("--semantic-review-file")
    _add_key_arg(verify)

    receipt = sub.add_parser("receipt", help="enumerate mixed state after a failed transaction leg")
    receipt.add_argument("lock")
    receipt.add_argument("--out", required=True)
    receipt.add_argument("--failure-point", required=True)
    _add_key_arg(receipt)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "build":
            build_packet(_absolute(args.manifest, "manifest"), Path(args.out), args.hmac_key_file)
            return 0
        if args.command == "decision":
            record_decision(_absolute(args.lock, "lock"), args.verdict, Path(args.evidence_file), args.hmac_key_file)
            return 0
        if args.command == "verify":
            commits = _absolute(args.commits, "--commits") if args.commits else None
            semantic = _absolute(args.semantic_review_file, "--semantic-review-file") if args.semantic_review_file else None
            verify_packet(_absolute(args.lock, "lock"), args.phase, args.hmac_key_file, commits, semantic)
            return 0
        if args.command == "receipt":
            return write_partial_receipt(_absolute(args.lock, "lock"), Path(args.out), args.failure_point, args.hmac_key_file)
        raise SanctionError(f"unsupported command {args.command}")
    except SanctionError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return EXIT_INVALID


if __name__ == "__main__":
    raise SystemExit(main())
