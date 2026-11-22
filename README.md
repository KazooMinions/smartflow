# SmartFlow: adaptive traffic-signal prototype

One real Phnom Penh intersection, **IS-03: Monivong Blvd × Charles de Gaulle Blvd (St. 217)**, simulated in SUMO 1.28 with traffic from JICA's 2022 counts. The goal is a signal controller that adapts its green times to the traffic and measurably beats fixed-time signals.

**Data honesty, for the video and slides:**
- **Measured (JICA 2022 weekday count):** traffic volumes, turning movements, hour-by-hour pattern and vehicle mix.
- **Calibrated:** lane counts and left-turn lanes are "effective width" settings, not the painted lanes (see step 2).
- **Assumed:** the signal phasing. JICA does not publish IS-03's real timing plan.
- **Simulated:** rainy-day and holiday traffic, always. There are no counts for them, so label them as simulated. In step 4, the rain effects are calibrated to published studies, while the holiday effects are assumptions. The step 5 forecast is trained and tested on simulated days too.

**Website: https://kazoominions.github.io/smartflow/** runs in any browser, with nothing to install: recordings of the live junction for the five test days, and the statistics. Code: https://github.com/KazooMinions/smartflow

## Quick start: run the website

The website above plays recordings. To run the simulation itself, from any day and time, run the website on your own computer. You need Python 3.12 or 3.13 and git. Get the project:

```bash
git clone https://github.com/KazooMinions/smartflow.git
```

```bash
cd smartflow
```

Then, on macOS or Linux:

```bash
python3 -m venv .venv
```

```bash
.venv/bin/pip install -r requirements.txt
```

```bash
.venv/bin/python live.py
```

On Windows, in PowerShell: `py -3.13 -m venv .venv`, then `.venv\Scripts\pip install -r requirements.txt`, then `.venv\Scripts\python live.py`.

Then open http://localhost:8600: the live junction, with a link to the statistics. The install downloads a few hundred MB, mostly SUMO and scikit-learn. To get later changes, run `git pull` in the `smartflow` folder. The repository leaves out SUMO's trip files and the JICA PDFs, which the website doesn't need. To run the simulations again, follow steps 1 to 5 below (`days.py` takes about 75 minutes).

## Progress

| Step | What | Status |
|---|---|---|
| 1 | SUMO installed, four-way intersection, fixed-time run | ✅ done 2026-11-21 |
| 2 | JICA traffic volumes → CSV → arrival rates per approach | ✅ done 2026-11-21 |
| 3 | TraCI adaptive control vs fixed-time | ✅ done 2026-11-21 |
| 4 | Open-Meteo weather, holiday calendar, rain/holiday scenarios | ✅ done 2026-11-22 |
| 5 | Random Forest demand forecast that shares out the green | ✅ done 2026-11-22 |
| 6 | Website: the live junction (fixed-time and SmartFlow side by side) and a statistics page | ✅ done 2026-11-22 |

## Setup (once)

```bash
cd ~/Documents/smartflow
```

```bash
python3.13 -m venv .venv
```

```bash
.venv/bin/pip install -r requirements.txt
```

Check it worked with `.venv/bin/sumo --version`. The first line should read `Eclipse SUMO sumo 1.28.0`. The pip package includes `sumo`, `sumo-gui`, `netedit` and `netconvert`. The windowed apps need XQuartz, which is already installed on this Mac.

## Step 1: the intersection

```bash
cd net && ../.venv/bin/netconvert -c cross.netccfg && cd ..
```

It prints `Warning: The traffic light 'C' has a high cycle time of 140.00.` twice, then `Success.` The warning is expected.

The network is built from plain text files, following SUMO's own traffic-light tutorial, so it rebuilds exactly:

| File | What it holds |
|---|---|
| `net/cross.nod.xml` | Junction `C` at (0,0) and the far ends of four 300 m arms, at the real road angles from OpenStreetMap (Monivong 352°/172°, Charles de Gaulle 51°/231°) |
| `net/cross.edg.xml` | 8 road pieces at 40 km/h: Monivong 4 lanes each way, Charles de Gaulle 3 |
| `net/cross.con.xml` | Which lanes may turn which way on Monivong South and Charles de Gaulle West: left turns get two lanes there (added in step 3, see "Why two left-turn lanes") |
| `net/cross.netccfg` | netconvert settings: one green per approach, 3 s yellow, 2 s all-red |
| `net/cross.net.xml` | The generated network SUMO runs (don't edit by hand) |

Approach names: `N_in` = Monivong North, `S_in` = Monivong South, `E_in` = Charles de Gaulle East (north-east side), `W_in` = Charles de Gaulle West (south-west side). `X_out` is traffic leaving towards side X.

**Signal phasing:** each approach gets its own green in turn, **East → South → West → North**. Each green is followed by 3 s yellow and 2 s all-red, so no two movements ever cross. I tried the alternative, where both directions of a road share one green and left turns find gaps in oncoming traffic. It gridlocked within an hour at these volumes, because left-turning motorbikes waiting for gaps blocked the junction.

To look at or edit the junction:

```bash
.venv/bin/netedit net/cross.net.xml
```

Either edit in NETEDIT and save, or edit the `.nod`/`.edg` files and rebuild. Don't do both, because a rebuild overwrites NETEDIT changes.

## Step 2: JICA traffic

### Sources

The reports are downloaded in `data/` from JICA's public library:

| Folder | Report |
|---|---|
| `data/jica/` | JICA (Feb 2023) *Data Collection Survey on Urban Transport in Phnom Penh*, Final Report, part 1 ([12371746_01.pdf](https://openjicareport.jica.go.jp/pdf/12371746_01.pdf)) |
| `data/jica_part2/` | The same report, part 2, with Appendix 1, "Transport Surveys" ([12371746_02.pdf](https://openjicareport.jica.go.jp/pdf/12371746_02.pdf)) |
| `data/jica_2015/` | JICA (Jan 2015) *Preparatory Survey for Project of Development of Traffic Management System in Phnom Penh* ([12184941.pdf](https://openjicareport.jica.go.jp/pdf/12184941.pdf)) |

### Extracted CSV files

Each file's first line names the exact table or figure and page.

| File | What it holds | From |
|---|---|---|
| `data/jica_is03_movements.csv` | PCU per 16 h for all 12 turning movements at IS-03 | Appendix 1, Figure 1.3.79 + Table 1.3.25 (p. A1-76) |
| `data/jica_hourly_profile.csv` | % of daily traffic in each hour, towards and away from the city centre | Figure 5.3.21 (p. 5-21), read from the PDF's vector chart |
| `data/jica_roadside.csv` | Daily traffic and vehicle mix at 17 roadside stations | Table 5.3.11 (pp. 5-29–5-30) |
| `data/jica_intersections.csv` | Total traffic entering all 13 surveyed intersections, 2012 and 2022 | Figure 5.3.37 (p. 5-31) |

Checks: the 12 IS-03 movements add up to the table's IN and OUT totals for every leg, within 1 PCU of rounding, and to the 56,719 PCU total in Figure 5.3.37. One label in the figure is a misprint: movement 9 reads 6,387, but only 636 matches the totals. All 25 bar labels in Figure 5.3.37 match their bar heights within 0.6%.

### From counts to arrival rates

```bash
.venv/bin/python make_demand.py
```

The script turns the counts into arrival rates in four steps:
1. Each approach's 16-hour PCU count is spread over the hours with JICA's hourly profile. Approaches heading into the city centre (Monivong South, Charles de Gaulle West) follow the "to city" curve, and the others the "from city" curve.
2. PCU is converted to vehicles with JICA's PCU factors (Table 6.1.1, p. 6-2: motorbike 0.30, tuk-tuk 0.75, car 1.0, bus/truck 2.5) and the average mix of the 17 roadside stations: 66% motorbikes, 17% cars, 12% tuk-tuks, 5% buses/trucks. On average, 1 vehicle = 0.58 PCU.
3. Each approach's vehicles split into left/through/right by its real turning shares.
4. Vehicles arrive at random (Poisson) at those rates. Times are seconds since midnight, so 25200 = 07:00.

You should see `IS-03, 06:00-22:00: 56,718 PCU = 97,463 vehicles`, then a table of vehicles per hour on each approach. The busiest hours are Monivong South at 3,162/h at 07:00 (into the city) and Monivong North at 2,321/h at 17:00 (out of the city). Then:

```
Fixed plan (net/fixed_plan.add.xml), 140 s cycle, green seconds: N_in 30, S_in 35, E_in 23, W_in 32
```

It writes:
- `data/arrival_rates.csv`: one row per hour × approach, with vehicles/hour, PCU/hour, arrivals per second, average gap between arrivals, vehicle mix and turning shares.
- `routes/jica_day.rou.xml`: the SUMO traffic.
- `net/fixed_plan.add.xml`: the fixed-time baseline. It's one plan all day, with each green sized to its approach's average traffic (Webster's method), like a traffic engineer working from the JICA counts would set it.

`--scale 1.3` multiplies all traffic, for quick tests. Rain and holiday days are made with `scenario.py` (step 4).

### Run the day with fixed-time signals

```bash
.venv/bin/sumo -c fixed.sumocfg
```

It takes about 3 minutes for 16 simulated hours. The end of the output should read (exact numbers, because the seed is fixed):

```
Vehicles:
 Inserted: 97539
 Running: 0
 Waiting: 0
 Teleports: 0 (Collisions: 686)
 Emergency Braking: 198
Statistics (avg of 97539):
 ...
 TimeLoss: 68.41
 DepartDelay: 0.26
```

Then the delay table:

```bash
.venv/bin/python summarize.py out/fixed_tripinfo.xml
```

```
hour     Monivong N    CdG East  Monivong S    CdG West   all
06:00            51          61          54          56    55
07:00            58          66         184         130   131
...
17:00           107         119          67          77    89
...
Whole run: 97,539 vehicles, average delay 68.7 s
```

This is the baseline for step 3. A single fixed plan suits neither peak. In the morning the inbound approaches queue (Monivong South at 184 s, Charles de Gaulle West at 130 s), and in the evening the outbound ones do (Charles de Gaulle East at 119 s, Monivong North at 107 s). An adaptive controller should move green time between them.

What the other numbers mean:
- `Waiting: 0` means traffic never backed up to the start of an arm.
- `Teleports: 0` means no stuck vehicle was removed.
- `Collisions: 686` are not crashes. They're overlaps of a few centimetres between queued motorbikes riding side by side, a known side effect of SUMO's sublane model. They don't stop or change the run.
- `Emergency Braking` counts vehicles braking hard as the light turned yellow.

### Watch it (for the video)

Start at 06:45, so queues have built by 07:00:

```bash
.venv/bin/sumo-gui -c fixed.sumocfg --gui-settings-file view.xml -b 24300
```

Press the green ▶ button. The time display reads seconds since midnight (25200 = 07:00). You'll see the stop lines turn green one approach at a time, East → South → West → North, and the Monivong South queue growing through the morning peak. The `Delay` box next to ▶ sets playback speed. `out/step2_gui_0713.png` shows what it looks like at 07:13.

### Why 4 and 3 lanes

OpenStreetMap tags Monivong as 2 lanes each way and Charles de Gaulle as 2, widening to 4 for the last 112 m on the south-west side. With 2 SUMO lanes and one green per approach, the junction can't pass the traffic JICA counted, and counts measure traffic that actually got through. In Phnom Penh, motorbikes ride several abreast across the whole carriageway, so the lane count here is an effective-width calibration. Each approach's discharge rate was measured in SUMO by overloading every approach and counting what got through: vehicles per hour of green, Monivong N 11,268, S 12,080, Charles de Gaulle E 8,381, W 8,118. These are averages of 4 runs with different random seeds, because a single run varies by 5–10%. With these rates, the busiest hours need 75% (07:00) and 79% (17:00) of the time as green, out of the 86% that a 140 s cycle offers (the rest is yellow and all-red). So the junction is busy but under capacity. If you change the lanes, re-measure and update `SATURATION` in `make_demand.py`.

### Why two left-turn lanes

netconvert's default gives each left turn only the leftmost lane, shared with through traffic. On Monivong South and Charles de Gaulle West about 30% of vehicles turn left (JICA movements 4 and 1), so that one lane became the bottleneck of the whole junction. In a test of the morning peak with fixed-time signals, Monivong South's left-turners lost 416 s each, against 119 s for its through traffic. Real left-turning motorbikes spread over the whole left side of the road, so `net/cross.con.xml` gives left turns two lanes on those approaches: the leftmost lane is left-only and the next one is through or left, so no paths cross. I found this while building step 3 and changed it for both the fixed and the adaptive runs. That's why the fixed-time numbers above are better than in the first version of step 2 (average delay 68.7 s, was 77.3 s).

### Context for the slides (with sources)

- In 2015, every signal in Phnom Penh ran one fixed timing regardless of time of day or traffic (JICA 2015, p. 7). Average city-centre speed was 12.5 km/h, and major intersections ran at 1.37× capacity in the evening peak (p. 4).
- Since December 2018, Japan has installed signals at 115 intersections, 109 of them connected to a Traffic Control Centre using "flexible signal parameter settings" (JICA 2023, p. 3-29). So present the 2015 finding as history. SmartFlow's angle is control that responds to each approach's queue and predicts demand shifts from weather and holidays.
- JICA chose IS-02 (Russian Blvd × Monivong, also on Monivong and close to IS-03 on JICA's map) as the training site for signal-timing optimisation at the Traffic Control Centre (Appendix 1, p. A1-75). For IS-03, JICA notes that the next junction west is very close, so optimal operation matters (p. A1-75).

### Limits

- One intersection, no coordination with neighbouring signals, no pedestrians.
- Turning shares are the 16-hour average and don't change through the day.
- The vehicle mix is the city-wide average of JICA's roadside stations, because no station sits on Monivong or Charles de Gaulle.
- The signal phasing and the fixed plan are modelled, not IS-03's actual plan.

## Step 3: adaptive signals (SmartFlow)

`adaptive.py` runs the same day as `fixed.sumocfg`, with the same network, traffic and random seed, but sets the light itself through TraCI (SUMO's Python remote control).

### The rule

For each approach in turn:
1. When its light turns green, SmartFlow notes every vehicle standing still on it. That's the queue.
2. The light stays green until all of those vehicles have crossed the stop line and nothing on the approach is standing still, so vehicles that join the back of the queue go too.
3. Every green lasts at least 10 s and at most 50 s.

**Safety:** SmartFlow only decides when the current green ends. The order (East → South → West → North) and the 3 s yellow and 2 s all-red after every green are in the signal program, and it never changes them. With the 50 s cap, no approach waits more than 3 × 50 + 4 × 5 = 170 s for its next green.

In a real junction the queue would come from a camera or detectors at each stop line. SUMO measures it perfectly, so a real system would do somewhat worse.

### Run it

```bash
.venv/bin/python adaptive.py
```

It takes about 4 minutes. First it prints the average green SmartFlow gave each approach, hour by hour:

```
hour       CdG East  Monivong S    CdG West  Monivong N   cycle
06:00            11          17          14          11      73
07:00            17          36          30          20     123
...
12:00            15          20          17          17      89
...
17:00            31          41          39          40     171
...
21:00            10          11          11          10      62
```

Then SUMO's summary, with exact numbers because the seed is fixed:

```
 Inserted: 97539
 Running: 0
 Waiting: 0
 Teleports: 0 (Collisions: 452)
 ...
 TimeLoss: 47.44
 DepartDelay: 0.26
```

The hourly table is the timing plan SmartFlow arrives at from the traffic alone. In the morning the inbound roads (Monivong South, Charles de Gaulle West) get the long greens. In the evening the outbound ones (Monivong North, Charles de Gaulle East) catch up and the cycle stretches to 171 s. At night every green drops to the minimum and the cycle to about 62 s. The fixed plan uses 140 s all day.

It also writes `out/adaptive_greens.csv`, one row per green: start time, approach, queue, green length, and whether the green ended because the queue cleared (2,547 times over the day) or because it reached 50 s (23 times). Greens that stop at the minimum show 10.5 s, because SUMO switches at the next half-second step.

### Compare with fixed-time

```bash
.venv/bin/python summarize.py out/fixed_tripinfo.xml out/adaptive_tripinfo.xml
```

```
Average delay per vehicle in seconds, by hour of arrival: fixed → adaptive
hour      Monivong N     CdG East   Monivong S     CdG West          all
06:00      51 →   34    61 →   34    54 →   34    56 →   38    55 →   35
07:00      58 →   61    66 →   61   184 →   57   130 →   63   131 →   59
08:00      57 →   51    65 →   52    77 →   49    72 →   51    69 →   50
09:00      57 →   42    70 →   41    56 →   42    62 →   43    60 →   42
10:00      60 →   42    90 →   43    58 →   40    55 →   44    63 →   42
11:00      63 →   45    84 →   47    56 →   45    60 →   48    63 →   46
12:00      58 →   45    71 →   41    54 →   43    59 →   44    59 →   43
13:00      62 →   46    69 →   49    58 →   45    65 →   49    62 →   47
14:00      61 →   45    66 →   44    55 →   42    65 →   47    61 →   44
15:00      58 →   46    74 →   50    59 →   44    58 →   48    61 →   47
16:00      61 →   46    73 →   49    57 →   47    58 →   51    61 →   48
17:00     107 →   84   119 →   83    67 →   81    77 →   88    89 →   84
18:00      69 →   48    98 →   50    57 →   50    60 →   53    69 →   50
19:00      58 →   36    71 →   38    50 →   37    53 →   38    57 →   37
20:00      51 →   28    58 →   28    52 →   30    52 →   31    52 →   29
21:00      53 →   27    56 →   27    46 →   27    51 →   28    51 →   27
Whole day: fixed 68.7 s → adaptive 47.7 s average delay per vehicle (-31%), 97,539 vehicles, 568 vehicle-hours of waiting saved
```

What it shows:
- Over the whole day, average delay falls from 68.7 s to 47.7 s per vehicle (31% less). That adds up to 568 vehicle-hours of waiting saved per day at this one junction.
- The biggest gain is the morning peak: at 07:00, 131 s → 59 s, mostly because Monivong South no longer queues for three minutes (184 s → 57 s).
- Through the rest of the day SmartFlow is 21–47% better, most of all at night, when short cycles mean nobody waits long (21:00: 51 s → 27 s).
- The smallest gain is at 17:00 (89 s → 84 s), when the junction is closest to capacity. SmartFlow then favours the outbound roads. Monivong North and Charles de Gaulle East improve (107 → 84 s, 119 → 83 s), while Monivong South and Charles de Gaulle West wait longer than with fixed-time (67 → 81 s, 77 → 88 s). With Monivong North at 07:00 (58 → 61 s), those are the only approach-hours where fixed-time does better.

**Is the fixed plan a fair opponent?** I kept its split and tried other cycle lengths over the whole day: 120 s gives 69.5 s and 100 s gives 91.5 s, against 68.7 s for the 140 s plan. So the step 2 plan is the best of the three. Fixed-time doesn't lose because its timing is careless. It loses because one plan can't suit both peaks and the night.

**Does it hold on another day?** I re-ran both with a different random seed, which gives different random arrivals at the same hourly rates. Fixed-time averaged 72.3 s and SmartFlow 49.8 s, again 31% less (608 vehicle-hours saved). Single hours move much more between seeds: 17:00 was 89 → 84 s with seed 42 but 110 → 91 s with seed 7. So quote the whole-day figure, not a single hour.

### How I chose the rule

Worth knowing if a judge asks why this rule:
- **A formula for each green** (queue ÷ discharge rate) halved the morning delay, but left-turners got left behind. They queue in fewer lanes, so their part of the queue clears last.
- **Ending the green when the flow over the stop line drops** (the idea behind the UK's MOVA system) ended many greens with dozens of vehicles still waiting in the left-turn lane.
- **Waiting until every queued vehicle has crossed** worked best. The cap matters: with 60 s the evening cycle grew to about 200 s and 17:00 got worse than fixed-time. Over a whole day, 50 s did best: 47.7 s average delay, against 48.3 s with 40 s, 48.4 s with 45 s and 49.6 s with 60 s.
- Testing also showed that the single left-turn lane was a bottleneck for both controllers, which is why the network changed (see "Why two left-turn lanes" in step 2).

### Watch it (for the video)

```bash
.venv/bin/python adaptive.py --gui -b 24300
```

Press ▶ in sumo-gui. The terminal prints each green as it ends, for example:

```
07:06:20  Monivong S  queue 108 vehicles  ->  green   41 s (queue cleared)
07:07:06  CdG West    queue  53 vehicles  ->  green   36 s (queue cleared)
```

Record the terminal next to the sumo-gui window, so viewers see each decision and the traffic together. To show the timings changing, right-click the traffic light (the coloured bars across a stop line) and choose **Track Phases**. It draws each phase as a bar, so SmartFlow's greens grow and shrink, while the fixed run (the step 2 command) repeats the same bars every cycle. `out/step2_gui_0713.png` (fixed) and `out/step3_gui_0713.png` (SmartFlow) show each run at 07:13.

### Limits

- SUMO sees the queue perfectly. A real camera or detector misses some vehicles, so real-world gains would be smaller.
- SmartFlow reacts to the queue in front of it and doesn't look ahead. Step 5 adds prediction.
- The rule's two numbers (10 s and 50 s) were tuned on this one simulated day. Step 4's rain and holiday scenarios test it on traffic it wasn't tuned on.

## Step 4: weather, holidays and what-if scenarios

Everything in this step that changes traffic is **simulated**. JICA counted one normal weekday, and nobody has counted IS-03 in the rain or on a holiday. The weather and the holiday dates are real data; how traffic reacts to them is modelled. SmartFlow itself doesn't use the weather or the calendar, it only sees queues. The weather and holiday data feed the scenarios now and the prediction model in step 5.

### Weather now (Open-Meteo)

```bash
.venv/bin/python weather.py
```

You should see the weather at the junction now, then the rain expected in each hour of today (your numbers will differ):

```
IS-03 at 2026-11-22 00:30: 26.7 °C, overcast, rain 0.0 mm in the last 15 min (dry)
Rain today, mm per hour (chance):
  06:00 0.0 (0%)  07:00 0.0 (0%)  08:00 0.0 (0%) ...
```

[Open-Meteo](https://open-meteo.com/en/docs) is free and needs no key. Its numbers come from weather models, not from a rain gauge at the junction.

### Rain history

```bash
.venv/bin/python weather.py --history 2022 2025
```

It downloads hourly rain for 2022–2025 from Open-Meteo's [historical archive](https://open-meteo.com/en/docs/historical-weather-api) (the ERA5 reanalysis) into `data/openmeteo/rain_hourly_2022-2025.csv`, 35,064 hours, and prints:

```
Share of hours with rain (0.5 mm or more), by month:
    J    F    M    A    M    J    J    A    S    O    N    D
   1%   1%   2%   5%  12%  10%  13%  12%  18%  18%   9%   2%
Rainy season (May-October), share of hours with rain by hour of day:
  ...  14:00 35%  15:00 42%  16:00 37%  17:00 28% ...
Wettest days between 06:00 and 22:00 (use one with: scenario.py --rain-day DATE):
  2023-09-21   42.7 mm, rain 11:00-22:00, wettest hour 16:00 (26.0 mm)
  ...
```

For the slides: in the rainy season, Phnom Penh's rain falls mostly in the afternoon, peaking at 15:00, just before the evening rush hour. September and October are the wettest months.

### Holidays

```bash
.venv/bin/python holidays_kh.py
```

```
2026-11-22 (Sunday): not a public holiday. Traffic pattern: normal
Next holidays:
  2026-11-23 (Mon)  Water Festival (day 1)
  ...
```

Add a date to check another day: `.venv/bin/python holidays_kh.py 2026-10-09` says `exodus` (the day before Pchum Ben). The 2026 holidays are in `data/cambodia_holidays_2026.csv`, from Sub-Decree No. 167 of 18 September 2025 as published by [Andersen Cambodia](https://kh.andersen.com/publications/cambodia-sets-official-2026-public-holiday-schedule/). The Water Festival runs 23–25 November, so it ends on the day the application is due.

### Make a scenario (the manual controls)

```bash
.venv/bin/python scenario.py --rain heavy --hours 17-19
```

| Option | What it does |
|---|---|
| `--rain light`, `moderate` or `heavy`, with `--hours 17-19` | rain of that strength from 17:00 to 19:00 |
| `--rain-day 2023-09-21` | the real rain of a past day, hour by hour, from the Open-Meteo archive |
| `--holiday exodus`, `festival` or `quiet` | a holiday traffic pattern (below) |
| `--live` | today's weather from Open-Meteo and today's holiday pattern |

Options combine, e.g. `--rain heavy --hours 17-19 --holiday festival`. Each scenario is written to `routes/NAME.rou.xml`, plus `routes/NAME.json` with the rain and the holiday hour by hour, and the script prints the commands that run it. You should see, for example:

```
SIMULATED scenario: rain_heavy_17-19
Rain:    17:00 heavy (15.0 mm), 18:00 heavy (15.0 mm)
Holiday: none
Wrote routes/rain_heavy_17-19.rou.xml (97,463 vehicles; the normal day has 97,463) and routes/rain_heavy_17-19.json
```

**How rain works.** Rain changes how people drive, not how many travel. No study we found measures how rain changes the number of trips in a motorbike city, so we don't guess one. Vehicles that set off in a rainy hour drive slower, react later, accelerate more gently and keep bigger gaps. These settings were tuned in SUMO, with the same overload test as the discharge rates in step 2 (3 random seeds each). They were adjusted until each approach moved about as many fewer vehicles per hour of green as studies of rain at signalised intersections measured:

| Rain | mm per hour | Speed | Reaction time | Acceleration | Gap | Fewer vehicles per hour of green, SUMO | Studies |
|---|---|---|---|---|---|---|---|
| light | 0.5–2.5 | −5% | +0.12 s | −10% | +0.2 m | 7% | 7% |
| moderate | 2.5–10 | −10% | +0.30 s | −20% | +0.4 m | 14% | 14–17% |
| heavy | 10 or more | −15% | +0.45 s | −25% | +0.5 m | 21% | 19–21% |

The studies: capacity at signalised intersections fell 7.4%, 14.3% and 19.2% in light, moderate and heavy rain ([Bentham, Open Transportation Journal vol. 14](https://benthamopen.com/ABSTRACT/TOTJ-14-214)). Saturation flow in Seoul fell 7%, 17% and 21% ([Kim, Roh and Son, 2015](https://koreascience.kr/article/JAKO201509364589136.page)). Free-flow speed was about 9% lower in rain ([Demetsky and Tantillo](https://swov.nl/en/publicatie/investigating-impacts-rainy-weather-isolated-signalized-intersections)).

**How holidays work.** No counts exist, so these are assumptions, chosen to show the kind of surge each holiday brings:

| Pattern | When | Assumed change |
|---|---|---|
| exodus | the day before Khmer New Year or Pchum Ben | traffic leaving the centre (Monivong North, CdG East) ×1.5 from 12:00 to 21:00, as people head to their provinces |
| festival | Water Festival days | traffic heading to the centre and riverside (Monivong South, CdG West) ×1.4 from 15:00 to 22:00 |
| quiet | other holidays | all traffic ×0.7 |

### Compare fixed-time and SmartFlow on a scenario

```bash
.venv/bin/python compare.py rain_heavy_17-19
```

It runs both at once (about 5 minutes; logs in `out/NAME_fixed.log` and `out/NAME_adaptive.log`) and prints the same delay table as step 3. Results for four scenarios, all simulated, average delay per vehicle over the day:

| Day | Fixed-time | SmartFlow | Change | 18:00 hour, fixed → SmartFlow |
|---|---|---|---|---|
| Normal day (step 3) | 68.7 s | 47.7 s | −31% | 69 → 50 s |
| Heavy rain 17:00–19:00 | 152.0 s | 108.4 s | −29% | 600 → 574 s |
| Real rain of 21 Sep 2023 | 126.1 s | 77.1 s | −39% | 386 → 160 s |
| Water Festival | 204.3 s | 109.0 s | −47% | 807 → 447 s |
| Exodus (eve of Khmer New Year or Pchum Ben) | 896.7 s | 152.0 s | −83% | 1,798 → 566 s |

What this shows:
- **SmartFlow helps more when traffic changes in ways a fixed plan can't follow:** 31% on a normal day, 39% on the real rainy day, 47% on the festival day. The exception is when the junction is over capacity (next point).
- **When the junction is over capacity, no timing keeps up.** Heavy rain at 17:00 removes a fifth of the junction's capacity when the evening rush already needs 79% of the time as green. Both controllers then build queues with 5–10 minute waits. SmartFlow mainly helps by clearing the backlog faster afterwards (19:00: 540 → 129 s).
- **SmartFlow's weak spot shows here.** When every road has a long queue, every green reaches the 50 s limit, so all roads get equal time whatever their traffic. In heavy rain, Monivong South then waits longer than with fixed-time (18:00: 114 → 699 s). Step 5's forecast shares the time by expected traffic, which cuts this day's delay by a further 24%.
- **The exodus result is extreme, so don't headline it.** Our assumed +50% surge of traffic leaving the centre lasts 9 hours and overloads the fixed plan's short greens for Monivong North and CdG East. Queues grow all afternoon, and when the run ends at 22:05 about 1,900 vehicles are still waiting to enter (so the fixed-time average even leaves out the worst cases). SmartFlow gives those roads longer greens and copes. But the −83% depends entirely on a guessed surge, and in reality traffic police would step in.

### Watch a scenario (video, 50–75 s)

```bash
.venv/bin/python adaptive.py --gui --scenario rain_heavy_17-19 -b 60300
```

And fixed-time on the same day:

```bash
.venv/bin/sumo-gui -c fixed.sumocfg --route-files routes/rain_heavy_17-19.rou.xml --gui-settings-file view.xml -b 60300
```

Press ▶. The run starts at 16:45 and the rain at 17:00 (61200 on the clock). Vehicles move off more slowly and the queues build. Show "SIMULATED heavy rain" on screen. For the holiday segment, use `holiday_festival` with `-b 53100` (14:45).

### Limits

- Rain only changes driving. Real downpours can also flood streets and make riders stop to shelter, and neither is modelled.
- The holiday factors are guesses, and the base day is a weekday. Holidays and weekends have their own daily rhythm.
- Open-Meteo gives model data on a 10–25 km grid, not a gauge at the junction. The history (ERA5) smooths short storms, so real downpours are heavier and shorter than it shows.
- A vehicle keeps the driving of the hour it set off in for its whole trip, about 2 minutes.
- The holiday calendar only covers 2026.

## Step 5: a forecast that changes the lights

Every 5 minutes, a Random Forest (scikit-learn) forecasts how many vehicles will arrive on each road in the next 15 minutes. SmartFlow then shares out its maximum green by that forecast, so the roads expected to be busiest can keep their green longer. Like step 4, everything here is **simulated**: the forecast learns from simulated days and is tested on simulated days.

### What the forecast sees

| Input | At a real junction, it would come from |
|---|---|
| time of day | the clock |
| which road, its queue, and the queues on all four roads | a camera at the junction |
| vehicles that arrived on the road in the last 15 minutes | a counter where the road starts, 300 m before the junction |
| rain this hour | Open-Meteo (step 4) |
| holiday pattern | the 2026 calendar (step 4) |

It answers one question per road: how many vehicles will arrive in the next 15 minutes?

### Training and test days

```bash
.venv/bin/python days.py
```

It builds 20 simulated days and runs SmartFlow on each, recording arrivals and queues every 5 minutes in `out/days/NAME_adaptive_ticks.csv`. It takes about 75 minutes (8 simulations at a time). Runs that already have results are skipped, so you can stop it and run it again.
- **15 training days:** 3 normal days, 6 days with the real rain of rainy-season days from 2022–2024 (picked at random from the Open-Meteo archive), and 6 holiday days (exodus, festival and quiet, each once dry and once with real rain). Each training day has its own random seed, so no two have the same traffic.
- **5 test days, never seen while learning:** a normal day, the real rain of 10 August 2025, heavy rain 17:00–19:00, the Water Festival and the exodus. They use seed 42, like steps 3 and 4.

It also runs fixed-time on the test days. You should see each simulation as it finishes, then:

```
Test days, average delay per vehicle (simulated):
day                               fixed-time  SmartFlow  + forecast
test1_normal                          68.7 s     47.7 s           -
test2_rain_2025-08-10                 83.4 s     54.2 s           -
test3_rain_heavy_17-19               152.0 s    108.4 s           -
test4_festival                       204.3 s    109.0 s           -
test5_exodus                         896.7 s    152.0 s           -
```

The normal, heavy-rain, festival and exodus days match steps 3 and 4 exactly, which shows nothing changed in the simulation.

### Train and test the forecast

```bash
.venv/bin/python forecast.py
```

About 15 seconds. It saves the model to `models/demand_rf.joblib` and compares its errors with two simple guesses: "the next 15 minutes will be like the last 15" and "JICA's normal-day average for this time":

```
Trained a Random Forest on 15 simulated days (11,220 rows of 15-minute arrivals); saved models/demand_rf.joblib

Test days (never seen in training): average error of the 15-minute arrival forecast, vehicles per approach
day                               Random Forest  last 15 min  JICA average   arrivals
test1_normal                               17.0         28.6          16.4      383 on average
test2_rain_2025-08-10                      17.1         28.6          16.4      383 on average
test3_rain_heavy_17-19                     19.2         29.3          18.3      383 on average
test4_festival                             24.0         34.2          46.0      418 on average
test5_exodus                               23.0         34.5          62.6      435 on average
all test days                              20.1         31.0          31.9

What the forecast relies on (Random Forest feature importance):
  arrived, last 15 min      93.1%
  time of day                4.9%
  ...
```

What this shows:
- **Over all test days, the forecast is 35% more accurate than either simple guess** (20 vehicles off per 15 minutes, against 31 and 32).
- **On normal and rainy days, it is about as good as JICA's average** (17 against 16). On those days, JICA's average is almost exactly the rate the simulation draws its traffic from, so it can hardly be beaten. About 383 vehicles arriving at random vary by about ±16 on their own.
- **On holidays, it is 2–3 times more accurate than JICA's average**, which doesn't know about the surge.
- **"Like the last 15 minutes" is worst on normal days.** It always lags behind the daily rhythm, e.g. 51 vehicles off during the 07:00 rush.
- **The forecast relies mostly on the live counts.** We also retrained it without each input. Without the holiday calendar it is hardly worse (24.4 instead of 24.0 on the festival day), because a surge shows in the counts within 15 minutes. Without the counts it is slightly better on most of our test days, because simulated traffic follows its assumed pattern exactly. Real traffic varies from day to day, so we keep the counts.

### SmartFlow with the forecast

```bash
.venv/bin/python days.py --predict
```

About 20 minutes. In step 3, every road's green could last at most 50 s, which is 200 s per cycle. With the forecast, every 5 minutes those 200 s are shared by each road's forecast divided by how fast it discharges (its saturation flow, step 2), between 10 and 80 s per road. The step 3 rule still ends each green as soon as its queue has cleared. So the forecast only matters when greens reach their maximum, which happens when queues are long. The 200 s and the 10–80 s limits were set before the test and not tuned. You should see:

| Test day (simulated) | Fixed-time | SmartFlow | SmartFlow + forecast | Forecast's effect |
|---|---|---|---|---|
| Normal day | 68.7 s | 47.7 s | 48.4 s | none (+0.7 s) |
| Real rain of 10 Aug 2025 | 83.4 s | 54.2 s | 52.7 s | −3% |
| Heavy rain 17:00–19:00 | 152.0 s | 108.4 s | 82.6 s | −24% |
| Water Festival | 204.3 s | 109.0 s | 100.0 s | −8% |
| Exodus | 896.7 s | 152.0 s | 112.2 s | −26% |

No vehicles were left waiting to enter at the end of any SmartFlow run, and none teleported. Compare any day hour by hour with `.venv/bin/python summarize.py out/days/test3_rain_heavy_17-19_adaptive_tripinfo.xml out/days/test3_rain_heavy_17-19_predict_tripinfo.xml`.

What this shows:
- **The forecast fixes step 4's weak spot.** In heavy rain, SmartFlow alone gave the three busy roads the same 50 s each. From 17:00 to 19:00, the forecast cut CdG East's greens (41 s on average instead of 46 s) and lengthened Monivong North's and South's (54 and 53 s instead of 50 s), while the cycles stayed the same length. Delay for vehicles arriving at 18:00 fell from 574 to 341 s, and Monivong South's from 699 to 436 s. CdG East paid for it (102 → 228 s).
- **On the exodus day, Monivong North gets the extra time.** Its 19:00 delay fell from 1,025 to 210 s.
- **On a normal day, it changes nothing**, as expected. Queues are short, so greens end when the queue clears, long before the maximum.
- **On the festival day, the gain is small (−8%)**, and Monivong South still has 15-minute delays at 18:00 (892 → 902 s). There are two reasons:
  1. Its queue reaches back past the counter at the start of the road, so the counter only sees what the queue lets through. At 17:00 it counted about 255 vehicles per 5 minutes while about 313 were coming. So the forecast underestimates the very road that needs help most.
  2. The green is shared by expected arrivals, not by vehicles already waiting. Monivong South (about 300 waiting) and CdG West (almost none) got about the same maximum, 53–63 s.

  A next version would share the green by queue + forecast, and count vehicles further upstream.

### Watch it (video, 50–65 s)

```bash
.venv/bin/python adaptive.py --gui --predict --scenario days/test3_rain_heavy_17-19 -b 60300
```

Press ▶. The run starts at 16:45. The forecast needs 15 minutes of counts, so from 17:00, when the rain starts, the terminal prints a forecast every 5 minutes between the greens. Here is the full-day run's at 17:00 (yours will differ a little, because the junction starts empty at 16:45):

```
17:00:00  forecast, next 15 min: CdG East 323 vehicles (max green 40 s), Monivong S 641 vehicles (max green 56 s), CdG West 404 vehicles (max green 52 s), Monivong N 554 vehicles (max green 52 s)
17:00:30  CdG East    queue  21 vehicles  ->  green   12 s (queue cleared)
```

Leave out `--predict` to watch SmartFlow without the forecast on the same day. Runs with `--gui` write their files as `out/..._partial_*`, so watching never replaces the whole-day results. Every 5-minute forecast and maximum green from the whole-day runs is in `out/days/NAME_predict_ticks.csv`, for the step 6 website.

### Limits

- The forecast learns from simulated days built from one JICA weekday and our rain and holiday models, so it learns those assumptions back. A real SmartFlow would learn from the junction's own camera counts, over months.
- Every simulated day follows the JICA pattern exactly, apart from rain and holidays. Real traffic varies from day to day, which would make the live counts more useful than they look here.
- The counter undercounts when a queue reaches back past it, as on the festival day.
- 15 training days is little: only 2 of each holiday pattern.
- The forecast is used only to share the maximum green. It doesn't change the phase order or warn of trouble ahead.

## Step 6: the website

One website with two pages for the five step 5 test days: the **live junction**, where you watch the simulation itself, and the **statistics** of each day. It replays simulations and isn't connected to a real junction. Only the weather and the holiday calendar on the Statistics page are live.

```bash
.venv/bin/python live.py
```

Then open http://localhost:8600 in your browser. The links in the header switch between **Live junction** and **Statistics** and keep the same day and time. Ctrl+C in the terminal stops it. If port 8600 is taken, for example by a `live.py` still running in another terminal, it says so: use the one already running, stop it with Ctrl+C, or start this one with `--port 8601`.

### Live junction (the main page)

Choose a day and a start time (each day suggests one), tick or untick **AI forecast**, and press **Start**. It first simulates the 15 minutes before your start time without showing them (10–20 seconds), so the queues are already there. Then two SUMO simulations run side by side on the same traffic: fixed-time on the left, SmartFlow on the right. You can pause, change the speed (5× to 50×), scroll to zoom, drag to move and double-click to reset the view. An address like http://localhost:8600/?day=test3_rain_heavy_17-19&start=17:00 opens a day and start time directly.

What you should see on **Heavy rain 17:00-19:00** from **17:00**: rain over both junctions and "Rain this hour: 15.0 mm (simulated)". Under each junction are the vehicles waiting now, the average delay of the vehicles that have crossed since Start, the current green, each road's light, queue and green time, and the latest greens. On the left the greens repeat the plan (23, 30, 32 and 35 s). On the right they change with the queues and end with "queue cleared", and the forecast column shows the next 15 minutes for each road.

Both junctions fill up while it rains, the right one less (at 18:00, 699 vehicles waiting on the left and 544 on the right). The big difference comes when the rain stops at 19:00. The right junction has cleared its queues by 19:15 (27 vehicles waiting), while the left one still has 496. By 19:30 the average delay since 17:00 is 371 s on the left and 238 s on the right. These numbers come from running the live view's own code from 17:00 to 19:30 without the browser.

- The right junction runs the same `SmartFlow` class as `adaptive.py`. The rule moved into that class for the live view. Re-running the normal day and the heavy-rain day with the forecast afterwards gave byte-identical results.
- Start before the busy period. Each run only simulates the 15 minutes before its start, so a start in the middle of a jam begins with shorter queues than the whole-day run has at that time.
- "Average delay" here is the time lost by the vehicles that have left since you pressed Start. The Statistics page also counts the time spent waiting to enter the road, so its numbers are a little higher.
- At 50× it runs as fast as the computer can, about 25× in the heavy-rain jam.

### Statistics

The whole-day runs of step 5, at http://localhost:8600/stats. An address like http://localhost:8600/stats?day=test3_rain_heavy_17-19&time=18:00 opens a day and time directly. Choose **Heavy rain 17:00-19:00** and move the time to **18:00**:

- **Tiles for the whole day:** fixed-time 152.0 s, SmartFlow 108.4 s (−29% vs fixed-time), SmartFlow + forecast 82.6 s (−24% vs SmartFlow), and 1,879 vehicle-hours of waiting saved.
- **Delay hour by hour:** the three lines climb together from 17:00, and SmartFlow + forecast (orange) peaks lowest. Hover over the chart to read the numbers. The dark vertical line is the time you chose.
- **At 18:00:** rain 15.0 mm (heavy), holiday pattern none, and SmartFlow's latest cycle 219 s.
  - *Measured and forecast:* Monivong N has 288 vehicles queuing, and the forecast expects 511 more in the next 15 minutes (508 came).
  - *Signal timings:* the new forecast gives CdG East, the quietest road, 41 s of maximum green. Monivong S and N get 51 s each and CdG West 58 s. The fixed-time plan's greens are 23 to 35 s.
- **Forecast vs counted arrivals:** on Monivong S, the two lines follow each other all day.
- **Live inputs, today** (on the right): Open-Meteo's weather at IS-03 now and today's holiday status from the 2026 calendar. These are real, live data.

The page reads each day's averages from `out/summary/DAY.json`. `live.py` makes those small files from SUMO's trip files the first time, and again whenever the trip files change, so the website works without the 1.9 GB of trip files.

### For the video (75–90 s)

Record the browser window at least 1280 px wide, so the tiles aren't cut off. A possible order on the Statistics page:

1. The heavy rain day at 18:00: the tiles, then the delay chart. Say that the day is simulated.
2. Scroll to the signal timings: the forecast gives the busy roads more green than the quiet one.
3. Switch to Water Festival or Holiday exodus to show the holiday patterns.
4. Point at the live inputs: the weather and calendar are real and work today.

Don't headline the exodus figures. Fixed-time collapses on that day, so its numbers are extreme.

### Share it with teammates

The project is on GitHub: https://github.com/KazooMinions/smartflow. Teammates clone it and follow "Quick start" at the top of this README, then `git pull` for updates. The repository leaves out what is big and can be made again (see `.gitignore`): `.venv` (the setup makes it), SUMO's trip files (1.9 GB, made by steps 2 to 5) and the JICA PDFs (55 MB, linked under "Sources" in step 2).

For someone without git, `share.py` packs the same files into `smartflow.zip`, next to the project folder:

```bash
.venv/bin/python share.py
```

### The website on GitHub Pages

https://kazoominions.github.io/smartflow/ is a copy of the website in `docs/`, which GitHub Pages serves from the `main` branch. GitHub Pages only serves files, so it can't run SUMO:

- **Live junction:** it plays back recordings of the same two simulations: fixed-time, and SmartFlow with its forecast on. Each day is recorded for 90 minutes from its start time on the live page, and the heavy-rain day from 17:00 to 19:30, so that the jam and its end are both in it. The browser draws a picture every 2 simulated seconds and glides between them. Start, Pause, Speed, zoom and the numbers all work as on the computer, but only within the recorded times, and only with the forecast on.
- **Statistics:** the same numbers, read from files.
- **Live inputs:** the visitor's browser asks Open-Meteo for the weather itself, and reads the 2026 holiday calendar from a file.

`web/pages.js` plays the recordings and answers the requests that `live.py` answers on a computer. `build_site.py` makes `docs/`:

```bash
.venv/bin/python build_site.py
```

It copies the pages and the data. It also records any day that has no recording yet: 2 to 6 MB each, 19 MB for all five, which take about 20 minutes to record with the days running side by side. After changing `web/` or the results, run it again (with `--record` to record every day again), then commit and push `docs/`. GitHub Pages updates within a minute or two.

### Limits

- It replays simulated days. There are no cameras or counters at the junction, so the live weather and calendar aren't connected to a live forecast.
- It shows only the five test days, which are the days with fixed-time, SmartFlow and SmartFlow + forecast runs.
- On the exodus day, 2,571 vehicles are still queuing when the fixed-time run stops at 22:05 (`fixed.sumocfg` ends there). They are left out of its average, so fixed-time's real delay was even higher. The page notes this.
