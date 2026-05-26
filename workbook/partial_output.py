from __future__ import annotations

import yaml
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class RejectedTable:
    """Single table rejection with error annotation."""

    source_tab_title: str | None
    source_workbook_code: str | None
    check_id: str
    message: str
    action: str | None = None


@dataclass
class PartialOutputCollector:
    """Accumulate rejected tables during contract validation or scaffolding."""

    rejected: list[RejectedTable] = field(default_factory=list)

    def add(
        self,
        table: dict[str, Any],
        *,
        check_id: str,
        message: str,
        action: str | None = None,
    ) -> None:
        """Record a rejected table."""
        self.rejected.append(
            RejectedTable(
                source_tab_title=table.get("bundle_worksheet_title"),
                source_workbook_code=table.get("workbook_code"),
                check_id=check_id,
                message=message,
                action=action,
            )
        )

    def is_empty(self) -> bool:
        return len(self.rejected) == 0

    def write_rejection_file(self, path: Path) -> None:
        """Serialize rejected tables to YAML."""
        path.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = {
            "rejected_tables": [
                {
                    "table": {
                        "source_tab_title": r.source_tab_title,
                        "source_workbook_code": r.source_workbook_code,
                    },
                    "error": {
                        "check_id": r.check_id,
                        "message": r.message,
                        "action": r.action,
                    },
                }
                for r in self.rejected
            ]
        }
        path.write_text(
            yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )

    def summary(self) -> str:
        """Return a human-readable summary string."""
        lines = ["WARN[SCAFFOLD_PARTIAL_OUTPUT]: wrote partial output."]
        lines.append(f"  Tables rejected: {len(self.rejected)}")
        for r in self.rejected:
            tab_info = f" ({r.source_tab_title})" if r.source_tab_title else ""
            lines.append(f"  - {r.check_id}: {r.message}{tab_info}")
        if self.rejected:
            lines.append(
                "  Action: Review rejected tables, fix upstream data, and re-run without --continue-on-error."
            )
        return "\n".join(lines)
