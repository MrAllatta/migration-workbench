"""Validation record and coverage report framework — backward-compat shim.

This module is a thin re-export shim that imports from the new MWBS
validation layer in ``profiler.tools.behavioral_spec_validation``.

It exists so that existing callers (primarily ``pipeline_state.py``) continue
to work without immediate import changes.
"""

from profiler.tools.behavioral_spec_validation import (  # noqa: F401
    CoverageReport,
    ValidationRecord,
    compute_coverage_metrics,
)
