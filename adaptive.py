"""Steps 3 and 5: SmartFlow adaptive signal control for IS-03, through TraCI.

    .venv/bin/python adaptive.py                  # the whole day, no window (about 4 minutes)
    .venv/bin/python adaptive.py --gui -b 24300   # watch it in sumo-gui, starting at 06:45
    .venv/bin/python adaptive.py --scenario NAME  # a rain or holiday day made by scenario.py (step 4)
    .venv/bin/python adaptive.py --predict        # with the Random Forest forecast (step 5, after forecast.py)

The rule, for each approach in turn:
  1. When its light turns green, SmartFlow notes every vehicle standing still on it. That is the queue.
  2. The light stays green until all of those vehicles have crossed the stop line and nothing on the approach
     is standing still any more (so vehicles that joined the back of the queue are served too).
  3. Every green lasts at least 10 s and at most 50 s.
  4. The exit check: if nobody has crossed the stop line for 5 s while vehicles on the approach are still standing
     still, SmartFlow looks at the roads those vehicles are heading into. If one has vehicles standing still within
     30 m of the junction, it is full (a jam spilling back from the next junction), so the green ends at once
     instead of running to its maximum, and the time goes to roads that can move.
     Both signs are needed: a vehicle that stalls at the stop line also stops everyone crossing for a while
     (README step 3). blocked_exit.py tests the check by jamming an exit on purpose.
Waiting for every queued vehicle matters because queues are uneven across lanes. Left turns use fewer lanes,
so their part of the queue clears last.

With --predict (step 5), every 5 minutes the Random Forest forecasts how many vehicles will arrive on each
approach in the next 15 minutes. The 4 x 50 = 200 s of maximum green per cycle are then shared in proportion
to that forecast (relative to how fast each approach discharges) instead of 50 s each, between 10 and 80 s.
The queue rule still ends each green as soon as its queue has cleared, so this only matters when queues are
long: the roads the model expects to be busiest may then keep their green longer.

Only the green lengths change. The phase order (East, South, West, North) and the 3 s yellow and 2 s all-red
after every green are part of the signal program, and SmartFlow never changes them.
The rule lives in the SmartFlow class below, so live.py runs exactly the same controller.

Writes out/adaptive_tripinfo.xml and out/adaptive_stats.xml (the same format as the fixed run, for summarize.py),
out/adaptive_greens.csv (every green: start time, approach, queue, length, why it ended, its maximum) and
out/adaptive_ticks.csv (every 5 minutes and approach: vehicles that arrived, queue, maximum green, forecast).
With --scenario NAME the files are out/NAME_adaptive_*, and with --predict "predict" replaces "adaptive".
With --out PREFIX they are PREFIX_tripinfo.xml and so on instead (seeds.py uses this).
Runs with --gui, -b or -e may stop early, so their files end in _partial (e.g. out/adaptive_partial_greens.csv)
and never replace the whole-day results.
"""
import argparse
import csv
import json
import os
import sys
from collections import defaultdict, deque

import traci

from make_demand import HOURS, SATURATION

TLS = "C"                       # the traffic light at the junction
MIN_GREEN, MAX_GREEN = 10, 50   # seconds. 50 beat 40, 45 and 60 over a whole day (README step 3)
EXIT_GAP, EXIT_NEAR = 5, 30     # nobody crossing for 5 s, and vehicles standing within 30 m on their exit: it's full
TICK = 300                      # every 5 minutes: count arrivals, read the queues, update the forecast
BUDGET, FORECAST_MAX = 4 * MAX_GREEN, 80   # with --predict: 200 s of maximum green per cycle, at most 80 s each
NAMES = {"N_in": "Monivong N", "E_in": "CdG East", "S_in": "Monivong S", "W_in": "CdG West"}


def read_program(conn=traci):
    """Which approach each green phase serves, and the yellow + all-red time per cycle, from the signal program."""
    links = conn.trafficlight.getControlledLinks(TLS)      # link index -> [(from lane, to lane, via lane)]
    program = conn.trafficlight.getProgram(TLS)
    logic = next(l for l in conn.trafficlight.getAllProgramLogics(TLS) if l.programID == program)
    greens, clearance = {}, 0
    for i, p in enumerate(logic.phases):
        if "G" in p.state:
            lane = links[p.state.index("G")][0][0]           # e.g. "S_in_2"
            greens[i] = lane.rsplit("_", 1)[0]               # -> "S_in"
        else:
            clearance += p.duration
    return greens, clearance


def clock(t):
    return f"{int(t // 3600):02d}:{int(t % 3600 // 60):02d}:{int(t % 60):02d}"


def share_greens(forecast, order):
    """Maximum green per approach: the 200 s budget shared by expected demand relative to discharge rate."""
    y = {a: max(forecast[a], 1.0) / SATURATION[a] for a in order}
    return {a: max(MIN_GREEN, min(FORECAST_MAX, round(BUDGET * y[a] / sum(y.values())))) for a in order}


class SmartFlow:
    """SmartFlow's rule on one running simulation (a TraCI connection), applied one step at a time.
    With a forecast model, every 5 minutes it also shares out the maximum greens."""

    def __init__(self, conn=traci, model=None, rain_mm=None, holiday=None, exit_check=True):
        self.conn, self.model, self.rain_mm, self.holiday = conn, model, rain_mm or {}, holiday
        self.exit_check = exit_check                             # rule 4 (blocked_exit.py turns it off to compare)
        if model is not None:
            import forecast
            self.predict = forecast.predict
        self.greens, self.clearance = read_program(conn)
        self.order = list(self.greens.values())
        self.limit = {a: MAX_GREEN for a in self.order}          # maximum green per approach
        self.arrived = {a: 0 for a in self.order}                # vehicles that entered each approach since the last tick
        self.recent = {a: deque(maxlen=3) for a in self.order}   # the last three 5-minute counts = the last 15 minutes
        self.expected = {}                                       # the latest forecast, once there is one
        self.next_tick = conn.simulation.getTime() + TICK
        self.last_phase = self.green = None                      # green = the approach that has green now

    def step(self):
        """Advance the simulation by one step and apply the rule. Returns (time, tick, ended):
        tick is set every 5 minutes ({"queues", "arrived"}), ended when a green has just ended."""
        c = self.conn
        c.simulationStep()
        t = c.simulation.getTime()
        for v in c.simulation.getDepartedIDList():
            self.arrived[v[:4]] += 1            # vehicle ids start with their approach, e.g. "S_in_left_moto_07.12"
        tick = ended = None
        if t >= self.next_tick:                 # every 5 minutes: record, and update the forecast
            queues = {b: c.edge.getLastStepHaltingNumber(b) for b in self.order}
            for b in self.order:
                self.recent[b].append(self.arrived[b])
                self.arrived[b] = 0
            self.expected = {}
            if self.model is not None and all(len(self.recent[b]) == 3 for b in self.order):
                self.expected = self.predict(self.model, t, queues, {b: sum(self.recent[b]) for b in self.order},
                                             self.rain_mm.get(int(t // 3600), 0.0), self.holiday)
                self.limit = share_greens(self.expected, self.order)
            tick = {"queues": queues, "arrived": {b: self.recent[b][-1] for b in self.order}}
            self.next_tick += TICK
        phase = c.trafficlight.getPhase(TLS)
        if phase != self.last_phase:
            if self.green:                      # a green has just ended
                ended = {"start": self.started, "approach": self.green, "queue": len(self.queue_at_start),
                         "length": t - self.started, "ended_by": self.ended_by, "max": self.maximum}
                self.green = None
            if phase in self.greens:            # a new green starts
                self.green, self.started, self.ended_by = self.greens[phase], t, "max green"
                self.maximum = self.limit[self.green]
                self.on_road = set(c.edge.getLastStepVehicleIDs(self.green))
                self.queue_at_start = {v for v in self.on_road if c.vehicle.getSpeed(v) < 0.1}
                self.queue = set(self.queue_at_start)
                self.last_crossed = t
                c.trafficlight.setPhaseDuration(TLS, self.maximum)    # SUMO ends it at the maximum ...
        elif self.green and self.ended_by == "max green":
            on_road = set(c.edge.getLastStepVehicleIDs(self.green))
            if self.on_road - on_road:                                # someone has crossed the stop line
                self.last_crossed = t
            self.on_road = on_road
            if t - self.started >= MIN_GREEN:
                self.queue &= on_road                                 # ... unless the queue clears first
                standing = c.edge.getLastStepHaltingNumber(self.green)
                if not self.queue and standing == 0:
                    c.trafficlight.setPhaseDuration(TLS, 0)           # go to yellow now
                    self.ended_by = "queue cleared"
                elif self.exit_check and standing and t - self.last_crossed >= EXIT_GAP and self.exit_full():
                    c.trafficlight.setPhaseDuration(TLS, 0)           # ... or when nobody can move (rule 4)
                    self.ended_by = "exit blocked"
        self.last_phase = phase
        return t, tick, ended

    def exit_full(self):
        """Does a road that the vehicles waiting on the green approach are heading into have vehicles standing still
        near the junction? A camera at the junction sees the first 30 m of each exit."""
        c, exits = self.conn, set()
        for v in c.edge.getLastStepVehicleIDs(self.green):
            if c.vehicle.getSpeed(v) < 0.1:
                route, i = c.vehicle.getRoute(v), c.vehicle.getRouteIndex(v)
                exits.update(route[i + 1:i + 2])
        return any(c.vehicle.getSpeed(v) < 0.1 and c.vehicle.getLanePosition(v) < EXIT_NEAR
                   for e in exits for v in c.edge.getLastStepVehicleIDs(e))


def main():
    ap = argparse.ArgumentParser(description="SmartFlow adaptive signals for IS-03")
    ap.add_argument("--gui", action="store_true", help="run in sumo-gui and print every green")
    ap.add_argument("-b", "--begin", type=int, help="start time, seconds since midnight (24300 = 06:45)")
    ap.add_argument("-e", "--end", type=int, help="stop at this time instead of when the last vehicle has left")
    ap.add_argument("--scenario", help="run routes/NAME.rou.xml, a rain or holiday day made by scenario.py")
    ap.add_argument("--predict", action="store_true", help="share the maximum greens by the Random Forest forecast")
    ap.add_argument("--seed", type=int, help="SUMO random seed (default 42, from adaptive.sumocfg)")
    ap.add_argument("--out", metavar="PREFIX", help="write PREFIX_tripinfo.xml and so on instead of the usual files in out/")
    args = ap.parse_args()
    prefix = args.out or f"out/{args.scenario + '_' if args.scenario else ''}{'predict' if args.predict else 'adaptive'}"
    if args.gui or args.begin or args.end:
        prefix += "_partial"        # may not cover the whole day, so it must not replace the whole-day results

    sumo = os.path.join(os.path.dirname(sys.executable), "sumo-gui" if args.gui else "sumo")
    cmd = [sumo, "-c", "adaptive.sumocfg", "--tripinfo-output", f"{prefix}_tripinfo.xml",
           "--statistic-output", f"{prefix}_stats.xml"]
    if args.gui:
        cmd += ["--gui-settings-file", "view.xml"]
    if args.begin:
        cmd += ["--begin", str(args.begin)]
    if args.seed is not None:
        cmd += ["--seed", str(args.seed)]
    rain_mm, holiday = {}, None              # what the weather feed and the holiday calendar say (step 4)
    if args.scenario:
        cmd += ["--route-files", f"routes/{args.scenario}.rou.xml"]
        with open(f"routes/{args.scenario}.json") as f:
            info = json.load(f)
        rain_mm, holiday = {int(h[:2]): mm for h, mm in info["rain_mm"].items()}, info["holiday"]
    model = None
    if args.predict:
        import forecast
        model = forecast.load()
    traci.start(cmd)

    ctl = SmartFlow(traci, model, rain_mm, holiday)
    order = ctl.order
    lengths = defaultdict(list)             # (hour, approach) -> lengths of the greens it got
    log = open(f"{prefix}_greens.csv", "w", newline="")
    out = csv.writer(log)
    out.writerow(["start_s", "clock", "approach", "queue_veh", "green_s", "ended_by", "max_green_s"])
    tick_log = open(f"{prefix}_ticks.csv", "w", newline="")
    ticks = csv.writer(tick_log)
    ticks.writerow(["time_s", "approach", "arrived_5min", "queue_veh", "max_green_s", "forecast_15min"])
    if args.gui:
        print("Press the green play button in sumo-gui to start.")
    else:
        print("SmartFlow's average green per approach and cycle length (s), hour by hour:")
        print("hour   " + "".join(f"{NAMES[a]:>12}" for a in order) + "   cycle")

    def hour_row(h):
        avg = [sum(lengths[(h, a)]) / len(lengths[(h, a)]) for a in order if lengths[(h, a)]]
        if h in HOURS and len(avg) == len(order):
            print(f"{h:02d}:00  " + "".join(f"{g:12.0f}" for g in avg) + f"{sum(avg) + ctl.clearance:8.0f}", flush=True)

    t = traci.simulation.getTime()
    hour = int(t // 3600)
    try:
        while traci.simulation.getMinExpectedNumber() > 0 and (args.end is None or t < args.end):
            t, tick, ended = ctl.step()
            if tick:
                if ctl.expected and args.gui:
                    print(f"{clock(t)}  forecast, next 15 min: " + ", ".join(
                        f"{NAMES[b]} {ctl.expected[b]:.0f} vehicles (max green {ctl.limit[b]} s)" for b in order),
                        flush=True)
                for b in order:
                    ticks.writerow([t, b, tick["arrived"][b], tick["queues"][b], ctl.limit[b],
                                    round(ctl.expected[b]) if ctl.expected else ""])
            if ended:
                out.writerow([ended["start"], clock(ended["start"]), ended["approach"], ended["queue"],
                              ended["length"], ended["ended_by"], ended["max"]])
                lengths[(int(ended["start"] // 3600), ended["approach"])].append(ended["length"])
                if args.gui:
                    print(f"{clock(ended['start'])}  {NAMES[ended['approach']]:<11} queue {ended['queue']:3d} vehicles"
                          f"  ->  green {ended['length']:4.0f} s ({ended['ended_by']})", flush=True)
            if not args.gui and int(t // 3600) != hour:
                hour_row(hour)
                hour = int(t // 3600)
        if not args.gui:
            hour_row(hour)
        traci.close()
    except traci.exceptions.FatalTraCIError:
        print("SUMO was closed before the end of the run.")
    log.close()
    tick_log.close()
    print(f"Wrote {prefix}_tripinfo.xml, {prefix}_stats.xml, {prefix}_greens.csv and {prefix}_ticks.csv")


if __name__ == "__main__":
    main()
