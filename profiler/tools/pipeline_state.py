"""PipelineState — re-export shim with phase methods.

The thin PipelineState checkpoint object (dataclass fields, serialization,
migration, validation) has moved to ``profiler/pipeline/state.py``.

Phase methods have moved to ``profiler/pipeline/phases/``.

This module re-exports all public names from ``profiler.pipeline.state`` and
assembles the :class:`PipelineState` class with phase methods imported from
the phase modules under ``profiler.pipeline.phases``.
"""

from __future__ import annotations

# Re-export all names from the thin checkpoint module.
from profiler.pipeline.state import (
    PipelineState as _PipelineState,
    DecisionRecord,
    DeepProfileIndex,
    DiscoveryState,
    DomainKnowledge,
    _CHECKPOINT_CURRENT_VERSION,
    _CHECKPOINT_MIGRATIONS,
    _PHASE_ORDER,
    _col_index_to_letter,
    _extract_approved_tabs,
    _is_scored_shortlist,
    _migrate_v0_0_8_to_v0_0_9,
    _migrate_v0_0_9_to_v0_1_0,
    _migrate_v0_2_0_to_v0_3_0,
    _resolve_artifacts,
    _version_less_eq,
    _version_less_than,
    _version_tuple,
    _write_contract_artifact,
)

# Shared utility functions (module-level, assigned as static methods).
from profiler.pipeline.phases._base import (
    _build_google_services as _base_build_google_services,
    _load_json_artifact as _base_load_json_artifact,
)

# Phase method imports.
from profiler.pipeline.phases.discover import discover
from profiler.pipeline.phases.score_select import score_and_select
from profiler.pipeline.phases.deep_profile import (
    _enrich_entry_with_formula_dependencies,
    _extract_columns_from_entry,
    deep_profile,
)
from profiler.pipeline.phases.derive_contracts import (
    _classify_deep_profiled_tabs,
    _emit_profiler_signals,
    _filter_ui_config_tabs,
    derive_contracts,
)
from profiler.pipeline.phases.scan_formulas import scan_formulas
from profiler.pipeline.phases.operational_model import (
    _derive_doc_scaffold_from_operational_model,
    _derive_schema_contract_from_operational_model,
    _derive_test_scaffold_from_operational_model,
    derive_operational_model,
    validate_operational_model,
)
from profiler.pipeline.phases.behavioral_spec import (
    derive_behavioral_spec,
    derive_state_projections,
    validate_behavioral_spec,
)


class PipelineState(_PipelineState):
    """PipelineState with phase methods (assembled from phase modules).

    All state fields and checkpoint I/O are inherited from
    ``profiler.pipeline.state.PipelineState``.  Phase methods are
    imported from ``profiler.pipeline.phases.*``.
    """

    # ------------------------------------------------------------------
    # Phase methods
    # ------------------------------------------------------------------
    discover = discover
    score_and_select = score_and_select
    deep_profile = deep_profile
    derive_contracts = derive_contracts
    scan_formulas = scan_formulas

    # BPRS phase methods
    derive_operational_model = derive_operational_model
    derive_behavioral_spec = derive_behavioral_spec
    derive_state_projections = derive_state_projections
    validate_operational_model = validate_operational_model
    validate_behavioral_spec = validate_behavioral_spec

    # ------------------------------------------------------------------
    # Static helpers (module-level functions wrapped as static methods)
    # ------------------------------------------------------------------
    _load_json_artifact = staticmethod(_base_load_json_artifact)
    _build_google_services = staticmethod(_base_build_google_services)

    # ------------------------------------------------------------------
    # Private helper methods
    # ------------------------------------------------------------------
    _enrich_entry_with_formula_dependencies = (
        _enrich_entry_with_formula_dependencies
    )
    _extract_columns_from_entry = _extract_columns_from_entry
    _classify_deep_profiled_tabs = _classify_deep_profiled_tabs
    _filter_ui_config_tabs = _filter_ui_config_tabs
    _emit_profiler_signals = _emit_profiler_signals
    _derive_schema_contract_from_operational_model = (
        _derive_schema_contract_from_operational_model
    )
    _derive_test_scaffold_from_operational_model = (
        _derive_test_scaffold_from_operational_model
    )
    _derive_doc_scaffold_from_operational_model = (
        _derive_doc_scaffold_from_operational_model
    )
