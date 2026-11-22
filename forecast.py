"""Step 5: forecast how many vehicles will arrive on each approach in the next 15 minutes, with a Random Forest.

    .venv/bin/python forecast.py      # learn from the training days, test on the test days, save the model

Run days.py first: it simulates the days this learns from. Every 5 minutes and for each approach, the model sees
what SmartFlow could know at a real junction:
    the time of day, which approach, its queue and the queues on all approaches (a camera),
    vehicles that arrived on it in the last 15 minutes (a counter where the road starts),
    rain this hour (Open-Meteo) and the holiday pattern (the 2026 calendar)
and learns how many vehicles will arrive on that approach in the next 15 minutes.
It is saved to models/demand_rf.joblib, which adaptive.py --predict uses.
"""
import csv
import json
import os
from collections import defaultdict

import joblib
import numpy as np
from sklearn.ensemble import RandomForestRegressor

APPROACHES = ("N_in", "E_in", "S_in", "W_in")
NAMES = {"N_in": "Monivong N", "E_in": "CdG East", "S_in": "Monivong S", "W_in": "CdG West"}
PATTERNS = ("exodus", "festival", "quiet")
FEATURES = ["time of day", *(f"approach {a}" for a in APPROACHES), "queue", "queues, all approaches",
            "arrived, last 15 min", "rain this hour", *(f"holiday {p}" for p in PATTERNS)]
MODEL = "models/demand_rf.joblib"


def row(t, approach, queues, arrived_15min, rain_mm, holiday):
    """One row of features, in FEATURES order. t = seconds since midnight."""
    return [t / 60, *(float(approach == a) for a in APPROACHES), queues[approach], sum(queues.values()),
            arrived_15min, rain_mm, *(float(holiday == p) for p in PATTERNS)]


def predict(model, t, queues, arrived_15min, rain_mm, holiday):
    """Expected arrivals on each approach in the next 15 minutes."""
    X = np.array([row(t, a, queues, arrived_15min[a], rain_mm, holiday) for a in APPROACHES])
    return dict(zip(APPROACHES, model.predict(X)))


def load(path=MODEL):
    return joblib.load(path)


def day_rows(name):
    """Features and targets from one simulated day: out/days/NAME_adaptive_ticks.csv and routes/days/NAME.json."""
    with open(f"routes/days/{name}.json") as f:
        info = json.load(f)
    rain = {int(h[:2]): mm for h, mm in info["rain_mm"].items()}
    counts, queues = defaultdict(dict), defaultdict(dict)        # time -> approach -> value
    with open(f"out/days/{name}_adaptive_ticks.csv") as f:
        for r in csv.DictReader(f):
            counts[float(r["time_s"])][r["approach"]] = int(r["arrived_5min"])
            queues[float(r["time_s"])][r["approach"]] = int(r["queue_veh"])
    times = sorted(counts)
    X, y, past = [], [], []
    for k in range(2, len(times) - 3):
        t = times[k]
        if not 22500 <= t <= 78300:          # 06:15 to 21:45, so both 15-minute windows lie inside the counted day
            continue
        for a in APPROACHES:
            before = sum(counts[times[j]][a] for j in (k - 2, k - 1, k))
            X.append(row(t, a, queues[t], before, rain.get(int(t // 3600), 0.0), info["holiday"]))
            y.append(sum(counts[times[j]][a] for j in (k + 1, k + 2, k + 3)))
            past.append(before)
    return np.array(X), np.array(y), np.array(past)


def jica_average(X):
    """Baseline: arrivals expected from JICA's normal-day counts alone (data/arrival_rates.csv)."""
    with open("data/arrival_rates.csv") as f:
        vph = {(int(r["hour"][:2]), r["approach"]): float(r["veh_per_hour"]) for r in csv.DictReader(f)}
    out = []
    for r in X:
        minute, a = r[0] + 7.5, APPROACHES[int(np.argmax(r[1:5]))]       # middle of the next 15 minutes
        out.append(vph.get((int(minute // 60), a), 0.0) / 4)
    return np.array(out)


def main():
    import days                              # the list of training and test days
    train = [d for d in days.plan() if not d.test]
    test = [d for d in days.plan() if d.test]
    parts = [day_rows(d.name) for d in train]
    X, y = np.vstack([p[0] for p in parts]), np.concatenate([p[1] for p in parts])
    model = RandomForestRegressor(n_estimators=150, min_samples_leaf=5, n_jobs=-1, random_state=42).fit(X, y)
    os.makedirs("models", exist_ok=True)
    joblib.dump(model, MODEL, compress=3)
    print(f"Trained a Random Forest on {len(train)} simulated days ({len(y):,} rows of 15-minute arrivals); "
          f"saved {MODEL}")

    print("\nTest days (never seen in training): average error of the 15-minute arrival forecast, vehicles per approach")
    print(f"{'day':32} {'Random Forest':>14} {'last 15 min':>12} {'JICA average':>13}   arrivals")
    errors = defaultdict(list)
    for d in test:
        Xt, yt, past = day_rows(d.name)
        guesses = {"rf": model.predict(Xt), "last": past, "jica": jica_average(Xt)}
        mae = {k: np.mean(np.abs(g - yt)) for k, g in guesses.items()}
        for k, g in guesses.items():
            errors[k].append(np.abs(g - yt))
        print(f"{d.name:32} {mae['rf']:14.1f} {mae['last']:12.1f} {mae['jica']:13.1f}   {yt.mean():6.0f} on average")
    every = {k: np.concatenate(v) for k, v in errors.items()}
    print(f"{'all test days':32} {every['rf'].mean():14.1f} {every['last'].mean():12.1f} {every['jica'].mean():13.1f}")

    weight = defaultdict(float)              # importance, with the one-column-per-value features added up
    for name, w in zip(FEATURES, model.feature_importances_):
        weight[name.split(" ")[0] if name.startswith(("approach", "holiday")) else name] += w
    print("\nWhat the forecast relies on (Random Forest feature importance):")
    for name, w in sorted(weight.items(), key=lambda kv: -kv[1]):
        print(f"  {name:24} {100 * w:5.1f}%")


if __name__ == "__main__":
    main()
