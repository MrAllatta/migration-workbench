"""Runtime state mixin for import pipeline commands.

:class:`ImporterChassisMixin` owns the per-run mutable state (stats dict,
row-error list, FK cache) that every import command tier writes into.  It is
mixed in *before* Django's ``BaseCommand`` so ``self.stderr`` is always
available when recording errors.

Typical MRO in a concrete import command::

    class Command(BaseImportCommand):  # BaseImportCommand(ImporterChassisMixin, BaseCommand)
        ...
"""

from collections import defaultdict


class ImporterChassisMixin:
    """Mixin that initialises and manages per-run import state.

    Provides a unified interface for recording row-level errors and outcome
    counters so all model tiers write to the same shared summary payload.
    """

    def setup_runtime(self):
        """Initialise per-run state containers.

        Must be called once at the start of each ``handle()`` invocation before
        any tier writes stats or errors.  Resetting here (rather than in
        ``__init__``) ensures a fresh slate on every management-command
        invocation even when the process is reused.
        """
        self.row_errors = []
        # defaultdict lets tiers write self.stats["ModelName"]["created"] += 1
        # without first checking whether the key exists.
        self.stats = defaultdict(
            lambda: {
                "created": 0,
                "updated": 0,
                "skipped": 0,
                "error": 0,
                "processed": 0,
                "errors": 0,
            }
        )
        # Shared FK resolution cache populated lazily by resolve_fk_by_text.
        self.normalized_lookup_indexes = {}

    def record_row_error(self, model_name, row_number, code, field_path, message):
        """Append a structured row-level error to the run's error log.

        Args:
            model_name: Label of the Django model being imported (e.g. ``"Crop"``).
            row_number: 1-based row number from the source CSV.
            code: Short error code identifying the failure class (e.g.
                ``"stale_fk"``, ``"missing_required"``).
            field_path: Dotted field path for the failing value
                (e.g. ``"crop.variety"``).
            message: Human-readable description of the failure.
        """
        self.row_errors.append(
            {
                "model": model_name,
                "row": row_number,
                "code": code,
                "field_path": field_path,
                "message": str(message),
            }
        )

    def record_stale_fk(self, model_name, row_number, field_path, missing_label, raw_value):
        """Record a foreign-key miss and write an error line to stderr.

        A "stale FK" means the source data references a related record that
        does not exist in the target database (e.g. a crop variety that was
        removed after the last sync).

        Args:
            model_name: Label of the model being imported.
            row_number: 1-based source row number.
            field_path: Dotted field path for the FK column.
            missing_label: Human-readable name of the missing related object.
            raw_value: The raw cell value that failed to resolve.
        """
        message = f"{missing_label} not found '{raw_value}'"
        self.stderr.write(f"    ERROR row {row_number}: {message}")
        self.record_row_error(model_name, row_number, "stale_fk", field_path, message)

    def record_missing_required(self, model_name, row_number, field_path, field_label):
        """Record a missing required field and write an error line to stderr.

        Args:
            model_name: Label of the model being imported.
            row_number: 1-based source row number.
            field_path: Dotted path to the field that was blank.
            field_label: Human-readable field name shown in the error message.
        """
        message = f"missing required value for '{field_label}'"
        self.stderr.write(f"    ERROR row {row_number}: {message}")
        self.record_row_error(model_name, row_number, "missing_required", field_path, message)
