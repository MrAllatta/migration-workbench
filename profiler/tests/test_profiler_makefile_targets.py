"""Tests for ``workbook/makefile_targets.py`` — shared Makefile target generators."""

from workbook.makefile_targets import (
    MakeContext,
    phonies,
    profile_phase_blocks,
    profile_clean_block,
    full_targets_block,
    derive_behavioral_spec_block,
    validate_behavioral_spec_block,
)


class TestPhonies:
    """Verify the phony target list includes new targets."""

    def test_profile_phase_validate_included(self):
        """profile-phase-validate is a registered phony."""
        names = phonies(MakeContext())
        assert "profile-phase-validate" in names

    def test_profile_clean_included(self):
        """profile-clean is a registered phony."""
        names = phonies(MakeContext())
        assert "profile-clean" in names


class TestProfilePhaseBlocks:
    """Verify profile_phase_blocks output."""

    def test_includes_validate_target(self):
        """profile-phase-validate target is present."""
        output = profile_phase_blocks(MakeContext())
        assert "profile-phase-validate" in output

    def test_includes_domain_context_expansion(self):
        """DOMAIN_CONTEXT env var expansion syntax is present."""
        output = profile_phase_blocks(MakeContext())
        assert "DOMAIN_CONTEXT" in output

    def test_includes_pipeline_checkpoint_var(self):
        """PIPELINE_CHECKPOINT Makefile variable is referenced."""
        output = profile_phase_blocks(MakeContext())
        assert "PIPELINE_CHECKPOINT" in output

    def test_deprecation_header_present(self):
        """Deprecation notice mentions old phased workflow."""
        output = profile_phase_blocks(MakeContext())
        assert "profile-cohort-corpus-phase" in output

    def test_all_five_phases_present(self):
        """discover, score_and_select, deep_profile, derive_contracts, validate."""
        output = profile_phase_blocks(MakeContext())
        for phase in (
            "discover",
            "score_and_select",
            "deep_profile",
            "derive_contracts",
            "validate",
        ):
            assert f"--phase {phase}" in output

    def test_all_target_has_all_phases(self):
        """profile-phase-all runs all phases."""
        output = profile_phase_blocks(MakeContext())
        assert "profile-phase-all" in output
        assert "--phase all" in output


class TestProfileCleanBlock:
    """Verify profile-clean target output."""

    def test_profile_clean_present(self):
        """profile-clean target is in the block."""
        output = profile_clean_block(MakeContext())
        assert "profile-clean" in output

    def test_removes_pipeline_checkpoint(self):
        """rm -f references PIPELINE_CHECKPOINT."""
        output = profile_clean_block(MakeContext())
        assert "rm -f" in output

    def test_removes_profile_snapshots(self):
        """rm -rf data/profile_snapshots/ is present."""
        output = profile_clean_block(MakeContext())
        assert "data/profile_snapshots" in output

    def test_confirmation_prompt(self):
        """Confirmation prompt is present."""
        output = profile_clean_block(MakeContext())
        assert "Are you sure" in output

    def test_force_clean_bypass(self):
        """FORCE=1 bypasses prompt but cleanup always runs."""
        output = profile_clean_block(MakeContext())
        assert 'if [ -z "$$FORCE" ]; then' in output
        assert "rm -f" in output
        # "FORCE not set - skipping cleanup" should NOT exist;
        # cleanup runs regardless of FORCE after the prompt gate
        assert "FORCE not set" not in output


class TestBehavioralSpecBlocks:
    """Verify behavioral spec target blocks."""

    def test_derive_behavioral_spec_present(self):
        """derive-behavioral-spec target is in the block."""

        output = derive_behavioral_spec_block(MakeContext())
        assert "derive-behavioral-spec" in output

    def test_validate_behavioral_spec_present(self):
        """validate-behavioral-spec target is in the block."""

        output = validate_behavioral_spec_block(MakeContext())
        assert "validate-behavioral-spec" in output

    def test_behavioral_spec_targets(self):
        """Both derive-behavioral-spec and validate-behavioral-spec appear in generated blocks."""

        derive_output = derive_behavioral_spec_block(MakeContext())
        validate_output = validate_behavioral_spec_block(MakeContext())
        assert "derive-behavioral-spec" in derive_output
        assert "validate-behavioral-spec" in validate_output


class TestFullTargetsBlock:
    """Verify full_targets_block wires everything together."""

    def test_includes_profile_clean(self):
        """profile-clean appears in the full block."""
        output = full_targets_block(MakeContext())
        assert "profile-clean" in output

    def test_includes_profile_phase_validate(self):
        """profile-phase-validate appears in the full block."""
        output = full_targets_block(MakeContext())
        assert "profile-phase-validate" in output
