"""Average delay per approach and hour, from SUMO trip files.

    .venv/bin/python summarize.py out/fixed_tripinfo.xml                            # one run
    .venv/bin/python summarize.py out/fixed_tripinfo.xml out/adaptive_tripinfo.xml  # compare two runs

Delay per vehicle = time lost against driving at its desired speed (SUMO's timeLoss)
                  + time spent waiting to enter the road when the queue reached back to the start (departDelay).
"""
import os
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict

APPROACHES = {"N_in": "Monivong N", "E_in": "CdG East", "S_in": "Monivong S", "W_in": "CdG West"}


def load(path):
    delays = defaultdict(lambda: defaultdict(list))   # approach -> hour -> [delay]
    for t in ET.parse(path).getroot().iter("tripinfo"):
        a = t.get("departLane").rsplit("_", 1)[0]
        hour = int(float(t.get("depart")) // 3600)
        delays[a][hour].append(float(t.get("timeLoss")) + float(t.get("departDelay")))
    return delays


def mean(xs):
    return sum(xs) / len(xs) if xs else 0


def every(d, hour=None):
    return [x for a in APPROACHES for h in d[a] if hour in (None, h) for x in d[a][h]]


def one(path):
    d = load(path)
    hours = sorted({h for a in d for h in d[a]})
    print(f"Average delay per vehicle in seconds, by hour of arrival ({path})")
    print("hour   " + "".join(f"{name:>12}" for name in APPROACHES.values()) + "   all")
    for h in hours:
        print(f"{h:02d}:00  " + "".join(f"{mean(d[a][h]):12.0f}" for a in APPROACHES) + f"{mean(every(d, h)):6.0f}")
    trips = every(d)
    print(f"Whole run: {len(trips):,} vehicles, average delay {mean(trips):.1f} s")


def compare(path_a, path_b):
    a, b = load(path_a), load(path_b)
    name_a, name_b = (os.path.basename(p).replace("_tripinfo.xml", "") for p in (path_a, path_b))
    day = os.path.commonprefix([name_a, name_b])
    day = day[:day.rfind("_") + 1] if "_" in day else ""        # e.g. "rain_heavy_17-19_" for a scenario day
    name_a, name_b = name_a[len(day):], name_b[len(day):]
    hours = sorted({h for d in (a, b) for x in d.values() for h in x})
    print(f"Average delay per vehicle in seconds, by hour of arrival: {name_a} → {name_b}"
          + (f" ({day[:-1]})" if day else ""))
    print("hour   " + "".join(f"{name:>13}" for name in APPROACHES.values()) + f"{'all':>13}")
    for h in hours:
        cells = [(mean(a[ap][h]), mean(b[ap][h])) for ap in APPROACHES] + [(mean(every(a, h)), mean(every(b, h)))]
        print(f"{h:02d}:00  " + "".join(f"{x:6.0f} →{y:5.0f}" for x, y in cells))
    ta, tb = every(a), every(b)
    saved = (mean(ta) - mean(tb)) * len(tb) / 3600
    print(f"Whole day: {name_a} {mean(ta):.1f} s → {name_b} {mean(tb):.1f} s average delay per vehicle "
          f"({100 * (mean(tb) / mean(ta) - 1):+.0f}%), {len(tb):,} vehicles, {saved:,.0f} vehicle-hours of waiting saved")


if __name__ == "__main__":
    paths = sys.argv[1:] or ["out/fixed_tripinfo.xml"]
    one(paths[0]) if len(paths) == 1 else compare(paths[0], paths[1])
