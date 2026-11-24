const $ = (id) => document.getElementById(id);
const tauri = window.__TAURI__;
const desktop = Boolean(tauri);
const pillPage = new URLSearchParams(location.search).has("pill");
const alarmPage = new URLSearchParams(location.search).has("alarm");
const quitPage = new URLSearchParams(location.search).has("quit");
const reminderPage = new URLSearchParams(location.search).has("reminder");
const currentWindow = tauri?.window.getCurrentWindow();
const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)");
const root = document.documentElement;
const dashboard = $("dashboard");
const floating = $("floating");
let demoSession = null;
let demoHistory = stored("rusted-history", []);
let snapshot = null;
let expanded = false;
let pinned = false;
let snapshotAt = 0;
let fillFrame;
let visibleProgress = 0;
let won = false;
let audio;
let nextClockTick = 0;
let pendingHandoff = false;

function stored(key, fallback) {
  try {
    return JSON.parse(localStorage.getItem(key)) ?? fallback;
  } catch {
    return fallback;
  }
}

function saveLocal(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch (error) {
    // File previews can run with browser storage disabled.
    console.warn(error);
  }
}

async function command(name, args) {
  if (desktop) return tauri.core.invoke(name, args);
  switch (name) {
    case "history": {
      const seen = new Set();
      let migrated = false;
      for (const record of demoHistory) {
        if (!record.id || seen.has(record.id)) {
          record.id = crypto.randomUUID();
          migrated = true;
        }
        seen.add(record.id);
      }
      if (migrated) saveLocal("rusted-history", demoHistory);
      return demoHistory;
    }
    case "delete_session":
    case "rename_session": {
      const index = demoHistory.findIndex(record => record.id === args.id);
      if (index < 0) throw Error("Session no longer exists.");
      if (name === "delete_session") demoHistory.splice(index, 1);
      else demoHistory[index].goal = args.goal;
      saveLocal("rusted-history", demoHistory);
      break;
    }
    case "begin": {
      const alphabet = "23456789abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ!@#$%&*?=";
      const code = Array.from(crypto.getRandomValues(new Uint8Array(26)), byte => alphabet[byte % alphabet.length]).join("");
      demoSession = { plan: args.plan, started: performance.now(), code };
      break;
    }
    case "quit_code": return demoSession?.code;
    case "snapshot": return demoSession && {
      plan: demoSession.plan, elapsedSeconds: (performance.now() - demoSession.started) / 1000,
    };
    case "finish": {
      const data = await command("snapshot");
      const record = { ...data.plan, id: crypto.randomUUID(), elapsedSeconds: data.elapsedSeconds, distractions: 0,
        completed: data.elapsedSeconds >= data.plan.minutes * 60,
        completedAt: Math.floor(Date.now() / 1000) };
      if (!record.completed && args?.code !== demoSession.code) throw Error("The code doesn’t match.");
      demoHistory.push(record);
      saveLocal("rusted-history", demoHistory);
      demoSession = null;
      return record;
    }
    case "show_pill": floating.hidden = false; break;
    case "show_dashboard":
      floating.hidden = true;
      dashboard.inert = false;
      dashboard.classList.remove("browser-session-running");
      break;
  }
}

const phrases = {
  start: [[57, 0], [64, .16], [69, .31], [71, .48], [69, .7]],
  complete: [[60, 0], [64, .16], [67, .32], [72, .48], [76, .66]],
  early: [[65, 0], [61, .22], [57, .44], [53, .69]],
};

const interfaceCues = {
  tap: ["click_003", .18],
  select: ["toggle_001", .20],
  countdown: ["pluck_001", .20],
  colorFill: ["glass_006", .20],
  duration: ["select_004", .18],
  deletePrompt: ["question_002", .19],
  deleted: ["drop_002", .22],
  open: ["open_002", .20],
  close: ["close_002", .20],
  error: ["error_002", .20],
  studying: ["confirmation_003", .24],
};
const interfacePlayers = new Map();

function sound(cue, enabled) {
  if (!enabled) return;
  try {
    if (interfaceCues[cue]) {
      let player = interfacePlayers.get(cue);
      if (!player) {
        const [file, volume] = interfaceCues[cue];
        player = new Audio(`sounds/${file}.ogg`);
        player.volume = volume;
        interfacePlayers.set(cue, player);
      }
      player.currentTime = 0;
      void player.play().catch(console.warn);
      return;
    }
    audio ??= new AudioContext();
    void audio.resume().then(() => {
      for (const [note, delay, duration = .55, volume = .12] of phrases[cue]) {
        const time = audio.currentTime + delay + .012;
        const gain = audio.createGain();
        const tone = audio.createOscillator();
        tone.type = "triangle";
        tone.frequency.value = 440 * 2 ** ((note - 69) / 12);
        const end = time + duration;
        gain.gain.setValueAtTime(0, time);
        gain.gain.linearRampToValueAtTime(volume, time + .016);
        gain.gain.exponentialRampToValueAtTime(.001, end);
        tone.connect(gain).connect(audio.destination);
        tone.start(time);
        tone.stop(end);
      }
    }).catch(console.warn);
  } catch (error) { console.warn(error); }
}

function clockTicks(count, enabled) {
  if (!enabled || count === 0) return;
  count = Math.min(count, 12);
  try {
    audio ??= new AudioContext();
    const context = audio;
    const play = () => {
      const now = context.currentTime;
      const start = Math.max(now + .008, Math.min(nextClockTick, now + .035));
      const interval = Math.min(.024, .09 / count);
      for (let i = 0; i < count; i++) {
        const time = start + interval * i;
        const tone = context.createOscillator();
        const gain = context.createGain();
        tone.type = "triangle";
        tone.frequency.setValueAtTime(1840, time);
        tone.frequency.exponentialRampToValueAtTime(670, time + .012);
        gain.gain.setValueAtTime(.048, time);
        gain.gain.exponentialRampToValueAtTime(.001, time + .016);
        tone.connect(gain).connect(context.destination);
        tone.start(time);
        tone.stop(time + .017);
      }
      nextClockTick = start + Math.min(.09, interval * count);
    };
    if (context.state === "running") play();
    else void context.resume().then(play).catch(console.warn);
  } catch (error) { console.warn(error); }
}

function clock(seconds) {
  const value = Math.max(0, Math.ceil(seconds));
  return `${String(Math.floor(value / 60)).padStart(2, "0")}:${String(value % 60).padStart(2, "0")}`;
}

function status(id, message = "") {
  $(id).textContent = message;
  $(id).hidden = !message;
}

const settings = {
  minutes: 25, goal: "", style: "digits", sound: true, sites: "", blockedSites: "", blocklistMode: false,
  warnUnreadableBrowser: true, allowedApps: "",
  ...stored("rusted-plan", {}),
};

function updateSettings(animate = false) {
  for (const button of document.querySelectorAll("[data-style]"))
    button.setAttribute("aria-pressed", button.dataset.style === settings.style);
  const sample = $("sample");
  const digits = sample?.querySelector(".sample-digits");
  const isFill = settings.style === "fill";
  if (sample) {
    if (animate && !reduceMotion.matches && digits) {
      digits.classList.add("digits-fading");
      sample.classList.toggle("is-fill", isFill);
      setTimeout(() => {
        digits.textContent = isFill ? "Focus" : clock(settings.minutes * 60);
        digits.classList.remove("digits-fading");
      }, 220);
    } else {
      sample.classList.toggle("is-fill", isFill);
      if (digits) digits.textContent = isFill ? "Focus" : clock(settings.minutes * 60);
    }
  }
  $("sound").textContent = settings.sound ? "Sound on" : "Sound off";
  $("sound").setAttribute("aria-pressed", settings.sound);
  saveLocal("rusted-plan", settings);
}

function playStyleSound(style, enabled) {
  if (!enabled) return;
  try {
    audio ??= new AudioContext();
    const ctx = audio;
    const play = () => {
      const now = ctx.currentTime;
      if (style === "digits") {
        // Countdown: Crisp, rhythmic digital stopwatch clicks (two quick micro-ticks: 950Hz and 1450Hz)
        const t1 = now + 0.005;
        const tone1 = ctx.createOscillator();
        const gain1 = ctx.createGain();
        tone1.type = "sine";
        tone1.frequency.setValueAtTime(950, t1);
        tone1.frequency.exponentialRampToValueAtTime(1450, t1 + 0.025);
        gain1.gain.setValueAtTime(0.09, t1);
        gain1.gain.exponentialRampToValueAtTime(0.001, t1 + 0.035);
        tone1.connect(gain1).connect(ctx.destination);
        tone1.start(t1);
        tone1.stop(t1 + 0.04);

        const t2 = now + 0.042;
        const tone2 = ctx.createOscillator();
        const gain2 = ctx.createGain();
        tone2.type = "sine";
        tone2.frequency.setValueAtTime(1400, t2);
        tone2.frequency.exponentialRampToValueAtTime(1850, t2 + 0.03);
        gain2.gain.setValueAtTime(0.08, t2);
        gain2.gain.exponentialRampToValueAtTime(0.001, t2 + 0.04);
        tone2.connect(gain2).connect(ctx.destination);
        tone2.start(t2);
        tone2.stop(t2 + 0.045);
      } else {
        // Color Fill: Smooth, lush ambient glass/liquid chord (523Hz C5, 659Hz E5, 784Hz G5)
        const notes = [523.25, 659.25, 783.99];
        const t = now + 0.008;
        notes.forEach((freq, idx) => {
          const osc = ctx.createOscillator();
          const gain = ctx.createGain();
          osc.type = "triangle";
          osc.frequency.setValueAtTime(freq, t);
          gain.gain.setValueAtTime(0, t);
          gain.gain.linearRampToValueAtTime(0.06 / (idx + 1), t + 0.04);
          gain.gain.exponentialRampToValueAtTime(0.0005, t + 0.38 + idx * 0.05);
          osc.connect(gain).connect(ctx.destination);
          osc.start(t);
          osc.stop(t + 0.45);
        });
      }
    };
    if (ctx.state === "running") play();
    else void ctx.resume().then(play).catch(console.warn);
  } catch (e) {
    console.warn(e);
  }
}

function setupDurationRuler() {
  const ruler = $("duration-ruler");
  const scale = $("duration-scale");
  const input = $("minutes");
  const minimum = Number(input.min);
  const maximum = Number(input.max);
  const spacing = parseFloat(getComputedStyle(ruler).getPropertyValue("--tick-step"));
  const stops = [10, 20, 30, 40, 50, 60, 90, 120];
  const clamp = (value) => Math.max(minimum, Math.min(maximum, value));
  const shortLabel = (minute) => minute === 90 ? "1.5 hr" : minute === 120 ? "2 hr" : String(minute);
  const displayLabel = (minute) => minute === 1 ? "1 minute" : `${minute} minutes`;
  const marks = document.createDocumentFragment();
  for (let minute = minimum; minute <= maximum; minute++) {
    const mark = document.createElement("div");
    const major = stops.includes(minute);
    mark.className = "duration-mark" + (major ? " major" : minute % 5 === 0 ? " medium" : "");
    if (major) mark.append(Object.assign(document.createElement("span"), { textContent: shortLabel(minute) }));
    marks.append(mark);
  }
  scale.append(marks);

  let currentPos = clamp(Number(settings.minutes) || 25);
  let targetPos = currentPos;
  let drag = null;
  let rafId = null;
  let settleTimer = null;
  let lastFrame;

  function renderTransform(pos) {
    scale.style.transform = `translateX(${-(pos - minimum + .5) * spacing}px)`;
  }

  function syncValues(pos, tick = false) {
    const minute = Math.round(pos);
    const crossed = Math.abs(minute - settings.minutes);
    input.value = minute;
    ruler.setAttribute("aria-valuenow", minute);
    ruler.setAttribute("aria-valuetext", displayLabel(minute));
    if (crossed) {
      settings.minutes = minute;
      updateSettings();
      if (tick) clockTicks(crossed, settings.sound);
    }
  }

  function smoothLoop(now) {
    if (reduceMotion.matches) {
      currentPos = targetPos;
      renderTransform(currentPos);
      syncValues(currentPos, true);
      rafId = null;
      return;
    }
    const diff = targetPos - currentPos;
    const elapsed = Math.min(32, Math.max(0, now - (lastFrame ?? now - 16.7)));
    lastFrame = now;
    if (Math.abs(diff) > 0.005) {
      currentPos += diff * (1 - Math.exp(-elapsed / 52));
      renderTransform(currentPos);
      syncValues(currentPos, true);
      rafId = requestAnimationFrame(smoothLoop);
    } else {
      currentPos = targetPos;
      renderTransform(currentPos);
      syncValues(currentPos, true);
      rafId = null;
    }
  }

  function wakeLoop() {
    if (rafId === null) {
      lastFrame = undefined;
      rafId = requestAnimationFrame(smoothLoop);
    }
  }

  function stopMotion() {
    clearTimeout(settleTimer);
    if (rafId !== null) cancelAnimationFrame(rafId);
    rafId = null;
    targetPos = currentPos;
  }

  function settle() {
    const nearest = stops.reduce((best, stop) =>
      Math.abs(targetPos - stop) < Math.abs(targetPos - best) ? stop : best);
    const magnetic = Math.abs(targetPos - nearest) <= 1.6;
    ruler.classList.toggle("magnetic", magnetic);
    targetPos = magnetic ? nearest : Math.round(targetPos);
    wakeLoop();
  }

  ruler.addEventListener("pointerdown", (event) => {
    if (drag || !event.isPrimary || event.button !== 0) return;
    stopMotion();
    ruler.classList.remove("magnetic");
    ruler.focus({ preventScroll: true });
    ruler.setPointerCapture(event.pointerId);
    drag = { id: event.pointerId, startX: event.clientX, startPos: currentPos, moved: false,
      position: currentPos, time: event.timeStamp, velocity: 0 };
    ruler.classList.add("dragging");
  });

  ruler.addEventListener("pointermove", (event) => {
    if (drag?.id !== event.pointerId) return;
    const distance = drag.startX - event.clientX;
    if (Math.abs(distance) > 3) drag.moved = true;
    if (!drag.moved) return;
    const position = clamp(drag.startPos + distance / spacing);
    drag.velocity = (position - drag.position) / Math.max(1, event.timeStamp - drag.time);
    drag.position = position;
    drag.time = event.timeStamp;
    currentPos = targetPos = position;
    renderTransform(position);
    syncValues(position, true);
  });

  function endDrag(event) {
    if (drag?.id !== event.pointerId) return;
    if (event.type === "pointerup" && !drag.moved) {
      const rect = ruler.getBoundingClientRect();
      targetPos = clamp(currentPos + (event.clientX - rect.left - rect.width / 2) / spacing);
      wakeLoop();
    } else if (event.type === "pointerup" && !reduceMotion.matches && event.timeStamp - drag.time < 75) {
      targetPos = clamp(currentPos + Math.max(-6, Math.min(6, drag.velocity * 90)));
    }
    drag = null;
    ruler.classList.remove("dragging");
    settle();
  }

  for (const event of ["pointerup", "pointercancel", "lostpointercapture"]) {
    ruler.addEventListener(event, endDrag);
  }

  ruler.addEventListener("wheel", (event) => {
    if (event.ctrlKey || drag) return;
    event.preventDefault();
    clearTimeout(settleTimer);
    ruler.classList.remove("magnetic");
    const horizontal = Math.abs(event.deltaX) > Math.abs(event.deltaY);
    const units = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? ruler.clientWidth : 1;
    const delta = (horizontal ? event.deltaX : event.deltaY * .42) * units / spacing;
    targetPos = clamp(targetPos + delta);
    wakeLoop();
    settleTimer = setTimeout(settle, 180);
  }, { passive: false });

  ruler.addEventListener("keydown", (event) => {
    const current = Math.round(targetPos);
    const targets = { ArrowLeft: current - 1, ArrowDown: current - 1,
      ArrowRight: current + 1, ArrowUp: current + 1, PageDown: current - 10,
      PageUp: current + 10, Home: minimum, End: maximum };
    if (!Object.hasOwn(targets, event.key)) return;
    event.preventDefault();
    stopMotion();
    currentPos = targetPos = clamp(targets[event.key]);
    renderTransform(currentPos);
    syncValues(currentPos, true);
  });

  input.oninput = () => {
    if (!input.validity.valid) return;
    stopMotion();
    currentPos = targetPos = clamp(input.valueAsNumber);
    renderTransform(currentPos);
    syncValues(currentPos);
  };
  input.onchange = () => { if (input.validity.valid) sound("duration", settings.sound); };

  renderTransform(currentPos);
  syncValues(currentPos);
}

function relativeTime(unixSecs) {
  if (!unixSecs) return "";
  const diff = Math.floor(Date.now() / 1000) - unixSecs;
  const d = new Date(unixSecs * 1000);
  const timeStr = d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  if (diff < 60) return "Just now";
  if (diff < 3600) return `${Math.floor(diff / 60)} min ago`;
  const today = new Date();
  const isToday = d.toDateString() === today.toDateString();
  const yesterday = new Date();
  yesterday.setDate(today.getDate() - 1);
  const isYesterday = d.toDateString() === yesterday.toDateString();
  if (isToday) return `Today at ${timeStr}`;
  if (isYesterday) return `Yesterday at ${timeStr}`;
  return `${d.toLocaleDateString([], { month: "short", day: "numeric" })} at ${timeStr}`;
}

let chartRecords = [];
let chartRange = 7;
let selectedDay;
let activityChart;

function localDay(date) {
  return [date.getFullYear(), date.getMonth(), date.getDate()].join("/");
}

function studyDuration(seconds) {
  seconds = Math.floor(seconds);
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor(seconds % 3600 / 60);
  if (hours) return minutes ? `${hours} hr ${minutes} min` : `${hours} hr`;
  return minutes ? `${minutes} min` : `${seconds} sec`;
}

function distractionCount(count) {
  return `${count} distraction${count === 1 ? "" : "s"}`;
}

function renderAnalytics() {
  const today = new Date();
  const dayFormat = new Intl.DateTimeFormat(undefined, { weekday: "long", month: "long", day: "numeric", year: "numeric" });
  const shortFormat = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short" });
  const dates = new Map();
  for (let offset = chartRange - 1; offset >= 0; offset--) {
    const date = new Date(today.getFullYear(), today.getMonth(), today.getDate() - offset);
    dates.set(localDay(date), { date, seconds: 0, distractions: 0, sessions: [] });
  }
  let undated = 0;
  for (const record of chartRecords) {
    if (!record.completedAt) {
      undated++;
      continue;
    }
    const day = dates.get(localDay(new Date(record.completedAt * 1000)));
    if (!day) continue;
    day.seconds += record.elapsedSeconds;
    day.distractions += record.distractions ?? 0;
    day.sessions.push(record);
  }
  const days = [...dates.values()];
  const sum = (get) => days.reduce((total, day) => total + get(day), 0);
  const totals = [
    [studyDuration(sum(day => day.seconds)), "Time studied"],
    [sum(day => day.sessions.length), "Sessions"],
    [sum(day => day.distractions), "Distractions"],
  ];
  $("chart-totals").replaceChildren(...totals.map(([value, label]) => {
    const tile = document.createElement("div");
    tile.append(Object.assign(document.createElement("strong"), { textContent: value }),
      Object.assign(document.createElement("span"), { textContent: label }));
    return tile;
  }));
  $("chart-range").textContent = `${shortFormat.format(days[0].date)} – ${shortFormat.format(today)}`;
  status("analytics-note", undated ? `${undated} older session${undated === 1 ? " has" : "s have"} no saved date and still appear${undated === 1 ? "s" : ""} on Home.` : "");

  function showDay(day) {
    $("chart-day").textContent = dayFormat.format(day.date);
    $("chart-day-summary").textContent = day.sessions.length
      ? `${studyDuration(day.seconds)} studied · ${distractionCount(day.distractions)}`
      : "No sessions recorded for this day.";
    $("chart-sessions").replaceChildren(...day.sessions.slice().reverse().map(record => {
      const row = document.createElement("li");
      row.append(Object.assign(document.createElement("strong"), { textContent: record.goal || "Focus session" }),
        Object.assign(document.createElement("span"), {
          textContent: `${new Date(record.completedAt * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })} · ${studyDuration(record.elapsedSeconds)} · ${distractionCount(record.distractions ?? 0)}`,
        }));
      return row;
    }));
  }
  if (!dates.has(selectedDay)) {
    selectedDay = [...dates].reverse().find(([, day]) => day.sessions.length)?.[0] ?? localDay(today);
  }
  drawActivityChart(days, shortFormat, dayFormat, (index) => {
    selectedDay = localDay(days[index].date);
    showDay(days[index]);
  });
  showDay(dates.get(selectedDay));
}

function drawActivityChart(days, shortFormat, dayFormat, selectDay) {
  const canvas = $("study-chart");
  canvas.parentElement.classList.toggle("fortnight", days.length === 14);
  activityChart?.destroy();
  const minutes = new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 });
  const ticks = { color: "#5f5873", precision: 0, maxTicksLimit: 6 };
  const Chart = window.Chart;
  activityChart = new Chart(canvas, {
    type: "bar",
    data: {
      labels: days.map(day => shortFormat.format(day.date)),
      datasets: [
        {
          label: "Study time", data: days.map(day => day.seconds / 60),
          yAxisID: "study", order: 2, maxBarThickness: 24, minBarLength: 2,
          borderRadius: { topLeft: 5, topRight: 5 },
          backgroundColor: ({ raw }) => raw ? "#7655d9" : "#e9e5ef",
          hoverBackgroundColor: ({ raw }) => raw ? "#6140be" : "#d5cde4",
        },
        {
          type: "line", label: "Distractions", data: days.map(day => day.distractions),
          yAxisID: "distractions", order: 1, borderColor: "#d44979", borderWidth: 2,
          cubicInterpolationMode: "monotone", pointRadius: 3, pointHoverRadius: 5,
          pointBackgroundColor: "#d44979", pointBorderColor: "#fff",
        },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      animation: reduceMotion.matches ? false : { duration: 280 },
      interaction: { mode: "index", intersect: false },
      onClick: (_event, items) => { if (items.length) selectDay(items[0].index); },
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: "#fff", titleColor: "#211931", bodyColor: "#3d344c",
          borderColor: "#dcd5e8", borderWidth: 1, padding: 12,
          displayColors: false, caretPadding: 6,
          callbacks: {
            title: ([item]) => dayFormat.format(days[item.dataIndex].date),
            label: ({ datasetIndex, raw }) => datasetIndex === 0
              ? `${minutes.format(raw)} min studied` : distractionCount(raw),
            afterBody: ([item]) => {
              const count = days[item.dataIndex].sessions.length;
              return `${count} session${count === 1 ? "" : "s"}`;
            },
          },
        },
      },
      scales: {
        x: { offset: true, grid: { display: false }, border: { color: "#dad4e4" },
          ticks: { autoSkip: false, color: ticks.color, minRotation: 45, maxRotation: 45, font: { size: 11 } } },
        study: { position: "left", beginAtZero: true, suggestedMax: 5, ticks,
          title: { display: true, text: "Study time (min)", color: "#5a4199" },
          border: { display: false, dash: [4, 4] }, grid: { color: "#e7e2ed", drawTicks: false } },
        distractions: { position: "right", beginAtZero: true, suggestedMax: 2, ticks,
          title: { display: true, text: "Distractions", color: "#aa315d" },
          border: { display: false }, grid: { drawOnChartArea: false, drawTicks: false } },
      },
    },
  });
  canvas.onkeydown = (event) => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const current = days.findIndex(day => localDay(day.date) === selectedDay);
    const next = event.key === "Home" ? 0 : event.key === "End" ? days.length - 1
      : Math.max(0, Math.min(days.length - 1, current + (event.key === "ArrowLeft" ? -1 : 1)));
    selectDay(next);
    const elements = [0, 1].map(datasetIndex => ({ datasetIndex, index: next }));
    const x = activityChart.scales.x.getPixelForValue(next);
    activityChart.setActiveElements(elements);
    activityChart.tooltip.setActiveElements(elements, { x, y: activityChart.chartArea.top });
    activityChart.update("none");
    const frame = canvas.closest(".chart-scroll");
    if (x < frame.scrollLeft || x > frame.scrollLeft + frame.clientWidth) {
      frame.scrollLeft = x - frame.clientWidth / 2;
    }
  };
  canvas.onblur = () => {
    activityChart.setActiveElements([]);
    activityChart.tooltip.setActiveElements([], { x: 0, y: 0 });
    activityChart.update("none");
  };
}

function setupDashboardViews() {
  const home = $("nav-home");
  const analytics = $("nav-analytics");
  function navigate(showAnalytics) {
    $("home-view").hidden = showAnalytics;
    $("analytics-view").hidden = !showAnalytics;
    home.removeAttribute("aria-current");
    analytics.removeAttribute("aria-current");
    (showAnalytics ? analytics : home).setAttribute("aria-current", "page");
    if (showAnalytics) renderAnalytics();
    window.scrollTo(0, 0);
  }
  home.onclick = () => navigate(false);
  analytics.onclick = () => navigate(true);
  dashboard.querySelector(".brand").onclick = (event) => { event.preventDefault(); navigate(false); };
  for (const [id, range] of [["chart-week", 7], ["chart-fortnight", 14]]) {
    $(id).onclick = () => {
      if (chartRange === range) return;
      chartRange = range;
      $("chart-week").setAttribute("aria-pressed", range === 7);
      $("chart-fortnight").setAttribute("aria-pressed", range === 14);
      renderAnalytics();
    };
  }
}

function renameSession(record) {
  const dialog = $("rename-dialog");
  const input = $("rename-goal");
  const save = $("rename-save");
  input.value = record.goal;
  status("rename-status");
  $("rename-cancel").onclick = () => dialog.close();
  dialog.oncancel = (event) => { if (save.disabled) event.preventDefault(); };
  $("rename-form").onsubmit = async (event) => {
    event.preventDefault();
    const goal = input.value.trim();
    if (!goal) {
      status("rename-status", "Enter a session name.");
      return;
    }
    save.disabled = $("rename-cancel").disabled = true;
    try {
      await command("rename_session", { id: record.id, goal });
      dialog.close();
      await refreshHistory();
      $("history").querySelector(`[data-session-id="${CSS.escape(record.id)}"] .rename-session`)?.focus();
    } catch (error) {
      status("rename-status", String(error));
    } finally {
      save.disabled = $("rename-cancel").disabled = false;
    }
  };
  dialog.showModal();
  input.select();
}

async function refreshHistory() {
  try {
    const records = await command("history");
    chartRecords = records;
    status("analytics-status");
    if (!$("analytics-view").hidden) renderAnalytics();
    const list = $("history");
    list.replaceChildren();
    if (!records.length) {
      list.append(Object.assign(document.createElement("li"), { textContent: "Your sessions will appear here." }));
    }
    for (const record of records.slice().reverse()) {
      const row = document.createElement("li");
      row.className = "history-row";
      row.dataset.sessionId = record.id;
      const detail = document.createElement("details");
      const count = record.distractions ?? 0;
      const when = record.completedAt ? ` · ${relativeTime(record.completedAt)}` : "";
      detail.append(
        Object.assign(document.createElement("summary"), { textContent: record.goal || "Focus session" }),
        Object.assign(document.createElement("p"), {
          textContent: `${record.completed ? "Completed" : "Ended early"} · ${clock(record.elapsedSeconds)} of ${record.minutes} min · ${count} distraction${count === 1 ? "" : "s"}${when}`,
        }),
      );
      const remove = Object.assign(document.createElement("button"), { type: "button", textContent: "Delete" });
      remove.dataset.sound = "manual";
      remove.onclick = async () => {
        if (remove.textContent === "Delete") {
          remove.textContent = "Confirm delete";
          sound("deletePrompt", settings.sound);
          return;
        }
        for (const control of list.querySelectorAll("button")) control.disabled = true;
        try {
          await command("delete_session", { id: record.id });
          sound("deleted", settings.sound);
          await refreshHistory();
        } catch (error) {
          status("dashboard-status", String(error));
          for (const control of list.querySelectorAll("button")) control.disabled = false;
        }
      };
      const rename = Object.assign(document.createElement("button"), { type: "button", textContent: "Rename", className: "rename-session" });
      rename.onclick = () => renameSession(record);
      const actions = document.createElement("div");
      actions.className = "history-actions";
      actions.append(rename, remove);
      row.append(detail, actions);
      list.append(row);
    }
    const congratsTime = sessionStorage.getItem("focuzzer-congrats");
    if (congratsTime) {
      sessionStorage.removeItem("focuzzer-congrats");
      status("dashboard-status", `🎉 Congrats! Your study time is ${congratsTime}!`);
      $("dashboard-status").classList.add("congrats-status");
      setTimeout(() => {
        $("dashboard-status").classList.remove("congrats-status");
      }, 7000);
      const firstRow = list.querySelector(".history-row");
      if (firstRow) firstRow.classList.add("history-latest-glow");
    }
  } catch {
    status("dashboard-status", "Could not load session history.");
    status("analytics-status", "Could not load session history.");
  }
}

async function handoff() {
  const sample = $("sample");
  const rect = sample.getBoundingClientRect();
  const origin = [rect.left + rect.width / 2, rect.top + rect.height / 2];
  const reducedMotion = reduceMotion.matches;
  dashboard.inert = true;
  sample.classList.add("handoff-source");
  let ghost;
  let active = false;
  try {
    if (desktop) {
      await command("show_pill", { origin, reducedMotion });
      return;
    }
    const duration = reducedMotion ? 160 : 460;
    const fade = dashboard.animate([{ opacity: 1 }, { opacity: .28 }], { duration, fill: "forwards" });
    try {
      if (!reducedMotion) {
        ghost = sample.cloneNode(true);
        ghost.removeAttribute("id");
        ghost.classList.remove("handoff-source");
        ghost.classList.add("handoff");
        Object.assign(ghost.style, { left: `${rect.left}px`, top: `${rect.top}px` });
        document.body.append(ghost);
        await ghost.animate([
          { transform: "translate(0, 0)" },
          { transform: `translate(${innerWidth / 2 - origin[0]}px, ${43 - origin[1]}px) scale(${196 / rect.width}, ${54 / rect.height})` },
        ], { duration, easing: "cubic-bezier(.2,.75,.24,1)", fill: "forwards" }).finished;
      } else {
        await fade.finished;
      }
      dashboard.classList.add("browser-session-running");
      await refreshPill();
      await command("show_pill");
      active = true;
    } finally {
      fade.cancel();
    }
  } finally {
    ghost?.remove();
    sample.classList.remove("handoff-source");
    if (!active) {
      dashboard.inert = false;
      dashboard.classList.remove("browser-session-running");
    }
  }
}

document.addEventListener("click", (event) => {
  const button = event.target.closest("button");
  if (!button || button.disabled || button.dataset.sound === "manual" || button.dataset.style ||
      ["start", "finish", "quit-confirm", "quit-cancel", "sound", "confirm-studying"].includes(button.id)) return;
  sound("tap", snapshot?.plan.sound ?? settings.sound);
}, { capture: true });

// ── Bubble Picker Presets & Logic ──────────────────────────────────────────
const PRESET_SITES = [
  { label: "Gemini", value: "gemini.google.com" },
  { label: "NotebookLM", value: "notebooklm.google.com" },
  { label: "ChatGPT", value: "chatgpt.com" },
  { label: "Discord", value: "discord.com" },
  { label: "WhatsApp", value: "whatsapp.com" },
  { label: "Google Meet", value: "meet.google.com" },
  { label: "YouTube", value: "youtube.com" },
  { label: "Wikipedia", value: "wikipedia.org" },
  { label: "Khan Academy", value: "khanacademy.org" },
  { label: "Notion", value: "notion.so" },
  { label: "Coursera", value: "coursera.org" },
];

const PRESET_APPS = [
  { label: "VS Code", value: "code" },
  { label: "Discord", value: "discord" },
  { label: "Word", value: "winword" },
  { label: "Excel", value: "excel" },
  { label: "PowerPoint", value: "powerpnt" },
  { label: "Obsidian", value: "obsidian" },
  { label: "Notion", value: "notion" },
  { label: "Anki", value: "anki" },
  { label: "Zotero", value: "zotero" },
  { label: "ChatGPT App", value: "chatgpt" },
  { label: "LibreOffice", value: "soffice" },
];

async function validateAllowItem(value, website, presets) {
  if (desktop) return command("validate_allow_item", { value, website });
  const name = value.toLowerCase().trim();
  const known = presets.find((item) => item.label.toLowerCase() === name || item.value === name.replace(/\.exe$/, ""));
  if (known) return known.value;
  if (website) {
    const alias = { "notebook lm": "notebooklm.google.com", "notebook.google.com": "notebooklm.google.com", "whatsap.com": "whatsapp.com", "web.whatsapp.com": "whatsapp.com", "gmeet.com": "meet.google.com" }[name];
    if (alias) return alias;
    try {
      const url = new URL(name.includes("://") ? name : `https://${name}`);
      if (["https:", "http:"].includes(url.protocol) && /^(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z0-9]{2,}$/i.test(url.hostname)) {
        return url.hostname.replace(/^www\./, "");
      }
    } catch { /* Show the same message for invalid URLs. */ }
    throw Error("Choose a listed website, or enter a full domain such as example.edu.");
  }
  if (["spotify", "codex", "system apps"].includes(name.replace(/\.exe$/, ""))) return name.replace(/\.exe$/, "");
  throw Error("Choose a listed app. Installed executable paths can be added in the Windows app.");
}

async function buildBubblePicker(containerId, hiddenInputId, presets, initialValue) {
  const container = $(containerId);
  const hidden = $(hiddenInputId);
  if (!container || !hidden) return;

  const presetMap = new Map(presets.map(p => [p.value.toLowerCase(), p.label]));
  const isSites = containerId === "site-bubbles";
  const initItems = initialValue
    ? initialValue.split(/[,\n]/).map(s => s.trim()).filter(Boolean)
    : [];
  const selectedSet = new Map();
  const customItems = [];

  const validated = await Promise.allSettled(initItems.map(item => validateAllowItem(item, isSites, presets)));
  for (const result of validated) {
    if (result.status !== "fulfilled") continue;
    const item = result.value;
    const lower = item.toLowerCase();
    if (selectedSet.has(lower)) continue;
    if (presetMap.has(lower)) {
      selectedSet.set(lower, item);
    } else {
      customItems.push(item);
      selectedSet.set(lower, item);
    }
  }

  function syncHidden() {
    hidden.value = [...selectedSet.values()].join(", ");
  }

  function makeBubble(label, value, isCustom = false) {
    const btn = document.createElement("button");
    btn.type = "button";
    const lower = value.toLowerCase();
    btn.className = "bubble" + (selectedSet.has(lower) ? " selected" : "");
    btn.dataset.value = value;
    btn.setAttribute("aria-pressed", selectedSet.has(lower));
    btn.textContent = label;
    if (isCustom) {
      const x = document.createElement("span");
      x.textContent = " ×";
      x.style.cssText = "margin-left:3px;opacity:.75;font-weight:bold";
      btn.append(x);
    }
    btn.onclick = () => {
      if (selectedSet.has(lower)) {
        selectedSet.delete(lower);
        btn.classList.remove("selected");
        if (isCustom) btn.remove();
      } else {
        selectedSet.set(lower, value);
        btn.classList.add("selected");
      }
      syncHidden();
      btn.setAttribute("aria-pressed", selectedSet.has(lower));
      sound("tap", settings.sound);
    };
    return btn;
  }

  container.replaceChildren();
  for (const { label, value } of presets) {
    container.append(makeBubble(label, value));
  }
  for (const item of customItems) {
    container.append(makeBubble(item.split(/[/\\]/).at(-1), item, true));
  }

  const addBtn = document.createElement("button");
  addBtn.type = "button";
  addBtn.className = "bubble bubble-add";
  addBtn.textContent = "+ Add";

  const customRow = document.createElement("div");
  customRow.className = "bubble-custom-row";
  customRow.hidden = true;
  const customInput = document.createElement("input");
  customInput.type = "text";
  customInput.placeholder = isSites ? "Website name or domain" : "Known app or full .exe path";
  customInput.maxLength = 240;
  const customConfirm = document.createElement("button");
  customConfirm.type = "button";
  customConfirm.textContent = "Add";
  customRow.append(customInput, customConfirm);
  const message = document.createElement("p");
  message.className = "field-note";
  message.setAttribute("role", "status");
  message.hidden = true;

  addBtn.onclick = () => {
    addBtn.hidden = true;
    customRow.hidden = false;
    customInput.classList.remove("error");
    message.hidden = true;
    customInput.focus();
  };

  async function confirmCustom() {
    if (customConfirm.disabled) return;
    const val = customInput.value.trim();
    if (!val) { addBtn.hidden = false; customRow.hidden = true; return; }
    customConfirm.disabled = true;
    let canonical;
    try { canonical = await validateAllowItem(val, isSites, presets); }
    catch (error) {
      customInput.classList.add("error");
      message.textContent = error instanceof Error ? error.message : String(error);
      message.hidden = false;
      sound("error", settings.sound);
      customInput.focus();
      return;
    } finally { customConfirm.disabled = false; }
    const lower = canonical.toLowerCase();
    if (!selectedSet.has(lower)) {
      const preset = [...container.querySelectorAll("button[data-value]")].find(button => button.dataset.value === lower);
      if (preset) preset.click();
      else {
        selectedSet.set(lower, canonical);
        const bubble = makeBubble(canonical.split(/[/\\]/).at(-1), canonical, true);
        container.insertBefore(bubble, addBtn);
        sound("tap", settings.sound);
      }
      syncHidden();
    }
    customInput.value = "";
    customInput.classList.remove("error");
    addBtn.hidden = false;
    customRow.hidden = true;
    message.hidden = true;
  }

  customConfirm.onclick = confirmCustom;
  customInput.onkeydown = (e) => {
    if (e.key === "Enter") { e.preventDefault(); confirmCustom(); }
    if (e.key === "Escape") { addBtn.hidden = false; customRow.hidden = true; }
  };

  container.append(addBtn, customRow, message);
  syncHidden();
}

if (!pillPage && !alarmPage && !quitPage && !reminderPage) {
  root.classList.add("dashboard-root");
  dashboard.hidden = false;
  const info = $("dashboard-info");
  info.onclick = (event) => {
    if (event.target !== info) return;
    const bounds = info.getBoundingClientRect();
    if (event.clientX < bounds.left || event.clientX > bounds.right
      || event.clientY < bounds.top || event.clientY > bounds.bottom) info.close();
  };
  function showInfo(about) {
    $("dashboard-info-title").textContent = about ? "About Focuzzer" : "How this app works";
    $("help-content").hidden = about;
    $("about-content").hidden = !about;
    status("repo-status");
    info.showModal();
  }
  $("show-help").onclick = () => showInfo(false);
  $("show-about").onclick = () => showInfo(true);
  $("repo-link").onclick = async (event) => {
    if (!desktop) return;
    event.preventDefault();
    try { await command("open_repo"); }
    catch (error) { status("repo-status", String(error)); }
  };
  $("minutes").value = settings.minutes;
  $("goal").value = settings.goal;
  const sitePicker = buildBubblePicker("site-bubbles", "sites", PRESET_SITES, settings.sites);
  $("blocked-sites").value = settings.blockedSites;
  $("warn-unreadable-browser").checked = settings.warnUnreadableBrowser;
  $("warn-unreadable-browser").onchange = (event) => {
    settings.warnUnreadableBrowser = event.target.checked;
    updateSettings();
  };
  const appPicker = buildBubblePicker("app-bubbles", "allowed-apps", PRESET_APPS, settings.allowedApps);
  $("site-mode").value = settings.blocklistMode ? "blocklist" : "allowlist";
  function updateSiteMode() {
    settings.blocklistMode = $("site-mode").value === "blocklist";
    $("allowed-websites-field").hidden = settings.blocklistMode;
  }
  $("site-mode").onchange = updateSiteMode;
  updateSiteMode();
  updateSettings();
  void refreshHistory();
  window.addEventListener("focus", refreshHistory);
  function syncExitSound() {
    if (desktop) void command("set_exit_sound", { enabled: settings.sound }).catch(console.warn);
  }
  syncExitSound();
  $("sound").onclick = () => {
    settings.sound = !settings.sound;
    updateSettings();
    syncExitSound();
    sound("select", settings.sound);
  };
  setupDurationRuler();
  setupDashboardViews();
  for (const button of document.querySelectorAll("[data-style]")) {
    button.onclick = () => {
      const prev = settings.style;
      settings.style = button.dataset.style;
      updateSettings(prev !== settings.style);
      playStyleSound(settings.style, settings.sound);
    };
  }
  const form = $("session-form");
  const startButton = $("start");
  const clearStartGlow = () => startButton.classList.remove("pointer-near");
  form.addEventListener("pointerleave", clearStartGlow);
  form.addEventListener("pointermove", (event) => {
    if (event.pointerType !== "mouse") return;
    const bounds = startButton.getBoundingClientRect();
    const distanceX = Math.max(bounds.left - event.clientX, 0, event.clientX - bounds.right);
    const distanceY = Math.max(bounds.top - event.clientY, 0, event.clientY - bounds.bottom);
    startButton.classList.toggle("pointer-near", Math.hypot(distanceX, distanceY) <= 16);
  });
  form.onsubmit = async (event) => {
    event.preventDefault();
    const start = $("start");
    start.disabled = true;
    status("dashboard-status");
    try {
      if (!pendingHandoff) {
        await Promise.all([sitePicker, appPicker]);
        settings.goal = $("goal").value.trim();
        settings.sites = $("sites").value.trim();
        settings.blockedSites = $("blocked-sites").value.trim();
        settings.allowedApps = $("allowed-apps").value.trim();
        await command("begin", { plan: { ...settings } });
        saveLocal("rusted-plan", settings);
        pendingHandoff = true;
        sound("start", settings.sound);
      }
      await handoff();
      pendingHandoff = false;
    } catch (error) {
      status("dashboard-status", String(error));
    } finally { start.disabled = false; }
  };
}

if (pillPage) {
  root.classList.add("pill-root");
  document.body.classList.add("pill-page");
  floating.hidden = false;
}
if (alarmPage) {
  root.classList.add("pill-root");
  document.body.classList.add("pill-page");
  $("alarm-banner").hidden = false;
  $("blocked-site").textContent = "This website is outside the allowlist.";
  let updating = false;
  setInterval(async () => {
    if (updating) return;
    updating = true;
    try {
      const active = await command("snapshot");
      if (active?.blockedSite) $("blocked-site").textContent = active.blockedSite;
    } catch (error) { console.warn(error); }
    finally { updating = false; }
  }, 150);
}
if (quitPage) {
  document.body.classList.add("quit-page");
  window.addEventListener("focus", () => void revealQuit());
}
if (reminderPage) {
  root.classList.add("pill-root");
  document.body.classList.add("pill-page");
  const card = $("reminder-card");
  card.hidden = false;
  let cueEnabled = false;
  let reading = false;
  let checkinSoundPlayed = false;
  if (tauri?.event) {
    tauri.event.listen("checkin-start", () => {
      sound("studying", true);
    });
  }
  setInterval(async () => {
    if (reading) return;
    reading = true;
    try {
      const reminder = await command("reminder");
      if (!reminder) return;
      cueEnabled = reminder.sound;
      if (!checkinSoundPlayed) {
        checkinSoundPlayed = true;
        sound("studying", reminder.sound);
      }
      const left = reminder.secondsLeft;
      $("reminder-status").textContent = left
        ? `Confirm within ${left} second${left === 1 ? "" : "s"}.`
        : "Time’s up. Confirm to silence the reminder.";
      card.classList.toggle("overdue", left === 0);
    } catch (error) { console.warn(error); }
    finally { reading = false; }
  }, 140);
  $("confirm-studying").onclick = async () => {
    sound("studying", cueEnabled);
    try { await command("confirm_studying"); }
    catch (error) { $("reminder-status").textContent = String(error); }
  };
}
if (!desktop && !pillPage) floating.classList.add("browser-preview");

let size = 0;
let velocity = 0;
let moving = false;
async function animatePill() {
  if (!desktop || moving) return;
  moving = true;
  let previous = performance.now();
  try {
    while (true) {
      const target = Number(expanded);
      const now = await new Promise(requestAnimationFrame);
      const step = Math.min(.033, (now - previous) / 1000);
      previous = now;
      if (reduceMotion.matches || (Math.abs(target - size) < .003 && Math.abs(velocity) < .04)) {
        size = target;
        velocity = 0;
        await command("pill_expand", { amount: size });
        if (target === Number(expanded)) break;
      } else {
        velocity += (520 * (target - size) - 46 * velocity) * step;
        size = Math.max(0, Math.min(1, size + velocity * step));
        await command("pill_expand", { amount: size });
      }
    }
  } catch (error) { console.warn(error); }
  finally { moving = false; }
}
function expand(next) {
  if (expanded === next) return;
  expanded = next;
  $("pill-top").setAttribute("aria-expanded", next);
  $("pill-detail").inert = !next;
  floating.classList.toggle("expanded", next);
  void animatePill();
}

function renderPill() {
  if (!snapshot) return;
  const remaining = Math.max(0, snapshot.plan.minutes * 60 - snapshot.elapsedSeconds);
  const complete = remaining === 0;
  if (complete && !won) sound("complete", snapshot.plan.sound);
  won = complete;
  const fill = snapshot.plan.style === "fill";
  $("fill").hidden = !fill;
  if (fill && fillFrame === undefined) fillFrame = requestAnimationFrame(updateFill);
  $("pill-value").textContent = complete ? "Done" : fill ? "Focus" : clock(remaining);
  const tab = $("pill-tab");
  tab.textContent = complete ? "" : snapshot.activeTab ?? "";
  tab.title = tab.textContent;
  tab.hidden = !tab.textContent;
  $("pill-goal").textContent = snapshot.plan.goal || "Focus session";
  $("pill-remaining").textContent = complete ? "Goal reached" : `${clock(remaining)} remaining`;
  const count = snapshot.distractions ?? 0;
  $("pill-distractions").textContent = `${count} distraction${count === 1 ? "" : "s"}`;
  floating.classList.toggle("is-blocked", Boolean(snapshot.blockedSite));
  floating.classList.toggle("is-won", won);
  $("finish").textContent = complete ? "Finish" : "End early";
}

function updateFill(now) {
  fillFrame = undefined;
  if (!snapshot || snapshot.plan.style !== "fill") return;
  const elapsed = snapshot.elapsedSeconds + Math.max(0, now - snapshotAt) / 1000;
  const target = Math.max(0, Math.min(1, elapsed / (snapshot.plan.minutes * 60)));
  visibleProgress += (target - visibleProgress) * 0.12;
  if (Math.abs(target - visibleProgress) < 0.0002) visibleProgress = target;
  $("fill").style.setProperty("--progress", visibleProgress.toFixed(4));
  if (visibleProgress < 1) fillFrame = requestAnimationFrame(updateFill);
}

async function refreshPill() {
  try {
    const next = await command("snapshot");
    if (snapshot && (!next || next.elapsedSeconds < snapshot.elapsedSeconds)) {
      visibleProgress = 0;
      won = false;
      pinned = false;
      size = 0;
      velocity = 0;
      expand(false);
    }
    snapshot = next;
    snapshotAt = performance.now();
    if (snapshot) renderPill();
    else { won = false; visibleProgress = 0; $("fill").style.removeProperty("--progress"); }
  } catch (error) { status("pill-status", String(error)); }
}

if (pillPage || !desktop) {
  const top = $("pill-top");
  let closeDelay;
  let drag = null;
  let dragged = false;
  floating.onpointerenter = () => { clearTimeout(closeDelay); expand(true); };
  floating.onpointerleave = () => {
    if (!pinned) closeDelay = setTimeout(() => expand(false), 110);
  };
  top.onclick = async () => {
    if (dragged) { dragged = false; return; }
    if (won) {
      $("finish").disabled = true;
      try {
        const result = await command("finish", { code: null });
        sound("complete", snapshot?.plan.sound ?? settings.sound);
        pinned = false;
        expand(false);
        const studyTimeStr = clock(result.elapsedSeconds);
        sessionStorage.setItem("focuzzer-congrats", studyTimeStr);
        await command("show_dashboard");
        if (!desktop) await refreshHistory();
        snapshot = null;
      } catch (error) {
        status("pill-status", String(error));
      } finally { $("finish").disabled = false; }
      return;
    }
    pinned = !pinned;
    expand(pinned);
  };
  top.onpointerdown = (event) => {
    if (event.button !== 0) return;
    dragged = false;
    drag = { x: event.screenX, y: event.screenY };
  };
  top.onpointermove = (event) => {
    if (!desktop || !drag || event.buttons !== 1) return;
    if (Math.hypot(event.screenX - drag.x, event.screenY - drag.y) > 7) {
      dragged = true;
      drag = null;
      void currentWindow.startDragging().catch(console.warn);
    }
  };
  top.onpointerup = top.onpointercancel = () => { drag = null; };
  floating.onkeydown = (event) => {
    if (event.key === "Escape") { pinned = false; top.focus(); expand(false); }
  };
  $("finish").onclick = async () => {
    if (!snapshot) return;
    if (!won) {
      sound("open", snapshot.plan.sound);
      try {
        if (desktop) await command("open_quit");
        else await revealQuit();
      } catch (error) { status("pill-status", String(error)); }
      return;
    }
    $("finish").disabled = true;
    try {
      const result = await command("finish", { code: null });
      if (!result.completed) sound("early", snapshot.plan.sound);
      else sound("complete", snapshot.plan.sound);
      pinned = false;
      expand(false);
      const studyTimeStr = clock(result.elapsedSeconds);
      sessionStorage.setItem("focuzzer-congrats", studyTimeStr);
      await command("show_dashboard");
      if (!desktop) await refreshHistory();
      snapshot = null;
    } catch (error) {
      status("pill-status", String(error));
    } finally { $("finish").disabled = false; }
  };
  let busy = false;
  async function updatePill() {
    if (busy) return;
    busy = true;
    try { await refreshPill(); } finally { busy = false; }
  }
  setInterval(updatePill, 200);
  if (desktop) tauri.event.listen("session-handoff", updatePill).catch(console.warn);
}

async function revealQuit() {
  const dialog = $("quit-dialog");
  if (dialog.open) {
    $("quit-input").value = "";
    status("quit-status");
    $("quit-input").focus();
    return;
  }
  try {
    const code = await command("quit_code");
    $("quit-code").textContent = code;
    $("quit-input").value = "";
    status("quit-status");
    dialog.showModal();
    $("quit-input").focus();
  } catch (error) { console.warn(error); }
}

async function dismissQuit() {
  $("quit-dialog").close();
  $("quit-input").value = "";
  if (desktop) await command("close_quit");
}

$("quit-cancel").onclick = async () => {
  const active = await command("snapshot");
  sound("close", active?.plan.sound);
  await dismissQuit();
};
$("quit-dialog").addEventListener("cancel", (event) => {
  event.preventDefault();
  void dismissQuit();
});
$("quit-form").onsubmit = async (event) => {
  event.preventDefault();
  $("quit-confirm").disabled = true;
  try {
    const active = await command("snapshot");
    const result = await command("finish", { code: $("quit-input").value });
    if (!result.completed) sound("early", active?.plan.sound);
    await dismissQuit();
    pinned = false;
    expand(false);
    await command("show_dashboard");
    if (!desktop) await refreshHistory();
  } catch (error) {
    status("quit-status", String(error));
    const active = await command("snapshot");
    sound("error", active?.plan.sound);
    $("quit-input").focus();
  } finally { $("quit-confirm").disabled = false; }
};
