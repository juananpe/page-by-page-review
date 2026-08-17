"use strict";

const $ = (id) => document.getElementById(id);
const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const SEV = ["error", "warning", "note", "ok"];
const RANK = { error: 0, warning: 1, note: 2, clean: 3 };

const state = {
  cfg: null,
  doc: null,          // {id, name, page_count}
  pages: new Map(),   // number -> {number, state, result?, error?}
  cross: null,        // array of findings, or null
  crossState: "idle", // idle | running | done | failed
  crossError: null,
  cur: 1,
  filter: "all",
  zoom: "fit",
  view: "pages",      // pages | cross
  stream: null,
  usage: { input: 0, output: 0 },
};

/* --------------------------------------------------------------- gate */

async function loadConfig() {
  try {
    state.cfg = await (await fetch("/api/config")).json();
  } catch {
    state.cfg = { provider: "?", model: "?", ready: false, problem: "Backend unreachable." };
  }
  const c = state.cfg;
  $("gate-meta").innerHTML =
    `<dt>Provider</dt><dd>${esc(c.provider)}</dd>` +
    `<dt>Model</dt><dd>${esc(c.model)}</dd>` +
    `<dt>Page limit</dt><dd>${c.max_pages} pages · ${c.max_upload_mb} MB</dd>` +
    `<dt>Concurrency</dt><dd>${c.concurrency} pages at a time` +
    `${c.cross_page ? " · cross-page pass on" : ""}</dd>`;
  $("drop-sub").textContent = `${c.provider} · ${c.model}`;
  if (!c.ready) {
    gateStatus(
      `<strong>Not configured yet.</strong> ${esc(c.problem || "")}<br>` +
        `Copy <code>.env.example</code> to <code>.env</code>, add a key, and restart. ` +
        `You can also set <code>PROVIDER=mock</code> to try the app without a key.`,
      "bad"
    );
  }
}

function gateStatus(html, kind) {
  const el = $("gate-status");
  el.hidden = false;
  el.className = "gate-status" + (kind ? " " + kind : "");
  el.innerHTML = html;
}

function wireGate() {
  const drop = $("drop");
  const file = $("file");
  file.onchange = () => file.files[0] && upload(file.files[0]);
  ["dragenter", "dragover"].forEach((e) =>
    drop.addEventListener(e, (ev) => { ev.preventDefault(); drop.classList.add("over"); }));
  ["dragleave", "drop"].forEach((e) =>
    drop.addEventListener(e, () => drop.classList.remove("over")));
  drop.addEventListener("drop", (ev) => {
    ev.preventDefault();
    const f = ev.dataTransfer?.files?.[0];
    if (f) upload(f);
  });
}

async function upload(f) {
  if (!/\.pdf$/i.test(f.name) && f.type !== "application/pdf") {
    return gateStatus("That file is not a PDF.", "bad");
  }
  gateStatus(`Rendering <strong>${esc(f.name)}</strong>…`, "busy");
  const body = new FormData();
  body.append("file", f);
  let doc;
  try {
    const r = await fetch("/api/documents", { method: "POST", body });
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || `HTTP ${r.status}`);
    doc = await r.json();
  } catch (err) {
    return gateStatus(`Upload failed: ${esc(err.message)}`, "bad");
  }

  state.doc = doc;
  state.pages = new Map();
  for (const p of doc.pages) state.pages.set(p.number, { number: p.number, state: "pending" });
  state.cur = 1;
  state.cross = null;
  state.crossState = "idle";
  state.crossError = null;
  state.usage = { input: 0, output: 0 };
  state.view = "pages";

  $("cross-btn").hidden = true;
  $("cross-btn").setAttribute("aria-pressed", "false");
  $("cross-btn").textContent = "Across pages";
  $("gate").hidden = true;
  $("app").hidden = false;
  $("brand").textContent = doc.name;
  $("brand").title = doc.name;

  buildSpine();
  buildRows();
  render();
  startStream(false);
}

/* --------------------------------------------------------------- stream */

function startStream(force) {
  stopStream();
  setDownloadsEnabled(false);
  const url = `/api/documents/${state.doc.id}/analyze${force ? "?force=true" : ""}`;
  const es = new EventSource(url);
  state.stream = es;

  if (force) {
    for (const p of state.pages.values()) { p.state = "pending"; p.result = null; p.error = null; }
    state.cross = null;
    state.crossState = "idle";
    state.usage = { input: 0, output: 0 };
    buildSpine(); buildRows(); render();
  }

  es.addEventListener("start", (e) => {
    const d = JSON.parse(e.data);
    for (const p of state.pages.values()) if (p.state === "pending") p.state = "queued";
    tick();
  });

  es.addEventListener("page", (e) => {
    const r = JSON.parse(e.data);
    const p = state.pages.get(r.number);
    if (!p) return;
    p.state = "done"; p.result = r; p.error = null;
    state.usage.input += r.usage?.input || 0;
    state.usage.output += r.usage?.output || 0;
    updateRow(r.number); updateTick(r.number); tick();
    if (r.number === state.cur) render();
  });

  es.addEventListener("failed", (e) => {
    const d = JSON.parse(e.data);
    const p = state.pages.get(d.number);
    if (!p) return;
    p.state = "failed"; p.error = d.message;
    updateRow(d.number); updateTick(d.number); tick();
    if (d.number === state.cur) render();
  });

  es.addEventListener("cross_start", () => { state.crossState = "running"; tick(); });
  es.addEventListener("cross", (e) => {
    state.cross = JSON.parse(e.data).findings || [];
    state.crossState = "done";
    $("cross-btn").hidden = false;
    $("cross-btn").textContent = `Across pages ${state.cross.length}`;
    tick();
    if (state.view === "cross") render();
  });
  es.addEventListener("cross_failed", (e) => {
    state.crossState = "failed";
    state.crossError = JSON.parse(e.data).message;
    $("cross-btn").hidden = false;
    tick();
  });

  es.addEventListener("fatal", (e) => {
    const d = JSON.parse(e.data);
    stopStream();
    for (const p of state.pages.values()) if (p.state !== "done") { p.state = "failed"; p.error = d.message; }
    buildRows(); buildSpine(); render(); tick();
  });

  es.addEventListener("done", () => { stopStream(); setDownloadsEnabled(true); tick(); });

  es.onerror = () => {
    // EventSource retries on its own; a closed stream means the run ended or the server went away.
    if (es.readyState === EventSource.CLOSED) { stopStream(); tick(); }
  };
}

function stopStream() {
  if (state.stream) { state.stream.close(); state.stream = null; }
  const running = [...state.pages.values()].some((p) => p.state === "queued");
  if (running) for (const p of state.pages.values()) if (p.state === "queued") p.state = "pending";
}

async function retryPage(n) {
  const p = state.pages.get(n);
  if (!p) return;
  p.state = "queued"; p.error = null;
  updateRow(n); updateTick(n); render();
  try {
    const r = await fetch(`/api/documents/${state.doc.id}/pages/${n}/analyze`, { method: "POST" });
    const body = await r.json();
    if (!r.ok) throw new Error(body.detail || `HTTP ${r.status}`);
    p.state = "done"; p.result = body;
    state.usage.input += body.usage?.input || 0;
    state.usage.output += body.usage?.output || 0;
  } catch (err) {
    p.state = "failed"; p.error = err.message;
  }
  updateRow(n); updateTick(n); tick(); render();
}

async function retryCross() {
  if (!state.doc || state.crossState === "running") return;
  state.crossState = "running";
  state.crossError = null;
  tick();
  if (state.view === "cross") render();
  try {
    const r = await fetch(`/api/documents/${state.doc.id}/cross`, { method: "POST" });
    const body = await r.json();
    if (!r.ok) throw new Error(body.detail || `HTTP ${r.status}`);
    state.cross = body.findings || [];
    state.crossState = "done";
    $("cross-btn").hidden = false;
    $("cross-btn").textContent = `Across pages ${state.cross.length}`;
  } catch (err) {
    state.crossState = "failed";
    state.crossError = err.message;
  }
  tick();
  if (state.view === "cross") render();
}

/* --------------------------------------------------------------- derived */

const pageSeverity = (p) =>
  p.state === "failed" ? "failed" : p.state === "done" ? p.result.severity : null;

function visible() {
  const all = [...state.pages.values()];
  if (state.filter === "all") return all;
  return all.filter((p) => {
    const s = pageSeverity(p);
    if (state.filter === "error") return s === "error" || s === "failed";
    if (state.filter === "warning") return s === "warning";
    if (state.filter === "minor") return s === "note" || s === "clean";
    return true;
  });
}

/* --------------------------------------------------------------- chrome */

function buildSpine() {
  const host = $("spine");
  host.innerHTML = "";
  for (const p of state.pages.values()) {
    const b = document.createElement("button");
    b.className = "tick";
    b.dataset.n = p.number;
    b.onclick = () => go(p.number);
    host.appendChild(b);
    updateTick(p.number);
  }
}

function updateTick(n) {
  const el = $("spine").querySelector(`.tick[data-n="${n}"]`);
  if (!el) return;
  const p = state.pages.get(n);
  const sev = pageSeverity(p);
  if (sev) el.dataset.sev = sev; else el.removeAttribute("data-sev");
  el.dataset.state = p.state === "queued" ? "running" : p.state;
  el.title = `p${n} — ${p.state === "done" ? p.result.gist : p.state}`;
  el.setAttribute("aria-current", String(n === state.cur && state.view === "pages"));
}

function rowHTML(p) {
  if (p.state === "done") {
    const flags = SEV.map((k) =>
      p.result.counts[k] ? `<span class="dot ${k}" title="${p.result.counts[k]} ${k}"></span>` : "")
      .join("");
    return `<span class="row-n">p${p.number}</span>` +
      `<span class="row-gist">${esc(p.result.gist)}</span>` +
      `<span class="row-flags">${flags}</span>`;
  }
  const label = p.state === "failed" ? "failed" : p.state === "queued" ? "reading…" : "queued";
  return `<span class="row-n">p${p.number}</span>` +
    `<span class="row-gist waiting">${label}</span><span class="row-flags"></span>`;
}

function buildRows() {
  const list = visible();
  const host = $("rows");
  host.innerHTML = "";
  if (!list.length) {
    host.innerHTML = `<p class="rail-empty">No pages match this filter yet.</p>`;
    return;
  }
  for (const p of list) {
    const b = document.createElement("button");
    b.className = "row";
    b.dataset.n = p.number;
    b.innerHTML = rowHTML(p);
    b.onclick = () => go(p.number);
    b.setAttribute("aria-current", String(p.number === state.cur && state.view === "pages"));
    host.appendChild(b);
  }
}

function updateRow(n) {
  const el = $("rows").querySelector(`.row[data-n="${n}"]`);
  const p = state.pages.get(n);
  if (!el) {
    if (visible().some((x) => x.number === n)) buildRows();
    return;
  }
  el.innerHTML = rowHTML(p);
  if (state.filter !== "all" && !visible().some((x) => x.number === n)) buildRows();
}

function tick() {
  const pages = [...state.pages.values()];
  const done = pages.filter((p) => p.state === "done");
  const failed = pages.filter((p) => p.state === "failed").length;
  const counts = { error: 0, warning: 0, note: 0, clean: 0 };
  let items = 0;
  for (const p of done) {
    counts[p.result.severity] = (counts[p.result.severity] || 0) + 1;
    items += p.result.findings.filter((f) => f.severity !== "ok").length;
  }
  const pct = pages.length ? Math.round((done.length + failed) / pages.length * 100) : 0;
  $("progress-bar").style.width = pct + "%";

  const busy = !!state.stream;
  const head = busy
    ? `<b>${done.length + failed}</b>/${pages.length} pages analysed`
    : `<b>${pages.length}</b> pages`;
  const tok = state.usage.input
    ? ` · <b>${state.usage.input.toLocaleString()}</b> in / <b>${state.usage.output.toLocaleString()}</b> out`
    : "";
  const crossBit =
    state.crossState === "running" ? " · cross-page pass…" :
    state.crossState === "failed" ? " · cross-page pass failed" : "";
  $("tally").innerHTML =
    head + ` · <b>${counts.error}</b> error · <b>${counts.warning}</b> warning · ` +
    `<b>${counts.note}</b> minor · <b>${counts.clean}</b> clean` +
    (failed ? ` · <b>${failed}</b> unread` : "") + ` · <b>${items}</b> findings` + tok + crossBit;

  $("f-error").textContent = `Errors ${counts.error + failed}`;
  $("f-warning").textContent = `Warnings ${counts.warning}`;
  $("f-minor").textContent = `Minor ${counts.note + counts.clean}`;
  $("rail-head").textContent = busy
    ? `Page index · reading ${done.length + failed} of ${pages.length}`
    : "Page index · what each page does";
}

function setDownloadsEnabled(on) {
  $("dl-md").disabled = !on;
  $("dl-json").disabled = !on;
}

/* --------------------------------------------------------------- panels */

function findingHTML(f, withPages) {
  const where =
    withPages && f.pages?.length
      ? `<span class="where"> pages ${f.pages
          .map((n) => `<button data-goto="${n}">${n}</button>`)
          .join(", ")}</span> `
      : "";
  return `<div class="finding"><span class="kind ${f.severity}">${f.severity}</span>` +
    `<p>${where}${esc(f.text)}</p></div>`;
}

function renderCross() {
  const box = $("notes-inner");
  const list = state.cross || [];
  box.innerHTML =
    `<p class="eyebrow">Whole document</p><h2>Across pages</h2>` +
    `<p class="summary">Problems that no single page could show: the same quantity given two
      values in different sections, a claim the results do not support, a promised table that
      never arrives.</p>` +
    (state.crossState === "running"
      ? `<p class="pending">Running the cross-page pass…</p>`
      : state.crossState === "failed"
      ? `<div class="failed">The cross-page pass failed.<code>${esc(state.crossError || "")}</code>` +
        `<button class="chip" data-cross-retry="1">Try again</button></div>`
      : list.length
      ? `<div class="sec"><div class="sec-title">${list.length} finding${list.length > 1 ? "s" : ""}</div>` +
        list.map((f) => findingHTML(f, true)).join("") + `</div>`
      : `<p class="pending">Nothing found that spans pages.</p>`) +
    `<p class="hint"><kbd>Esc</kbd> back to pages</p>`;
  box.querySelectorAll("[data-goto]").forEach((b) => {
    b.onclick = () => go(Number(b.dataset.goto));
  });
  const crossRetry = box.querySelector("[data-cross-retry]");
  if (crossRetry) crossRetry.onclick = retryCross;
}

function render() {
  if (state.view === "cross") {
    $("pglabel").textContent = "ACROSS PAGES";
    document.querySelectorAll(".row,.tick").forEach((el) => el.setAttribute("aria-current", "false"));
    renderCross();
    return;
  }

  const n = state.cur;
  const p = state.pages.get(n);
  if (!p) return;

  $("sheet").src = `/api/documents/${state.doc.id}/pages/${n}/image`;
  $("sheet").alt = `Page ${n} of ${state.doc.name}`;
  const label = p.state === "done" ? p.result.section : p.state;
  $("pglabel").textContent = `PAGE ${n} / ${state.doc.page_count} · ${String(label).toUpperCase()}`;

  const box = $("notes-inner");
  if (p.state === "done") {
    const r = p.result;
    const fixes = r.findings.filter((f) => f.severity !== "ok");
    box.innerHTML =
      `<p class="eyebrow">Page ${n} · ${esc(r.section)}</p>` +
      `<h2>${esc(r.gist)}</h2>` +
      `<p class="summary">${esc(r.summary)}</p>` +
      `<div class="sec"><div class="sec-title">` +
      (r.findings.length ? (fixes.length ? "Findings" : "Checks") : "Nothing flagged") +
      `</div>` +
      (r.findings.length
        ? r.findings.map((f) => findingHTML(f, false)).join("")
        : `<p class="pending">The model flagged nothing on this page.</p>`) +
      `</div>` +
      `<p class="usage">${(r.usage?.input || 0).toLocaleString()} in · ` +
      `${(r.usage?.output || 0).toLocaleString()} out · ` +
      `<button class="chip" style="margin-left:8px" data-retry="1">Re-read page</button></p>` +
      `<p class="hint"><kbd>←</kbd> <kbd>→</kbd> pages · <kbd>F</kbd> filter · <kbd>Z</kbd> zoom</p>`;
    const btn = box.querySelector("[data-retry]");
    if (btn) btn.onclick = () => retryPage(n);
  } else if (p.state === "failed") {
    box.innerHTML =
      `<p class="eyebrow">Page ${n}</p><h2>This page was not read</h2>` +
      `<div class="failed">The request for this page failed.<code>${esc(p.error || "")}</code>` +
      `<button class="chip" data-retry="1">Try this page again</button></div>`;
    box.querySelector("[data-retry]").onclick = () => retryPage(n);
  } else {
    box.innerHTML =
      `<p class="eyebrow">Page ${n}</p><h2>Waiting for the model</h2>` +
      `<p class="pending">${p.state === "queued" ? "Reading this page…" : "Queued."}</p>`;
  }

  document.querySelectorAll(".row").forEach((r) =>
    r.setAttribute("aria-current", String(Number(r.dataset.n) === n)));
  document.querySelectorAll(".tick").forEach((t) =>
    t.setAttribute("aria-current", String(Number(t.dataset.n) === n)));
  const row = $("rows").querySelector(`.row[data-n="${n}"]`);
  if (row) row.scrollIntoView({ block: "nearest", inline: "nearest" });
  $("reader").scrollTop = 0;
  $("notes").scrollTop = 0;
}

function go(n) {
  state.view = "pages";
  state.cur = n;
  $("cross-btn").setAttribute("aria-pressed", "false");
  render();
}

function step(d) {
  const list = visible();
  if (!list.length) return;
  let i = list.findIndex((p) => p.number === state.cur);
  if (i === -1) return go(list[0].number);
  i = Math.min(list.length - 1, Math.max(0, i + d));
  go(list[i].number);
}

function setFilter(f) {
  state.filter = f;
  ["all", "error", "warning", "minor"].forEach((k) =>
    $("f-" + k).setAttribute("aria-pressed", String(k === f)));
  buildRows();
  const list = visible();
  if (list.length && !list.some((p) => p.number === state.cur)) state.cur = list[0].number;
  render();
}

function setZoom(z) {
  state.zoom = z;
  $("sheet").className = "sheet " + (z === "fit" ? "fit" : z === "100" ? "zoom100" : "zoom150");
  ["fit", "100", "150"].forEach((k) => $("z-" + k).setAttribute("aria-pressed", String(k === z)));
}

/* --------------------------------------------------------------- wiring */

$("prev").onclick = () => step(-1);
$("next").onclick = () => step(1);
$("f-all").onclick = () => setFilter("all");
$("f-error").onclick = () => setFilter("error");
$("f-warning").onclick = () => setFilter("warning");
$("f-minor").onclick = () => setFilter("minor");
$("z-fit").onclick = () => setZoom("fit");
$("z-100").onclick = () => setZoom("100");
$("z-150").onclick = () => setZoom("150");
$("sheet").onclick = () => setZoom(state.zoom === "fit" ? "100" : state.zoom === "100" ? "150" : "fit");
$("cross-btn").onclick = () => {
  state.view = "cross";
  $("cross-btn").setAttribute("aria-pressed", "true");
  render();
};
$("dl-md").onclick = () => location.assign(`/api/documents/${state.doc.id}/report.md`);
$("dl-json").onclick = () => location.assign(`/api/documents/${state.doc.id}/results.json`);
$("reset").onclick = async () => {
  stopStream();
  if (state.doc) fetch(`/api/documents/${state.doc.id}`, { method: "DELETE" }).catch(() => {});
  state.doc = null;
  $("app").hidden = true;
  $("gate").hidden = false;
  $("file").value = "";
  $("gate-status").hidden = true;
};

addEventListener("keydown", (e) => {
  if ($("app").hidden || e.metaKey || e.ctrlKey || e.altKey) return;
  const k = e.key.toLowerCase();
  if (k === "escape" && state.view === "cross") return go(state.cur);
  if (k === "arrowright" || k === "j") { step(1); e.preventDefault(); }
  else if (k === "arrowleft" || k === "k") { step(-1); e.preventDefault(); }
  else if (k === "f") setFilter(
    state.filter === "all" ? "error" : state.filter === "error" ? "warning" :
    state.filter === "warning" ? "minor" : "all");
  else if (k === "z") setZoom(state.zoom === "fit" ? "100" : state.zoom === "100" ? "150" : "fit");
});

setDownloadsEnabled(false);
wireGate();
loadConfig();
