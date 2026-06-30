"""Tests for workbook/makefile_targets.py shared Makefile target builders."""

from workbook.makefile_targets import (
    MakeContext,
    phonies,
    variables_block,
    generate_models_block,
    generate_admin_block,
    generate_import_block,
    generate_view_manifest_block,
    generate_pipeline_manifest_block,
    generate_all_block,
    codegen_tooling_block,
    import_blocks,
    profile_blocks,
    deploy_blocks,
)


def test_phonies_returns_list():
    names = phonies(MakeContext())
    assert isinstance(names, list)
    assert len(names) > 0
    assert "generate-models" in names
    assert "generate-view-manifest" in names
    assert "generate-pipeline-manifest" in names
    assert "import-preflight" in names
    assert "import-apply" in names
    assert "pull-preflight" in names
    assert "pull-apply" in names


def test_phonies_has_no_duplicates():
    names = phonies(MakeContext())
    assert len(names) == len(set(names))


def test_variables_block_contains_expected_assignments():
    block = variables_block(MakeContext())
    assert "CONTRACT" in block
    assert "CORE" in block
    assert "BUNDLE_OUT" in block
    assert "VIEW_MANIFEST" in block
    assert "DATE_STAMP" in block


def test_generate_models_block():
    block = generate_models_block(MakeContext())
    assert block.startswith("generate-models:")
    assert "wb generate models" in block
    assert "$(MANAGE) generate_models" not in block
    assert "--contract" in block


def test_generate_admin_block():
    block = generate_admin_block(MakeContext())
    assert block.startswith("generate-admin:")
    assert "wb generate admin" in block
    assert "$(MANAGE) generate_admin" not in block
    # Uses shell conditionals instead of make if/else
    assert (
        '$(shell if [ -f "$(VIEW_MANIFEST)" ]; then echo "--manifest $(VIEW_MANIFEST)"; fi)'
        in block
    )
    assert (
        '$(shell if [ -f "build/codegen-manifest.yaml" ]; then echo "--codegen-manifest build/codegen-manifest.yaml"; fi)'
        in block
    )
    assert '--out "$(CORE)/admin.py"' in block


def test_generate_import_block():
    block = generate_import_block(MakeContext())
    assert block.startswith("generate-import:")
    assert "wb generate import" in block
    assert "$(MANAGE) generate_import" not in block


def test_generate_view_manifest_block():
    block = generate_view_manifest_block(MakeContext())
    assert block.startswith("generate-view-manifest:")
    assert "wb generate manifest" in block
    assert "scaffold_view_manifest" not in block


def test_generate_pipeline_manifest_block():
    block = generate_pipeline_manifest_block(MakeContext())
    assert block.startswith("generate-pipeline-manifest:")
    assert "$(MANAGE) generate_pipeline_manifest" in block
    assert "wb generate manifest --pipeline" not in block
    assert "CORPUS_CONFIG" in block
    assert "PIPELINE_MANIFEST_OUT" in block


def test_generate_all_block_includes_pipeline_manifest():
    block = generate_all_block(MakeContext())
    assert block.startswith("generate-all:")
    assert "generate-models" in block
    assert "generate-view-manifest" in block
    assert "generate-admin" in block
    assert "generate-import" in block
    assert "generate-pipeline-manifest" in block


def test_codegen_tooling_block_contains_targets():
    block = codegen_tooling_block(MakeContext())
    assert "diff-generated:" in block
    assert "generate-admin-light:" in block
    assert "post-generate:" in block
    assert "check-generated:" in block
    assert "snapshot-codegen:" in block
    assert "check-snapshots:" in block
    assert "drift-check:" in block


def test_import_blocks_contains_all_targets():
    block = import_blocks(MakeContext())
    assert "pull-bundle:" in block
    assert "load-data:" in block
    assert "push-data:" in block
    assert "import-preflight:" in block
    assert "import-apply:" in block
    assert "pull-preflight:" in block
    assert "pull-apply:" in block


def test_import_preflight_uses_import_preflight_script():
    block = import_blocks(MakeContext())
    assert "import_preflight" in block
    preflight_section = block[block.index("import-preflight:") :]
    preflight_section = preflight_section[
        : (
            preflight_section.index("\n\n")
            if "\n\n" in preflight_section
            else len(preflight_section)
        )
    ]
    assert "import_preflight" in preflight_section


def test_import_apply_uses_import_apply_script():
    block = import_blocks(MakeContext())
    apply_section = block[block.index("import-apply:") :]
    apply_section = apply_section[
        : apply_section.index("\n\n") if "\n\n" in apply_section else len(apply_section)
    ]
    assert "import_apply" in apply_section


def test_pull_preflight_uses_pull_preflight_script():
    block = import_blocks(MakeContext())
    assert "pull_preflight" in block


def test_pull_apply_uses_pull_apply_script():
    block = import_blocks(MakeContext())
    assert "pull_apply" in block


def test_profile_blocks_contains_all_profiles():
    block = profile_blocks(MakeContext())
    assert "profile-preflight:" in block
    assert "profile-drive-folder:" in block
    assert "profile-coda-corpus:" in block
    assert "profile-cohort-corpus:" in block
    assert "profile-cohort-corpus-phase1:" in block
    assert "profile-cohort-corpus-phase2:" in block
    assert "profile-cohort-corpus-phase3:" in block


def test_deploy_blocks_contains_all_deploy_targets():
    block = deploy_blocks(MakeContext())
    assert "docker-build:" in block
    assert "fly-launch:" in block
    assert "fly-volume:" in block
    assert "fly-secrets:" in block
    assert "fly-deploy:" in block
    assert "deploy:" in block


def test_generate_view_manifest_appears_exactly_once_in_full_output():
    """Regression: the old template had duplicate generate-view-manifest."""
    from workbook.makefile_targets import full_targets_block

    block = full_targets_block(MakeContext())
    count = block.count("generate-view-manifest:")
    assert count == 1, f"Expected exactly 1 generate-view-manifest target, got {count}"


def test_codegen_tooling_uses_wb_for_codegen():
    block = codegen_tooling_block(MakeContext())
    for cmd in [
        "generate_models",
        "generate_admin",
        "generate_import",
        "scaffold_view_manifest",
    ]:
        assert f"$(MANAGE) {cmd}" not in block
    assert "wb generate models" in block
    assert "wb generate admin" in block
    assert "wb generate import" in block
    assert "$(MANAGE) check" in block


def test_full_targets_routes_to_real_commands():
    from workbook.makefile_targets import full_targets_block

    full = full_targets_block(MakeContext())
    assert "wb generate models" in full
    assert "wb generate admin" in full
    assert "wb generate import" in full
    assert "wb generate manifest" in full
    assert "$(MANAGE) generate_pipeline_manifest" in full
    assert "$(MANAGE) generate_discovery_interview" in full
    assert "$(MANAGE) merge_discovery_notes" in full
    assert "wb generate manifest --pipeline" not in full
    assert "wb generate discovery-interview" not in full


def test_import_blocks_discovery_interview_uses_manage():
    block = import_blocks(MakeContext())
    assert "$(MANAGE) generate_discovery_interview" in block
    assert "wb generate discovery-interview" not in block
