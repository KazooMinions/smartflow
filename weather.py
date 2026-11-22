"""Step 4: weather at IS-03 from Open-Meteo (free, no API key).

    .venv/bin/python weather.py                       # weather now, and rain hour by hour for today
    .venv/bin/python weather.py --history 2022 2025   # download hourly rain for those years and summarise it

Open-Meteo's "now" comes from weather models, and its history (archive API) is the ERA5 reanalysis, a model
reconstruction on a grid of roughly 10-25 km. Neither is a rain gauge at the junction.

Rain intensity per hour, using the classes of the rain-and-signals study in README step 4:
    dry < 0.5 mm    light 0.5-2.5 mm    moderate 2.5-10 mm    heavy 10 mm or more
"""
import argparse
import csv
import json
import os
import urllib.parse
import urllib.request
from collections import defaultdict

LAT, LON = 11.5674, 104.9189            # IS-03, Monivong x Charles de Gaulle
TZ = "Asia/Phnom_Penh"
HISTORY_DIR = "data/openmeteo"          # downloaded data lives in its own folder
WEATHER = {0: "clear", 1: "mostly clear", 2: "partly cloudy", 3: "overcast", 45: "fog", 48: "fog",
           51: "light drizzle", 53: "drizzle", 55: "heavy drizzle", 61: "light rain", 63: "rain", 65: "heavy rain",
           80: "light showers", 81: "showers", 82: "violent showers", 95: "thunderstorm", 96: "thunderstorm with hail",
           99: "thunderstorm with hail"}


def rain_level(mm):
    if mm < 0.5:
        return "dry"
    return "light" if mm < 2.5 else "moderate" if mm < 10 else "heavy"


def get(url, timeout=60, **params):
    query = urllib.parse.urlencode({"latitude": LAT, "longitude": LON, "timezone": TZ, **params})
    with urllib.request.urlopen(f"{url}?{query}", timeout=timeout) as r:
        return json.load(r)


def today(timeout=60):
    """Weather now, plus today's rain hour by hour (earlier hours are model analysis, later hours forecast)."""
    d = get("https://api.open-meteo.com/v1/forecast", timeout, current="temperature_2m,precipitation,weather_code",
            hourly="precipitation,precipitation_probability", forecast_days=1)
    h = d["hourly"]
    return {"time": d["current"]["time"], "temperature_c": d["current"]["temperature_2m"],
            "precipitation_mm": d["current"]["precipitation"], "weather_code": d["current"]["weather_code"],
            "rain_mm": {int(t[11:13]): mm for t, mm in zip(h["time"], h["precipitation"])},
            "rain_chance": {int(t[11:13]): p for t, p in zip(h["time"], h["precipitation_probability"])}}


def rain_on(date):
    """Rain hour by hour on a past date (YYYY-MM-DD), from the Open-Meteo archive."""
    d = get("https://archive-api.open-meteo.com/v1/archive", start_date=date, end_date=date, hourly="precipitation")
    return {int(t[11:13]): mm or 0.0 for t, mm in zip(d["hourly"]["time"], d["hourly"]["precipitation"])}


def download_history(first_year, last_year):
    d = get("https://archive-api.open-meteo.com/v1/archive", start_date=f"{first_year}-01-01",
            end_date=f"{last_year}-12-31", hourly="precipitation")
    os.makedirs(HISTORY_DIR, exist_ok=True)
    path = f"{HISTORY_DIR}/rain_hourly_{first_year}-{last_year}.csv"
    with open(path, "w", newline="") as f:
        f.write(f"# Open-Meteo archive (ERA5), hourly precipitation in mm at {LAT}, {LON}, local time ({TZ})\n")
        w = csv.writer(f)
        w.writerow(["time", "precipitation_mm"])
        for t, mm in zip(d["hourly"]["time"], d["hourly"]["precipitation"]):
            w.writerow([t, mm if mm is not None else ""])
    return path


def summarise(path):
    rows = [r for r in csv.DictReader(l for l in open(path) if not l.startswith("#")) if r["precipitation_mm"]]
    by_month, by_hour, days = defaultdict(list), defaultdict(list), defaultdict(dict)
    for r in rows:
        mm, month, hour = float(r["precipitation_mm"]), int(r["time"][5:7]), int(r["time"][11:13])
        by_month[month].append(mm >= 0.5)
        if 5 <= month <= 10:
            by_hour[hour].append(mm >= 0.5)
        if 6 <= hour < 22:
            days[r["time"][:10]][hour] = mm
    pct = lambda xs: 100 * sum(xs) / len(xs)
    print(f"{len(rows):,} hours from {path}")
    print("Share of hours with rain (0.5 mm or more), by month:")
    print("  " + "  ".join(f"{m:>3}" for m in "JFMAMJJASOND"))
    print("  " + "  ".join(f"{pct(by_month[m]):2.0f}%" for m in range(1, 13)))
    print("Rainy season (May-October), share of hours with rain by hour of day:")
    for start in (6, 14):
        print("  " + "  ".join(f"{h:02d}:00 {pct(by_hour[h]):2.0f}%" for h in range(start, start + 8)))
    print("Wettest days between 06:00 and 22:00 (use one with: scenario.py --rain-day DATE):")
    for day, hours in sorted(days.items(), key=lambda kv: -sum(kv[1].values()))[:8]:
        wet = [h for h, mm in sorted(hours.items()) if mm >= 0.5]
        print(f"  {day}  {sum(hours.values()):5.1f} mm, rain {wet[0]:02d}:00-{wet[-1] + 1:02d}:00, "
              f"wettest hour {max(hours, key=hours.get):02d}:00 ({max(hours.values()):.1f} mm)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Weather at IS-03 from Open-Meteo")
    ap.add_argument("--history", nargs=2, type=int, metavar=("FIRST_YEAR", "LAST_YEAR"))
    args = ap.parse_args()
    if args.history:
        summarise(download_history(*args.history))
    else:
        w = today()
        print(f"IS-03 at {w['time'].replace('T', ' ')}: {w['temperature_c']:.1f} °C, "
              f"{WEATHER.get(w['weather_code'], 'weather code %d' % w['weather_code'])}, "
              f"rain {w['precipitation_mm']:.1f} mm in the last 15 min ({rain_level(4 * w['precipitation_mm'])})")
        print("Rain today, mm per hour (chance):")
        for start in (6, 14):
            print("  " + "  ".join(f"{h:02d}:00 {w['rain_mm'][h]:.1f} ({w['rain_chance'][h]}%)"
                                   for h in range(start, start + 8)))
