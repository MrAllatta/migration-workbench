"""Operational Model dataclasses and YAML serialization.

The Operational Model is the primary artifact of the BPRS unified pipeline.
It captures capabilities, workflows, commands, events, and invariants derived
from profiler evidence.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

OPERATIONAL_MODEL_VERSION = "operational-model-1"


@dataclass
class Capability:
    """A business outcome independent of implementation."""

    id: str
    owner: str = ""
    criticality: str = "medium"
    workflows: list[str] = field(default_factory=list)


@dataclass
class Workflow:
    """A repeatable sequence of commands to achieve a business outcome."""

    id: str
    frequency: str = ""
    actor: str = ""
    commands: list[str] = field(default_factory=list)
    outcome: str = ""
    evidence: list[str] = field(default_factory=list)


@dataclass
class Command:
    """An intentional action performed by an actor."""

    id: str
    actor: str = ""
    produces: list[str] = field(default_factory=list)
    precondition: str = ""
    postcondition: str = ""


@dataclass
class Event:
    """A business fact that occurred. Immutable."""

    id: str
    payload: list[str] = field(default_factory=list)
    sourced_from: list[dict[str, str]] = field(default_factory=list)
    immutable: bool = True


@dataclass
class Invariant:
    """A business truth that must hold."""

    id: str
    expression: str = ""
    enforcement: str = "application_logic"
    violations_are: str = "warning"


@dataclass
class OperationalModel:
    """Layered operational model — the primary BPRS artifact."""

    version: str = OPERATIONAL_MODEL_VERSION
    generated_at: str = ""
    source_id: str = ""
    capabilities: list[Capability] = field(default_factory=list)
    workflows: list[Workflow] = field(default_factory=list)
    commands: list[Command] = field(default_factory=list)
    events: list[Event] = field(default_factory=list)
    invariants: list[Invariant] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to a plain dict for JSON/YAML serialization."""
        return {
            "version": self.version,
            "generated_at": self.generated_at,
            "source_id": self.source_id,
            "capabilities": [asdict(capability) for capability in self.capabilities],
            "workflows": [asdict(workflow) for workflow in self.workflows],
            "commands": [asdict(command) for command in self.commands],
            "events": [asdict(event) for event in self.events],
            "invariants": [asdict(invariant) for invariant in self.invariants],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OperationalModel:
        """Reconstruct from a plain dict.

        Args:
            data: Dictionary with keys matching OperationalModel fields.

        Returns:
            A new OperationalModel instance populated from the dict.
        """
        return cls(
            version=data.get("version", OPERATIONAL_MODEL_VERSION),
            generated_at=data.get("generated_at", ""),
            source_id=data.get("source_id", ""),
            capabilities=[
                Capability(**capability_data)
                for capability_data in data.get("capabilities", [])
            ],
            workflows=[
                Workflow(**workflow_data) for workflow_data in data.get("workflows", [])
            ],
            commands=[
                Command(**command_data) for command_data in data.get("commands", [])
            ],
            events=[Event(**event_data) for event_data in data.get("events", [])],
            invariants=[
                Invariant(**invariant_data)
                for invariant_data in data.get("invariants", [])
            ],
        )

    def to_yaml(self, path: str | Path) -> None:
        """Serialize to YAML file.

        Args:
            path: Filesystem path for the output YAML file.
        """
        import yaml  # type: ignore[import-untyped]

        file_path = Path(path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(
            yaml.safe_dump(self.to_dict(), sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )

    @classmethod
    def from_yaml(cls, path: str | Path) -> OperationalModel:
        """Deserialize from YAML file.

        Args:
            path: Filesystem path to the YAML file.

        Returns:
            A new OperationalModel instance populated from the YAML content.

        Raises:
            ValueError: If the YAML root is not a mapping.
        """
        import yaml  # type: ignore[import-untyped]

        file_path = Path(path)
        raw = yaml.safe_load(file_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError(f"YAML at {file_path} is not a mapping.")
        return cls.from_dict(raw)
