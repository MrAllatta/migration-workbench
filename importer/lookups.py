"""FK resolution helpers for text-keyed spreadsheet imports.

Provides a two-pass lookup strategy:

1. **Exact match** — ``QuerySet.filter`` on the raw cell value (fast, precise).
2. **Normalized fuzzy match** — collapse whitespace and casefold, then look up
   against a per-model cache built on first use.

The cache avoids repeated ``objects.all()`` queries when many rows reference the
same model.  Pass the shared ``normalized_lookup_indexes`` dict from
:class:`~importer.chassis.ImporterChassisMixin` so the cache is reused across
all model tiers in a single import run.
"""

from collections import defaultdict


def normalize_lookup_value(raw_value):
    """Collapse whitespace and casefold *raw_value* for fuzzy comparison.

    ``None`` maps to ``""`` so callers can always compare strings without an
    extra guard.

    Args:
        raw_value: Any value; ``str()`` is called before normalizing.

    Returns:
        str: Lowercased, single-space-collapsed string.
    """
    if raw_value is None:
        return ""
    return " ".join(str(raw_value).strip().split()).casefold()


def build_normalized_lookup_index(model, field_name):
    """Build a ``normalized_value -> [id, ...]`` index for *model* and *field_name*.

    Fetches all rows with ``only("id", field_name)`` to minimize data transfer,
    then stores each ``id`` under its normalized field value.  A list is used per
    key so ambiguous matches are detectable by the caller.

    Args:
        model: Django model class to index.
        field_name: Name of the text field used as the lookup key.

    Returns:
        defaultdict[str, list[int]]: Mapping from normalized field value to a
        list of matching primary keys, ordered by ``id``.
    """
    normalized_index = defaultdict(list)
    for obj in model.objects.all().only("id", field_name).order_by("id"):
        normalized_index[normalize_lookup_value(getattr(obj, field_name))].append(obj.id)
    return normalized_index


def resolve_fk_by_text(model, field_name, raw_value, label, cache, stdout, style, write_disabled=False):
    """Resolve a foreign-key reference using exact-then-normalized text matching.

    **Pass 1 — exact match**: filters the queryset with the raw cell value
    unchanged so spelling-preserved references never hit the fuzzy path.

    **Pass 2 — normalized match**: casefolds and collapses whitespace, then
    checks a per-model in-memory index (built lazily and stored in *cache*).

    Warns via *stdout* when multiple candidates share a key; in that case the
    lowest ``id`` wins.

    Args:
        model: Django model class that owns the target rows.
        field_name: Field on *model* to match against.
        raw_value: Raw text from the source spreadsheet cell.
        label: Human-readable name for the model (used in warning messages).
        cache: Shared ``dict`` that stores previously built normalized indexes;
            mutated in place so repeated calls reuse the same index.
        stdout: Django management command ``stdout`` stream for warnings.
        style: Django management command ``style`` object (e.g. ``self.style``).
        write_disabled: When ``True``, skip the DB entirely and return *raw_value*
            as-is (used in dry-run / validate-only modes).

    Returns:
        model instance or None: Matching object, or ``None`` when no match is found.
        Returns *raw_value* unchanged when *write_disabled* is ``True``.
    """
    if write_disabled:
        return raw_value
    if not raw_value:
        return None

    # Exact match is cheaper and should cover the majority of rows.
    exact_value = str(raw_value).strip()
    exact_matches = model.objects.filter(**{field_name: exact_value}).order_by("id")
    first_exact = exact_matches.first()
    if first_exact:
        if exact_matches.count() > 1:
            stdout.write(
                style.WARNING(
                    f"   Multiple {label} matches for '{raw_value}'; using id={first_exact.id}"
                )
            )
        return first_exact

    # Fall back to the normalized index for casing/whitespace mismatches.
    normalized_value = normalize_lookup_value(raw_value)
    if not normalized_value:
        return None

    cache_key = f"{model._meta.label_lower}:{field_name}"
    if cache_key not in cache:
        cache[cache_key] = build_normalized_lookup_index(model, field_name)
    candidate_ids = cache[cache_key].get(normalized_value, [])
    if not candidate_ids:
        return None

    candidate = model.objects.filter(id=candidate_ids[0]).first()
    if candidate and len(candidate_ids) > 1:
        stdout.write(
            style.WARNING(
                f"   Multiple normalized {label} matches for '{raw_value}'; using id={candidate.id}"
            )
        )
    return candidate
