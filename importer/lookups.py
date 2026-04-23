from collections import defaultdict


def normalize_lookup_value(raw_value):
    if raw_value is None:
        return ""
    return " ".join(str(raw_value).strip().split()).casefold()


def build_normalized_lookup_index(model, field_name):
    normalized_index = defaultdict(list)
    for obj in model.objects.all().only("id", field_name).order_by("id"):
        normalized_index[normalize_lookup_value(getattr(obj, field_name))].append(obj.id)
    return normalized_index


def resolve_fk_by_text(model, field_name, raw_value, label, cache, stdout, style, write_disabled=False):
    if write_disabled:
        return raw_value
    if not raw_value:
        return None

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
