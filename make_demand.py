"""Step 2: turn JICA traffic counts into vehicle arrival rates for each approach, and a SUMO route file.

    .venv/bin/python make_demand.py

Reads   data/jica_is03_movements.csv   PCU per 16 hours for each of the 12 turning movements at IS-03
        data/jica_hourly_profile.csv   share of daily traffic in each hour, towards / away from the city centre
        data/jica_roadside.csv         vehicle mix (average of JICA's 17 roadside count stations)
Writes  data/arrival_rates.csv         vehicles per hour and arrivals per second, per approach and hour
        routes/jica_day.rou.xml        random (Poisson) arrivals for SUMO, 06:00-22:00

Options: --scale 1.3 multiplies all traffic (used later for holiday and rain scenarios)
         --out routes/other.rou.xml writes the routes somewhere else
"""
import argparse
import csv
from collections import defaultdict

HOURS = range(6, 22)  # JICA counted 06:00-22:00
# Which hourly profile each approach follows. The city centre (Central Market, Daun Penh) lies north-east of IS-03,
# so traffic from Monivong South and Charles de Gaulle West is heading into the centre. The counts agree:
# those two approaches carry more traffic over the day than the opposite ones.
PROFILE = {"S_in": "pct_to_city", "W_in": "pct_to_city", "N_in": "pct_from_city", "E_in": "pct_from_city"}
# PCU per vehicle, JICA (2023) Table 6.1.1. 3-wheelers -> tuk-tuk; buses and trucks -> "truck" (2.0-3.0, so 2.5).
PCU = {"moto": 0.30, "car": 1.00, "tuktuk": 0.75, "truck": 2.50}
VTYPES = tuple(PCU)
# Fixed-time plan. Discharge rates were measured in SUMO on this network: vehicles per hour of green, with each
# approach's real turning mix, in an oversaturated test, averaged over 4 random seeds (single runs vary by 5-10%).
# They change if you change the lanes in net/cross.edg.xml or net/cross.con.xml.
SATURATION = {"N_in": 11268, "E_in": 8381, "S_in": 12080, "W_in": 8118}
CYCLE = 140  # seconds, same as the step-1 plan
EXITS = {  # right-hand traffic: exit road for each movement
    "N_in": {"through": "S_out", "left": "E_out", "right": "W_out"},
    "S_in": {"through": "N_out", "left": "W_out", "right": "E_out"},
    "E_in": {"through": "W_out", "left": "S_out", "right": "N_out"},
    "W_in": {"through": "E_out", "left": "N_out", "right": "S_out"},
}


def read_csv(path):
    with open(path) as f:
        return list(csv.DictReader(line for line in f if not line.startswith("#")))


def vehicle_mix():
    """Average vehicle shares (by count) over JICA's roadside stations; buses/trucks/others are the remainder."""
    rs = read_csv("data/jica_roadside.csv")
    avg = lambda col: sum(float(r[col]) for r in rs) / len(rs) / 100
    mix = {"moto": avg("motorbike_pct"), "car": avg("sedan_pct"), "tuktuk": avg("three_wheeler_pct")}
    mix["truck"] = 1 - sum(mix.values())
    return mix


def build_rates(scale=1.0):
    pcu_16h = defaultdict(float)          # approach -> PCU over 16 hours
    turn_pcu = defaultdict(dict)          # approach -> {turn: PCU}
    for r in read_csv("data/jica_is03_movements.csv"):
        pcu_16h[r["model_approach"]] += float(r["pcu_16h"])
        turn_pcu[r["model_approach"]][r["turn"]] = float(r["pcu_16h"])
    prof = {int(r["hour"]): r for r in read_csv("data/jica_hourly_profile.csv")}
    mix = vehicle_mix()
    pcu_per_veh = sum(mix[v] * PCU[v] for v in VTYPES)

    rates = {}
    for a, total in pcu_16h.items():
        turns = {t: p / total for t, p in turn_pcu[a].items()}
        col = PROFILE[a]
        window = sum(float(prof[h][col]) for h in HOURS)
        for h in HOURS:
            pcu = scale * total * float(prof[h][col]) / window   # this hour's share of the 16-hour count
            rates[(h, a)] = {"pcu_h": pcu, "vph": pcu / pcu_per_veh, "mix": mix, "turns": turns}
    return rates, pcu_per_veh


def write_fixed_plan(rates, path, net="net/cross.net.xml"):
    """One all-day fixed plan, sized to the JICA counts the way a traffic engineer would (Webster):
    each approach's green is proportional to its average traffic divided by how fast it discharges."""
    import xml.etree.ElementTree as ET
    root = ET.parse(net).getroot()
    approach_of_link = {int(c.get("linkIndex")): c.get("from") for c in root.iter("connection") if c.get("tl") == "C"}
    phases = [(int(p.get("duration")), p.get("state")) for p in root.find("tlLogic").iter("phase")]
    avg = {a: sum(rates[(h, a)]["vph"] for h in HOURS) / len(HOURS) for a in EXITS}
    y = {a: avg[a] / SATURATION[a] for a in EXITS}
    lost = sum(d for d, s in phases if "G" not in s)            # yellow + all-red time per cycle
    exact = {a: (CYCLE - lost) * y[a] / sum(y.values()) for a in EXITS}
    greens = {a: int(g) for a, g in exact.items()}
    for a in sorted(exact, key=lambda a: exact[a] - greens[a], reverse=True)[:CYCLE - lost - sum(greens.values())]:
        greens[a] += 1                                          # round so the greens add up to exactly CYCLE - lost
    out = []
    for d, s in phases:
        if "G" in s:
            a = approach_of_link[s.index("G")]
            d = greens[a]
            out.append(f'        <phase duration="{d}" state="{s}"/>  <!-- {a} green -->')
        else:
            out.append(f'        <phase duration="{d}" state="{s}"/>')
    with open(path, "w") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n<!-- Generated by make_demand.py. Fixed-time plan for IS-03 sized to the\n'
                '     JICA 2022 counts: one plan all day, greens proportional to average traffic / discharge rate. -->\n'
                f'<additional>\n    <tlLogic id="C" type="static" programID="jica_fixed" offset="0">\n'
                + "\n".join(out) + "\n    </tlLogic>\n</additional>\n")
    return greens, lost + sum(greens.values())


def write_rates_csv(rates, path):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["hour", "approach", "veh_per_hour", "pcu_per_hour", "arrivals_per_s", "mean_gap_s",
                    "moto_pct", "car_pct", "tuktuk_pct", "truck_pct", "through_pct", "left_pct", "right_pct"])
        for (h, a), r in sorted(rates.items()):
            lam = r["vph"] / 3600
            w.writerow([f"{h:02d}:00", a, round(r["vph"]), round(r["pcu_h"]), round(lam, 3), round(1 / lam, 2),
                        *(round(100 * r["mix"][v], 1) for v in VTYPES),
                        *(round(100 * r["turns"][t], 1) for t in ("through", "left", "right"))])


def write_routes(rates, path, note, rain=None, vtypes=""):
    """rain: {hour: "light"/"moderate"/"heavy"}. Vehicles that set off in those hours use the wet version of their
    type (e.g. "moto_rain_heavy"), whose definitions come in `vtypes` (step 4, scenario.py)."""
    rain = rain or {}
    lines = []
    for h in HOURS:  # SUMO wants flows sorted by start time
        for a in EXITS:
            r = rates[(h, a)]
            for turn, to in EXITS[a].items():
                for v in VTYPES:
                    lam = r["vph"] * r["turns"][turn] * r["mix"][v] / 3600   # arrivals per second
                    if lam < 1e-5:
                        continue
                    vtype = f"{v}_rain_{rain[h]}" if h in rain else v
                    lat = ' departPosLat="random_free"' if v == "moto" else ""
                    lines.append(f'    <flow id="{a}_{turn}_{v}_{h:02d}" type="{vtype}" from="{a}" to="{to}" begin="{h*3600}" '
                                 f'end="{(h+1)*3600}" period="exp({lam:.5f})" departLane="best" departSpeed="max"{lat}/>')
    with open(path, "w") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n<!-- Generated by make_demand.py: ' + note + '\n'
                '     Random (Poisson) arrivals. Times are seconds since midnight (25200 = 07:00). -->\n<routes>\n'
                + vtypes + "\n".join(lines) + "\n</routes>\n")
    return len(lines)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--scale", type=float, default=1.0, help="multiply all traffic, e.g. 1.3 = 30%% more")
    ap.add_argument("--out", default="routes/jica_day.rou.xml")
    args = ap.parse_args()
    rates, pcu_per_veh = build_rates(args.scale)
    write_rates_csv(rates, "data/arrival_rates.csv")
    n = write_routes(rates, args.out, f"JICA 2022 counts at IS-03 (Monivong x Charles de Gaulle), scale {args.scale}")
    if args.scale == 1.0:  # the fixed plan is sized to the normal counts only
        greens, cycle = write_fixed_plan(rates, "net/fixed_plan.add.xml")

    pcu = sum(r["pcu_h"] for r in rates.values())
    veh = sum(r["vph"] for r in rates.values())
    print(f"IS-03, 06:00-22:00: {pcu:,.0f} PCU = {veh:,.0f} vehicles (1 vehicle = {pcu_per_veh:.2f} PCU on average)")
    print("Vehicles per hour arriving on each approach:")
    print("hour   " + "  ".join(f"{a:>5}" for a in EXITS) + "  total")
    for h in HOURS:
        row = [rates[(h, a)]["vph"] for a in EXITS]
        print(f"{h:02d}:00  " + "  ".join(f"{x:5.0f}" for x in row) + f"  {sum(row):5.0f}")
    print(f"Wrote data/arrival_rates.csv and {args.out} ({n} flows)")
    if args.scale == 1.0:
        print(f"Fixed plan (net/fixed_plan.add.xml), {cycle} s cycle, green seconds: "
              + ", ".join(f"{a} {g}" for a, g in greens.items()))
