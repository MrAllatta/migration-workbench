from datetime import datetime
from decimal import Decimal, InvalidOperation


def to_int(value, default=0):
    if not value:
        return default
    try:
        return int(float(str(value).strip()))
    except (ValueError, TypeError):
        return default


def to_int_or_none(value):
    if not value or str(value).strip() in ("", "0", "na", "NA"):
        return None
    try:
        parsed = int(float(str(value).strip()))
        return parsed if parsed > 0 else None
    except (ValueError, TypeError):
        return None


def to_decimal(value, default="0"):
    if not value:
        return Decimal(default)
    try:
        cleaned = str(value).strip().replace("$", "").replace(",", "")
        return Decimal(cleaned) if cleaned else Decimal(default)
    except (InvalidOperation, TypeError):
        return Decimal(default)


def to_decimal_or_none(value):
    if not value or str(value).strip() in ("", "0", "na", "NA"):
        return None
    try:
        cleaned = str(value).strip().replace("$", "").replace(",", "")
        parsed = Decimal(cleaned)
        return parsed if parsed > 0 else None
    except (InvalidOperation, TypeError):
        return None


def parse_iso_date(date_str):
    return datetime.strptime(str(date_str).strip(), "%Y-%m-%d").date()


def split_on(value, delimiter="//"):
    raw = str(value or "")
    if delimiter not in raw:
        return raw.strip(), ""
    left, right = raw.split(delimiter, 1)
    return left.strip(), right.strip()
