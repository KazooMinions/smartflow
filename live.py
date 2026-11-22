"""Step 6: the SmartFlow website. Watch the junction live, and see the statistics of every simulated test day.

    .venv/bin/python live.py      # then open http://localhost:8600 in your browser; Ctrl+C here stops it
    .venv/bin/python live.py --port 8601    # if something else already uses port 8600

Live junction (the main page, /): pick a simulated day and a start time, then press Start. Two SUMO simulations of
IS-03 run while you watch, with the same traffic: on the left the fixed-time plan, on the right SmartFlow (with or
without its forecast), which is the same SmartFlow class that adaptive.py runs. Both simulate the 15 minutes before
the chosen time without showing them, so the queues are already there.

Statistics (/stats): for each test day, the average delay with fixed-time, SmartFlow and SmartFlow + forecast, hour
by hour, and at any 5-minute moment the queues, the forecast and the signal timings, from the step 5 runs. Each
day's averages are kept in out/summary/DAY.json, so the site works without SUMO's big trip files. Those summaries
are the only files it writes.
"""
import argparse
import asyncio
import csv
import datetime as dt
import json
import math
import os
import re
import socket
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from collections import deque
from itertools import count

import sumolib
import traci
import traci.constants as tc
import uvicorn
from starlette.applications import Starlette
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Mount, Route, WebSocketRoute
from starlette.staticfiles import StaticFiles
from starlette.websockets import WebSocketDisconnect

import adaptive
import forecast
import holidays_kh
import summarize
import weather
from days import TEST_DAYS
from make_demand import HOURS

os.chdir(os.path.dirname(os.path.abspath(__file__)))    # the data paths are relative to the project folder

PORT = 8600
WARMUP = 900                    # seconds simulated before the chosen time, without being shown
FRAME = 0.1                     # seconds between pictures sent to the browser
STEP = 0.5                      # SUMO's step length, from the .sumocfg files
DAY_START, DAY_END = 21600, 79200   # 06:00 to 22:00, the counted day
KINDS = ("moto", "car", "tuktuk", "truck")
APPROACHES = ("N_in", "E_in", "S_in", "W_in")
RUNS = ("fixed", "adaptive", "predict")
SUMO = os.path.join(os.path.dirname(sys.executable), "sumo")
MODEL = forecast.load()
LABELS = count(1)               # every simulation gets its own TraCI connection label


# ---- The live junction ----

def network():
    """The junction's shape for drawing: lanes, the junction area, stop lines with their signal link, vehicle sizes."""
    net = sumolib.net.readNet("net/cross.net.xml")
    pt = lambda p: [round(p[0], 2), round(p[1], 2)]
    lanes, marks = [], []
    for edge in net.getEdges():
        shapes = [lane.getShape() for lane in edge.getLanes()]
        lanes += [{"shape": [pt(p) for p in lane.getShape()], "width": lane.getWidth()} for lane in edge.getLanes()]
        for a, b in zip(shapes, shapes[1:]):                # a dashed line between neighbouring lanes
            if len(a) == len(b):
                marks.append([pt(((p[0] + q[0]) / 2, (p[1] + q[1]) / 2)) for p, q in zip(a, b)])
    stops, links = [], {}
    for lane, _, index in net.getTLS(adaptive.TLS).getConnections():
        if any(s["lane"] == lane.getID() for s in stops):     # one stop line per lane, from its first link
            continue
        (x0, y0), (x1, y1) = lane.getShape()[-2:]
        d = math.hypot(x1 - x0, y1 - y0)
        nx, ny, h = -(y1 - y0) / d, (x1 - x0) / d, lane.getWidth() / 2
        stops.append({"lane": lane.getID(), "a": pt((x1 + nx * h, y1 + ny * h)), "b": pt((x1 - nx * h, y1 - ny * h)),
                      "link": index})
        links.setdefault(lane.getEdge().getID(), index)
    types = {vt.get("id"): vt for vt in ET.parse("net/vtypes.add.xml").iter("vType")}
    return {"lanes": lanes, "marks": marks, "junction": [pt(p) for p in net.getNode(adaptive.TLS).getShape()],
            "stops": stops, "links": links, "names": adaptive.NAMES,
            "arms": {a: pt(net.getEdge(a).getLanes()[0].getShape()[0]) for a in APPROACHES},
            "sizes": [[float(types[k].get("length")), float(types[k].get("width"))] for k in KINDS]}


def default_start(info):
    """A good time to watch a day: its holiday crowds, its first real rain, or else the morning peak."""
    if info["holiday"] == "festival":
        return "17:00"
    if info["holiday"] == "exodus":
        return "16:00"
    wet = [h for h, mm in sorted(info["rain_mm"].items()) if mm >= 2.5]
    return wet[0] if wet else "07:00"


def day_list():
    days = []
    for name, (label, about) in TEST_DAYS.items():
        with open(f"routes/days/{name}.json") as f:
            days.append({"id": name, "label": label, "about": about, "start": default_start(json.load(f))})
    return days


class Junction:
    """One SUMO simulation of the day, run by the fixed-time plan or by SmartFlow."""

    def __init__(self, config, day, begin, smartflow=False, model=None, rain_mm=None, holiday=None):
        label = f"live{next(LABELS)}"
        traci.start([SUMO, "-c", config, "--route-files", f"routes/days/{day}.rou.xml", "--begin", str(begin),
                     "--seed", "42", "--tripinfo-output", os.devnull, "--statistic-output", os.devnull,
                     "--duration-log.statistics", "false"], label=label, stdout=subprocess.DEVNULL)
        self.conn = c = traci.getConnection(label)
        self.ctl = adaptive.SmartFlow(c, model, rain_mm, holiday) if smartflow else None
        self.greens, _ = adaptive.read_program(c)
        logic = next(l for l in c.trafficlight.getAllProgramLogics(adaptive.TLS)
                     if l.programID == c.trafficlight.getProgram(adaptive.TLS))
        self.plan = {a: round(logic.phases[i].duration) for i, a in self.greens.items()}
        self.ids = {}                   # SUMO vehicle id -> a short number for the browser
        self.loss = {}                  # time lost so far by each vehicle near the junction
        self.vehicles = []              # the latest sample: (id, position, angle, type)
        self.done, self.lost = 0, 0.0   # vehicles that have left since the picture started, and the time they lost
        self.log = deque(maxlen=6)      # the latest greens: start, road, length, queue at the start, why it ended
        self.phase = self.green_start = None
        self.queue_start = 0
        self.watching = False

    def watch(self):
        """From now on, count the delay of the vehicles that leave."""
        self.watching = True
        self.sample()

    def sample(self):
        """Every vehicle near the junction now: position, heading, type and time lost so far. Asked for once per
        picture, not every step, because reading hundreds of vehicles every 0.5 s would slow the simulation down."""
        c = self.conn
        c.junction.subscribeContext(adaptive.TLS, tc.CMD_GET_VEHICLE_VARIABLE, 400,
                                    [tc.VAR_POSITION, tc.VAR_ANGLE, tc.VAR_TYPE, tc.VAR_TIMELOSS])
        results = c.junction.getContextSubscriptionResults(adaptive.TLS) or {}
        self.vehicles = [(v, r[tc.VAR_POSITION], r[tc.VAR_ANGLE], r[tc.VAR_TYPE]) for v, r in results.items()]
        for v, r in results.items():
            self.loss[v] = r[tc.VAR_TIMELOSS]       # a vehicle loses hardly any time after it has crossed
        c.junction.unsubscribeContext(adaptive.TLS, tc.CMD_GET_VEHICLE_VARIABLE, 400)

    def step(self):
        c, ended = self.conn, None
        if self.ctl:
            t, _, ended = self.ctl.step()
        else:
            c.simulationStep()
            t = c.simulation.getTime()
        phase = c.trafficlight.getPhase(adaptive.TLS)
        if phase != self.phase:
            if self.phase in self.greens and self.green_start is not None:
                why, queue = (ended["ended_by"], ended["queue"]) if ended else ("fixed plan", self.queue_start)
                self.log.appendleft([adaptive.clock(self.green_start), adaptive.NAMES[self.greens[self.phase]],
                                     round(t - self.green_start), queue, why])
            if phase in self.greens:
                self.green_start = t
                self.queue_start = c.edge.getLastStepHaltingNumber(self.greens[phase])
            self.phase = phase
        if self.watching:
            for v in c.simulation.getArrivedIDList():
                if v in self.loss:
                    self.done += 1
                    self.lost += self.loss.pop(v)
        return t

    def state(self, t):
        """What the browser draws and lists for this junction now."""
        c, veh = self.conn, []
        for v, (x, y), angle, vtype in self.vehicles:
            kind = vtype.split("_")[0]                    # rain types are named like "moto_rain_heavy"
            veh += [self.ids.setdefault(v, len(self.ids)), round(x, 1), round(y, 1), round(angle),
                    KINDS.index(kind) if kind in KINDS else 1]
        queues = {a: c.edge.getLastStepHaltingNumber(a) for a in APPROACHES}
        green = None
        if self.phase in self.greens:
            green = {"approach": self.greens[self.phase], "elapsed": round(t - self.green_start),
                     "max": self.ctl.maximum if self.ctl else round(c.trafficlight.getPhaseDuration(adaptive.TLS))}
        expected = self.ctl.expected if self.ctl else {}
        return {"veh": veh, "signal": c.trafficlight.getRedYellowGreenState(adaptive.TLS), "queues": queues,
                "waiting": sum(queues.values()), "done": self.done,
                "delay": round(self.lost / self.done, 1) if self.done else None, "green": green, "log": list(self.log),
                "limits": self.ctl.limit if self.ctl else self.plan,
                "expected": {a: round(n) for a, n in expected.items()} if expected else None}

    def close(self):
        try:
            self.conn.close()
        except Exception:               # SUMO has already gone
            pass


class Session:
    """The chosen day from the chosen time: fixed-time (left) and SmartFlow (right), stepped together."""

    def __init__(self, day, start, use_forecast):
        with open(f"routes/days/{day}.json") as f:
            info = json.load(f)
        self.rain = {int(h[:2]): mm for h, mm in info["rain_mm"].items()}
        begin = max(DAY_START, start - WARMUP)
        self.sides = []
        try:
            self.sides.append(Junction("fixed.sumocfg", day, begin))
            self.sides.append(Junction("adaptive.sumocfg", day, begin, True, MODEL if use_forecast else None,
                                       self.rain, info["holiday"]))
            self.t = begin
            while self.t < start:       # the warm-up, not shown
                self.t = [j.step() for j in self.sides][0]
            for j in self.sides:
                j.watch()
        except Exception:
            self.close()
            raise

    def advance(self, steps):
        for _ in range(steps):
            if self.t >= DAY_END:
                break
            self.t = [j.step() for j in self.sides][0]
        for j in self.sides:
            j.sample()
        return self.frame()

    def frame(self):
        return {"type": "frame", "t": self.t, "clock": adaptive.clock(self.t),
                "rain_mm": self.rain.get(int(self.t // 3600), 0.0), "sides": [j.state(self.t) for j in self.sides]}

    def close(self):
        for j in self.sides:
            j.close()


async def stream(ws):
    """One browser tab: it sends start, play, pause and speed; this sends it a picture every 0.1 s while playing."""
    await ws.accept()
    await ws.send_json({"type": "hello", "days": day_list(), "net": NET})
    inbox = asyncio.Queue()

    async def listen():
        try:
            while True:
                await inbox.put(await ws.receive_json())
        except Exception:               # the tab was closed
            await inbox.put({"cmd": "bye"})

    listener = asyncio.create_task(listen())
    session, playing, speed = None, False, 10
    try:
        while True:
            if session is None or not playing:
                msg = await inbox.get()             # nothing to run: wait for the next command
            else:
                msg = None if inbox.empty() else inbox.get_nowait()
            if msg is not None:
                cmd = msg.get("cmd")
                if cmd == "bye":
                    break
                if cmd == "start":
                    if session:
                        session.close()
                        session = None
                    start = int(msg["start"][:2]) * 3600 + int(msg["start"][3:5]) * 60
                    await ws.send_json({"type": "status", "text": f"Simulating the 15 minutes before {msg['start']}"
                                                                  " so the queues are there…"})
                    try:
                        session = await asyncio.to_thread(Session, msg["day"], start, bool(msg.get("forecast")))
                    except Exception as e:
                        await ws.send_json({"type": "status", "text": f"SUMO could not start: {e}"})
                        continue
                    playing = True
                    await ws.send_json({"type": "ready"})
                    await ws.send_json(session.frame())
                elif cmd == "play":
                    playing = session is not None and session.t < DAY_END
                elif cmd == "pause":
                    playing = False
                elif cmd == "speed":
                    speed = max(1, min(100, int(msg["value"])))
                continue
            began = time.monotonic()
            frame = await asyncio.to_thread(session.advance, max(1, round(speed * FRAME / STEP)))
            await ws.send_json(frame)
            if session.t >= DAY_END:
                playing = False
                await ws.send_json({"type": "status", "text": "22:00: the end of the counted day.", "end": True})
            await asyncio.sleep(max(0.0, FRAME - (time.monotonic() - began)))
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        listener.cancel()
        if session:
            session.close()


# ---- The statistics ----

def fixed_plan():
    """Green seconds per approach and the cycle length of the fixed-time plan (net/fixed_plan.add.xml)."""
    with open("net/fixed_plan.add.xml") as f:
        xml = f.read()
    greens = {a: int(d) for d, a in re.findall(r'duration="(\d+)"[^>]*/>\s*<!-- (\w+) green -->', xml)}
    return greens, sum(int(d) for d in re.findall(r'duration="(\d+)"', xml))


def summary(day):
    """The day's three runs: average delay per vehicle, vehicles, and delay hour by hour (summarize.py's
    definition). Made from SUMO's trip files the first time, then read from out/summary/DAY.json."""
    path = f"out/summary/{day}.json"
    trips = [f"out/days/{day}_{run}_tripinfo.xml" for run in RUNS]
    newest = max((os.path.getmtime(p) for p in trips if os.path.exists(p)), default=0)
    if os.path.exists(path) and os.path.getmtime(path) >= newest:
        with open(path) as f:
            return json.load(f)
    if not all(os.path.exists(p) for p in trips):
        return None
    runs = {}
    for run, p in zip(RUNS, trips):
        d = summarize.load(p)
        every = summarize.every(d)
        runs[run] = {"avg": summarize.mean(every), "vehicles": len(every),
                     "hourly": [round(summarize.mean(summarize.every(d, h)), 1) for h in HOURS]}
    os.makedirs("out/summary", exist_ok=True)
    with open(path, "w") as f:
        json.dump(runs, f)
    return runs


def day_stats(day):
    """Everything the statistics page shows for one test day."""
    runs = summary(day)
    files = [f"out/days/{day}_predict_{kind}.csv" for kind in ("ticks", "greens")]
    if runs is None or not all(os.path.exists(p) for p in files):
        return {"error": "This day has no results yet. Run days.py, forecast.py and days.py --predict (README step 5)."}
    with open(f"routes/days/{day}.json") as f:
        info = json.load(f)
    with open(files[0]) as f:
        ticks = [[float(r["time_s"]), r["approach"], int(r["arrived_5min"]), int(r["queue_veh"]),
                  int(r["max_green_s"]), int(r["forecast_15min"]) if r["forecast_15min"] else None]
                 for r in csv.DictReader(f)]
    with open(files[1]) as f:
        greens = [[float(r["start_s"]), r["approach"], int(r["queue_veh"]), float(r["green_s"]), r["ended_by"],
                   int(r["max_green_s"])] for r in csv.DictReader(f)]
    plan, cycle = fixed_plan()
    return {"hours": list(HOURS), "runs": runs, "rain_mm": info["rain_mm"], "holiday": info["holiday"],
            "plan": plan, "plan_cycle": cycle, "names": adaptive.NAMES, "ticks": ticks, "greens": greens}


INPUTS = {"until": 0, "data": None}


def live_inputs():
    """Today's real inputs: Open-Meteo's weather at IS-03 and the 2026 holiday calendar (kept for 15 minutes)."""
    if time.time() < INPUTS["until"]:
        return INPUTS["data"]
    try:
        w = weather.today(timeout=10)
        now = {"time": w["time"][11:], "temperature_c": w["temperature_c"], "rain_mm_15min": w["precipitation_mm"],
               "sky": weather.WEATHER.get(w["weather_code"], f"weather code {w['weather_code']}"),
               "rain_today_mm": round(sum(mm or 0 for h, mm in w["rain_mm"].items() if h in HOURS), 1)}
        keep = 900
    except Exception as e:              # offline, or Open-Meteo did not answer: try again in a minute
        now, keep = {"error": f"{type(e).__name__}: {e}"}, 60
    cal, today = holidays_kh.load(), dt.date.today()
    upcoming = [d for d in sorted(cal) if d > today]
    about = lambda d: {"date": d.isoformat(), "name": cal.get(d, (None,))[0],
                       "pattern": holidays_kh.traffic_pattern(d, cal)}
    INPUTS.update(until=time.time() + keep, data={"weather": now, "today": about(today),
                                                  "next": about(upcoming[0]) if upcoming else None})
    return INPUTS["data"]


# ---- The website ----

async def live_page(request):
    return FileResponse("web/live.html")


async def stats_page(request):
    return FileResponse("web/stats.html")


async def days_api(request):
    return JSONResponse(day_list())


async def stats_api(request):
    day = request.path_params["day"]
    if day not in TEST_DAYS:
        return JSONResponse({"error": "Unknown day."}, status_code=404)
    return JSONResponse(await asyncio.to_thread(day_stats, day))


async def inputs_api(request):
    return JSONResponse(await asyncio.to_thread(live_inputs))


NET = network()
app = Starlette(routes=[
    Route("/", live_page), Route("/stats", stats_page),
    Route("/api/days", days_api), Route("/api/stats/{day}", stats_api), Route("/api/inputs", inputs_api),
    WebSocketRoute("/ws", stream), Mount("/static", StaticFiles(directory="web")),
])

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="The SmartFlow website: the live junction and the statistics")
    ap.add_argument("--port", type=int, default=PORT, help=f"the website's port (default {PORT})")
    port = ap.parse_args().port
    with socket.socket() as probe:
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            sys.exit(f"Port {port} is already in use, probably by another live.py that is still running. Open "
                     f"http://localhost:{port}, or stop the other one with Ctrl+C in its terminal, or use another "
                     f"port: .venv/bin/python live.py --port {port + 1}")
    print(f"SmartFlow: open http://localhost:{port} in your browser (Ctrl+C stops it)", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
