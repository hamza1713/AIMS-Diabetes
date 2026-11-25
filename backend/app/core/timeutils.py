"""
Time Helpers
============
The database stores naive UTC datetimes (``datetime.utcnow`` convention). The mobile
client works in local time, so date-scoped endpoints accept ``tz_offset`` — the
client's UTC offset in minutes (e.g. +300 for UTC+05:00) — to map a local calendar
day onto a UTC range. Responses emit timezone-aware UTC datetimes (ISO-8601 with
``Z``/``+00:00``) so clients can convert to local time unambiguously.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Optional, Tuple

from fastapi import HTTPException


def utcnow() -> datetime:
    """Naive UTC now (matches the existing DB convention)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_naive_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Normalises an incoming datetime to naive UTC. Naive input is assumed to be UTC already."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def as_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Marks a naive UTC datetime as UTC-aware for serialization."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def local_today(tz_offset: int = 0) -> date:
    return (utcnow() + timedelta(minutes=tz_offset)).date()


def to_local_date(dt: datetime, tz_offset: int = 0) -> date:
    return (dt + timedelta(minutes=tz_offset)).date()


def parse_date(value: Optional[str], field: str = "date") -> Optional[date]:
    if value is None or value == "":
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"'{field}' must be YYYY-MM-DD.")


def parse_month(value: Optional[str], tz_offset: int = 0) -> date:
    """'YYYY-MM' -> first day of that month (defaults to the current local month)."""
    if not value:
        today = local_today(tz_offset)
        return today.replace(day=1)
    try:
        y, m = value.split("-")
        return date(int(y), int(m), 1)
    except (ValueError, TypeError):
        raise HTTPException(status_code=422, detail="'month' must be YYYY-MM.")


def next_month(first: date) -> date:
    return date(first.year + (first.month // 12), first.month % 12 + 1, 1)


def day_bounds_utc(day: date, tz_offset: int = 0) -> Tuple[datetime, datetime]:
    """UTC [start, end) of a local calendar day."""
    start_local = datetime.combine(day, time.min)
    start = start_local - timedelta(minutes=tz_offset)
    return start, start + timedelta(days=1)


def range_bounds_utc(first_day: date, last_day_exclusive: date, tz_offset: int = 0) -> Tuple[datetime, datetime]:
    start, _ = day_bounds_utc(first_day, tz_offset)
    end, _ = day_bounds_utc(last_day_exclusive, tz_offset)
    return start, end


def week_start(day: date) -> date:
    """Monday of the week containing ``day``."""
    return day - timedelta(days=day.weekday())


def resolve_window(
    date_str: Optional[str], days: Optional[int], tz_offset: int = 0
) -> Optional[Tuple[datetime, datetime]]:
    """
    Shared ``?date=`` / ``?days=`` filter:
      date=YYYY-MM-DD -> that local day
      days=N          -> the last N local days including today
      neither         -> None (no filter)
    """
    d = parse_date(date_str)
    if d is not None:
        return day_bounds_utc(d, tz_offset)
    if days is not None:
        if days < 1:
            raise HTTPException(status_code=422, detail="'days' must be >= 1.")
        today = local_today(tz_offset)
        return range_bounds_utc(today - timedelta(days=days - 1), today + timedelta(days=1), tz_offset)
    return None
