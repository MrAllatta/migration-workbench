"""Import tests for new phase modules under profiler/pipeline/phases/.

These modules are being extracted from profiler/tools/pipeline_state.py
as part of e06s03. The tests verify the modules can be imported before
any phase methods are assigned to PipelineState.
"""


class TestPhaseModuleImports:
    """Verify each phase module can be imported."""

    def test_import_discover_module(self):
        """profiler.pipeline.phases.discover imports cleanly."""
        from profiler.pipeline.phases import discover  # noqa: F401

        assert discover is not None

    def test_import_deep_profile_module(self):
        """profiler.pipeline.phases.deep_profile imports cleanly."""
        from profiler.pipeline.phases import deep_profile  # noqa: F401

        assert deep_profile is not None

    def test_import_derive_contracts_module(self):
        """profiler.pipeline.phases.derive_contracts imports cleanly."""
        from profiler.pipeline.phases import derive_contracts  # noqa: F401

        assert derive_contracts is not None

    def test_import_scan_formulas_module(self):
        """profiler.pipeline.phases.scan_formulas imports cleanly."""
        from profiler.pipeline.phases import scan_formulas  # noqa: F401

        assert scan_formulas is not None

    def test_import_bprs_module(self):
        """profiler.pipeline.phases.bprs imports cleanly (backward compat)."""
        from profiler.pipeline.phases import bprs  # noqa: F401

        assert bprs is not None

    def test_import_score_select_module(self):
        """profiler.pipeline.phases.score_select imports cleanly."""
        from profiler.pipeline.phases import score_select  # noqa: F401

        assert score_select is not None

    def test_import_operational_model_module(self):
        """profiler.pipeline.phases.operational_model imports cleanly."""
        from profiler.pipeline.phases import operational_model  # noqa: F401

        assert operational_model is not None

    def test_import_behavioral_spec_module(self):
        """profiler.pipeline.phases.behavioral_spec imports cleanly."""
        from profiler.pipeline.phases import behavioral_spec  # noqa: F401

        assert behavioral_spec is not None
