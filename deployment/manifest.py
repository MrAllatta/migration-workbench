"""Load and validate the ``deploy/spaces.yml`` deployment manifest.

The manifest describes every hosted *space* (one Django instance per
customer/project) and the shared infrastructure profiles, replication
defaults, and secret contracts they must satisfy.

**Typical call sequence**::

    payload = load_manifest(Path("deploy/spaces.yml"))
    ensure_manifest_valid(payload)          # raises ManifestValidationError on failure
    # -- or, to inspect issues without raising --
    issues = validate_manifest(payload)
    for issue in issues:
        print(issue.path, issue.message)
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


class ManifestValidationError(ValueError):
    """Raised when ``deploy/spaces.yml`` violates the required contract.

    Inherits from :class:`ValueError` so callers can catch it without importing
    this module specifically.  The message contains a newline-separated list of
    ``- path: message`` items when multiple issues were found.
    """


# Frozen contract: secret names must match Django/Fly usage (see deploy docs / .env.example).
CANONICAL_SECRET_NAMES = frozenset(
    {
        "DJANGO_SECRET_KEY",
        "DJANGO_ALLOWED_HOSTS",
        "CSRF_TRUSTED_ORIGINS",
        "LITESTREAM_ACCESS_KEY_ID",
        "LITESTREAM_SECRET_ACCESS_KEY",
        "LITESTREAM_BUCKET",
    }
)

# Non-secret vars declared under spaces.<name>.environment.required (Fly [env], etc.).
CANONICAL_RUNTIME_ENV_NAMES = frozenset({"SQLITE_PATH"})


@dataclass(frozen=True)
class ManifestValidationIssue:
    """A single validation failure within the manifest.

    Attributes:
        path: Dot-separated YAML path to the offending key
            (e.g. ``"spaces.farm.provider.regions"``).
        message: Human-readable description of the constraint that was violated.
    """

    path: str
    message: str


def load_manifest(path: Path) -> dict[str, Any]:
    """Read and parse a YAML manifest file.

    Args:
        path: Filesystem path to the manifest (typically ``deploy/spaces.yml``).

    Returns:
        dict: Parsed manifest payload.

    Raises:
        ManifestValidationError: If the YAML root is not a mapping.
        yaml.YAMLError: On YAML parse failure.
    """
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
    """Validate *payload* against the full manifest schema contract.

    Walks every section (``profiles``, ``replication_defaults``, ``spaces``)
    and collects all constraint violations rather than stopping at the first
    error.  This lets operators fix all issues in a single edit cycle.

    Args:
        payload: Parsed manifest dict, as returned by :func:`load_manifest`.

    Returns:
        list[ManifestValidationIssue]: All issues found.  An empty list means
        the manifest is valid.
    """
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
        else:
            for name in required_secrets:
                if name == "ALLOWED_HOSTS":
                    issues.append(
                        ManifestValidationIssue(
                            f"{spath}.secrets.required",
                            "must use DJANGO_ALLOWED_HOSTS, not ALLOWED_HOSTS (Django reads DJANGO_ALLOWED_HOSTS)",
                        )
                    )
                elif name not in CANONICAL_SECRET_NAMES:
                    issues.append(
                        ManifestValidationIssue(
                            f"{spath}.secrets.required",
                            f"unknown or disallowed secret name {name!r}; allowed: {sorted(CANONICAL_SECRET_NAMES)}",
                        )
                    )

        env_contract = _require_mapping(s.get("environment"), f"{spath}.environment", issues)
        required_runtime = env_contract.get("required")
        if not isinstance(required_runtime, list) or not required_runtime:
            issues.append(
                ManifestValidationIssue(
                    f"{spath}.environment.required",
                    "must be a non-empty list of non-secret env var names",
                )
            )
        elif not all(_is_non_empty_string(item) for item in required_runtime):
            issues.append(
                ManifestValidationIssue(f"{spath}.environment.required", "must contain only non-empty strings")
            )
        else:
            for name in required_runtime:
                if name not in CANONICAL_RUNTIME_ENV_NAMES:
                    issues.append(
                        ManifestValidationIssue(
                            f"{spath}.environment.required",
                            f"unknown runtime env name {name!r}; allowed: {sorted(CANONICAL_RUNTIME_ENV_NAMES)}",
                        )
                    )
            if "SQLITE_PATH" not in required_runtime:
                issues.append(
                    ManifestValidationIssue(
                        f"{spath}.environment.required",
                        "must include SQLITE_PATH for sqlite-backed spaces (match spaces.<name>.storage.sqlite_path at deploy time)",
                    )
                )

        environments = _require_mapping(s.get("environments"), f"{spath}.environments", issues)
        for env in ("preview", "production"):
            env_cfg = _require_mapping(environments.get(env), f"{spath}.environments.{env}", issues)
            _require_string(env_cfg, "branch_pattern", f"{spath}.environments.{env}", issues)

    return issues


def ensure_manifest_valid(payload: dict[str, Any]) -> None:
    """Assert that *payload* passes all manifest validation checks.

    This is the raising counterpart to :func:`validate_manifest`.  Use it in
    CLI commands and CI scripts where a single point of failure is preferable
    to iterating over issues.

    Args:
        payload: Parsed manifest dict, as returned by :func:`load_manifest`.

    Raises:
        ManifestValidationError: If any validation issues are found.  The
            exception message lists all issues prefixed with ``"- path: msg"``.
    """
    issues = validate_manifest(payload)
    if not issues:
        return
    detail = "\n".join(f"- {issue.path}: {issue.message}" for issue in issues)
    raise ManifestValidationError(f"Manifest validation failed:\n{detail}")
