"""Step 4: run a scenario day with fixed-time signals and with SmartFlow at the same time, then compare them.

    .venv/bin/python compare.py rain_heavy_17-19      # a NAME printed by scenario.py

Takes about 5 minutes. The SUMO logs go to out/NAME_fixed.log and out/NAME_adaptive.log.
"""
import json
import os
import subprocess
import sys

import summarize

if len(sys.argv) != 2:
    sys.exit(__doc__)
name = sys.argv[1]
with open(f"routes/{name}.json") as f:
    info = json.load(f)
wet = {h: level for h, level in info["rain_level"].items() if level != "dry"}
print(f"SIMULATED scenario {name}: rain {', '.join(f'{h} {lv}' for h, lv in wet.items()) or 'none'}; "
      f"holiday {info['holiday'] or 'none'}. Running fixed-time and SmartFlow (about 5 minutes)...", flush=True)

venv_bin = os.path.dirname(sys.executable)
runs = {
    "fixed": [os.path.join(venv_bin, "sumo"), "-c", "fixed.sumocfg", "--route-files", f"routes/{name}.rou.xml",
              "--tripinfo-output", f"out/{name}_fixed_tripinfo.xml", "--statistic-output", f"out/{name}_fixed_stats.xml"],
    "adaptive": [sys.executable, "adaptive.py", "--scenario", name],
}
procs = {k: subprocess.Popen(cmd, stdout=open(f"out/{name}_{k}.log", "w"), stderr=subprocess.STDOUT)
         for k, cmd in runs.items()}
for k, p in procs.items():
    if p.wait() != 0:
        sys.exit(f"The {k} run failed, see out/{name}_{k}.log")
summarize.compare(f"out/{name}_fixed_tripinfo.xml", f"out/{name}_adaptive_tripinfo.xml")
