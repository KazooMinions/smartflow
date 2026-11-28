"""What-if: the road beyond the junction is jammed. Tests SmartFlow's exit check (rule 4 in adaptive.py).

    .venv/bin/python blocked_exit.py      # Monivong South's exit jammed 07:30-07:40 on the normal day (about 1 minute)
    .venv/bin/python blocked_exit.py --exit W_out --at 17:30 --minutes 15 --day test3_rain_heavy_17-19

SIMULATED. The model has one junction, and vehicles leave the map 275 m after crossing, so an exit never fills up
on its own. Here every vehicle on the chosen exit is stopped once it is 20 m in, so the exit fills right up to the
junction, like a jam spilling back from the next junction. Vehicles heading into that exit can't cross; the rest can.
Three copies of the same day run side by side after the same 15-minute warm-up: the fixed-time plan, SmartFlow
without the exit check, and SmartFlow as it is. When the jam ends, all three run 5 more minutes.
"""
import argparse
import json
from types import SimpleNamespace

import adaptive
import live

STOP_AT = 20.0                  # metres into the exit where its vehicles are stopped
AFTER = 300                     # seconds simulated after the jam ends
FACING = {"S_out": "N_in", "N_out": "S_in", "E_out": "W_in", "W_out": "E_in"}   # whose straight traffic it blocks

# SUMO removes ("teleports") a vehicle that has stood still for 300 s, which would quietly empty the jam. Not here.
_start = live.traci.start
live.traci.start = lambda cmd, **kw: _start(cmd + ["--time-to-teleport", "-1"], **kw)


def main():
    ap = argparse.ArgumentParser(description="SmartFlow with a jammed exit (simulated)")
    ap.add_argument("--day", default="test1_normal", help="a day in routes/days (default test1_normal)")
    ap.add_argument("--at", default="07:30", help="when the jam starts, HH:MM (default 07:30)")
    ap.add_argument("--minutes", type=int, default=10, help="how long the jam lasts (default 10)")
    ap.add_argument("--exit", default="S_out", choices=sorted(FACING),
                    help="the jammed exit (default S_out, where Monivong North's straight-on traffic goes)")
    args = ap.parse_args()
    start = int(args.at[:2]) * 3600 + int(args.at[3:5]) * 60
    stop = start + 60 * args.minutes
    road = FACING[args.exit]

    with open(f"routes/days/{args.day}.json") as f:
        info = json.load(f)
    rain = {int(h[:2]): mm for h, mm in info["rain_mm"].items()}
    begin = max(live.DAY_START, start - live.WARMUP)
    sides = {"fixed-time": live.Junction("fixed.sumocfg", args.day, begin),
             "SmartFlow without the exit check": live.Junction("adaptive.sumocfg", args.day, begin, True, live.MODEL,
                                                               rain, info["holiday"]),
             "SmartFlow": live.Junction("adaptive.sumocfg", args.day, begin, True, live.MODEL, rain, info["holiday"])}
    sides["SmartFlow without the exit check"].ctl.exit_check = False
    seen = {n: SimpleNamespace(box=[e for e in s.conn.edge.getIDList() if e.startswith(":")],  # inside the junction
                               stopped=set(), ids={}, crossed={a: 0 for a in live.APPROACHES}, after=0,
                               greens=[], green=None, since=0, crossed_since=0, in_box=0, waiting=0)
            for n, s in sides.items()}

    t = begin
    while t < stop + AFTER:
        for n, s in sides.items():
            c, w = s.conn, seen[n]
            t = s.step()
            if t < start:
                continue
            jammed = t < stop
            if jammed:
                for v in c.edge.getLastStepVehicleIDs(args.exit):
                    if v not in w.stopped and c.vehicle.getLanePosition(v) >= STOP_AT:
                        c.vehicle.setSpeed(v, 0)
                        w.stopped.add(v)
            elif w.stopped:                           # the jam ends: let them go
                for v in w.stopped & set(c.vehicle.getIDList()):
                    c.vehicle.setSpeed(v, -1)
                w.stopped = set()
            for a in live.APPROACHES:                 # vehicles that crossed the stop line this step
                now = set(c.edge.getLastStepVehicleIDs(a))
                gone = len(w.ids.get(a, now) - now)
                w.ids[a] = now
                if jammed:
                    w.crossed[a] += gone
                else:
                    w.after += gone
            green = s.greens.get(c.trafficlight.getPhase(adaptive.TLS))
            if green != w.green:
                if w.green == road and jammed:        # one of the blocked road's greens has just ended
                    w.greens.append((adaptive.clock(w.since), round(t - w.since), w.crossed[road] - w.crossed_since,
                                     s.log[0][4]))
                if green:
                    w.since, w.crossed_since = t, w.crossed[green]
                w.green = green
            if jammed:
                w.in_box = max(w.in_box, sum(c.edge.getLastStepHaltingNumber(e) for e in w.box))
                w.waiting = sum(c.edge.getLastStepHaltingNumber(a) for a in live.APPROACHES)

    for s in sides.values():
        s.close()
    name = adaptive.NAMES[road]
    print(f"SIMULATED: the exit {args.exit} jammed from {args.at} for {args.minutes} minutes on {args.day}, "
          f"so {name}'s straight-on traffic can't cross.\n")
    rows = [(f"{name}: green time / vehicles crossed", lambda w: f"{sum(g[1] for g in w.greens)} s / {w.crossed[road]}"),
            ("All roads: vehicles crossed during the jam", lambda w: sum(w.crossed.values())),
            ("Waiting when the jam ended", lambda w: w.waiting),
            ("Stopped inside the junction, most at once", lambda w: w.in_box),
            (f"Crossed in the {AFTER // 60} minutes after", lambda w: w.after)]
    print(f"{'':44}" + "".join(f"{n:>34}" for n in sides))
    for label, value in rows:
        print(f"{label:44}" + "".join(f"{value(w):>34}" for w in seen.values()))
    for n, w in seen.items():
        print(f"\n{n}, {name}'s greens during the jam:")
        for clock, length, crossed, why in w.greens:
            print(f"  {clock}  green {length:3d} s, {crossed:3d} vehicles crossed, ended: {why}")


if __name__ == "__main__":
    main()
