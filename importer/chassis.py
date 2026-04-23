from collections import defaultdict


class ImporterChassisMixin:
    def setup_runtime(self):
        self.row_errors = []
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
        self.normalized_lookup_indexes = {}

    def record_row_error(self, model_name, row_number, code, field_path, message):
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
        message = f"{missing_label} not found '{raw_value}'"
        self.stderr.write(f"    ERROR row {row_number}: {message}")
        self.record_row_error(model_name, row_number, "stale_fk", field_path, message)

    def record_missing_required(self, model_name, row_number, field_path, field_label):
        message = f"missing required value for '{field_label}'"
        self.stderr.write(f"    ERROR row {row_number}: {message}")
        self.record_row_error(model_name, row_number, "missing_required", field_path, message)
