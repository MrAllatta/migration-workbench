"""Header detection, row normalisation, and CSV output for tabular connectors.

The core public functions are:

* :func:`canonicalize_header_row` — apply alias substitutions to a raw header.
* :func:`detect_header_row` — locate the header row in a raw row list.
* :func:`normalize_rows` — detect + project + transform a row list in one call.
* :func:`normalize_csv_file` — read a CSV, normalize it, and write the output.

All functions operate on plain ``list[list]`` data (as returned by
:mod:`csv.reader`) so they are provider-agnostic and easy to test without
filesystem or network access.

**Header detection strategies** (in priority order):

1. ``prefer_anchor_token`` — look for a sentinel value in the first cell and
   use the *following* row as the header (useful when a label row precedes the
   real header).
2. Required-header set scan — walk rows until all required headers are present.
3. ``anchor_token`` fallback — same sentinel strategy without the priority flag.
4. ``header_row_index`` — use an explicit 0-based row index (last resort).
"""

import csv
from datetime import date
from pathlib import Path


def _normalize_text(value):
    if value is None:
        return ""
    return " ".join(str(value).strip().split()).casefold()


def canonicalize_header_row(header_row, aliases=None):
    """Apply alias substitutions to *header_row* and strip extra whitespace.

    Each cell is looked up in the normalised alias map; if found, the alias
    value is used as the canonical name.  Otherwise the cell is returned
    with interior whitespace collapsed (but original casing preserved).

    Args:
        header_row: List of raw header cell values.
        aliases: Optional ``{raw_name: canonical_name}`` mapping.  Keys are
            matched after normalisation (casefold + whitespace collapse).

    Returns:
        list[str]: Canonicalised header names, same length as *header_row*.
    """
    alias_map = {_normalize_text(key): value for key, value in (aliases or {}).items()}
    canonical = []
    for cell in header_row:
        normalized = _normalize_text(cell)
        canonical.append(alias_map.get(normalized, " ".join(str(cell).strip().split())))
    return canonical


def summarize_header_detection_failure(
    rows,
    required_headers,
    aliases=None,
    max_scan_rows=200,
    anchor_token=None,
    header_row_index=None,
    prefer_anchor_token=False,
    preview_limit=5,
):
    """Return compact diagnostics for header-contract misses.

    This helper is intentionally read-only: it explains why detection failed
    without changing matching behavior.
    """
    normalized_required = {_normalize_text(value) for value in required_headers}
    scan_limit = min(len(rows), max_scan_rows)
    alias_map = {_normalize_text(key): value for key, value in (aliases or {}).items()}

    def _row_score(row):
        canonical = canonicalize_header_row(row, aliases=aliases)
        normalized = {_normalize_text(value) for value in canonical}
        match_count = len(normalized_required & normalized)
        missing = [
            value
            for value in required_headers
            if _normalize_text(value) not in normalized
        ]
        return canonical, match_count, missing

    candidates = []
    for index in range(scan_limit):
        row = rows[index] if index < len(rows) else []
        if not row or all(str(cell).strip() == "" for cell in row):
            continue
        canonical, match_count, missing = _row_score(row)
        candidates.append(
            {
                "row_index": index,
                "match_count": match_count,
                "required_count": len(normalized_required),
                "missing_required_headers": missing[:8],
                "header_preview": canonical[:12],
            }
        )

    candidates.sort(key=lambda item: (-item["match_count"], item["row_index"]))

    anchor_rows = []
    if anchor_token:
        normalized_anchor = _normalize_text(anchor_token)
        for index in range(scan_limit):
            first_cell = rows[index][0] if rows[index] else ""
            if normalized_anchor in _normalize_text(first_cell):
                candidate_index = index + 1
                preview = rows[candidate_index] if candidate_index < len(rows) else []
                anchor_rows.append(
                    {
                        "anchor_row_index": index,
                        "candidate_header_row_index": candidate_index,
                        "candidate_preview": canonicalize_header_row(preview, aliases=aliases)[:12],
                    }
                )

    return {
        "scan_limit": scan_limit,
        "required_headers": list(required_headers),
        "required_header_count": len(normalized_required),
        "anchor_token": anchor_token,
        "header_row_index": header_row_index,
        "prefer_anchor_token": prefer_anchor_token,
        "alias_keys": list(alias_map.keys())[:20],
        "top_candidates": candidates[:preview_limit],
        "anchor_candidates": anchor_rows[:preview_limit],
    }


def _project_rows(rows, output_headers=None, column_map=None, default_values=None):
    if not output_headers:
        return rows

    source_header = rows[0] if rows else []
    source_index = {_normalize_text(value): index for index, value in enumerate(source_header)}
    column_map = column_map or {}
    default_values = default_values or {}

    projected_rows = [output_headers]
    for row in rows[1:]:
        projected_row = []
        for output_header in output_headers:
            source_reference = column_map.get(output_header, output_header)
            if isinstance(source_reference, int):
                source_idx = source_reference
            else:
                source_idx = source_index.get(_normalize_text(source_reference))
            if source_idx is None:
                projected_row.append(default_values.get(output_header, ""))
                continue
            value = row[source_idx] if source_idx < len(row) else ""
            if value == "":
                value = default_values.get(output_header, "")
            projected_row.append(value)
        projected_rows.append(projected_row)
    return projected_rows


def _filter_rows_missing_required_outputs(rows, required_output_values=None):
    """Drop projected rows whose named output columns are blank.

    This runs after projection/defaults/transforms, so lane configs can remove
    formula-skeleton rows without making importers treat connector padding as
    source data.
    """
    if not required_output_values or len(rows) < 2:
        return rows
    header = rows[0]
    idx = {_normalize_text(h): i for i, h in enumerate(header)}
    required_indexes = [
        idx[_normalize_text(name)]
        for name in required_output_values
        if _normalize_text(name) in idx
    ]
    if not required_indexes:
        return rows

    filtered = [header]
    for row in rows[1:]:
        keep = True
        for i in required_indexes:
            value = row[i] if i < len(row) else ""
            if str(value).strip() == "":
                keep = False
                break
        if keep:
            filtered.append(row)
    return filtered


def _split_value(value, delimiter):
    if delimiter not in value:
        return value.strip(), ""
    left, right = value.split(delimiter, 1)
    return left.strip(), right.strip()


def _monday_for_iso_week(year_value, week_value):
    if year_value in ("", None) or week_value in ("", None):
        return ""
    try:
        year = int(str(year_value).strip())
        week = int(str(week_value).strip())
    except ValueError:
        return ""
    return date.fromisocalendar(year, week, 1).isoformat()


def _value_for_transform(source_name, transformed_row, transformed_index, source_row, source_index):
    projected_idx = transformed_index.get(_normalize_text(source_name))
    if projected_idx is not None:
        return transformed_row[projected_idx]
    original_idx = source_index.get(_normalize_text(source_name))
    if original_idx is not None and original_idx < len(source_row):
        return source_row[original_idx]
    return ""


def _apply_row_transforms(rows, row_transforms=None, source_rows=None):
    if not row_transforms:
        return rows

    output_headers = rows[0] if rows else []
    transformed_index = {_normalize_text(value): index for index, value in enumerate(output_headers)}
    source_headers = source_rows[0] if source_rows else []
    source_index = {_normalize_text(value): index for index, value in enumerate(source_headers)}
    transformed_rows = [output_headers]

    for row_number, row in enumerate(rows[1:], start=1):
        transformed_row = list(row)
        source_row = source_rows[row_number] if source_rows and row_number < len(source_rows) else []
        for transform in row_transforms:
            transform_type = transform["type"]
            if transform_type == "split":
                left_value, right_value = _split_value(
                    _value_for_transform(
                        transform["source"],
                        transformed_row,
                        transformed_index,
                        source_row,
                        source_index,
                    ),
                    transform.get("delimiter", "//"),
                )
                left_target = transformed_index.get(_normalize_text(transform["left_target"]))
                right_target = transformed_index.get(_normalize_text(transform["right_target"]))
                if left_target is not None:
                    transformed_row[left_target] = left_value
                if right_target is not None:
                    transformed_row[right_target] = right_value
            elif transform_type == "copy":
                value = _value_for_transform(
                    transform["source"],
                    transformed_row,
                    transformed_index,
                    source_row,
                    source_index,
                )
                for target in transform.get("targets", []):
                    target_index = transformed_index.get(_normalize_text(target))
                    if target_index is not None:
                        transformed_row[target_index] = value
            elif transform_type == "week_monday":
                target_index = transformed_index.get(_normalize_text(transform["target"]))
                if target_index is None:
                    continue
                transformed_row[target_index] = _monday_for_iso_week(
                    _value_for_transform(
                        transform["year_source"],
                        transformed_row,
                        transformed_index,
                        source_row,
                        source_index,
                    ),
                    _value_for_transform(
                        transform["week_source"],
                        transformed_row,
                        transformed_index,
                        source_row,
                        source_index,
                    ),
                )
        transformed_rows.append(transformed_row)

    return transformed_rows


def _parse_week_column_header(cell):
    """Return ISO week number 1–53 if *cell* names a week column, else None."""
    if cell is None:
        return None
    raw = str(cell).strip()
    if not raw:
        return None
    if raw.isdigit():
        w = int(raw)
        if 1 <= w <= 53:
            return w
        return None
    folded = _normalize_text(raw)
    for prefix in ("week ", "wk "):
        if folded.startswith(prefix):
            tail = raw[len(prefix) :].strip()
            if tail.isdigit():
                w = int(tail)
                if 1 <= w <= 53:
                    return w
    return None


def _grid_unpivot_for_product_week_plan(source_rows, grid_unpivot):
    """
    Expand a wide worksheet (identity columns + week columns 1..53) into long
    rows matching ``product_week_plan.csv`` (Channel Name, Product Name, Week,
    Planned Quantity).
    """
    if not source_rows or len(source_rows) < 2:
        return source_rows

    header = source_rows[0]
    header_idx = {_normalize_text(h): i for i, h in enumerate(header)}
    identity = grid_unpivot.get("identity_columns") or []
    if not identity:
        raise ValueError("grid_unpivot requires identity_columns")

    out_headers = grid_unpivot.get("output_headers")
    if not out_headers or len(out_headers) != 4:
        raise ValueError(
            "grid_unpivot output_headers must be exactly four columns: "
            "channel, product, week, planned quantity (importer contract)"
        )

    skip_blank = grid_unpivot.get("skip_blank_quantity", True)
    reserved = set()
    identity_specs = []
    for entry in identity:
        out_name = entry.get("output")
        if not out_name:
            raise ValueError("each identity_columns entry needs output")
        if "fixed" in entry and entry["fixed"] is not None:
            identity_specs.append({"output": out_name, "fixed": str(entry["fixed"]), "source_idx": None})
            continue
        src = entry.get("source")
        if not src:
            raise ValueError("identity_columns entry needs source or fixed")
        idx = header_idx.get(_normalize_text(src))
        if idx is None:
            raise ValueError(f"grid_unpivot: source column {src!r} not found in header")
        identity_specs.append({"output": out_name, "fixed": None, "source_idx": idx})
        reserved.add(idx)

    outputs_declared = {s["output"] for s in identity_specs}
    ch_out, prod_out, _, _ = out_headers
    if ch_out not in outputs_declared or prod_out not in outputs_declared:
        raise ValueError(
            "identity_columns must declare outputs matching output_headers[0] (channel) "
            "and output_headers[1] (product)"
        )

    week_pairs = []
    for i, h in enumerate(header):
        if i in reserved:
            continue
        wn = _parse_week_column_header(h)
        if wn is not None:
            week_pairs.append((wn, i))
    week_pairs.sort(key=lambda x: x[0])
    if not week_pairs:
        raise ValueError("grid_unpivot: no week columns (1–53) detected in header row")

    out = [out_headers]

    for row in source_rows[1:]:
        id_values = {}
        for spec in identity_specs:
            if spec["source_idx"] is None:
                id_values[spec["output"]] = spec["fixed"]
            else:
                idx = spec["source_idx"]
                cell = row[idx] if idx < len(row) else ""
                id_values[spec["output"]] = str(cell).strip() if cell is not None else ""

        product_val = id_values.get(prod_out, "")
        if not str(product_val).strip():
            continue

        for wn, col_idx in week_pairs:
            qty = row[col_idx] if col_idx < len(row) else ""
            if skip_blank and (qty is None or str(qty).strip() == ""):
                continue
            out.append(
                [
                    id_values.get(ch_out, ""),
                    product_val,
                    str(wn),
                    str(qty).strip() if qty is not None else "",
                ]
            )

    return out


def _apply_constant_columns(rows, constant_columns):
    """Set output cells to fixed literals (e.g. Component Source Type = crop)."""
    if not constant_columns:
        return rows
    header = rows[0] if rows else []
    idx = {_normalize_text(h): i for i, h in enumerate(header)}
    for row in rows[1:]:
        for out_name, value in constant_columns.items():
            j = idx.get(_normalize_text(out_name))
            if j is None:
                continue
            while len(row) <= j:
                row.append("")
            row[j] = value
    return rows


def _apply_fold_into_notes(projected_rows, folds, source_rows):
    """Append labeled snippets from source columns into a target column (e.g. Notes).

    folds: list of dicts with keys ``into`` (output header), ``from`` (source header),
    optional ``prefix`` (e.g. ``Variety`` -> ``Variety: value``).
    """
    if not folds or len(projected_rows) < 2:
        return projected_rows
    projected_header = projected_rows[0]
    p_idx = {_normalize_text(h): i for i, h in enumerate(projected_header)}
    source_header = source_rows[0] if source_rows else []
    s_idx = {_normalize_text(h): i for i, h in enumerate(source_header)}

    for row_i in range(1, len(projected_rows)):
        prow = projected_rows[row_i]
        srow = source_rows[row_i] if row_i < len(source_rows) else []
        for fold in folds:
            into = fold.get("into", "Notes")
            frm = fold.get("from")
            prefix = (fold.get("prefix") or "").strip()
            if not frm:
                continue
            si = s_idx.get(_normalize_text(frm))
            ti = p_idx.get(_normalize_text(into))
            if ti is None:
                continue
            raw = ""
            if si is not None and si < len(srow):
                raw = srow[si]
            chunk = str(raw).strip() if raw is not None else ""
            if not chunk:
                continue
            label = f"{prefix}: {chunk}" if prefix else chunk
            prev = str(prow[ti]).strip() if ti < len(prow) else ""
            while len(prow) <= ti:
                prow.append("")
            prow[ti] = f"{prev}\n{label}".strip() if prev else label
    return projected_rows


def _truncate_source_rows(source_rows, stop_on_blank_in=None):
    if not stop_on_blank_in or not source_rows:
        return source_rows

    header = source_rows[0]
    rows = source_rows[1:]
    header_index = {_normalize_text(value): index for index, value in enumerate(header)}
    stop_indexes = []
    for header_name in stop_on_blank_in:
        index = header_index.get(_normalize_text(header_name))
        if index is not None:
            stop_indexes.append(index)

    if not stop_indexes:
        return source_rows

    truncated_rows = [header]
    for row in rows:
        should_stop = False
        for index in stop_indexes:
            value = row[index] if index < len(row) else ""
            if value == "":
                should_stop = True
                break
        if should_stop:
            break
        truncated_rows.append(row)
    return truncated_rows


def _normalize_single_region(
    rows,
    required_headers,
    aliases=None,
    max_scan_rows=200,
    anchor_token=None,
    header_row_index=None,
    output_headers=None,
    column_map=None,
    default_values=None,
    row_transforms=None,
    stop_on_blank_in=None,
    prefer_anchor_token=False,
    grid_unpivot=None,
    fold_into_notes=None,
    constant_columns=None,
    skip_rows_missing=None,
):
    header_index, canonical_header, strategy = detect_header_row(
        rows,
        required_headers=required_headers,
        aliases=aliases,
        max_scan_rows=max_scan_rows,
        anchor_token=anchor_token,
        header_row_index=header_row_index,
        prefer_anchor_token=prefer_anchor_token,
    )
    source_rows = [canonical_header] + rows[header_index + 1 :]
    source_rows = _truncate_source_rows(source_rows, stop_on_blank_in=stop_on_blank_in)
    if grid_unpivot:
        source_rows = _grid_unpivot_for_product_week_plan(source_rows, grid_unpivot)
        output_headers = None
        column_map = None
        default_values = None
        row_transforms = None
        fold_into_notes = None
        constant_columns = None
    normalized_rows = _project_rows(
        source_rows,
        output_headers=output_headers,
        column_map=column_map,
        default_values=default_values,
    )
    normalized_rows = _apply_fold_into_notes(
        normalized_rows, fold_into_notes or [], source_rows
    )
    normalized_rows = _apply_constant_columns(
        normalized_rows, constant_columns or {}
    )
    normalized_rows = _apply_row_transforms(
        normalized_rows,
        row_transforms=row_transforms,
        source_rows=source_rows,
    )
    normalized_rows = _filter_rows_missing_required_outputs(
        normalized_rows,
        required_output_values=skip_rows_missing,
    )
    return {
        "header_row_index": header_index,
        "strategy": strategy,
        "rows": normalized_rows,
    }


def detect_header_row(
    rows,
    required_headers,
    aliases=None,
    max_scan_rows=200,
    anchor_token=None,
    header_row_index=None,
    prefer_anchor_token=False,
):
    """Locate the header row within *rows* and return its canonicalised form.

    Detection strategies are tried in this order (see module docstring for
    full rationale):

    1. Anchor-token priority (when *prefer_anchor_token* is ``True``).
    2. Required-header set scan.
    3. Anchor-token fallback.
    4. Explicit *header_row_index*.

    Args:
        rows: Raw row list (list of lists) from a CSV or provider fetch.
        required_headers: Iterable of column names that must all be present in
            the detected header row.
        aliases: Optional ``{raw_name: canonical_name}`` mapping passed to
            :func:`canonicalize_header_row`.
        max_scan_rows: Maximum number of rows to examine before giving up.
            Defaults to ``200``.
        anchor_token: Sentinel string to search for in the first cell of each
            row; the *following* row is treated as the header candidate.
        header_row_index: Explicit 0-based row index to use as a last resort
            when no strategy succeeds.
        prefer_anchor_token: When ``True``, try the anchor-token strategy
            *before* the required-header scan.

    Returns:
        tuple[int, list[str], str]: ``(header_row_index, canonical_header, strategy)``
        where *strategy* is one of ``"anchor_token"``,
        ``"required_header_set_scan"``, or ``"header_row_index"``.

    Raises:
        ValueError: When no header row is found and *header_row_index* is not
            provided or is out of range.
    """
    normalized_required = {_normalize_text(value) for value in required_headers}
    scan_limit = min(len(rows), max_scan_rows)

    if anchor_token and prefer_anchor_token:
        normalized_anchor = _normalize_text(anchor_token)
        for index in range(scan_limit):
            first_cell = rows[index][0] if rows[index] else ""
            if normalized_anchor in _normalize_text(first_cell):
                candidate_index = index + 1
                if candidate_index < len(rows):
                    canonical = canonicalize_header_row(rows[candidate_index], aliases=aliases)
                    return candidate_index, canonical, "anchor_token"

    for index in range(scan_limit):
        canonical = canonicalize_header_row(rows[index], aliases=aliases)
        if normalized_required <= {_normalize_text(value) for value in canonical}:
            return index, canonical, "required_header_set_scan"

    if anchor_token:
        normalized_anchor = _normalize_text(anchor_token)
        for index in range(scan_limit):
            first_cell = rows[index][0] if rows[index] else ""
            if normalized_anchor in _normalize_text(first_cell):
                candidate_index = index + 1
                if candidate_index < len(rows):
                    canonical = canonicalize_header_row(rows[candidate_index], aliases=aliases)
                    return candidate_index, canonical, "anchor_token"

    if header_row_index is not None:
        if header_row_index < 0 or header_row_index >= len(rows):
            raise ValueError(f"header_row_index {header_row_index} is out of range")
        canonical = canonicalize_header_row(rows[header_row_index], aliases=aliases)
        return header_row_index, canonical, "header_row_index"

    raise ValueError(
        f"no header row matching contract found in first {scan_limit} rows"
    )


def normalize_rows(
    rows,
    required_headers,
    aliases=None,
    max_scan_rows=200,
    anchor_token=None,
    header_row_index=None,
    output_headers=None,
    column_map=None,
    default_values=None,
    row_transforms=None,
    source_regions=None,
    stop_on_blank_in=None,
    prefer_anchor_token=False,
    grid_unpivot=None,
    fold_into_notes=None,
    constant_columns=None,
    skip_rows_missing=None,
):
    """Detect, project, and transform a raw row list into an import-ready form.

    This is the primary normalisation entry point when working with an
    in-memory row list (e.g. fetched from a provider).  For file-based
    workflows use :func:`normalize_csv_file` instead.

    When *source_regions* is provided, each region is normalised independently
    and their data rows (excluding repeated headers) are concatenated into a
    single result.  ``grid_unpivot`` and ``source_regions`` are mutually
    exclusive.

    Args:
        rows: Raw list of lists (header row + data rows) from the provider.
        required_headers: Column names that must appear in the detected header.
        aliases: Header alias mapping (see :func:`canonicalize_header_row`).
        max_scan_rows: Scan limit for header detection.  Defaults to ``200``.
        anchor_token: Sentinel first-cell value for anchor-based detection.
        header_row_index: Explicit header row index (last-resort fallback).
        output_headers: If provided, the output is projected to exactly these
            column names (in order), discarding all other columns.
        column_map: ``{output_header: source_header_or_int}`` remapping applied
            during projection.
        default_values: ``{output_header: default}`` applied when the source
            cell is blank or the column is absent.
        row_transforms: List of transform dicts (``split``, ``copy``,
            ``week_monday``) applied after projection.
        source_regions: List of per-region config dicts.  When supplied, each
            region is normalised with its own parameters and the results are
            merged.
        stop_on_blank_in: List of column names; row scanning stops when any of
            these columns is blank (useful for sheets with trailing summary rows).
        prefer_anchor_token: Prioritise anchor-token detection over
            required-header scan.
        grid_unpivot: Config dict for wide-to-long (pivot) expansion.  Cannot
            be combined with *source_regions*.
        fold_into_notes: List of fold dicts appending source columns into a
            target notes column.
        constant_columns: ``{output_header: literal_value}`` applied after all
            other transforms.
        skip_rows_missing: Output column names; rows where any of these are
            blank after all transforms are dropped.

    Returns:
        dict: Normalised result with keys:
        ``header_row_index`` (int), ``strategy`` (str), ``rows`` (list of
        lists, header first).  Multi-region results add
        ``header_row_indexes`` (list of ints).

    Raises:
        ValueError: If ``grid_unpivot`` and ``source_regions`` are both set,
            or if header detection fails without a fallback.
    """
    if grid_unpivot and source_regions:
        raise ValueError("grid_unpivot cannot be combined with source_regions in one tab")

    if not source_regions:
        return _normalize_single_region(
            rows,
            required_headers=required_headers,
            aliases=aliases,
            max_scan_rows=max_scan_rows,
            anchor_token=anchor_token,
            header_row_index=header_row_index,
            output_headers=output_headers,
            column_map=column_map,
            default_values=default_values,
            row_transforms=row_transforms,
            stop_on_blank_in=stop_on_blank_in,
            prefer_anchor_token=prefer_anchor_token,
            grid_unpivot=grid_unpivot,
            fold_into_notes=fold_into_notes,
            constant_columns=constant_columns,
            skip_rows_missing=skip_rows_missing,
        )

    region_results = []
    for region in source_regions:
        region_results.append(
            _normalize_single_region(
                rows,
                required_headers=region.get("required_headers", required_headers),
                aliases=region.get("aliases", aliases),
                max_scan_rows=region.get("max_scan_rows", max_scan_rows),
                anchor_token=region.get("anchor_token", anchor_token),
                header_row_index=region.get("header_row_index", header_row_index),
                output_headers=region.get("output_headers", output_headers),
                column_map=region.get("column_map", column_map),
                default_values=region.get("default_values", default_values),
                row_transforms=region.get("row_transforms", row_transforms),
                stop_on_blank_in=region.get("stop_on_blank_in", stop_on_blank_in),
                prefer_anchor_token=region.get("prefer_anchor_token", prefer_anchor_token),
                grid_unpivot=region.get("grid_unpivot"),
                fold_into_notes=region.get("fold_into_notes", fold_into_notes),
                constant_columns=region.get("constant_columns", constant_columns),
                skip_rows_missing=region.get("skip_rows_missing", skip_rows_missing),
            )
        )

    first_rows = region_results[0]["rows"]
    merged_rows = [first_rows[0]]
    for result in region_results:
        rows_without_header = result["rows"][1:]
        merged_rows.extend(rows_without_header)

    return {
        "header_row_index": region_results[0]["header_row_index"],
        "header_row_indexes": [result["header_row_index"] for result in region_results],
        "strategy": "multi_region",
        "rows": merged_rows,
    }


def normalize_csv_file(
    source_path,
    output_path,
    required_headers,
    aliases=None,
    max_scan_rows=200,
    anchor_token=None,
    header_row_index=None,
    output_headers=None,
    column_map=None,
    default_values=None,
    row_transforms=None,
    source_regions=None,
    stop_on_blank_in=None,
    prefer_anchor_token=False,
    grid_unpivot=None,
    append_without_header=False,
    fold_into_notes=None,
    constant_columns=None,
    skip_rows_missing=None,
):
    """Read *source_path*, normalise it, and write the result to *output_path*.

    All normalisation parameters are forwarded to :func:`normalize_rows`; see
    that function for full parameter documentation.

    The ``utf-8-sig`` encoding is used on read to strip the BOM that Excel
    and Google Sheets sometimes prepend to CSV exports.

    When *append_without_header* is ``True`` and *output_path* already exists,
    data rows are appended without repeating the header line — useful for
    merging multi-source CSVs in a pipeline step.

    Args:
        source_path: Path to the raw source CSV file.
        output_path: Destination path for the normalised CSV.  Parent
            directories are created automatically.
        required_headers: Column names that must appear in the detected header.
        aliases: Header alias mapping.
        max_scan_rows: Scan limit for header detection.  Defaults to ``200``.
        anchor_token: Sentinel first-cell value for anchor-based detection.
        header_row_index: Explicit fallback header row index.
        output_headers: Projected output column names.
        column_map: ``{output_header: source_header_or_int}`` remapping.
        default_values: ``{output_header: default}`` for blank cells.
        row_transforms: List of transform dicts applied after projection.
        source_regions: Per-region config list for multi-region sheets.
        stop_on_blank_in: Columns whose blank value halts row scanning.
        prefer_anchor_token: Prioritise anchor-token detection.
        grid_unpivot: Wide-to-long expansion config dict.
        append_without_header: Append to existing file without writing header.
        fold_into_notes: Fold config list for note-column accumulation.
        constant_columns: ``{output_header: literal_value}`` overrides.
        skip_rows_missing: Drop rows missing values in these output columns.

    Returns:
        dict: Normalised result dict (from :func:`normalize_rows`) augmented
        with ``"rows_written"`` (int) — the number of data rows written,
        excluding the header.
    """
    with Path(source_path).open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))

    normalized = normalize_rows(
        rows,
        required_headers=required_headers,
        aliases=aliases,
        max_scan_rows=max_scan_rows,
        anchor_token=anchor_token,
        header_row_index=header_row_index,
        output_headers=output_headers,
        column_map=column_map,
        default_values=default_values,
        row_transforms=row_transforms,
        source_regions=source_regions,
        stop_on_blank_in=stop_on_blank_in,
        prefer_anchor_token=prefer_anchor_token,
        grid_unpivot=grid_unpivot,
        fold_into_notes=fold_into_notes,
        constant_columns=constant_columns,
        skip_rows_missing=skip_rows_missing,
    )

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    data_rows = normalized["rows"][1:]
    if append_without_header and output_path.exists():
        with output_path.open("a", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerows(data_rows)
        normalized["rows_written"] = len(data_rows)
    else:
        with output_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerows(normalized["rows"])
        normalized["rows_written"] = max(len(normalized["rows"]) - 1, 0)
    return normalized
