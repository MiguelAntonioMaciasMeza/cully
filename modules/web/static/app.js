/*
File: Cully/modules/web/static/app.js
Description: The culling page. Renders /api/events, saves keep/reject through the API and shows the detail view.
Also has the status labels, filters, keyboard shortcuts and the Run panel (start main.py, watch it live).
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
  if (event.target.closest("#run-panel")) return; //The panel has its own buttons

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
let runSource = null; // EventSource while following a run
let reloadedFor = null; // started_at of the run whose results were last reloaded

/** "m:ss" for a number of seconds */
function clock(seconds) {
  const s = Math.max(0, Math.round(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

function openRunPanel() {
  runPanel.hidden = false;
  runButton.setAttribute("aria-expanded", "true");
  if (folderPath === null) loadFolders(null);
  runPanel.querySelector(".close").focus();
}

function closeRunPanel() {
  runPanel.hidden = true;
  runButton.setAttribute("aria-expanded", "false");
  runButton.focus();
}

/** Shows path's sub-folders in the picker. null means the home folder. */
async function loadFolders(path) {
  const url = path ? `/api/folders?path=${encodeURIComponent(path)}` : "/api/folders";
  let data;
  try {
    data = await api("GET", url);
  } catch (error) {
    toast(`Couldn't list folders: ${error.message}`);
    return;
  }
  folderPath = data.path;
  folderPhotos = data.photos;
  $("folder-path").textContent = data.path;
  $("folder-path").title = data.path;
  $("folder-up").disabled = data.parent === null;
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
  $("folder-count").textContent = data.photos
    ? `${plural(data.photos, "photo")} in this folder (sub-folders aren't scanned)`
    : "No photos in this folder itself. Open a sub-folder.";
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
  if (!state.started_at) return; // nothing has run since the server started
  runProgress.hidden = false;

  $("run-folder").textContent = `${state.running ? "Running on" : "Last run on"} ${state.folder}`;
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
    result.textContent = s
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

async function startRun() {
  try {
    const state = await api("POST", "/api/run", { folder: folderPath, embeddings: $("run-embeddings").checked });
    renderRun(state);
    followRun();
  } catch (error) {
    toast(`Couldn't start the run: ${error.message}`);
  }
}

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
  else if (button.classList.contains("folder")) loadFolders(button.dataset.path);
  else if (button.id === "folder-up") loadFolders(button.dataset.path);
  else if (button.id === "run-start") startRun();
  else if (button.id === "run-cancel") cancelRun();
});
runPanel.addEventListener("keydown", (event) => {
  if (event.key === "Escape") closeRunPanel();
});

load();
checkRun();
