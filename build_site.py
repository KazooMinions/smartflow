"""Build the GitHub Pages copy of the website in docs/: the same two pages, working without a server.

    .venv/bin/python build_site.py            # copy the pages and data; record any day not recorded yet
    .venv/bin/python build_site.py --record   # record every day again (about 20 minutes, the days run side by side)

GitHub Pages only serves files, so it can't run SUMO. Instead:
  - the live junction plays back recordings of the same two simulations as live.py (fixed-time, and SmartFlow
    with its forecast), made here: one picture every 2 simulated seconds, kept in docs/replays/;
  - the statistics are the same numbers that live.py serves at /api/stats, written to docs/data/;
  - the live inputs are fetched by the visitor's browser from Open-Meteo, next to the 2026 holiday calendar.
web/pages.js plays the recordings and answers the pages' other requests. After changing web/ or the results,
run this again and commit docs/.
"""
import argparse
import array
import gzip
import json
import os
import shutil
import time
from concurrent.futures import ProcessPoolExecutor

import adaptive
import holidays_kh
import live
import weather
from make_demand import HOURS

DOCS = "docs"
SAMPLE = 2.0                # simulated seconds between two recorded pictures; the browser glides in between
LENGTH = 90 * 60            # each day is recorded for 90 minutes from its start time on the live page,
LONGER = {"test3_rain_heavy_17-19": 150 * 60}   # and the heavy-rain day for 2.5 hours: the jam and its end
RUN = 10000                 # in a track, RUN + n means "stood still for n pictures"
ORDER = live.APPROACHES     # the order of the roads in the recordings


def seconds(text):
    return int(text[:2]) * 3600 + int(text[3:5]) * 60


def hhmm(t):
    return adaptive.clock(t)[:5]


class Track:
    """One vehicle's path through the picture: where it was first seen, then how far it moved in each picture,
    in tenths of a metre and whole degrees. Most vehicles stand still for a while, which costs one number."""
    __slots__ = ("id", "kind", "first", "n", "x", "y", "a", "still", "moves")

    def __init__(self, vid, kind, first, x, y, a):
        self.id, self.kind, self.first, self.n = vid, kind, first, 1
        self.x, self.y, self.a, self.still = x, y, a, 0
        self.moves = array.array("i", (x, y, a))

    def add(self, x, y, a):
        dx, dy, da = x - self.x, y - self.y, (a - self.a + 540) % 360 - 180
        if dx or dy or da:
            if self.still:
                self.moves.append(RUN + self.still)
                self.still = 0
            self.moves.extend((dx, dy, da))
            self.x, self.y, self.a = x, y, a
        else:
            self.still += 1
        self.n += 1

    def row(self):
        if self.still:
            self.moves.append(RUN + self.still)
            self.still = 0
        return [self.id, self.kind, self.first, self.n, *self.moves]


class Side:
    """Everything the live page shows for one junction, picture by picture. Values that change only now and
    then (the lights, the current green, the limits, the forecast, the log) are kept as changes."""

    def __init__(self):
        self.open, self.tracks = {}, []
        self.queues, self.done, self.lost = array.array("i"), array.array("i"), array.array("i")
        self.changes = {"signal": [], "green": [], "limits": [], "expected": [], "log": []}
        self.last, self.log_head = {}, None

    def change(self, name, f, value):
        if self.last.get(name) != value:
            self.last[name] = value
            self.changes[name].append([f, *value])

    def add(self, f, junction, s):
        v = s["veh"]
        for k in range(0, len(v), 5):
            vid, x, y, a, kind = v[k], round(v[k + 1] * 10), round(v[k + 2] * 10), v[k + 3], v[k + 4]
            assert abs(x) < 32000 and abs(y) < 32000, "positions must fit the browser's 16-bit arrays"
            track = self.open.get(vid)
            if track is not None and track.first + track.n == f:      # in the previous picture too
                track.add(x, y, a)
            else:
                track = self.open[vid] = Track(vid, kind, f, x, y, a)
                self.tracks.append(track)
        for vid in [vid for vid, t in self.open.items() if t.first + t.n <= f]:   # gone from the picture
            del self.open[vid]
        self.queues.extend(s["queues"][a] for a in ORDER)
        self.done.append(junction.done)
        self.lost.append(round(junction.lost))
        self.change("signal", f, (s["signal"],))
        g = s["green"]
        self.change("green", f, (ORDER.index(g["approach"]), round(junction.green_start, 1), g["max"]) if g
                    else (-1, 0, 0))
        self.change("limits", f, tuple(s["limits"][a] for a in ORDER))
        self.change("expected", f, tuple(s["expected"][a] for a in ORDER) if s["expected"] else ())
        new = []
        for entry in map(tuple, s["log"]):                  # newest first: keep the greens not seen yet
            if entry == self.log_head:
                break
            new.append(entry)
        if new:
            self.log_head = new[0]
            self.changes["log"] += [[f, *entry] for entry in reversed(new)]

    def pack(self):
        return {"tracks": [t.row() for t in self.tracks], "queues": self.queues.tolist(),
                "done": self.done.tolist(), "lost": self.lost.tolist(), **self.changes}


def record(day, start=None, length=None):
    """Run the live page's two simulations for this day and pack every picture of the recording."""
    info = next(d for d in live.day_list() if d["id"] == day)
    start = seconds(info["start"]) if start is None else start
    end = min(live.DAY_END, start + (length or LONGER.get(day, LENGTH)))
    session = live.Session(day, start, use_forecast=True)
    sides = [Side() for _ in session.sides]
    try:
        frame, f = session.frame(), 0
        while True:
            for side, junction, s in zip(sides, session.sides, frame["sides"]):
                side.add(f, junction, s)
            if session.t >= end:
                break
            frame = session.advance(round(SAMPLE / live.STEP))
            f += 1
    finally:
        session.close()
    return {"day": day, "start": start, "step": SAMPLE, "frames": f + 1, "rain": session.rain,
            "sides": [side.pack() for side in sides]}


def replay_path(day):
    return f"{DOCS}/replays/{day}.json.gz"


def record_to_file(day):
    began = time.time()
    rec = record(day)
    os.makedirs(os.path.dirname(replay_path(day)), exist_ok=True)
    text = json.dumps(rec, separators=(",", ":")).encode()
    with open(replay_path(day), "wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as f:
        f.write(text)                                   # mtime=0: the same recording gives the same file
    return day, {"start": rec["start"], "end": rec["start"] + (rec["frames"] - 1) * SAMPLE, "frames": rec["frames"],
                 "vehicles": [len(s["tracks"]) for s in rec["sides"]], "mb": round(os.path.getsize(replay_path(day)) / 1e6, 1),
                 "minutes": round((time.time() - began) / 60, 1)}


def write_json(path, value):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(value, f, separators=(",", ":"), ensure_ascii=False)


def page(src, dst):
    """A page from web/, with pages.js loaded first so that it knows there is no server."""
    with open(src) as f:
        html = f.read()
    assert html.count("</head>") == 1, f"{src}: expected one </head>"
    with open(dst, "w") as f:
        f.write(html.replace("</head>", '<script src="static/pages.js"></script>\n</head>'))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--record", action="store_true", help="record every day again")
    args = ap.parse_args()
    days = live.day_list()
    index_path = f"{DOCS}/replays/index.json"
    index = {}
    if os.path.exists(index_path) and not args.record:
        with open(index_path) as f:
            index = json.load(f)
    todo = [d["id"] for d in days if args.record or d["id"] not in index or not os.path.exists(replay_path(d["id"]))]
    if todo:
        print(f"Recording {len(todo)} day(s) side by side: {', '.join(todo)}")
        with ProcessPoolExecutor(max_workers=min(len(todo), os.cpu_count() or 1)) as pool:
            for day, meta in pool.map(record_to_file, todo):
                index[day] = meta
                print(f"  {day}: {hhmm(meta['start'])}-{hhmm(meta['end'])}, {meta['frames']} pictures, "
                      f"{meta['mb']} MB, {meta['minutes']} min")
        write_json(index_path, index)

    for d in days:                                      # the live page offers only the recorded times
        meta = index[d["id"]]
        d["start"], d["until"] = hhmm(meta["start"]), hhmm(meta["end"])
        d["times"] = [hhmm(t) for t in range(int(meta["start"]), int(meta["end"]) - 899, 900)]
    write_json(f"{DOCS}/data/days.json", days)
    write_json(f"{DOCS}/data/network.json", live.NET)
    for d in days:
        write_json(f"{DOCS}/data/stats/{d['id']}.json", live.day_stats(d["id"]))
    calendar = holidays_kh.load()
    write_json(f"{DOCS}/data/inputs.json", {
        "lat": weather.LAT, "lon": weather.LON, "tz": weather.TZ, "sky": weather.WEATHER,
        "hours": [min(HOURS), max(HOURS) + 1],
        "calendar": [{"date": d.isoformat(), "name": name, "kind": kind} for d, (name, kind) in sorted(calendar.items())]})

    os.makedirs(f"{DOCS}/static", exist_ok=True)
    page("web/live.html", f"{DOCS}/index.html")
    page("web/stats.html", f"{DOCS}/stats.html")
    for name in ("site.css", "pages.js"):
        shutil.copyfile(f"web/{name}", f"{DOCS}/static/{name}")
    open(f"{DOCS}/.nojekyll", "w").close()              # serve the files as they are
    size = sum(os.path.getsize(os.path.join(r, n)) for r, _, names in os.walk(DOCS) for n in names)
    print(f"Wrote {DOCS}/: {size / 1e6:.1f} MB. Commit it, and GitHub Pages serves it from main /docs.")


if __name__ == "__main__":
    main()
