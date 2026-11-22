"""Step 4: build a rain and/or holiday day for IS-03. These days are SIMULATED: no traffic counts exist for them.

    .venv/bin/python scenario.py --rain heavy --hours 17-19   # heavy rain from 17:00 to 19:00
    .venv/bin/python scenario.py --rain-day 2023-09-21        # the rain of a real day, hour by hour (Open-Meteo archive)
    .venv/bin/python scenario.py --holiday festival           # Water Festival crowds
    .venv/bin/python scenario.py --live                       # today's real weather and holiday status
The options combine, e.g. --rain heavy --hours 17-19 --holiday exodus.

It writes routes/NAME.rou.xml (traffic for SUMO) and routes/NAME.json (the rain and holiday, hour by hour),
and prints the commands that run the scenario.

How a scenario changes the normal JICA day:
- Rain changes how people drive, not how many travel (no study we found measures that for motorbike cities).
  Vehicles that set off in a rainy hour drive slower, accelerate more gently and leave longer gaps. The settings
  below are calibrated in SUMO so that each approach moves about 7% (light), 14% (moderate) or 19% (heavy rain)
  fewer vehicles per hour of green, the capacity losses measured at signalised intersections in rain (README).
- Holidays change how many travel and in which direction. These are assumptions, because no counts exist:
    exodus    the day before Khmer New Year or Pchum Ben: traffic leaving the centre x1.5, 12:00-21:00
    festival  Water Festival days: traffic heading to the centre and riverside x1.4, 15:00-22:00
    quiet     other holidays: all traffic x0.7
"""
import argparse
import datetime as dt
import json
import re
import xml.etree.ElementTree as ET

import holidays_kh
import weather
from make_demand import HOURS, PROFILE, build_rates, write_routes

RAIN = {  # how drivers change for each rain level; calibrated in SUMO (README step 4)
    "light":    {"speed": 0.95, "tau": 0.12, "accel": 0.90, "minGap": 0.2},
    "moderate": {"speed": 0.90, "tau": 0.30, "accel": 0.80, "minGap": 0.4},
    "heavy":    {"speed": 0.85, "tau": 0.45, "accel": 0.75, "minGap": 0.5},
}
RAIN_MM = {"light": 1.5, "moderate": 6.0, "heavy": 15.0}   # typical mm per hour, for --rain
HOLIDAY = {  # assumptions: (hours affected, factor for traffic leaving the centre, factor for traffic heading to it)
    "exodus":   (range(12, 21), 1.5, 1.0),
    "festival": (range(15, 22), 1.0, 1.4),
    "quiet":    (HOURS, 0.7, 0.7),
}
TO_CENTRE = {a for a, col in PROFILE.items() if col == "pct_to_city"}   # Monivong S and CdG W head into the centre


def wet_vtypes(levels):
    """A wet copy of every vehicle type in net/vtypes.add.xml for each rain level, e.g. "moto_rain_heavy"."""
    out = []
    for vt in ET.parse("net/vtypes.add.xml").getroot().iter("vType"):
        for level in levels:
            c, a = RAIN[level], dict(vt.attrib)
            a.pop("probability", None)
            a["id"] = f"{a['id']}_rain_{level}"
            mean, dev, lo, hi = map(float, re.fullmatch(r"normc\((.+),(.+),(.+),(.+)\)", a["speedFactor"]).groups())
            k = c["speed"]
            a["speedFactor"] = f"normc({mean * k:.2f},{dev:.2f},{lo * k:.2f},{hi * k:.2f})"
            a["tau"] = f"{float(a['tau']) + c['tau']:.2f}"
            a["accel"] = f"{float(a['accel']) * c['accel']:.2f}"
            a["minGap"] = f"{float(a['minGap']) + c['minGap']:.2f}"
            out.append("    <vType " + " ".join(f'{key}="{val}"' for key, val in a.items()) + "/>\n")
    return "".join(out)


def build(name, rain_mm, holiday, source):
    """rain_mm: {hour: mm of rain}; holiday: a HOLIDAY pattern or None. Writes routes/NAME.rou.xml and .json."""
    levels = {h: weather.rain_level(rain_mm.get(h, 0.0)) for h in HOURS}
    wet = {h: level for h, level in levels.items() if level != "dry"}
    rates, _ = build_rates()
    if holiday:
        hours, leaving, heading_in = HOLIDAY[holiday]
        for (h, a), r in rates.items():
            if h in hours:
                f = heading_in if a in TO_CENTRE else leaving
                rates[(h, a)] = {**r, "vph": r["vph"] * f, "pcu_h": r["pcu_h"] * f}
    write_routes(rates, f"routes/{name}.rou.xml", f"SIMULATED scenario {name} ({source})",
                 rain=wet, vtypes=wet_vtypes(sorted(set(wet.values()))))
    info = {"name": name, "simulated": True, "source": source, "holiday": holiday,
            "rain_mm": {f"{h:02d}:00": round(rain_mm.get(h, 0.0), 1) for h in HOURS},
            "rain_level": {f"{h:02d}:00": levels[h] for h in HOURS},
            "vehicles": round(sum(r["vph"] for r in rates.values()))}
    with open(f"routes/{name}.json", "w") as f:
        json.dump(info, f, indent=1)
    return info


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Build a simulated rain and/or holiday day for IS-03")
    ap.add_argument("--rain", choices=list(RAIN), help="rain level for --hours")
    ap.add_argument("--hours", default="17-19", help="when it rains, from-to: 17-19 means 17:00 to 19:00")
    ap.add_argument("--rain-day", metavar="YYYY-MM-DD", help="the rain of a real past day (Open-Meteo archive)")
    ap.add_argument("--holiday", choices=list(HOLIDAY))
    ap.add_argument("--live", action="store_true", help="today's weather (Open-Meteo) and holiday status")
    args = ap.parse_args()

    parts, rain_mm, holiday, source = [], {}, args.holiday, "set by hand"
    if args.live:
        today, now = dt.date.today(), weather.today()
        rain_mm, holiday = now["rain_mm"], holidays_kh.traffic_pattern(today)
        parts.append(f"live_{today}")
        source = f"live: Open-Meteo weather at {now['time']} and the 2026 holiday calendar"
    if args.rain_day:
        rain_mm = weather.rain_on(args.rain_day)
        parts.append(f"rain_{args.rain_day}")
        source = f"rain of {args.rain_day} from the Open-Meteo archive"
    elif args.rain:
        start, end = map(int, args.hours.split("-"))
        rain_mm = {h: RAIN_MM[args.rain] for h in range(start, end)}
        parts.append(f"rain_{args.rain}_{start:02d}-{end:02d}")
    if args.holiday and not args.live:
        parts.append(f"holiday_{args.holiday}")
    if not parts:
        ap.error("choose --rain, --rain-day, --holiday or --live")
    name = "+".join(parts)

    info = build(name, rain_mm, holiday, source)
    wet = [h for h in info["rain_level"] if info["rain_level"][h] != "dry"]
    print(f"SIMULATED scenario: {name}")
    print("Rain:    " + (", ".join(f"{h} {info['rain_level'][h]} ({info['rain_mm'][h]} mm)" for h in wet) or "none"))
    if holiday:
        hours, leaving, heading_in = HOLIDAY[holiday]
        print(f"Holiday: {holiday}, {hours[0]:02d}:00-{hours[-1] + 1:02d}:00, traffic leaving the centre x{leaving}, "
              f"heading to the centre x{heading_in} (assumed)")
    else:
        print("Holiday: none")
    print(f"Wrote routes/{name}.rou.xml ({info['vehicles']:,} vehicles; the normal day has 97,463) and routes/{name}.json")
    begin = max(21600, min([int(h[:2]) for h in wet] + ([HOLIDAY[holiday][0][0]] if holiday else []) or [17]) * 3600 - 900)
    print(f"Compare fixed-time and SmartFlow on this day (about 5 minutes):\n  .venv/bin/python compare.py '{name}'")
    print(f"Watch SmartFlow on it from {begin // 3600:02d}:{begin % 3600 // 60:02d}:\n"
          f"  .venv/bin/python adaptive.py --gui --scenario '{name}' -b {begin}")
