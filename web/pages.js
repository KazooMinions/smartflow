// SmartFlow on GitHub Pages: the stand-in for live.py.
//
// GitHub Pages only serves files, so the copy of the website in docs/ can't run SUMO. build_site.py loads this
// file into both pages there (the pages that live.py serves never load it), and it answers what they would ask
// live.py:
//   - the live junction plays back recordings of the same two simulations, made by build_site.py: fixed-time and
//     SmartFlow with its forecast, one picture every 2 simulated seconds (docs/replays/DAY.json.gz);
//   - the statistics are read from docs/data/, and the live inputs come straight from Open-Meteo.
(() => {
  const REPO = "https://github.com/KazooMinions/smartflow";
  const FRAME = 0.1;                                       // seconds between pictures, as in live.py
  const RUN = 10000;                                       // in a track, RUN + n = "stood still for n pictures"
  const ORDER = ["N_in", "E_in", "S_in", "W_in"];          // the order of the roads in the recordings
  const pad = n => String(Math.floor(n)).padStart(2, "0");
  const clock = t => `${pad(t / 3600)}:${pad(t % 3600 / 60)}:${pad(t % 60)}`;
  const seconds = s => Number(s.slice(0, 2)) * 3600 + Number(s.slice(3, 5)) * 60;

  const files = {};
  const json = path => files[path] ??= fetch(path)
    .then(r => { if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`); return r.json(); })
    .catch(e => { delete files[path]; throw e; });

  // ---- The statistics page: /api/days, /api/stats/DAY and /api/inputs ----

  async function api(path) {
    if (path === "days") return json("data/days.json");
    if (path.startsWith("stats/")) return json(`data/${path}.json`);
    if (path === "inputs") return inputs();
    throw new Error(`No such request: ${path}`);
  }

  async function inputs() {                                // as live_inputs() in live.py, but asked by the browser
    const info = await json("data/inputs.json");
    let weather;
    try {
      const q = new URLSearchParams({ latitude: info.lat, longitude: info.lon, timezone: info.tz, forecast_days: 1,
        current: "temperature_2m,precipitation,weather_code", hourly: "precipitation,precipitation_probability" });
      const r = await fetch(`https://api.open-meteo.com/v1/forecast?${q}`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = await r.json(), c = d.current, h = d.hourly;
      let today = 0;
      h.time.forEach((t, i) => { const hour = Number(t.slice(11, 13)); if (hour >= info.hours[0] && hour < info.hours[1]) today += h.precipitation[i] || 0; });
      weather = { time: c.time.slice(11), temperature_c: c.temperature_2m, rain_mm_15min: c.precipitation,
        sky: info.sky[c.weather_code] || `weather code ${c.weather_code}`, rain_today_mm: Math.round(today * 10) / 10 };
    } catch (e) {
      weather = { error: e.message || String(e) };
    }
    const cal = new Map(info.calendar.map(h => [h.date, h]));
    const next = d => { const [y, m, dd] = d.split("-").map(Number); return new Date(Date.UTC(y, m - 1, dd + 1)).toISOString().slice(0, 10); };
    const pattern = d => {                                 // as holidays_kh.traffic_pattern()
      const h = cal.get(d), t = cal.get(next(d));
      if (h) return h.kind === "water_festival" ? "festival" : "quiet";
      if (t && (t.kind === "new_year" || t.kind === "pchum_ben")) return "exodus";
      return null;
    };
    const about = d => ({ date: d, name: cal.get(d)?.name ?? null, pattern: pattern(d) });
    const today = new Date().toLocaleDateString("en-CA", { timeZone: info.tz });   // YYYY-MM-DD in Phnom Penh
    const upcoming = [...cal.keys()].sort().find(d => d > today);
    return { weather, today: about(today), next: upcoming ? about(upcoming) : null };
  }

  // ---- The live junction: plays a recording, speaking the same messages as live.py's /ws ----

  function replay() {
    const sock = { readyState: 1, onmessage: null, onclose: null, close() {}, send: m => command(JSON.parse(m)) };
    const emit = m => sock.onmessage && sock.onmessage({ data: JSON.stringify(m) });
    let days = [], rec = null, loaded = { day: null, promise: null }, t = 0, base = 0, playing = false, speed = 10, ticket = 0;

    Promise.all([json("data/days.json"), json("data/network.json")]).then(([d, net]) => {
      days = d;
      emit({ type: "hello", days, net });
      notes();
    }, e => emit({ type: "status", text: `The website's data could not be loaded (${e.message}). Reload the page to try again.` }));
    setInterval(tick, FRAME * 1000);
    return sock;

    async function command(m) {
      if (m.cmd === "start") {
        const mine = ++ticket;                             // a later Start wins over one still loading
        playing = false;
        speed = Number(document.getElementById("speed")?.value) || speed;
        emit({ type: "status", text: "Loading the recording…" });
        try {
          const r = await load(m.day);
          if (mine !== ticket) return;
          rec = r;
        } catch (e) {
          if (mine === ticket) emit({ type: "status", text: `The recording could not be loaded (${e.message}). Press Start to try again.` });
          return;
        }
        t = Math.min(rec.end, Math.max(rec.start, seconds(m.start)));
        base = picture(t);
        for (const s of rec.sides) s.at = Infinity;        // find the vehicles in the picture again
        playing = true;
        emit({ type: "ready" });
        emit(frame(t));
      } else if (m.cmd === "play") playing = !!rec && t < rec.end;
      else if (m.cmd === "pause") playing = false;
      else if (m.cmd === "speed") speed = Math.max(1, Math.min(100, Number(m.value) || 10));
    }

    function tick() {
      if (!playing || !rec) return;
      t = Math.min(rec.end, t + speed * FRAME);
      emit(frame(t));
      if (t >= rec.end) {
        playing = false;
        emit({ type: "status", end: true, text: `The recording ends at ${clock(rec.end).slice(0, 5)}. To watch the rest of the day, run the website on a computer.` });
      }
    }

    function load(day) {                                   // keeps one recording in memory: they are large
      if (loaded.day !== day) {
        loaded = { day, promise: fetchRecording(day) };
        loaded.promise.catch(() => { if (loaded.day === day) loaded = { day: null, promise: null }; });
      }
      return loaded.promise;
    }

    async function fetchRecording(day) {
      const r = await fetch(`replays/${encodeURIComponent(day)}.json.gz`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      let bytes = new Uint8Array(await r.arrayBuffer());
      if (bytes[0] === 0x1f && bytes[1] === 0x8b) {        // still gzipped: most servers send .gz files as they are
        if (typeof DecompressionStream === "undefined") throw new Error("this browser is too old to unpack it");
        bytes = new Uint8Array(await new Response(new Blob([bytes]).stream().pipeThrough(new DecompressionStream("gzip"))).arrayBuffer());
      }
      return unpack(JSON.parse(new TextDecoder().decode(bytes)));
    }

    function unpack(raw) {                                 // tracks to positions, one per picture
      const out = { start: raw.start, step: raw.step, frames: raw.frames, end: raw.start + (raw.frames - 1) * raw.step, rain: raw.rain, sides: [] };
      for (const s of raw.sides) {
        let total = 0;
        for (const tr of s.tracks) total += tr[3];
        const X = new Int16Array(total), Y = new Int16Array(total), A = new Int16Array(total), info = new Int32Array(s.tracks.length * 5);
        let o = 0;
        s.tracks.forEach((tr, i) => {
          let [id, kind, first, n, x, y, a] = tr;
          info.set([id, kind, first, n, o], i * 5);
          X[o] = x; Y[o] = y; A[o] = a; o++;
          for (let j = 7, k = 1; k < n;) {
            const v = tr[j++];
            if (v >= RUN) for (let r = v - RUN; r > 0; r--, k++, o++) { X[o] = x; Y[o] = y; A[o] = a; }
            else { x += v; y += tr[j++]; a += tr[j++]; X[o] = x; Y[o] = y; A[o] = a; o++; k++; }
          }
        });
        out.sides.push({ ...s, tracks: null, X, Y, A, info, count: s.tracks.length, active: [], next: 0, at: Infinity });
      }
      return out;
    }

    function picture(t) { return Math.min(rec.frames - 1, Math.max(0, Math.floor((t - rec.start) / rec.step + 1e-6))); }

    function frame(t) {
      const i = picture(t), u = Math.min(1, Math.max(0, (t - rec.start) / rec.step - i));
      return { type: "frame", t, clock: clock(t), rain_mm: rec.rain[Math.floor(t / 3600)] ?? 0, sides: rec.sides.map(s => side(s, i, u, t)) };
    }

    function side(s, i, u, t) {                            // what Junction.state() in live.py gives, at picture i (+ u)
      if (i < s.at) { s.active = []; s.next = 0; }         // went back: look through the tracks from the start
      while (s.next < s.count && s.info[s.next * 5 + 2] <= i) s.active.push(s.next++);
      s.active = s.active.filter(k => s.info[k * 5 + 2] + s.info[k * 5 + 3] > i);
      s.at = i;
      const veh = [];
      for (const k of s.active) {
        const b = k * 5, first = s.info[b + 2], o = s.info[b + 4] + i - first;
        let x = s.X[o], y = s.Y[o], a = s.A[o];
        if (u > 0 && i + 1 < first + s.info[b + 3]) { x += (s.X[o + 1] - x) * u; y += (s.Y[o + 1] - y) * u; a += (s.A[o + 1] - a) * u; }
        veh.push(s.info[b], Math.round(x) / 10, Math.round(y) / 10, Math.round((a % 360 + 360) % 360), s.info[b + 1]);
      }
      const queues = {}, limits = {}, g = latest(s.green, i), l = latest(s.limits, i), x = latest(s.expected, i);
      ORDER.forEach((a, k) => { queues[a] = s.queues[i * 4 + k]; limits[a] = l ? l[1 + k] : 0; });
      const done = s.done[i] - s.done[base], lost = s.lost[i] - s.lost[base];
      return {
        veh, signal: latest(s.signal, i)?.[1] ?? "", queues, waiting: ORDER.reduce((n, a) => n + queues[a], 0),
        done, delay: done ? Math.round(lost / done * 10) / 10 : null,
        green: g && g[1] >= 0 ? { approach: ORDER[g[1]], elapsed: Math.max(0, Math.round(t - g[2])), max: g[3] } : null,
        limits, expected: x && x.length > 1 ? Object.fromEntries(ORDER.map((a, k) => [a, x[1 + k]])) : null,
        log: recent(s.log, i),
      };
    }

    function latest(changes, i) {                          // the last change at or before picture i
      let lo = 0, hi = changes.length - 1, best = null;
      while (lo <= hi) { const mid = (lo + hi) >> 1; if (changes[mid][0] <= i) { best = changes[mid]; lo = mid + 1; } else hi = mid - 1; }
      return best;
    }

    function recent(log, i) {                              // the latest six greens, newest first
      let lo = 0, hi = log.length;
      while (lo < hi) { const mid = (lo + hi) >> 1; if (log[mid][0] <= i) lo = mid + 1; else hi = mid; }
      return log.slice(Math.max(0, lo - 6), lo).reverse().map(e => e.slice(1));
    }

    function notes() {                                     // say that this is a recording, and of what
      const box = document.getElementById("forecast");
      if (box) {
        box.checked = true;
        box.disabled = true;
        box.parentElement.title = "The recordings were made with SmartFlow's forecast on. To try it off, run the website on a computer.";
      }
      const badge = document.querySelector(".badge");
      if (badge) badge.textContent = "RECORDED FROM SUMO";
      const controls = document.querySelector(".controls"), select = document.getElementById("day");
      if (!controls || !select) return;
      const note = document.createElement("p");
      note.className = "info";
      note.style.color = "var(--ink)";
      controls.after(note);
      const show = () => {
        const d = days.find(d => d.id === select.value);
        note.innerHTML = `<span><b>This is a recording.</b> GitHub Pages can't run the simulation, so this copy of the website plays back ` +
          `the same two simulations, recorded with SmartFlow's forecast on${d ? `, here from ${d.start} to ${d.until}` : ""}. ` +
          `To run any day from any time, <a href="${REPO}#quick-start-run-the-website">run the website on a computer</a>.</span>`;
      };
      select.addEventListener("change", show);
      show();
    }
  }

  window.SmartFlowStatic = { api, replay };
})();
