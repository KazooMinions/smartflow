# SmartFlow: 90-second video script

About 205 words of narration, a calm 2.3 words a second. Record the narration on its own, then lay it over the screen clips in CapCut. Record each clip a few seconds longer than its slot, so you can trim.

Rain and holiday traffic must say **SIMULATED** on screen. Each clip below has its label. Put it in a corner for the whole clip.

Run the commands from `~/Documents/smartflow`. Start the website with `.venv/bin/python live.py`. The live junction is at http://localhost:8600 and the statistics at http://localhost:8600/stats.

## 0–10 s · The problem

- **Screen:** slide 2 of the deck ("Rush hour in Phnom Penh"), or a short clip of a busy junction you filmed yourself.
- **Text on screen:** City-centre traffic averaged 12.5 km/h (JICA, 2015)
- **Say:** "Phnom Penh's junctions jam every rush hour. A timing plan made in advance can't see today's queue, a sudden downpour, or a holiday rush."

## 10–20 s · Meet SmartFlow

- **Screen:** slide 3 ("Built on open data").
- **Say:** "Meet SmartFlow: traffic lights that adapt. It's built on open data: JICA's traffic counts, Open-Meteo weather and Cambodia's holiday calendar, tested in the SUMO traffic simulator."

## 20–35 s · Fixed-time signals

- **Screen:** the live view: **Normal weekday**, from **07:00**, speed **10×**, then press Start. Show the left junction (fixed-time plan): Monivong South's queue grows, and its list of greens repeats 23, 30, 32 and 35 s.
- **Text on screen:** Simulated: traffic from JICA's 2022 counts · fixed-time plan
- **Say:** "This is IS-03, Monivong and Charles de Gaulle, with traffic from JICA's counts. With a fixed plan, each road gets the same green, cycle after cycle. At 7 a.m., Monivong South waits about three minutes."

## 35–50 s · SmartFlow

- **Screen:** the same live view, now the right junction (SmartFlow). Its greens change length and end with "queue cleared", and it has fewer vehicles waiting and a lower average delay than the left one.
- **Text on screen:** Simulated: same traffic, side by side
- **Say:** "SmartFlow watches every queue and holds each green just until its queue has cleared. Over the whole day, the average delay falls from 68.7 to 47.7 seconds per vehicle: 31% less."

## 50–65 s · Heavy rain

- **Screen:** the live view: **Heavy rain 17:00-19:00**, from **17:00**, **AI forecast** ticked, speed **20×**. Rain falls over both junctions. On the right, the "Max green" and "Forecast, 15 min" columns show the forecast sharing out the green. The strongest moment to film is 18:45–19:15, just as the rain stops. The right junction empties (27 vehicles waiting at 19:15) while the left one stays jammed (496).
- **Text on screen:** SIMULATED heavy rain: 15 mm an hour, 17:00–19:00
- **Say:** "Now, simulated heavy rain. Drivers slow down and queues grow fast. Every five minutes, a Random Forest forecasts the next fifteen minutes of traffic and gives the busier roads more green. Delay drops another 24%."

## 65–75 s · Holiday

- **Screen:** the Statistics page on the Water Festival day: http://localhost:8600/stats?day=test4_festival&time=18:00
- **Text on screen:** SIMULATED Water Festival: assumed traffic pattern
- **Say:** "Holidays reshape traffic too. On a simulated Water Festival day, SmartFlow with the forecast halves the average delay, from 204 seconds to 100."

## 75–90 s · The statistics and what comes next

- **Screen:** the Statistics page on the heavy rain day, http://localhost:8600/stats?day=test3_rain_heavy_17-19&time=18:00. Show the tiles, scroll to the signal timings, then end on the deck's last slide ("Next: from one junction to the city").
- **Text on screen:** All results simulated in SUMO
- **Say:** "The statistics page puts it together: queues, forecasts, weather and signal timings. Next: a camera pilot at one junction, then a coordinated corridor along Monivong, and one day, the city's Traffic Control Centre."

## Recording tips

- **OBS:** a 1920×1080 canvas, with the browser full screen.
- **Live view:** press Start about 30 seconds before you record, so the numbers have settled. Scroll on a junction to zoom in so the vehicles are bigger, and drag to move. Pause freezes both sides for a still.
- **SUMO's own window** still works if you prefer it: `.venv/bin/python adaptive.py --gui -b 24300` (README step 3).
- **Statistics page:** make the browser window at least 1280 px wide. The address picks the day and time, so the links above open the right view.
- **CapCut:** auto-captions help judges who watch with the sound off.
- **Running long?** Cut "Drivers slow down and queues grow fast" at 50–65 s.

## Don't claim

- That SmartFlow runs on a real junction, or uses real camera data. Everything is simulated.
- That the forecast helps on a normal day. It doesn't (47.7 s → 48.4 s).
- The exodus day's −83%. Fixed-time collapses on that day, so the number is extreme.
- That Phnom Penh's lights are all fixed-time today. Since 2018, 109 signals are linked to a Traffic Control Centre (JICA 2023, p. 3-29).

## Numbers a judge might ask about

| Claim | Number | Where it comes from |
|---|---|---|
| Normal day, fixed-time → SmartFlow | 68.7 s → 47.7 s (−31%), 568 vehicle-hours a day | README step 3 |
| Same with another random seed | 72.3 s → 49.8 s (−31%) | README step 3 |
| Heavy rain, fixed-time → SmartFlow → + forecast | 152.0 s → 108.4 s → 82.6 s | README step 5 |
| Water Festival, fixed-time → + forecast | 204.3 s → 100.0 s | README step 5 |
| Forecast error, vehicles per road per 15 min | Random Forest 20.1, "same as the last 15 min" 31.0, JICA average 31.9 | README step 5 |
| City-centre speed, peak overload | 12.5 km/h, 1.37× capacity | JICA 2015, p. 4 |
