"""Type-coercion helpers for raw tabular cell values.

All functions accept the raw ``str`` (or any ``object``) that comes out of a
CSV or spreadsheet row and return a typed Python value.  They are designed to
be forgiving: blank cells, ``"na"``/``"NA"`` tokens, and currency symbols are
handled silently so callers don't need per-field ``try/except`` blocks.
"""

from datetime import datetime
from decimal import Decimal, InvalidOperation


def to_int(value, default=0):
    """Coerce *value* to an integer, returning *default* on failure.

    Accepts float-formatted strings (e.g. ``"3.0"``).  An empty or falsy
    value immediately returns *default* without raising.

    Args:
        value: Raw cell value to convert.
        default: Fallback returned when conversion fails.  Defaults to ``0``.

    Returns:
        int: Parsed integer, or *default*.
    """
    if not value:
        return default
    try:
        return int(float(str(value).strip()))
    except (ValueError, TypeError):
        return default


def to_int_or_none(value):
    """Coerce *value* to a positive integer, returning ``None`` for blanks/zero.

    Treats ``""``, ``"0"``, ``"na"``, and ``"NA"`` as absent rather than
    zero, which matches the convention used by spreadsheet exports where an
    empty cell and a zero have different meanings.

    Args:
        value: Raw cell value to convert.

    Returns:
        int or None: Positive integer if parseable and > 0, otherwise ``None``.
    """
    if not value or str(value).strip() in ("", "0", "na", "NA"):
        return None
    try:
        parsed = int(float(str(value).strip()))
        return parsed if parsed > 0 else None
    except (ValueError, TypeError):
        return None


def to_decimal(value, default="0"):
    """Coerce *value* to a ``Decimal``, stripping currency symbols first.

    Handles ``"$1,234.56"``-style strings produced by spreadsheet exports.

    Args:
        value: Raw cell value to convert.
        default: String representation of the fallback ``Decimal``.
            Defaults to ``"0"``.

    Returns:
        Decimal: Parsed value, or ``Decimal(default)`` on failure.
    """
    if not value:
        return Decimal(default)
    try:
        cleaned = str(value).strip().replace("$", "").replace(",", "")
        return Decimal(cleaned) if cleaned else Decimal(default)
    except (InvalidOperation, TypeError):
        return Decimal(default)


def to_decimal_or_none(value):
    """Coerce *value* to a positive ``Decimal``, returning ``None`` for blanks/zero.

    Treats ``""``, ``"0"``, ``"na"``, and ``"NA"`` as absent, consistent with
    :func:`to_int_or_none`.

    Args:
        value: Raw cell value to convert.

    Returns:
        Decimal or None: Positive decimal if parseable and > 0, else ``None``.
    """
    if not value or str(value).strip() in ("", "0", "na", "NA"):
        return None
    try:
        cleaned = str(value).strip().replace("$", "").replace(",", "")
        parsed = Decimal(cleaned)
        return parsed if parsed > 0 else None
    except (InvalidOperation, TypeError):
        return None


def parse_iso_date(date_str):
    """Parse an ISO 8601 date string (``YYYY-MM-DD``) to a :class:`datetime.date`.

    Args:
        date_str: String in ``YYYY-MM-DD`` format.

    Returns:
        datetime.date: Parsed date.

    Raises:
        ValueError: If *date_str* does not match ``YYYY-MM-DD``.
    """
    return datetime.strptime(str(date_str).strip(), "%Y-%m-%d").date()


def split_on(value, delimiter="//"):
    """Split *value* on the first occurrence of *delimiter* into a (left, right) pair.

    Returns ``(value.strip(), "")`` when the delimiter is absent, so callers
    can always unpack two values without a branch.

    Args:
        value: Raw cell value to split.  ``None`` is treated as ``""``.
        delimiter: Separator string.  Defaults to ``"//"``.

    Returns:
        tuple[str, str]: ``(left, right)`` pair, both stripped.

    Example::

        >>> split_on("Crop // Variety")
        ('Crop', 'Variety')
        >>> split_on("Crop only")
        ('Crop only', '')
    """
    raw = str(value or "")
    if delimiter not in raw:
        return raw.strip(), ""
    left, right = raw.split(delimiter, 1)
    return left.strip(), right.strip()
