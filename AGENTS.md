# AGENTS.md - Development Guidance

## Management Commands

### Domain Context Commands

- `extract_workbook_codes`: Extract unique workbook codes from drive tree
- `validate_domain_context`: Validate domain_context.yaml structure
- `draft_domain_context`: Draft domain_context.yaml from drive tree

### Profiling Commands

- `profile_cohort_corpus`: Profile cohort corpus with optional domain_context.yaml
- `profile_drive_folder`: Profile drive folder (Phase 0)
- `profile_tab`: Profile tabs (Phase 1)

## Dry-Run Mode

Commands that support `--dry-run` will output what they would do without making changes. Use this to verify behavior before running for real.

## Testing

Run `make chassis-gate` before merging to verify all tests pass.