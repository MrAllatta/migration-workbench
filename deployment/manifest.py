from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


class ManifestValidationError(ValueError):
    """Raised when deploy/spaces.yml violates the required contract."""


@dataclass(frozen=True)
class ManifestValidationIssue:
    path: str
    message: str


def load_manifest(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ManifestValidationError("Manifest root must be a mapping.")
    return payload


def _is_non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _require_mapping(obj: Any, path: str, issues: list[ManifestValidationIssue]) -> dict[str, Any]:
    if not isinstance(obj, dict):
        issues.append(ManifestValidationIssue(path, "must be a mapping"))
        return {}
    return obj


def _require_string(obj: dict[str, Any], key: str, path: str, issues: list[ManifestValidationIssue]):
    if not _is_non_empty_string(obj.get(key)):
        issues.append(ManifestValidationIssue(f"{path}.{key}", "must be a non-empty string"))


def _require_int(obj: dict[str, Any], key: str, path: str, issues: list[ManifestValidationIssue], minimum: int = 1):
    value = obj.get(key)
    if not isinstance(value, int) or value < minimum:
        issues.append(ManifestValidationIssue(f"{path}.{key}", f"must be an integer >= {minimum}"))


def validate_manifest(payload: dict[str, Any]) -> list[ManifestValidationIssue]:
    issues: list[ManifestValidationIssue] = []
    if payload.get("version") != 1:
        issues.append(ManifestValidationIssue("version", "must equal 1"))

    profiles = _require_mapping(payload.get("profiles"), "profiles", issues)
    for profile_name, profile in profiles.items():
        ppath = f"profiles.{profile_name}"
        p = _require_mapping(profile, ppath, issues)
        cpu = _require_mapping(p.get("cpu"), f"{ppath}.cpu", issues)
        _require_int(cpu, "cores", f"{ppath}.cpu", issues)
        _require_string(cpu, "type", f"{ppath}.cpu", issues)
        _require_int(p, "memory_mb", ppath, issues)
        _require_int(p, "volume_gb", ppath, issues)

    defaults = _require_mapping(payload.get("replication_defaults"), "replication_defaults", issues)
    _require_string(defaults, "provider", "replication_defaults", issues)
    _require_string(defaults, "bucket_env", "replication_defaults", issues)
    _require_int(defaults, "snapshot_interval_minutes", "replication_defaults", issues)
    _require_int(defaults, "retention_days", "replication_defaults", issues)

    spaces = _require_mapping(payload.get("spaces"), "spaces", issues)
    if not spaces:
        issues.append(ManifestValidationIssue("spaces", "must define at least one space"))
    for space_name, space in spaces.items():
        spath = f"spaces.{space_name}"
        s = _require_mapping(space, spath, issues)
        _require_string(s, "owner", spath, issues)
        _require_string(s, "project", spath, issues)
        profile = s.get("profile")
        if not _is_non_empty_string(profile):
            issues.append(ManifestValidationIssue(f"{spath}.profile", "must be a non-empty string"))
        elif profile not in profiles:
            issues.append(ManifestValidationIssue(f"{spath}.profile", f"unknown profile '{profile}'"))

        provider = _require_mapping(s.get("provider"), f"{spath}.provider", issues)
        _require_string(provider, "type", f"{spath}.provider", issues)
        _require_string(provider, "primary_region", f"{spath}.provider", issues)
        regions = provider.get("regions")
        if not isinstance(regions, list) or not regions or not all(_is_non_empty_string(x) for x in regions):
            issues.append(ManifestValidationIssue(f"{spath}.provider.regions", "must be a non-empty list of regions"))
        _require_string(provider, "app_name_template", f"{spath}.provider", issues)

        build = _require_mapping(s.get("build"), f"{spath}.build", issues)
        has_image = _is_non_empty_string(build.get("image"))
        has_build = _is_non_empty_string(build.get("dockerfile")) and _is_non_empty_string(build.get("context"))
        if not has_image and not has_build:
            issues.append(
                ManifestValidationIssue(
                    f"{spath}.build",
                    "must define image or dockerfile+context",
                )
            )

        runtime = _require_mapping(s.get("runtime"), f"{spath}.runtime", issues)
        _require_int(runtime, "internal_port", f"{spath}.runtime", issues)
        processes = _require_mapping(runtime.get("processes"), f"{spath}.runtime.processes", issues)
        _require_string(processes, "web", f"{spath}.runtime.processes", issues)
        _require_string(processes, "release", f"{spath}.runtime.processes", issues)
        _require_string(runtime, "healthcheck_path", f"{spath}.runtime", issues)
        _require_int(runtime, "healthcheck_timeout_s", f"{spath}.runtime", issues)

        storage = _require_mapping(s.get("storage"), f"{spath}.storage", issues)
        _require_string(storage, "sqlite_path", f"{spath}.storage", issues)
        _require_string(storage, "media_path", f"{spath}.storage", issues)
        if "volume_gb" in storage:
            issues.append(
                ManifestValidationIssue(
                    f"{spath}.storage.volume_gb",
                    "must not be set; volume is inherited from profile",
                )
            )

        replication = _require_mapping(s.get("replication"), f"{spath}.replication", issues)
        if not isinstance(replication.get("litestream_enabled"), bool):
            issues.append(ManifestValidationIssue(f"{spath}.replication.litestream_enabled", "must be boolean"))
        _require_string(replication, "replica_path_template", f"{spath}.replication", issues)

        backup = _require_mapping(s.get("backup"), f"{spath}.backup", issues)
        checkpoint = _require_mapping(backup.get("predeploy_checkpoint"), f"{spath}.backup.predeploy_checkpoint", issues)
        if not isinstance(checkpoint.get("required"), bool):
            issues.append(
                ManifestValidationIssue(
                    f"{spath}.backup.predeploy_checkpoint.required",
                    "must be boolean",
                )
            )
        _require_string(checkpoint, "method", f"{spath}.backup.predeploy_checkpoint", issues)
        _require_int(backup, "retention_days", f"{spath}.backup", issues)

        secrets = _require_mapping(s.get("secrets"), f"{spath}.secrets", issues)
        required_secrets = secrets.get("required")
        if not isinstance(required_secrets, list) or not required_secrets:
            issues.append(ManifestValidationIssue(f"{spath}.secrets.required", "must be a non-empty list"))
        elif not all(_is_non_empty_string(item) for item in required_secrets):
            issues.append(ManifestValidationIssue(f"{spath}.secrets.required", "must contain only non-empty strings"))

        environments = _require_mapping(s.get("environments"), f"{spath}.environments", issues)
        for env in ("preview", "production"):
            env_cfg = _require_mapping(environments.get(env), f"{spath}.environments.{env}", issues)
            _require_string(env_cfg, "branch_pattern", f"{spath}.environments.{env}", issues)

    return issues


def ensure_manifest_valid(payload: dict[str, Any]) -> None:
    issues = validate_manifest(payload)
    if not issues:
        return
    detail = "\n".join(f"- {issue.path}: {issue.message}" for issue in issues)
    raise ManifestValidationError(f"Manifest validation failed:\n{detail}")
