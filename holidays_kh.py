"""Step 4: Cambodia's 2026 public holidays (data/cambodia_holidays_2026.csv) and what they do to traffic.

    .venv/bin/python holidays_kh.py              # today: holiday or not, and the next holidays
    .venv/bin/python holidays_kh.py 2026-10-09   # any other date

Each date gets a holiday traffic pattern (used by scenario.py; the patterns themselves are assumptions):
    exodus    the day before Khmer New Year or Pchum Ben: people leave the city for their home provinces
    festival  Water Festival days: crowds travel to the riverside in the evening
    quiet     the other holidays, including Khmer New Year and Pchum Ben themselves: lighter traffic
"""
import csv
import datetime as dt
import sys

CALENDAR = "data/cambodia_holidays_2026.csv"


def load():
    with open(CALENDAR) as f:
        rows = csv.DictReader(l for l in f if not l.startswith("#"))
        return {dt.date.fromisoformat(r["date"]): (r["name"], r["kind"]) for r in rows}


def traffic_pattern(day, holidays=None):
    """The holiday traffic pattern for a date, or None for a normal day."""
    holidays = holidays or load()
    today, tomorrow = holidays.get(day), holidays.get(day + dt.timedelta(days=1))
    if today:
        return "festival" if today[1] == "water_festival" else "quiet"
    if tomorrow and tomorrow[1] in ("new_year", "pchum_ben"):
        return "exodus"
    return None


if __name__ == "__main__":
    day = dt.date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else dt.date.today()
    holidays = load()
    if day.year != 2026:
        print(f"Note: the calendar only has 2026; {day} is outside it.")
    name = holidays.get(day, (None,))[0]
    pattern = traffic_pattern(day, holidays)
    print(f"{day} ({day:%A}): {name or 'not a public holiday'}. Traffic pattern: {pattern or 'normal'}")
    print("Next holidays:")
    for d in [d for d in sorted(holidays) if d > day][:5]:
        print(f"  {d} ({d:%a})  {holidays[d][0]}")
