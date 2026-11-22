"""Step 5: the simulated days that train and test the forecast, and the runs on them.

    .venv/bin/python days.py             # build the 20 days and simulate them (about 75 minutes, 8 at a time)
    .venv/bin/python days.py --predict   # after forecast.py: SmartFlow with the forecast on the 5 test days

Needs the rain history first: .venv/bin/python weather.py --history 2022 2025
Training days get real rain from 2022-2024 and test days real rain from 2025, so the forecast is tested on rain
it has never seen. Every training day has its own random seed, and test days use seed 42, like steps 3 and 4.
The holiday patterns are the assumed ones from scenario.py. Runs that already have results are skipped.
"""
import argparse
import csv
import os
import random
import subprocess
import sys
import time
from collections import defaultdict, namedtuple

import scenario
import summarize

HISTORY = "data/openmeteo/rain_hourly_2022-2025.csv"
Day = namedtuple("Day", "name rain holiday seed test")
RAIN_NOTE = "In rain, drivers go slower and leave longer gaps, so each green moves up to 19% fewer vehicles."
TEST_DAYS = {  # the test days with a name and a line about each, for the website (live.py). All are simulated.
    "test1_normal": ("Normal weekday", "Traffic from JICA's 2022 weekday counts, no rain."),
    "test2_rain_2025-08-10": ("Rain of 10 Aug 2025", "Normal traffic with that day's real rain, hour by hour "
                              "(Open-Meteo archive). " + RAIN_NOTE),
    "test3_rain_heavy_17-19": ("Heavy rain 17:00-19:00", "A what-if: normal traffic with 15 mm of rain an hour "
                               "from 17:00 to 19:00. " + RAIN_NOTE),
    "test4_festival": ("Water Festival", "Assumed pattern: traffic towards the centre and the riverside x1.4 "
                       "from 15:00."),
    "test5_exodus": ("Holiday exodus", "Assumed pattern for the day before Khmer New Year or Pchum Ben: traffic "
                     "leaving the centre x1.5 from 12:00 to 21:00."),
}


def rainy_days():
    """Rainy-season days (May-October) with at least 5 mm of rain between 06:00 and 22:00: {date: {hour: mm}}."""
    found = defaultdict(dict)
    with open(HISTORY) as f:
        for r in csv.DictReader(l for l in f if not l.startswith("#")):
            hour = int(r["time"][11:13])
            if r["precipitation_mm"] and 5 <= int(r["time"][5:7]) <= 10 and 6 <= hour < 22:
                found[r["time"][:10]][hour] = float(r["precipitation_mm"])
    return {d: hours for d, hours in found.items() if sum(hours.values()) >= 5}


def plan():
    wet = rainy_days()
    pick = random.Random(5)                  # fixed, so the same days come out every time
    rain = pick.sample(sorted(d for d in wet if d < "2025"), 9)
    test_rain = pick.choice(sorted(d for d in wet if d >= "2025"))
    days = [Day(f"train{i + 1:02d}_normal", {}, None, i + 1, False) for i in range(3)]
    days += [Day(f"train{i + 4:02d}_rain_{d}", wet[d], None, i + 4, False) for i, d in enumerate(rain[:6])]
    for i, (pattern, d) in enumerate([("exodus", None), ("exodus", rain[6]), ("festival", None),
                                      ("festival", rain[7]), ("quiet", None), ("quiet", rain[8])]):
        days.append(Day(f"train{i + 10:02d}_{pattern}" + (f"+rain_{d}" if d else ""), wet[d] if d else {},
                        pattern, i + 10, False))
    days += [Day("test1_normal", {}, None, 42, True),
             Day(f"test2_rain_{test_rain}", wet[test_rain], None, 42, True),
             Day("test3_rain_heavy_17-19", {17: 15.0, 18: 15.0}, None, 42, True),
             Day("test4_festival", {}, "festival", 42, True),
             Day("test5_exodus", {}, "exodus", 42, True)]
    return days


def run_all(jobs, at_once=8):
    """jobs: [(label, command, result file)]. Runs them 8 at a time and reports each as it finishes."""
    jobs = [j for j in jobs if not os.path.exists(j[2])]
    running, started, done = [], time.time(), 0
    while jobs or running:
        while jobs and len(running) < at_once:
            label, cmd, _ = jobs.pop(0)
            running.append((label, subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)))
        time.sleep(2)
        for label, p in [r for r in running if r[1].poll() is not None]:
            running.remove((label, p))
            done += 1
            status = "done" if p.returncode == 0 else f"FAILED (exit {p.returncode})"
            print(f"  {done:2d} {status:6} {label}  ({(time.time() - started) / 60:.0f} min so far)", flush=True)


def table(days):
    print("\nTest days, average delay per vehicle (simulated):")
    print(f"{'day':32} {'fixed-time':>11} {'SmartFlow':>10} {'+ forecast':>11}")
    for d in days:
        cells = []
        for kind in ("fixed", "adaptive", "predict"):
            path = f"out/days/{d.name}_{kind}_tripinfo.xml"
            cells.append(f"{summarize.mean(summarize.every(summarize.load(path))):.1f} s" if os.path.exists(path) else "-")
        print(f"{d.name:32} {cells[0]:>11} {cells[1]:>10} {cells[2]:>11}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Simulate the training and test days for the forecast")
    ap.add_argument("--predict", action="store_true", help="run SmartFlow with the forecast on the test days")
    args = ap.parse_args()
    days = plan()
    os.makedirs("routes/days", exist_ok=True)
    os.makedirs("out/days", exist_ok=True)
    venv_bin = os.path.dirname(sys.executable)
    jobs = []
    for d in days:
        if not args.predict:
            if not os.path.exists(f"routes/days/{d.name}.json"):
                scenario.build(f"days/{d.name}", d.rain, d.holiday, "step 5 " + ("test" if d.test else "training") + " day")
            jobs.append((f"SmartFlow  {d.name}", [sys.executable, "adaptive.py", "--scenario", f"days/{d.name}",
                         "--seed", str(d.seed)], f"out/days/{d.name}_adaptive_tripinfo.xml"))
        if d.test and not args.predict:
            jobs.append((f"fixed-time {d.name}", [os.path.join(venv_bin, "sumo"), "-c", "fixed.sumocfg",
                         "--route-files", f"routes/days/{d.name}.rou.xml", "--seed", str(d.seed),
                         "--tripinfo-output", f"out/days/{d.name}_fixed_tripinfo.xml",
                         "--statistic-output", f"out/days/{d.name}_fixed_stats.xml"], f"out/days/{d.name}_fixed_tripinfo.xml"))
        if d.test and args.predict:
            jobs.append((f"SmartFlow + forecast {d.name}", [sys.executable, "adaptive.py", "--scenario", f"days/{d.name}",
                         "--seed", str(d.seed), "--predict"], f"out/days/{d.name}_predict_tripinfo.xml"))
    print(f"{len(days)} days ({sum(not d.test for d in days)} training, {sum(d.test for d in days)} test); "
          f"{len(jobs)} simulations to run")
    run_all(jobs)
    table([d for d in days if d.test])
