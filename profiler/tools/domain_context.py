"""Domain context artifact: the profiler's model of the business domain.

Loaded from a YAML file referenced by ``cohort_corpus.json``, the domain context
provides vocabulary (mapped to heuristic tokens), year scoping, structural
deduplication, and synonym expansion. When absent, all profiler behavior is
identical to the pre-domain-context baseline.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)


@dataclass
class DomainContext:
    """Structured domain knowledge consumed by the profiler at scoring time."""

    @dataclass
    class YearScope:
        active: list[int] = field(default_factory=list)
        archived: list[int] = field(default_factory=list)
        forward: list[int] = field(default_factory=list)

    @dataclass
    class DeduplicationContext:
        strategy: str = "latest_year"
        exceptions: list[dict] = field(default_factory=list)

    @dataclass
    class VocabularyContext:
        operational: list[str] = field(default_factory=list)
        reference: list[str] = field(default_factory=list)
        support: list[str] = field(default_factory=list)
        derived: list[str] = field(default_factory=list)

    domain: str = ""
    description: str = ""
    year_scope: YearScope = field(default_factory=YearScope)
    deduplication: DeduplicationContext = field(default_factory=DeduplicationContext)
    entities: list[dict] = field(default_factory=list)
    vocabulary: VocabularyContext = field(default_factory=VocabularyContext)
    glossary: dict[str, str] = field(default_factory=dict)
    scope_notes: str = ""

    def active_years(self) -> set[int]:
        years: set[int] = set(self.year_scope.active)
        years.update(self.year_scope.archived)
        years.update(self.year_scope.forward)
        return years

    def is_archived_year(self, year: int) -> bool:
        return year in self.year_scope.archived

    def is_deduplication_exception(self, tab_title: str) -> bool:
        for exc in self.deduplication.exceptions:
            if exc.get("tab_title") == tab_title:
                return True
        return False


def load_domain_context(path: str | Path) -> DomainContext | None:
    file_path = Path(path)
    if not file_path.exists():
        return None
    raw = yaml.safe_load(file_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return None
    raw = {k: v for k, v in raw.items() if not k.startswith("_")}

    year_scope_data = raw.get("year_scope") or {}
    dedup_data = raw.get("deduplication") or {}
    vocab_data = raw.get("vocabulary") or {}

    raw_exceptions = dedup_data.get("exceptions") or []
    normalized_exceptions: list[dict] = []
    for entry in raw_exceptions:
        if isinstance(entry, str):
            normalized_exceptions.append({"tab_title": entry})
        elif isinstance(entry, dict):
            normalized_exceptions.append(entry)

    return DomainContext(
        domain=str(raw.get("domain", "")),
        description=str(raw.get("description", "")),
        year_scope=DomainContext.YearScope(
            active=year_scope_data.get("active") or [],
            archived=year_scope_data.get("archived") or [],
            forward=year_scope_data.get("forward") or [],
        ),
        deduplication=DomainContext.DeduplicationContext(
            strategy=str(dedup_data.get("strategy", "latest_year")),
            exceptions=normalized_exceptions,
        ),
        entities=raw.get("entities") or [],
        vocabulary=DomainContext.VocabularyContext(
            operational=vocab_data.get("operational") or [],
            reference=vocab_data.get("reference") or [],
            support=vocab_data.get("support") or [],
            derived=vocab_data.get("derived") or [],
        ),
        glossary=raw.get("glossary") or {},
        scope_notes=str(raw.get("scope_notes", "")),
    )


def merge_vocabulary(
    heuristics: dict,
    domain_context: DomainContext | None,
) -> dict:
    if domain_context is None:
        return heuristics
    token_keys = {
        "operational_tokens": domain_context.vocabulary.operational,
        "reference_tokens": domain_context.vocabulary.reference,
        "support_tokens": domain_context.vocabulary.support,
        "derived_tokens": domain_context.vocabulary.derived,
    }
    merged = dict(heuristics)
    for hkey, vocab_list in token_keys.items():
        existing = set(merged.get(hkey) or [])
        for token in vocab_list:
            existing.add(token.lower())
        merged[hkey] = sorted(existing)
    return merged


def deduplicate_index_records(
    index_records: list[dict],
    approved_tabs: dict[str, list[str]],
    domain_context: DomainContext | None,
) -> list[dict]:
    """Filter index records for Phase 3 deep profiling.

    Removes records for archived years. Tab-level deduplication
    (latest-year-per-tab and exceptions) is handled in the
    deep-profiling loop where tab_title is in scope.

    When *domain_context* is ``None``, returns *index_records* unchanged.
    """
    if domain_context is None:
        return list(index_records)

    return [
        rec
        for rec in index_records
        if not domain_context.is_archived_year(rec.get("year"))
    ]


def has_meaningful_vocabulary(domain_context: DomainContext | None) -> bool:
    if domain_context is None:
        return False
    return bool(
        domain_context.vocabulary.operational or domain_context.vocabulary.reference
    )
