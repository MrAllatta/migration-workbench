"""PipelineState score_and_select phase method.

Extracted from ``profiler.pipeline.phases.discover``.
"""

from __future__ import annotations

import logging
from typing import Any

from profiler.tools.domain_context import DomainContext

logger = logging.getLogger(__name__)


def score_and_select(self) -> Any:
    """Phase 1/2: Re-score tabs using domain knowledge (no API calls).

    Scores ``broad_inventory`` entries against ``domain_knowledge.vocabulary``
    via ``score_tab()``, updates ``shortlist``, and auto-selects high-confidence
    tabs (confidence >= 0.90) into ``approved_tabs``.

    Returns
    -------
    PipelineState
        Self for chaining.

    Raises
    ------
    RuntimeError
        If ``discover()`` has not been run or ``shortlist`` is
        ``None``.
    """
    if self.discovery.source_tree is None:
        raise RuntimeError("score_and_select: discover() must run first")
    if self.discovery.shortlist is None:
        raise RuntimeError("score_and_select: shortlist is None")

    if not self.domain_knowledge.vocabulary.get(
        "operational"
    ) and not self.domain_knowledge.vocabulary.get("reference"):
        logger.warning(
            "DomainKnowledge is empty \u2014 score_and_select phase will not re-rank. "
            "Provide a domain context file via --domain-context, "
            "or populate config/domain_context.yaml."
        )

    from profiler.tools.cohort_corpus import score_tab

    domain_ctx = DomainContext(
        domain=self.domain_knowledge.domain,
        description=self.domain_knowledge.description,
        vocabulary=DomainContext.VocabularyContext(
            operational=self.domain_knowledge.vocabulary.get("operational", []),
            reference=self.domain_knowledge.vocabulary.get("reference", []),
            support=self.domain_knowledge.vocabulary.get("support", []),
            derived=self.domain_knowledge.vocabulary.get("derived", []),
        ),
        year_scope=DomainContext.YearScope(
            active=self.domain_knowledge.year_scope.get("active", []),
            archived=self.domain_knowledge.year_scope.get("archived", []),
            forward=self.domain_knowledge.year_scope.get("forward", []),
        ),
        deduplication=DomainContext.DeduplicationContext(
            strategy=self.domain_knowledge.deduplication.get(
                "strategy", "latest_year"
            ),
            exceptions=self.domain_knowledge.deduplication.get("exceptions", []),
        ),
        entities=list(self.domain_knowledge.entities),
        glossary=dict(self.domain_knowledge.glossary),
        scope_notes=self.domain_knowledge.scope_notes,
    )

    # Use tab-level shortlist (not workbook-level broad_inventory)
    shortlist_entries = self.discovery.shortlist
    if isinstance(shortlist_entries, dict):
        shortlist_entries = shortlist_entries.get("selected") or []
    if not isinstance(shortlist_entries, list):
        shortlist_entries = []

    scored_tabs: list[dict] = []
    for tab in shortlist_entries:
        title = tab.get("tab_title", "")
        rows = tab.get("rows_max", 0) or tab.get("row_count", 0) or 0
        cols = tab.get("cols_max", 0) or tab.get("column_count", 0) or 0

        raw_score, reasons, breakdown = score_tab(
            title=title,
            rows=rows,
            cols=cols,
            domain_context=domain_ctx,
        )

        # Normalize score to 0.0-1.0 range for confidence
        normalized = max(0.0, min(raw_score / 100.0, 1.0))

        entry = {
            "tab_title": title,
            "score": raw_score,
            "confidence": normalized,
            "scoring_rationale": (
                "; ".join(reasons) if reasons else "No domain match"
            ),
            "breakdown": breakdown,
        }
        scored_tabs.append(entry)

        self.record_decision(
            decision_id=f"rescore_{title}",
            phase="score_and_select",
            description=(
                f"Re-scored tab '{title}': "
                f"{'; '.join(reasons) if reasons else 'No domain match'}"
            ),
            outcome="approved" if normalized >= 0.5 else "deferred",
            confidence=normalized,
            metadata={"raw_score": raw_score, "tab_title": title},
        )

    self.discovery.shortlist = scored_tabs

    approved: dict[str, list[str]] = {}
    for tab in scored_tabs:
        if tab["confidence"] >= 0.90:
            approved.setdefault("auto_selected", []).append(tab["tab_title"])
    # Only overwrite approved_tabs if the re-scoring produced results.
    # Otherwise preserve the tab_selection from discover().
    if approved:
        self.discovery.approved_tabs = approved
    elif self.discovery.approved_tabs is None:
        self.discovery.approved_tabs = {}

    self.completed_phases.append("score_and_select")
    return self
