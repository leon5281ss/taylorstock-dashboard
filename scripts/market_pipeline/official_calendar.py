"""Resolve annual market schedules without inferring actual trading sessions."""

import json
import re
from datetime import date

from .sources import HOLIDAYS, SourceError, iso_date


OPEN_MARKERS = ("開始交易", "最後交易", "正常交易", "恢復交易")
CLOSED_MARKERS = ("放假", "休市", "無交易", "補假", "不交易", "僅辦理結算交割")


def _live_schedules(rows):
    if not isinstance(rows, list) or not rows:
        raise ValueError("invalid_calendar")
    by_year, invalid_years = {}, set()
    for row in rows:
        # An unparseable date could belong to any year. Trust no part of the feed.
        if not isinstance(row["Date"], str) or not re.fullmatch(r"[0-9]{7,8}", row["Date"]):
            raise ValueError("invalid_calendar_date")
        day = iso_date(row["Date"])
        year = date.fromisoformat(day).year
        name, description = row.get("Name"), row.get("Description", "")
        if not isinstance(name, str) or not name.strip() or not isinstance(description, str):
            invalid_years.add(year)
            continue
        opened = any(marker in name for marker in OPEN_MARKERS)
        closed = any(marker in name for marker in CLOSED_MARKERS)
        if not opened and not closed:
            # Descriptions of dated holidays include their own closure evidence.
            # An explicitly named opening takes priority over notices for later days
            # in the same description (e.g., the pre-Lunar New Year last session).
            closed = any(marker in description for marker in CLOSED_MARKERS)
            opened = any(marker in description for marker in OPEN_MARKERS)
        dates = by_year.setdefault(year, {})
        if opened == closed or (day in dates and dates[day] != opened):
            invalid_years.add(year)
        dates[day] = opened
    return {year: dates for year, dates in by_year.items() if year not in invalid_years
            and _annual_coverage(year, dates)}


def _annual_coverage(year, dates):
    # Require annual boundaries even when there is no pinned reference.
    return (any(not opened and f"{year}-01-01" <= day <= f"{year}-01-03"
                for day, opened in dates.items())
            and any(not opened and f"{year}-12-24" <= day <= f"{year}-12-31"
                    for day, opened in dates.items()))


def _pinned_schedule(config, year):
    path = config / f"official_twse_holidays_{year}.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    corroborating = record.get("corroboratingSource")
    if (record.get("schemaVersion") != 1 or record.get("year") != year
            or record.get("market") != "TWSE" or record.get("officialSource") != HOLIDAYS
            or not isinstance(corroborating, str)
            or not re.fullmatch(r"https://www[.]tpex[.]org[.]tw/storage/eb_data/[0-9]+/[0-9]+-1[.]pdf", corroborating)):
        raise ValueError("invalid_pinned_calendar")
    dates = {}
    for field, opened in (("closedDates", False), ("openDates", True)):
        values = record[field]
        if not isinstance(values, list):
            raise ValueError("invalid_pinned_calendar")
        for value in values:
            day = date.fromisoformat(value)
            if day.year != year or day.isoformat() != value or value in dates:
                raise ValueError("invalid_pinned_calendar")
            dates[value] = opened
    if not _annual_coverage(year, dates):
        raise ValueError("invalid_pinned_calendar")
    return dates, record["corroboratingSource"]


def official_schedule(client, config, first_year, last_year):
    try:
        live = _live_schedules(client.get(HOLIDAYS))
    except (SourceError, ValueError, TypeError, KeyError):
        live = {}
    dates, sources, missing, disputed = {}, [HOLIDAYS], [], set()
    for year in range(first_year, last_year + 1):
        observed = live.get(year, {})
        try:
            pinned, source = _pinned_schedule(config, year)
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            # An unpinned annual feed needs dated evidence in every quarter,
            # not just two boundary rows.
            quarters = {(date.fromisoformat(day).month - 1) // 3 for day in observed}
            if len(quarters) != 4:
                missing.append(year)
            else:
                dates.update(observed)
            continue

        if not pinned.keys() <= observed.keys():
            # Ignore additions from a partial feed, which may be a stale slice.
            dates.update(pinned)
            sources.append(source)
            continue

        conflicts = {day for day in pinned if pinned[day] != observed[day]}
        if conflicts:
            # A changed open/closed decision needs a dated, verified amendment,
            # not a silent preference between contradictory annual schedules.
            dates.update({day: opened for day, opened in pinned.items() if day not in conflicts})
            sources.append(source)
            disputed.update(conflicts)
        else:
            dates.update(observed)
    return dates, sources, missing, disputed
