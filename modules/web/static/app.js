/*
File: Cully/modules/web/static/app.js
Description: The culling page. Renders /api/events, saves keep/reject through the API and shows the detail view.
Also has the status labels, filters, keyboard shortcuts, the Run panel (start main.py, watch it live),
the out-of-date banner, the Settings panel (Basic / Advanced tabs) and Export.
*/
"use strict";

const eventsEl = document.getElementById("events");
const summaryEl = document.getElementById("summary");
const filtersEl = document.querySelector(".filters");
const toastEl = document.getElementById("toast");
const detailEl = document.getElementById("detail");
const detailName = document.getElementById("detail-name");
const detailPreview = document.getElementById("detail-preview");
const detailMeta = document.getElementById("detail-meta");
const detailFaces = document.getElementById("detail-faces");
const helpEl = document.getElementById("help");
const runButton = document.getElementById("run-button");
const runPanel = document.getElementById("run-panel");
const runProgress = document.getElementById("run-progress");
const settingsButton = document.getElementById("settings-button");
const settingsPanel = document.getElementById("settings-panel");
const settingsForm = document.getElementById("settings-form");

const STATUS_LABELS = { keep: "✓ Kept", reject: "✕ Rejected" };

const cards = new Map(); // hash -> card button
let detailHash = null; // photo shown in the detail view
let toastTimer = null;


// ---------- Helpers ----------

/** Calls the API. Returns the JSON reply, throws Error(message) on failure. */
async function api(method, url, body) {
  const options = { method, headers: {} };
  if (body !== undefined) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }
  let response;
  try {
    response = await fetch(url, options);
  } catch {
    throw new Error("server not reachable");
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `${response.status} ${response.statusText}`);
  return data;
}

/** Makes an element. Text always goes in as text, never as HTML. */
function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function plural(n, word) {
  return `${n} ${word}${n === 1 ? "" : "s"}`;
}

/** "2008-03-30T18:43:37.000" -> "2008-03-30 18:43:37" */
function shortTime(iso) {
  return iso ? iso.replace("T", " ").slice(0, 19) : "unknown time";
}

/** Shows a short message at the bottom for 4 seconds. */
function toast(message) {
  toastEl.textContent = message;
  // Hide and show again, so it lands above an open dialog
  if (toastEl.matches(":popover-open")) toastEl.hidePopover();
  toastEl.showPopover();
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toastEl.hidePopover(), 4000);
}


// ---------- Rendering ----------

function renderSummary(s) {
  const parts = [
    [s.photos, "photos"], [s.events, "events"], [s.bursts, "bursts"],
    [s.candidates, "candidates", "good"], [s.eyes_closed, "eyes closed"], [s.unranked, "unranked"],
    [s.kept, "kept", "good"], [s.rejected, "rejected"], [s.unreviewed, "unreviewed"],
  ];
  summaryEl.replaceChildren();
  parts.forEach(([n, label, cls], i) => {
    if (i) summaryEl.append(" · ");
    const span = el("span", cls || "");
    span.append(el("b", "", String(n)), ` ${label}`);
    summaryEl.append(span);
  });
}

function cardEl(photo, burstId) {
  const card = el("button", "card");
  card.type = "button";
  card.dataset.hash = photo.hash;
  card.dataset.burst = burstId ?? "";
  card.dataset.status = photo.culled_status ?? "";
  card.dataset.candidate = photo.is_candidate ? "1" : "";
  card.dataset.ranked = photo.rank !== null ? "1" : "";
  card.dataset.name = photo.name;
  card.setAttribute("aria-label", photo.name);
  if (photo.is_candidate) card.classList.add("candidate");
  if (photo.rank === null) card.classList.add("unranked");

  const thumb = el("span", "thumb");
  const img = el("img");
  img.src = `/thumb/${photo.hash}`;
  img.alt = "";
  img.loading = "lazy";
  img.addEventListener("error", () => thumb.replaceChildren("Can't read file"));
  thumb.append(img);

  const badges = el("span", "badges");
  if (photo.is_candidate) badges.append(el("span", "badge good", "✓ Candidate"));
  if (photo.rank !== null) {
    badges.append(el("span", "badge rank", `#${photo.rank}`));
    badges.append(el("span", "badge", photo.score.toFixed(2)));
  }
  if (photo.eyes_open === false) badges.append(el("span", "badge bad", "Eyes closed"));
  if (photo.unranked_reason) badges.append(el("span", "badge muted", photo.unranked_reason));

  const caption = el("span", "caption");
  caption.append(badges, el("span", "name", photo.name), el("span", "status-label"));
  card.append(thumb, caption);

  cards.set(photo.hash, card);
  showStatus(card);
  return card;
}

/** One labelled group of cards, or null when it has none. */
function laneEl(kind, label, photos, burstId) {
  if (!photos.length) return null;
  const lane = el("div", `lane ${kind}`);
  const title = el("div", "lane-label", `${label} `);
  title.append(el("span", "", String(photos.length)));
  const row = el("div", "cards");
  photos.forEach((p) => row.append(cardEl(p, burstId)));
  lane.append(title, row);
  return lane;
}

function burstEl(burst) {
  const candidates = burst.photos.filter((p) => p.is_candidate);
  const rest = burst.photos.filter((p) => p.rank !== null && !p.is_candidate);
  const unranked = burst.photos.filter((p) => p.rank === null);

  const section = el("section", "burst");
  section.dataset.burst = burst.id;
  if (candidates.length) section.classList.add("has-candidate");

  const header = el("header");
  const status = candidates.length ? plural(candidates.length, "candidate") : "not ranked";
  header.append(
    el("h3", "", `Burst ${burst.number}`),
    el("span", "meta", `${shortTime(burst.start).slice(11)} · ${plural(burst.photos.length, "photo")} · ${status}`),
  );
  if (candidates.length || rest.length) {
    const accept = el("button", "accept", "Accept");
    accept.type = "button";
    accept.dataset.accept = burst.id;
    accept.title = "Keep the candidates, reject the other ranked photos";
    header.append(accept);
  }

  const lanes = el("div", "lanes");
  lanes.append(...[
    laneEl("keep", "Keep", candidates, burst.id),
    laneEl("rest", "Rest", rest, burst.id),
    laneEl("unranked", "Unranked", unranked, burst.id),
  ].filter(Boolean));
  section.append(header, lanes);
  return section;
}

/** The outer box shared by events and the loose photos. */
function eventBox(title, meta, children, hasCandidate) {
  const section = el("section", "event");
  if (hasCandidate) section.classList.add("has-candidate");
  const head = el("header", "event-head");
  head.append(el("h2", "", title), el("span", "meta", meta));
  const bursts = el("div", "bursts");
  bursts.append(...children);
  section.append(head, bursts);
  return section;
}

function eventEl(event) {
  const photos = event.bursts.flatMap((b) => b.photos);
  const candidates = photos.filter((p) => p.is_candidate).length;
  const start = shortTime(event.start);
  const end = shortTime(event.end);
  let span = `${start} – ${end}`;
  if (start === end) span = start;
  else if (start.slice(0, 10) === end.slice(0, 10)) span = `${start} – ${end.slice(11)}`;
  const meta = `${span} · ${event.camera || "unknown camera"} · ${plural(event.bursts.length, "burst")} · `
    + `${plural(photos.length, "photo")} · ${plural(candidates, "candidate")}`;
  return eventBox(`Event ${event.number}`, meta, event.bursts.map(burstEl), candidates > 0);
}

function looseEl(photos) {
  const box = el("section", "burst");
  const lanes = el("div", "lanes");
  lanes.append(laneEl("unranked", "Unranked", photos, null));
  box.append(lanes);
  const meta = `${plural(photos.length, "photo")} · can't be grouped into bursts`;
  return eventBox("No capture time", meta, [box], false);
}


// ---------- Loading ----------

async function loadSummary() {
  try {
    renderSummary(await api("GET", "/api/summary"));
  } catch (error) {
    summaryEl.textContent = `Summary unavailable: ${error.message}`;
  }
}

async function load() {
  try {
    const data = await api("GET", "/api/events");
    cards.clear();
    const sections = data.events.map(eventEl);
    if (data.loose.length) sections.push(looseEl(data.loose));
    if (!sections.length) sections.push(el("p", "meta", "No photos in this catalog yet."));
    eventsEl.replaceChildren(...sections);
  } catch (error) {
    eventsEl.replaceChildren(el("p", "meta", `Couldn't load photos: ${error.message}`));
  }
  loadSummary();
  loadStaleness();
}


// ---------- Culling ----------

/** Sets a card's status on the page only (no saving). */
function applyStatus(card, status) {
  card.dataset.status = status;
  showStatus(card);
  if (card.dataset.hash === detailHash) updateDetailButtons();
}

/** Shows the card's status as text, so it doesn't rely on colour alone. */
function showStatus(card) {
  card.querySelector(".status-label").textContent = STATUS_LABELS[card.dataset.status] ?? "";
}

/** Marks one photo keep, reject or null. The card changes at once and rolls back if saving fails. */
async function setStatus(hash, status) {
  const card = cards.get(hash);
  if (!card) return;
  const before = card.dataset.status;
  const after = status || "";
  if (before === after) return;
  applyStatus(card, after);
  try {
    await api("PUT", `/api/photos/${hash}/status`, { status: status || null });
  } catch (error) {
    applyStatus(card, before);
    toast(`Couldn't save ${card.dataset.name}: ${error.message}`);
  }
  loadSummary();
}

/** Keeps a burst's candidates and rejects its other ranked photos, skipping photos already marked. */
async function acceptBurst(burstId) {
  if (!burstId) {
    toast("This photo isn't in a burst");
    return;
  }
  try {
    const result = await api("POST", `/api/bursts/${burstId}/accept`, {});
    // Same rule as the server, so the page matches without a reload
    for (const card of eventsEl.querySelectorAll(`.card[data-burst="${burstId}"]`)) {
      if (card.dataset.status || !card.dataset.ranked) continue;
      applyStatus(card, card.dataset.candidate ? "keep" : "reject");
    }
    toast(`Burst accepted: kept ${result.kept}, rejected ${result.rejected}`);
  } catch (error) {
    toast(`Couldn't accept the burst: ${error.message}`);
  }
  loadSummary();
}


// ---------- Detail view ----------

function isDetailOpen() {
  return detailEl.open;
}

function closeDetail() {
  if (detailEl.open) detailEl.close();
}

function updateDetailButtons() {
  const card = cards.get(detailHash);
  const status = card ? card.dataset.status : "";
  for (const button of detailEl.querySelectorAll("[data-set]")) {
    if (button.dataset.set) button.setAttribute("aria-pressed", String(button.dataset.set === status));
  }
}

/** Opens the full-screen view of one photo: big preview, then each face with its numbers. */
async function openDetail(hash) {
  const card = cards.get(hash);
  detailHash = hash;
  detailName.textContent = card ? card.dataset.name : "";
  detailPreview.src = `/preview/${hash}`;
  detailPreview.alt = card ? card.dataset.name : "";
  detailMeta.textContent = "Loading…";
  detailFaces.replaceChildren();
  updateDetailButtons();
  if (!detailEl.open) detailEl.showModal();

  let photo;
  try {
    photo = await api("GET", `/api/photos/${hash}`);
  } catch (error) {
    detailMeta.textContent = `Couldn't load details: ${error.message}`;
    return;
  }
  if (detailHash !== hash) return; // another photo was opened meanwhile

  const size = photo.width && photo.height ? `${photo.width} × ${photo.height}` : "unknown size";
  const meta = [photo.camera || "unknown camera", shortTime(photo.capture_time), size];
  if (photo.rank !== null) meta.push(`rank #${photo.rank}`, `score ${photo.score.toFixed(2)}`);
  if (photo.unranked_reason) meta.push(`Unranked: ${photo.unranked_reason}`);
  meta.push(photo.path);
  detailMeta.textContent = meta.join(" · ");

  if (!photo.faces.length) {
    detailFaces.append(el("p", "meta", "No usable face in this photo."));
    return;
  }
  for (const face of photo.faces) {
    const figure = el("figure", "face");
    const img = el("img");
    img.src = `/face/${face.id}`;
    img.alt = "Face crop";
    img.loading = "lazy";
    const ear = face.ear_left === null ? "EAR –" : `EAR ${face.ear_left.toFixed(2)} / ${face.ear_right.toFixed(2)}`;
    const sharp = face.sharpness === null ? "sharpness –" : `sharpness ${face.sharpness.toFixed(0)}`;
    figure.append(img, el("figcaption", "", `${sharp} · ${ear} · ${face.confidence.toFixed(0)}%`));
    detailFaces.append(figure);
  }
}

detailEl.addEventListener("click", (event) => {
  const button = event.target.closest("button");
  if (!button) return;
  if (button.classList.contains("close")) closeDetail();
  else if ("set" in button.dataset) setStatus(detailHash, button.dataset.set || null);
});

detailEl.addEventListener("close", () => {
  const card = cards.get(detailHash);
  detailHash = null;
  detailPreview.removeAttribute("src");
  if (card) card.focus();
});


// ---------- Page events ----------

// One listener for every card and Accept button (event delegation)
eventsEl.addEventListener("click", (event) => {
  const accept = event.target.closest("[data-accept]");
  if (accept) {
    acceptBurst(accept.dataset.accept);
    return;
  }
  const card = event.target.closest(".card");
  if (card) openDetail(card.dataset.hash); // Enter on a focused card clicks it too
});

/** Returns back the cards shown right now, in page order. */
function visibleCards() {
  return [...eventsEl.querySelectorAll(".card")].filter((card) => card.offsetParent !== null);
}

/** Focuses a card and scrolls it into view. */
function focusCard(card) {
  card.focus({ preventScroll: true });
  card.scrollIntoView({ block: "nearest", inline: "nearest" });
}

/** Moves focus step cards forward (1) or back (-1). With no card focused it goes to the first one. */
function moveFocus(card, step) {
  const visible = visibleCards();
  const index = visible.indexOf(card);
  const next = index === -1 ? visible[0] : visible[index + step];
  if (next) focusCard(next);
}

/** Marks the card, then moves on to the next card (mark and advance). */
function markAndAdvance(card, status) {
  if (!card) return;
  const visible = visibleCards();
  const index = visible.indexOf(card);
  setStatus(card.dataset.hash, status);
  //At the end, only step back if the card vanished under a filter
  let next = visible[index + 1];
  if (!next && card.offsetParent === null) next = visible[index - 1];
  if (next) focusCard(next);
}

/** Calls setFilter for the clicked filter button. */
function onFilterClick(event) {
  const button = event.target.closest("button[data-filter]");
  if (!button) return;
  setFilter(button.dataset.filter);
}

/** Shows only the photos matching name. The CSS reads body[data-filter] to hide the rest. */
function setFilter(name) {
  document.body.dataset.filter = name;
  for (const button of filtersEl.querySelectorAll("button[data-filter]")) {
    button.setAttribute("aria-pressed", String(button.dataset.filter === name));
  }
  //If the focused card got hidden, focus the first card still shown
  const card = document.activeElement?.closest(".card");
  if (card && card.offsetParent === null) {
    const first = visibleCards()[0];
    if (first) focusCard(first);
  }
}

/** Keyboard culling. Arrows move, K/X/U keep/reject/clear, A accepts the burst, ? toggles the help. */
function onKey(event) {
  //Leave browser shortcuts, typing and the detail view alone
  if (event.ctrlKey || event.metaKey || event.altKey) return;
  if (event.target.closest("input, textarea, select")) return;
  if (isDetailOpen()) return;
  if (event.target.closest("#run-panel, #settings-panel")) return; //The panels have their own buttons

  const card = document.activeElement?.closest(".card") ?? null;
  //"?" is Shift+/ so don't lower-case it
  const key = event.key === "?" ? "?" : event.key.toLowerCase();
  switch (key) {
    case "arrowright": moveFocus(card, 1); break;
    case "arrowleft": moveFocus(card, -1); break;
    case "k": markAndAdvance(card, "keep"); break;
    case "x": markAndAdvance(card, "reject"); break;
    case "u": markAndAdvance(card, null); break;
    case "a": if (card) acceptBurst(card.dataset.burst); break;
    case "?": helpEl.togglePopover(); break;
    default: return; //Not ours, let the browser have it
  }
  event.preventDefault();
}

filtersEl.addEventListener("click", onFilterClick);
document.addEventListener("keydown", onKey);


// ---------- Run panel ----------

const $ = (id) => document.getElementById(id);
let folderPath = null; // folder shown in the picker, the one Start runs on
let folderPhotos = 0;
let importTo = null; // where a card's photos get copied, null when the folder isn't on a card
let runSource = null; // EventSource while following a run
let reloadedFor = null; // started_at of the run whose results were last reloaded

/** "m:ss" for a number of seconds */
function clock(seconds) {
  const s = Math.max(0, Math.round(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

function openRunPanel() {
  closeSettings(false);
  if (!settingsPanel.hidden) return; // kept open for unsaved changes
  runPanel.hidden = false;
  runButton.setAttribute("aria-expanded", "true");
  //Reload every time, so a card put in since shows up
  loadFolders(folderPath);
  runPanel.querySelector(".close").focus();
}

function closeRunPanel(refocus = true) {
  if (runPanel.hidden) return;
  runPanel.hidden = true;
  runButton.setAttribute("aria-expanded", "false");
  if (refocus) runButton.focus();
}

/** Shows path's sub-folders in the picker. null means the home folder. */
async function loadFolders(path) {
  const url = path ? `/api/folders?path=${encodeURIComponent(path)}` : "/api/folders";
  let data;
  try {
    data = await api("GET", url);
  } catch (error) {
    toast(`Couldn't list folders: ${error.message}`);
    //A card that was taken out: go back home
    if (path !== null) loadFolders(null);
    return;
  }
  folderPath = data.path;
  folderPhotos = data.photos;
  importTo = data.import_to;
  $("folder-path").textContent = data.path;
  $("folder-path").title = data.path;
  $("folder-up").disabled = data.parent === null;
  $("folder-places").replaceChildren(...data.roots.map((root) => {
    const button = el("button", "place", root.name === "Home" ? "⌂ Home" : `💾 ${root.name}`);
    button.type = "button";
    button.dataset.path = root.path;
    button.title = root.path;
    button.setAttribute("aria-pressed", String(root.path === data.root));
    return button;
  }));
  $("folder-up").dataset.path = data.parent ?? "";

  const items = data.folders.map((folder) => {
    const button = el("button", "folder");
    button.type = "button";
    button.dataset.path = folder.path;
    button.append(el("span", "", folder.name));
    if (folder.photos) button.append(el("span", "badge", plural(folder.photos, "photo")));
    const item = el("li");
    item.append(button);
    return item;
  });
  if (!items.length) items.push(el("li", "meta", "No sub-folders"));
  $("folder-list").replaceChildren(...items);
  if (importTo) {
    $("folder-count").textContent = data.photos
      ? `${plural(data.photos, "photo")} here and in sub-folders. New ones are copied to ${importTo} first, then run.`
      : "No photos on this part of the card.";
  } else {
    $("folder-count").textContent = data.photos
      ? `${plural(data.photos, "photo")} in this folder (sub-folders aren't scanned)`
      : "No photos in this folder itself. Open a sub-folder.";
  }
  $("run-start").textContent = importTo ? "Copy and run" : "Start run";
  updateStart();
}

/** Start works when a folder with photos is chosen and nothing is running. */
function updateStart(running = runButton.dataset.running === "1") {
  $("run-start").disabled = running || !folderPhotos;
}

function stepLine(step, state) {
  const done = state.finished.find((f) => f.step === step);
  const item = el("li");
  if (done) {
    item.className = "finished";
    item.append(el("span", "icon", "✓"), el("span", "", `${step}: ${done.result} (${done.seconds}s)`));
  } else if (step === state.current_step) {
    item.className = "current";
    item.append(el("span", "icon spinner"), el("span", "", `${step}…`));
  } else {
    item.className = "waiting";
    item.append(el("span", "icon", "–"), el("span", "", step));
  }
  return item;
}

/** Draws a run state in the panel and on the Run button. */
function renderRun(state) {
  runButton.dataset.running = state.running ? "1" : "";
  runButton.textContent = state.running ? "Running…" : "Run";
  updateStart(state.running);
  $("stale-rerank").disabled = state.running;
  $("stale-redo").disabled = state.running;
  settingsLocked = state.running;
  updateSettingsButtons();
  if (state.steps?.includes("download") && settingsData) showDownload(state);
  else updateModelStatus();
  $("export-start").disabled = state.running || !exportReady;
  if (!state.started_at) return; // nothing has run since the server started
  runProgress.hidden = false;

  const exporting = state.steps.includes("export");
  const downloading = state.steps.includes("download");
  $("run-folder").textContent = downloading
    ? (state.running ? "Downloading a model" : "Last model download")
    : exporting
    ? (state.running ? "Exporting kept photos" : "Last export")
    : `${state.running ? "Running on" : "Last run on"} ${state.folder ?? "the whole catalog"}`;
  $("run-steps").replaceChildren(...state.steps.map((step) => stepLine(step, state)));

  //A bar with no value shows as "busy", for model loading before the first photo
  const bar = $("run-bar");
  bar.hidden = !state.running;
  if (state.current_step && state.total) bar.value = state.done / state.total;
  else bar.removeAttribute("value");

  let count = "";
  if (state.running && state.current_step && state.total) {
    count = `${state.current_step} ${state.done}/${state.total}`;
    if (state.done && state.step_started_at) {
      const elapsed = Date.now() / 1000 - state.step_started_at;
      count += ` · about ${clock((elapsed / state.done) * (state.total - state.done))} left`;
    }
  } else if (state.running && state.current_step) {
    count = `${state.current_step}: loading…`;
  }
  $("run-count").textContent = count;
  $("run-file").textContent = state.running ? state.file : "";
  $("run-cancel").hidden = !state.running || state.cancelled;

  const result = $("run-result");
  const log = $("run-log");
  result.className = "run-result";
  if (state.running) {
    result.textContent = state.cancelled ? "Cancelling…" : "";
    log.hidden = true;
  } else if (state.error) {
    result.classList.add("bad");
    result.textContent = state.error;
    log.textContent = state.log.join("\n");
    log.hidden = !state.log.length;
  } else {
    const s = state.summary;
    result.classList.add("good");
    //Runs without ranking (export) have no counts
    result.textContent = s && "bursts" in s
      ? `Done: ${plural(s.bursts, "burst")}, ${plural(s.candidates, "candidate")}, ${s.unranked} unranked.`
      : "Done.";
    log.hidden = true;
  }

  //New results: once ranking has finished, or when the run ends well
  const ranked = state.finished.some((f) => f.step === "ranking");
  if ((ranked || (!state.running && state.exit_code === 0)) && reloadedFor !== state.started_at) {
    reloadedFor = state.started_at;
    load();
  }
}

/** Follows the run live until it ends. */
function followRun() {
  if (runSource) return;
  runSource = new EventSource("/api/run/events");
  runSource.onmessage = (event) => {
    const state = JSON.parse(event.data);
    renderRun(state);
    if (!state.running) stopFollowing();
  };
  runSource.onerror = () => {
    //Server gone or restarted: stop the browser's own retries and check again in a bit
    stopFollowing();
    toast("Lost the connection to the server, retrying…");
    setTimeout(checkRun, 3000);
  };
}

function stopFollowing() {
  if (runSource) runSource.close();
  runSource = null;
}

/** Picks up a run that's going (for example after a page reload). */
async function checkRun() {
  try {
    const state = await api("GET", "/api/run");
    //Don't reload results for a run that ended before this page opened
    if (reloadedFor === null && !state.running) reloadedFor = state.started_at;
    renderRun(state);
    if (state.running) followRun();
  } catch {
    setTimeout(checkRun, 5000);
  }
}

/** Starts a run with body (see POST /api/run) and follows it. */
async function runWith(body) {
  try {
    const state = await api("POST", "/api/run", body);
    renderRun(state);
    followRun();
    return true;
  } catch (error) {
    toast(`Couldn't start the run: ${error.message}`);
    return false;
  }
}

function startRun() {
  const body = { folder: folderPath, embeddings: $("run-embeddings").checked };
  if (importTo) body.import = true;
  runWith(body);
}


// ---------- Out-of-date banner ----------

let staleRedoCount = 0;

/** Shows the banner when settings changed since the pipeline last ran. */
async function loadStaleness() {
  let s;
  try {
    s = await api("GET", "/api/staleness");
  } catch {
    return; // the banner is a hint, the page works without it
  }
  const parts = [];
  //Redoing objects redoes faces too, so objects decides
  const redo = s.objects ? "objects" : s.faces ? "faces" : null;
  staleRedoCount = s.objects || s.faces;
  if (s.objects) parts.push(`${plural(s.objects, "photo")} had people found with older settings`);
  else if (s.faces) parts.push(`${plural(s.faces, "photo")} had faces found with older settings`);
  if (s.ranking || s.sharpness) parts.push("the ranking used older settings");

  $("stale").hidden = !s.any;
  $("stale-text").textContent = `Settings changed since the pipeline last ran: ${parts.join(", and ")}.`;
  $("stale-redo").hidden = !redo;
  $("stale-redo").dataset.redo = redo ?? "";
  //A redo re-ranks too, so only offer Re-rank on its own
  $("stale-rerank").hidden = !(s.ranking || s.sharpness) || !!redo;
  //The same two buttons in the Settings panel, which covers the banner on wide screens
  $("settings-rerank").hidden = $("stale-rerank").hidden;
  $("settings-redo").hidden = $("stale-redo").hidden;
}

$("stale-rerank").addEventListener("click", async () => {
  if (await runWith({ steps: ["sharpness", "ranking"] })) openRunPanel();
});

$("stale-redo").addEventListener("click", async () => {
  const step = $("stale-redo").dataset.redo;
  const what = step === "objects" ? "people and faces" : "faces";
  const ok = confirm(
    `Redo detection for ${plural(staleRedoCount, "photo")}?\n\n`
    + `Their stored ${what} are deleted and found again with the current settings, then everything is re-ranked. `
    + "Your keep/reject choices stay. This can take a while."
  );
  if (ok && (await runWith({ redo: step }))) openRunPanel();
});

async function cancelRun() {
  try {
    renderRun(await api("POST", "/api/run/cancel", {}));
  } catch (error) {
    toast(`Couldn't cancel: ${error.message}`);
  }
}

runButton.addEventListener("click", () => (runPanel.hidden ? openRunPanel() : closeRunPanel()));
runPanel.addEventListener("click", (event) => {
  const button = event.target.closest("button");
  if (!button) return;
  if (button.classList.contains("close")) closeRunPanel();
  else if (button.classList.contains("folder") || button.classList.contains("place")) loadFolders(button.dataset.path);
  else if (button.id === "folder-up") loadFolders(button.dataset.path);
  else if (button.id === "run-start") startRun();
  else if (button.id === "run-cancel") cancelRun();
});
runPanel.addEventListener("keydown", (event) => {
  if (event.key === "Escape") closeRunPanel();
});



// ---------- Settings panel ----------

const APPLIES = {
  next_run: "Takes effect at the next ranking (Re-rank, seconds).",
  new_photos: "Takes effect for new photos. Older ones show in the out-of-date banner (Redo detection).",
  next_import: "Takes effect at the next card import.",
};
let settingsData = null; // last GET /api/settings
let settingsLocked = false; // a run is going
const dirty = new Set(); // keys changed in the form but not saved

/** "group.key" or "key" -> the value inside a nested settings dict */
function lookup(values, key) {
  const [group, sub] = key.split(".");
  return sub === undefined ? values[group] : values[group][sub];
}

function showValue(value) {
  return typeof value === "boolean" ? (value ? "on" : "off") : String(value);
}

/** One form row for a setting: label, control, help, when it applies and the default. */
function settingRow(key, info) {
  const value = lookup(settingsData.values, key);
  const fallback = lookup(settingsData.defaults, key);
  const id = `set-${key.replace(".", "-")}`;
  const row = el("div", "setting");
  row.dataset.key = key;
  if (!info.basic) row.classList.add("advanced");
  if (value !== fallback) row.classList.add("changed");

  let control;
  if (info.type === "model") {
    control = modelSelect(value);
  } else if (info.type === "boolean") {
    control = el("input");
    control.type = "checkbox";
    control.checked = value;
  } else if (info.type === "choice") {
    control = el("select");
    for (const choice of info.choices) {
      const option = el("option", "", choice);
      option.value = choice;
      control.append(option);
    }
    control.value = value;
  } else {
    control = el("input");
    if (info.type === "text") {
      control.type = "text";
    } else {
      control.type = "number";
      control.min = info.min;
      control.max = info.max;
      control.step = info.step;
      control.inputMode = info.type === "integer" ? "numeric" : "decimal";
    }
    control.value = value;
  }
  control.id = id;
  control.name = key;

  const label = el("label", "", info.label + (info.unit ? ` (${info.unit})` : ""));
  label.htmlFor = id;
  const help = el("p", "hint", info.help);
  const meta = el("p", "hint muted", `${APPLIES[info.applies]} Default: ${showValue(fallback)}.`);
  row.append(label, control, help, meta);
  if (info.type === "model") row.append(modelStatus());
  return row;
}

// ---------- Person detector models ----------

/** A drop-down of the official models by family, then the custom ones. */
function modelSelect(value) {
  const { official, custom } = settingsData.models;
  const select = el("select");
  const groups = new Map();
  for (const model of official) {
    if (!groups.has(model.family)) groups.set(model.family, el("optgroup"));
    groups.get(model.family).label = model.family;
    const option = el("option", "", `${model.family} ${model.size}${model.mb ? "" : " (not downloaded)"}`);
    option.value = model.name;
    groups.get(model.family).append(option);
  }
  select.append(...groups.values());
  if (custom.length) {
    const yours = el("optgroup");
    yours.label = "Your models";
    for (const model of custom) {
      const option = el("option", "", model.name);
      option.value = model.name;
      yours.append(option);
    }
    select.append(yours);
  }
  //A saved model that's no longer in the folder still shows, so the form doesn't change it silently
  if (![...select.options].some((o) => o.value === value)) {
    const missing = el("option", "", `${value} (missing)`);
    missing.value = value;
    select.append(missing);
  }
  select.value = value;
  return select;
}

/** The note and Download button under the model drop-down. */
function modelStatus() {
  const box = el("div", "hint model-status");
  const text = el("span");
  text.id = "model-status";
  const download = el("button", "", "Download");
  download.type = "button";
  download.id = "model-download";
  download.addEventListener("click", downloadModel);
  box.append(text, download);
  return box;
}

function selectedModel() {
  const name = settingsForm.elements.YOLOModel?.value;
  const { official, custom } = settingsData.models;
  return { name, official: official.find((m) => m.name === name), custom: custom.find((m) => m.name === name) };
}

/** Says what the chosen model is and whether it's installed. */
function updateModelStatus(progress = "") {
  const text = $("model-status");
  if (!text) return;
  const { official, custom } = selectedModel();
  const download = $("model-download");
  download.hidden = !official || !!official.mb || !!progress;
  download.disabled = settingsLocked;
  if (progress) text.textContent = progress;
  else if (official) {
    text.textContent = official.mb
      ? `${official.note} Installed (${official.mb} MB).`
      : `${official.note} Not downloaded yet: download it now, or it downloads when detection next runs.`;
  } else if (custom) {
    text.textContent = `Your model (${custom.mb} MB). It needs a 'person' class.`;
  } else {
    text.textContent = `Not found in ${settingsData.models.folder}.`;
  }
  //Custom trained models go here
  text.title = `Models folder: ${settingsData.models.folder}`;
}

async function downloadModel() {
  try {
    const state = await api("POST", "/api/models/download", { name: selectedModel().name });
    renderRun(state);
    followRun();
  } catch (error) {
    settingsNote(`Couldn't download: ${error.message}`, "bad");
  }
}

/** Download progress in the Settings panel; reloads the model list when it's done. */
async function showDownload(state) {
  if (state.running) {
    const mb = state.total ? `${state.done} of ${state.total} MB` : "starting…";
    updateModelStatus(`Downloading ${state.file || "model"}: ${mb}`);
    return;
  }
  if (downloadShownFor === state.started_at) return;
  downloadShownFor = state.started_at;
  try {
    settingsData.models = (await api("GET", "/api/settings")).models;
  } catch {
    //Keeps the old list, the next open reloads it
  }
  const select = settingsForm.elements.YOLOModel;
  if (select) select.replaceWith(Object.assign(modelSelect(select.value), { id: select.id, name: select.name }));
  updateModelStatus();
  if (state.error) settingsNote(state.error, "bad");
  else settingsNote(state.finished[0]?.result ?? "Downloaded.", "good");
}
let downloadShownFor = null;

/** Builds the form from settingsData, one fieldset per group in the order they first appear. */
function renderSettings() {
  const groups = new Map();
  for (const key of settingsData.order) {
    const info = settingsData.info[key];
    if (info.hidden) continue;
    if (!groups.has(info.group)) groups.set(info.group, []);
    groups.get(info.group).push(settingRow(key, info));
  }
  const sets = [...groups].map(([name, rows]) => {
    const set = el("fieldset");
    set.append(el("legend", "", name), ...rows);
    return set;
  });
  const where = el("p", "meta", `Saved in ${settingsData.path}. Custom trained models go in ${settingsData.models.folder}.`);
  settingsForm.replaceChildren(...basicNotes(), ...sets, where);
  dirty.clear();
  updateSettingsButtons();
  updateModelStatus();
}

/** Basic tab only: a tip, and a heads-up when advanced settings aren't at their defaults. */
function basicNotes() {
  const notes = [el("p", "basic-only", "These cover most shoots. Advanced has every setting.")];
  const changed = settingsData.order.filter((key) => {
    const info = settingsData.info[key];
    return !info.hidden && !info.basic && lookup(settingsData.values, key) !== lookup(settingsData.defaults, key);
  }).length;
  if (changed) {
    const show = el("button", "link-button", "Show them");
    show.type = "button";
    show.addEventListener("click", () => showSettingsView("advanced", true));
    const note = el("p", "basic-only", `${plural(changed, "advanced setting")} ${changed === 1 ? "is" : "are"} changed from default. `);
    note.id = "advanced-changed";
    note.append(show);
    notes.push(note);
  }
  return notes;
}

const VIEW_KEY = "cully.settingsView";

/** Shows the Basic or Advanced tab. Rows stay in the form, so unsaved edits survive the switch. */
function showSettingsView(view, focus = false) {
  settingsForm.dataset.view = view;
  for (const tab of document.querySelectorAll(".settings-tabs [role=tab]")) {
    const selected = tab.dataset.view === view;
    tab.setAttribute("aria-selected", String(selected));
    tab.tabIndex = selected ? 0 : -1;
    if (selected && focus) tab.focus();
  }
  try {
    localStorage.setItem(VIEW_KEY, view);
  } catch {
    //Storage blocked: the tab just isn't remembered
  }
}

function savedSettingsView() {
  try {
    return localStorage.getItem(VIEW_KEY) === "advanced" ? "advanced" : "basic";
  } catch {
    return "basic";
  }
}

function updateSettingsButtons() {
  $("settings-save").disabled = settingsLocked || !dirty.size;
  $("settings-reset").disabled = settingsLocked;
  $("settings-rerank").disabled = settingsLocked;
  $("settings-redo").disabled = settingsLocked;
  $("settings-redo-all").disabled = settingsLocked;
  const lockNote = "A run is going. Settings can change once it's done.";
  if (settingsLocked) settingsNote(lockNote, "");
  else if ($("settings-note").textContent === lockNote) settingsNote("", "");
}

function settingsNote(text, kind) {
  const note = $("settings-note");
  note.textContent = text;
  note.className = `settings-note ${kind}`;
}

async function openSettings() {
  closeRunPanel(false);
  settingsPanel.hidden = false;
  settingsButton.setAttribute("aria-expanded", "true");
  settingsNote("", "");
  try {
    settingsData = await api("GET", "/api/settings");
    renderSettings();
  } catch (error) {
    settingsNote(`Couldn't load settings: ${error.message}`, "bad");
  }
  settingsPanel.querySelector(".close").focus();
}

function closeSettings(refocus = true) {
  if (settingsPanel.hidden) return;
  if (dirty.size && !confirm("Close without saving your changes?")) return;
  dirty.clear();
  settingsPanel.hidden = true;
  settingsButton.setAttribute("aria-expanded", "false");
  if (refocus) settingsButton.focus();
}

/** The changed fields as a partial update, e.g. {ranking: {eye_gate: 0.5}}. Throws on a bad number. */
function changedSettings() {
  const body = {};
  for (const key of dirty) {
    const info = settingsData.info[key];
    const control = settingsForm.elements[key];
    let value = control.value;
    if (info.type === "boolean") value = control.checked;
    else if (info.type === "integer" || info.type === "number") {
      value = info.type === "integer" ? Number.parseInt(control.value, 10) : Number.parseFloat(control.value);
      if (Number.isNaN(value)) throw new Error(`${info.label} needs a number`);
    }
    const [group, sub] = key.split(".");
    if (sub === undefined) body[group] = value;
    else (body[group] ??= {})[sub] = value;
  }
  return body;
}

settingsForm.addEventListener("input", (event) => {
  const row = event.target.closest(".setting");
  if (!row) return;
  if (row.dataset.key === "YOLOModel") updateModelStatus();
  dirty.add(row.dataset.key);
  row.classList.add("dirty");
  settingsNote(`${plural(dirty.size, "unsaved change")}`, "");
  updateSettingsButtons();
});

settingsForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!dirty.size || settingsLocked) return;
  let body;
  try {
    body = changedSettings();
    settingsData = await api("PUT", "/api/settings", body);
  } catch (error) {
    //The server's message names the setting and the allowed range
    settingsNote(error.message.replace(/\[settings\.py\]\s*/g, ""), "bad");
    return;
  }
  renderSettings();
  settingsNote("Saved.", "good");
  loadStaleness(); // the banner says what the change left out of date
  loadSummary();
});

$("settings-reset").addEventListener("click", async () => {
  if (!confirm("Put every setting back to its default? This includes the Advanced ones.")) return;
  try {
    settingsData = await api("POST", "/api/settings/reset", {});
  } catch (error) {
    settingsNote(error.message, "bad");
    return;
  }
  renderSettings();
  settingsNote("All settings are back to their defaults.", "good");
  loadStaleness();
});

document.querySelector(".settings-tabs").addEventListener("click", (event) => {
  const tab = event.target.closest("[role=tab]");
  if (tab) showSettingsView(tab.dataset.view);
});
document.querySelector(".settings-tabs").addEventListener("keydown", (event) => {
  //Two tabs, so either arrow switches to the other one
  if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
  event.preventDefault();
  showSettingsView(settingsForm.dataset.view === "basic" ? "advanced" : "basic", true);
});
showSettingsView(savedSettingsView());

$("settings-rerank").addEventListener("click", () => $("stale-rerank").click());
$("settings-redo").addEventListener("click", () => $("stale-redo").click());
$("settings-redo-all").addEventListener("click", async () => {
  //The run reads the saved settings, so unsaved edits would be ignored
  if (dirty.size) {
    settingsNote("Save or reset your changes before redoing everything.", "bad");
    return;
  }
  //Redoes every photo, settings changed or not, so warn first
  const ok = confirm(
    "Force redo everything?\n\n"
    + "Every photo's people, faces, eye checks and sharpness scores are deleted and found again "
    + "from scratch, even if nothing changed. Then everything is re-ranked.\n\n"
    + "Your keep/reject choices stay. This runs on the whole catalog and can take a long time."
  );
  if (ok && (await runWith({ redo: "objects", all: true }))) openRunPanel();
});
settingsButton.addEventListener("click", () => (settingsPanel.hidden ? openSettings() : closeSettings()));
settingsPanel.querySelector(".close").addEventListener("click", () => closeSettings());
settingsPanel.addEventListener("keydown", (event) => {
  if (event.key === "Escape") closeSettings();
});



// ---------- Export ----------

const exportEl = $("export");
let exportReady = false; // something is kept and nothing is running

let exportInfo = null; // last GET /api/export

function exportMode() {
  return exportEl.querySelector("input[name=export-mode]:checked").value;
}

/** Fills the export popover with the current counts. */
async function loadExport() {
  $("export-start").disabled = true;
  try {
    exportInfo = await api("GET", "/api/export");
  } catch (error) {
    $("export-text").textContent = `Couldn't count the kept photos: ${error.message}`;
    return;
  }
  exportEl.querySelector(`input[value=${exportInfo.mode}]`).checked = true;
  showExport();
}

/** The popover's text and button for the chosen mode. */
function showExport() {
  const info = exportInfo;
  if (!info) return;
  let text, note;
  if (exportMode() === "copy") {
    exportReady = info.kept > 0;
    text = info.kept
      ? `Copy ${plural(info.kept, "kept photo")} to ${info.folder}, one folder per event, rated ${info.rating}★ for darktable and Lightroom. Photos already there only get their rating updated.`
      : "Nothing is marked keep yet. Press K on a photo to keep it.";
    note = info.undecided
      ? `${plural(info.undecided, "suggestion")} ${info.undecided === 1 ? "is" : "are"} still undecided and won't be copied.`
      : "";
  } else {
    exportReady = info.kept + info.rejected > 0;
    text = exportReady
      ? `Write a rating file next to each original: ${plural(info.kept, "kept photo")} get ${info.rating}★, ${plural(info.rejected, "rejected photo")} show as rejected. Nothing is copied. Import the original folders into your editor.`
      : "Nothing is marked keep or reject yet.";
    note = "JPEG ratings this way reach darktable only, Lightroom ignores JPEG sidecars. Sidecars your editor already made are left alone.";
  }
  $("export-text").textContent = text;
  $("export-undecided").textContent = note;
  $("export-start").disabled = !exportReady || runButton.dataset.running === "1";
}

exportEl.addEventListener("change", showExport);

exportEl.addEventListener("toggle", (event) => {
  if (event.newState === "open") loadExport();
});

$("export-start").addEventListener("click", async () => {
  try {
    const state = await api("POST", "/api/export", { mode: exportMode() });
    exportEl.hidePopover();
    renderRun(state);
    followRun();
    openRunPanel();
  } catch (error) {
    toast(`Couldn't start the export: ${error.message}`);
  }
});

load();
checkRun();
