"""Step 5: is the forecast's +0.7 s on the normal test day real, or luck? Run it after days.py --predict.

    .venv/bin/python seeds.py              # seeds 1, 2, 3 and 7: 8 runs, about 10 minutes
    .venv/bin/python seeds.py 11 12 13     # other seeds

SIMULATED, like every test day. A run's seed fixes the random moments at which vehicles arrive, and every test day
uses seed 42. Another seed gives another random version of the same normal day, with the same number of vehicles per
hour. Each seed runs SmartFlow with and without the forecast, and the table puts them next to seed 42's runs from
days.py. Nothing is tuned: the forecast and its limits stay as they are. The files go to out/seeds/, so the test
days' results are not touched. Runs that already have results are skipped.
"""
import csv
import os
import sys

import days
import summarize

DAY = "test1_normal"


def finished(path):
    """SUMO closes the trip file only at the end of a run, so a run that was stopped halfway is run again."""
    if not os.path.exists(path):
        return False
    with open(path, "rb") as f:
        f.seek(max(0, os.path.getsize(path) - 200))
        return b"</tripinfos>" in f.read()


def delay(prefix):
    """Average delay per vehicle in seconds, rounded like the tables in the README."""
    return round(summarize.mean(summarize.every(summarize.load(f"{prefix}_tripinfo.xml"))), 1)


def at_max(prefix):
    """How many greens ran into their maximum, i.e. ended with their queue not yet cleared."""
    with open(f"{prefix}_greens.csv") as f:
        return sum(r["ended_by"] == "max green" for r in csv.DictReader(f))


def main():
    seeds = [int(s) for s in sys.argv[1:]] or [1, 2, 3, 7]
    os.makedirs("out/seeds", exist_ok=True)
    jobs = []
    for seed in seeds:
        for kind, name in (("adaptive", "SmartFlow"), ("predict", "SmartFlow + forecast")):
            prefix = f"out/seeds/{DAY}_seed{seed}_{kind}"
            if os.path.exists(f"{prefix}_tripinfo.xml") and not finished(f"{prefix}_tripinfo.xml"):
                os.remove(f"{prefix}_tripinfo.xml")
            jobs.append((f"seed {seed}, {name}", [sys.executable, "adaptive.py", "--scenario", f"days/{DAY}",
                         "--seed", str(seed), "--out", prefix] + (["--predict"] if kind == "predict" else []),
                         f"{prefix}_tripinfo.xml"))
    print(f"{sum(not os.path.exists(j[2]) for j in jobs)} simulations to run")
    days.run_all(jobs)

    runs = [(42, f"out/days/{DAY}_adaptive", f"out/days/{DAY}_predict")]       # the test day itself, from days.py
    runs += [(s, f"out/seeds/{DAY}_seed{s}_adaptive", f"out/seeds/{DAY}_seed{s}_predict") for s in seeds]
    print("\nThe normal day with other random seeds, average delay per vehicle (simulated):")
    print(f"{'seed':>4} {'SmartFlow':>10} {'+ forecast':>11} {'effect':>8}   greens that ran into their maximum")
    effects = []
    for seed, alone, forecast in runs:
        if not (finished(f"{alone}_tripinfo.xml") and finished(f"{forecast}_tripinfo.xml")):
            print(f"{seed:>4}   no results" + (" (run days.py and days.py --predict first)" if seed == 42 else ""))
            continue
        a, f = delay(alone), delay(forecast)
        effects.append(f - a)
        print(f"{seed:>4} {a:8.1f} s {f:9.1f} s {f - a:+6.1f} s   "
              f"{at_max(alone)} without the forecast, {at_max(forecast)} with it")
    if effects:
        print(f"\nThe forecast's effect on the normal day: from {min(effects):+.1f} to {max(effects):+.1f} s, "
              f"{sum(effects) / len(effects):+.1f} s on average over {len(effects)} seeds")


if __name__ == "__main__":
    main()
