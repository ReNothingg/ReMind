import re
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from itertools import product
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from backend.errors import ApiError

UTC = timezone.utc
DAY = timedelta(days=1)
MAX_SEARCH_DAYS = 366 * 8
TIMING_KEYS = {
    "after": {"seconds"},
    "at": {"at"},
    "every": {"seconds"},
    "daily": {"time", "zone"},
    "weekly": {"time", "zone", "weekdays"},
    "monthly": {"time", "zone", "day"},
    "cron": {"expression", "zone"},
}
CRON_ITEM = re.compile(r"(\*|[0-9]{1,2}(?:-[0-9]{1,2})?)(?:/([0-9]{1,2}))?")


def utc_now():
    return datetime.now(UTC).replace(tzinfo=None)


def iso_utc(value):
    return value.replace(tzinfo=UTC).isoformat(timespec="seconds") if value is not None else None


def invalid_rule():
    return ApiError("invalid_automation_rule", status=400, code="invalid_automation_rule")


def cron_field(expression, low, high):
    values = set()
    for item in expression.split(","):
        match = CRON_ITEM.fullmatch(item)
        if not match:
            raise invalid_rule()
        selection, raw_step = match.groups()
        step = int(raw_step) if raw_step else 1
        if selection == "*":
            start, end = low, high
        elif "-" in selection:
            start, end = map(int, selection.split("-"))
        else:
            if raw_step:
                raise invalid_rule()
            start = end = int(selection)
        if not (low <= start <= end <= high and step > 0):
            raise invalid_rule()
        values.update(range(start, end + 1, step))
    return values


def local_instant(day, clock, zone):
    wall_time = datetime.combine(day, clock)
    candidate = wall_time.replace(tzinfo=zone, fold=0).astimezone(UTC)
    if candidate.astimezone(zone).replace(tzinfo=None) != wall_time:
        return None
    return candidate.replace(tzinfo=None)


@dataclass(frozen=True)
class CalendarRule:
    zone: ZoneInfo
    clocks: tuple
    weekdays: frozenset | None = None
    month_day: int | None = None
    cron_days: tuple | None = None

    def matches(self, day):
        if self.cron_days is None:
            if self.weekdays is not None:
                return day.isoweekday() in self.weekdays
            if self.month_day is not None:
                return day.day == self.month_day or (
                    day.day < self.month_day and (day + DAY).month != day.month
                )
            return True
        month_days, months, week_days, all_dates, all_weekdays = self.cron_days
        if day.month not in months:
            return False
        date_match = day.day in month_days
        weekday_match = day.isoweekday() % 7 in week_days
        return (
            date_match and weekday_match
            if all_dates or all_weekdays
            else date_match or weekday_match
        )

    def occurrence(self, now, *, forward):
        local_date = now.replace(tzinfo=UTC).astimezone(self.zone).date()
        day = local_date if forward else now.date() + DAY
        clocks = self.clocks if forward else self.clocks[::-1]
        step = DAY if forward else -DAY
        for _ in range(MAX_SEARCH_DAYS):
            if self.matches(day):
                for clock in clocks:
                    target = local_instant(day, clock, self.zone)
                    if target is not None and (target > now if forward else target <= now):
                        return target
            day += step
        return None


def calendar_rule(rule):
    try:
        zone = ZoneInfo(rule["zone"])
    except (TypeError, ValueError, ZoneInfoNotFoundError) as error:
        raise invalid_rule() from error
    if rule["kind"] == "cron":
        fields = rule["expression"].split()
        if len(fields) != 5:
            raise invalid_rule()
        minutes, hours, month_days, months, week_days = (
            cron_field(field, low, high)
            for field, (low, high) in zip(
                fields, ((0, 59), (0, 23), (1, 31), (1, 12), (0, 7)), strict=True
            )
        )
        clocks = tuple(time(h, m) for h, m in product(sorted(hours), sorted(minutes)))
        cron_days = (
            month_days,
            months,
            {day % 7 for day in week_days},
            fields[2].startswith("*"),
            fields[4].startswith("*"),
        )
        return CalendarRule(zone, clocks, cron_days=cron_days)
    clock = time.fromisoformat(rule["time"])
    weekdays = frozenset(rule["weekdays"]) if "weekdays" in rule else None
    return CalendarRule(zone, (clock,), weekdays, rule.get("day"))


def normalize_timing(value):
    if not isinstance(value, dict):
        raise invalid_rule()
    kind = value.get("kind")
    if (
        not isinstance(kind, str)
        or kind not in TIMING_KEYS
        or set(value) != {"kind", *TIMING_KEYS[kind]}
    ):
        raise invalid_rule()
    if kind in {"after", "every"}:
        seconds = value["seconds"]
        if type(seconds) is not int or not 60 <= seconds <= 366 * 86400:
            raise invalid_rule()
        return value
    if kind == "at":
        at = value["at"]
        if not isinstance(at, str) or not re.fullmatch(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}(?::[0-9]{2}(?:\.[0-9]{1,6})?)?(?:Z|[+-][0-9]{2}:[0-9]{2})",
            at,
        ):
            raise invalid_rule()
        try:
            instant = datetime.fromisoformat(at).astimezone(UTC)
        except (OverflowError, ValueError) as error:
            raise invalid_rule() from error
        if not 2000 <= instant.year < 9900:
            raise invalid_rule()
        return {"kind": kind, "at": iso_utc(instant)}
    zone = value["zone"]
    if not isinstance(zone, str) or not re.fullmatch(r"[A-Za-z0-9_+/-]{1,80}", zone):
        raise invalid_rule()
    if kind == "cron":
        expression = value["expression"]
        if not isinstance(expression, str) or not 1 <= len(expression) <= 160:
            raise invalid_rule()
        value = {**value, "expression": " ".join(expression.split())}
    else:
        if not isinstance(value["time"], str) or not re.fullmatch(
            r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", value["time"]
        ):
            raise invalid_rule()
        if kind == "weekly":
            days = value["weekdays"]
            if (
                not isinstance(days, list)
                or not 1 <= len(days) <= 7
                or any(type(day) is not int or not 1 <= day <= 7 for day in days)
            ):
                raise invalid_rule()
            value = {**value, "weekdays": sorted(set(days))}
        if kind == "monthly" and (type(value["day"]) is not int or not 1 <= value["day"] <= 31):
            raise invalid_rule()
    calendar_rule(value)
    return value


def first_occurrence(rule, now):
    kind = rule["kind"]
    if kind in {"after", "every"}:
        return now.replace(microsecond=0) + timedelta(seconds=rule["seconds"])
    if kind == "at":
        target = datetime.fromisoformat(rule["at"]).replace(tzinfo=None)
    else:
        target = calendar_rule(rule).occurrence(now, forward=True)
    if target is None or target <= now:
        raise invalid_rule()
    return target


def resolve_occurrence(rule, scheduled, now):
    if scheduled > now:
        raise invalid_rule()
    kind = rule["kind"]
    if kind in {"after", "at"}:
        return scheduled, None
    if kind == "every":
        interval = timedelta(seconds=rule["seconds"])
        occurrence = scheduled + ((now - scheduled) // interval) * interval
        return occurrence, occurrence + interval
    calendar = calendar_rule(rule)
    occurrence = calendar.occurrence(now, forward=False)
    return max(occurrence or scheduled, scheduled), calendar.occurrence(now, forward=True)
