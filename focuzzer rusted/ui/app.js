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
    case "history": return demoHistory;
    case "delete_session": demoHistory.splice(args.index, 1); saveLocal("rusted-history", demoHistory); break;
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
      const record = { ...data.plan, elapsedSeconds: data.elapsedSeconds, distractions: 0,
        completed: data.elapsedSeconds >= data.plan.minutes * 60 };
      if (!record.completed && args?.code !== demoSession.code) throw Error("The code doesn’t match.");
      demoHistory.push(record);
      saveLocal("rusted-history", demoHistory);
      demoSession = null;
      return record;
    }
    case "show_pill": floating.hidden = false; break;
    case "show_dashboard": floating.hidden = true; break;
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
  minutes: 25, goal: "", style: "digits", sound: true, sites: "", blockedSites: "", blocklistMode: false, allowedApps: "",
  ...stored("rusted-plan", {}),
};

function updateSettings() {
  for (const button of document.querySelectorAll("[data-style]"))
    button.setAttribute("aria-pressed", button.dataset.style === settings.style);
  $("sample").classList.toggle("is-fill", settings.style === "fill");
  $("sample").querySelector(".sample-digits").textContent = settings.style === "fill" ? "Focus" : clock(settings.minutes * 60);
  $("sound").textContent = settings.sound ? "Sound on" : "Sound off";
  $("sound").setAttribute("aria-pressed", settings.sound);
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

  let position = clamp(Number(settings.minutes) || 25);
  let drag = null;
  let animation;
  let settleTimer;

  function setPosition(value, tick = false) {
    position = clamp(value);
    scale.style.transform = `translateX(${-(position - minimum + .5) * spacing}px)`;
    const minute = Math.round(position);
    const crossed = Math.abs(minute - settings.minutes);
    settings.minutes = minute;
    input.value = minute;
    ruler.setAttribute("aria-valuenow", minute);
    ruler.setAttribute("aria-valuetext", displayLabel(minute));
    if (crossed) {
      updateSettings();
      if (tick) clockTicks(crossed, settings.sound);
    }
  }

  function interrupt() {
    if (animation !== undefined) cancelAnimationFrame(animation);
    animation = undefined;
    clearTimeout(settleTimer);
    ruler.classList.remove("magnetic");
  }

  function settle() {
    const nearest = stops.reduce((best, stop) =>
      Math.abs(position - stop) < Math.abs(position - best) ? stop : best);
    const magnetic = Math.abs(position - nearest) <= 2;
    const target = magnetic ? nearest : Math.round(position);
    if (magnetic && position !== target) ruler.classList.add("magnetic");
    if (reduceMotion.matches || Math.abs(position - target) < .01) {
      setPosition(target, true);
      return;
    }
    let velocity = 0;
    let previous = performance.now();
    function spring(now) {
      const seconds = Math.min(.025, (now - previous) / 1000);
      previous = now;
      velocity += (900 * (target - position) - 58 * velocity) * seconds;
      setPosition(position + velocity * seconds, true);
      if (Math.abs(position - target) < .012 && Math.abs(velocity) < .16) {
        setPosition(target, true);
        animation = undefined;
      } else {
        animation = requestAnimationFrame(spring);
      }
    }
    animation = requestAnimationFrame(spring);
  }

  ruler.addEventListener("pointerdown", (event) => {
    if (drag || !event.isPrimary || event.button !== 0) return;
    interrupt();
    ruler.focus({ preventScroll: true });
    ruler.setPointerCapture(event.pointerId);
    drag = { id: event.pointerId, x: event.clientX, position, moved: false };
    ruler.classList.add("dragging");
  });
  ruler.addEventListener("pointermove", (event) => {
    if (drag?.id !== event.pointerId) return;
    const distance = drag.x - event.clientX;
    if (Math.abs(distance) > 4) drag.moved = true;
    if (drag.moved) setPosition(drag.position + distance / spacing, true);
  });
  function endDrag(event) {
    if (drag?.id !== event.pointerId) return;
    if (event.type === "pointerup" && !drag.moved) {
      const rect = ruler.getBoundingClientRect();
      setPosition(position + (event.clientX - rect.left - rect.width / 2) / spacing, true);
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
    const horizontal = Math.abs(event.deltaX) > Math.abs(event.deltaY);
    const units = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? ruler.clientWidth : 1;
    const delta = (horizontal ? event.deltaX : event.deltaY * .45) * units / spacing;
    if (!delta) return;
    event.preventDefault();
    interrupt();
    setPosition(position + delta, true);
    settleTimer = setTimeout(settle, 155);
  }, { passive: false });
  ruler.addEventListener("keydown", (event) => {
    const current = Math.round(position);
    const targets = { ArrowLeft: current - 1, ArrowDown: current - 1,
      ArrowRight: current + 1, ArrowUp: current + 1, PageDown: current - 10,
      PageUp: current + 10, Home: minimum, End: maximum };
    if (!Object.hasOwn(targets, event.key)) return;
    event.preventDefault();
    interrupt();
    setPosition(targets[event.key], true);
  });
  input.oninput = () => {
    if (!input.validity.valid) return;
    interrupt();
    setPosition(input.valueAsNumber);
  };
  input.onchange = () => { if (input.validity.valid) sound("duration", settings.sound); };
  setPosition(position);
}

async function refreshHistory() {
  try {
    const records = await command("history");
    const list = $("history");
    list.replaceChildren();
    if (!records.length) {
      list.append(Object.assign(document.createElement("li"), { textContent: "Your sessions will appear here." }));
    }
    for (let index = records.length - 1; index >= 0; index--) {
      const record = records[index];
      const row = document.createElement("li");
      row.className = "history-row";
      const detail = document.createElement("details");
      const count = record.distractions ?? 0;
      detail.append(
        Object.assign(document.createElement("summary"), { textContent: record.goal || "Focus session" }),
        Object.assign(document.createElement("p"), {
          textContent: `${record.completed ? "Completed" : "Ended early"} · ${clock(record.elapsedSeconds)} of ${record.minutes} min · ${count} distraction${count === 1 ? "" : "s"}`,
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
          await command("delete_session", { index });
          sound("deleted", settings.sound);
          await refreshHistory();
        } catch (error) {
          status("dashboard-status", String(error));
          for (const control of list.querySelectorAll("button")) control.disabled = false;
        }
      };
      row.append(
        detail, remove,
      );
      list.append(row);
    }
  } catch {
    status("dashboard-status", "Could not load session history.");
  }
}

async function handoff() {
  if (reduceMotion.matches) return;
  const sample = $("sample");
  const origin = sample.getBoundingClientRect();
  const ghost = sample.cloneNode(true);
  ghost.removeAttribute("id");
  ghost.classList.add("handoff");
  Object.assign(ghost.style, { left: `${origin.left}px`, top: `${origin.top}px` });
  document.body.append(ghost);
  const targetX = innerWidth / 2 - origin.left - origin.width / 2;
  const animation = ghost.animate([
    { transform: "translate(0,0)", opacity: 1 },
    { transform: `translate(${targetX}px,${36 - origin.top}px) scale(.94)`, opacity: 0 },
  ], { duration: 310, easing: "cubic-bezier(.2,.75,.24,1)" });
  dashboard.animate([{ opacity: 1 }, { opacity: .55 }], { duration: 310 });
  try { await animation.finished; } finally { ghost.remove(); }
}

document.addEventListener("click", (event) => {
  const button = event.target.closest("button");
  if (!button || button.disabled || button.dataset.sound === "manual" ||
      ["start", "finish", "quit-confirm", "quit-cancel", "sound", "confirm-studying"].includes(button.id)) return;
  const { style } = button.dataset;
  const cue = style === "digits" ? "countdown" : style === "fill" ? "colorFill" : "tap";
  sound(cue, snapshot?.plan.sound ?? settings.sound);
}, { capture: true });

if (!pillPage && !alarmPage && !quitPage && !reminderPage) {
  root.classList.add("dashboard-root");
  dashboard.hidden = false;
  const info = $("dashboard-info");
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
  $("sites").value = settings.sites;
  $("blocked-sites").value = settings.blockedSites;
  $("allowed-apps").value = settings.allowedApps;
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
  $("sound").onclick = () => { settings.sound = !settings.sound; updateSettings(); sound("select", settings.sound); };
  setupDurationRuler();
  for (const button of document.querySelectorAll("[data-style]")) {
    button.onclick = () => { settings.style = button.dataset.style; updateSettings(); };
  }
  $("session-form").onsubmit = async (event) => {
    event.preventDefault();
    const start = $("start");
    start.disabled = true;
    status("dashboard-status");
    try {
      if (!pendingHandoff) {
        settings.goal = $("goal").value.trim();
        settings.sites = $("sites").value.trim();
        settings.blockedSites = $("blocked-sites").value.trim();
        settings.allowedApps = $("allowed-apps").value.trim();
        saveLocal("rusted-plan", settings);
        await command("begin", { plan: { ...settings } });
        pendingHandoff = true;
        sound("start", settings.sound);
      }
      await handoff();
      await command("show_pill");
      pendingHandoff = false;
      if (!desktop) await refreshPill();
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
  setInterval(async () => {
    if (reading) return;
    reading = true;
    try {
      const reminder = await command("reminder");
      if (!reminder) return;
      cueEnabled = reminder.sound;
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
  $("finish").textContent = complete ? "Finish" : "End early";
}

function updateFill(now) {
  fillFrame = undefined;
  if (!snapshot || snapshot.plan.style !== "fill") return;
  const elapsed = snapshot.elapsedSeconds + Math.max(0, now - snapshotAt) / 1000;
  visibleProgress = Math.max(visibleProgress, Math.min(1, elapsed / (snapshot.plan.minutes * 60)));
  $("fill").style.setProperty("--progress", String(visibleProgress));
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
  top.onclick = () => {
    if (dragged) { dragged = false; return; }
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
      pinned = false;
      expand(false);
      await command("show_dashboard");
      if (!desktop) await refreshHistory();
      snapshot = null;
    } catch (error) {
      status("pill-status", String(error));
    } finally { $("finish").disabled = false; }
  };
  let busy = false;
  setInterval(async () => {
    if (busy) return;
    busy = true;
    try { await refreshPill(); } finally { busy = false; }
  }, 200);
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
$("quit-input").addEventListener("paste", (event) => event.preventDefault());
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
