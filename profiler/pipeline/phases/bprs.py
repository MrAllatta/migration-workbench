"""Backward-compat re-exports for bprs phase methods.

Functions have moved to ``operational_model`` and ``behavioral_spec``.
This module re-exports all public names for backward compatibility.
"""

from profiler.pipeline.phases.behavioral_spec import (  # noqa: F401
    derive_behavioral_spec,
    derive_state_projections,
    validate_behavioral_spec,
)
from profiler.pipeline.phases.operational_model import (  # noqa: F401
    _derive_doc_scaffold_from_operational_model,
    _derive_schema_contract_from_operational_model,
    _derive_test_scaffold_from_operational_model,
    derive_operational_model,
    validate_operational_model,
)
