"use strict";
// The review page of one PDF Part's store: serve.py's docstring gives the review records this page appends
const WRITABLE = document.documentElement.dataset.writable === "true";
const KIND_NAMES = {
  number_gap: "Number gap", number_duplicate: "Duplicate number", letter_order: "Letter out of order",
  page_number: "Page number", page_missing: "Missing page", no_owner: "Leading Block with no owner",
  unknown_abbreviation: "Unknown Source Abbreviation", citation_no_pages: "Citation with no pages",
  citation_unsplit: "Citation not split",
};
const ZOOMS = [1, 1.5, 2, 3];
const ITALIC = /\*([^*]+)\*/g;

let E = null, W = [];               // entries.json, warnings.json
const PAGES = {};                   // PDF page -> its page of entries.json
let PAGE_LIST = [];                 // every PDF page with an answer or a Warning, in order
const ENTRIES = {};                 // name -> its verbatim Proverb Entry
let checks = {}, fixes = {};        // name -> its latest "check" record / its Fix
let current = null, zoom = 0;

const $ = sel => document.querySelector(sel);

function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) if (kid != null && kid !== false) el.append(kid);
  return el;
}

function toast(message) {
  const t = $("#toast");
  t.textContent = message;
  t.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { t.hidden = true; }, 3500);
}

async function getText(url) {
  try {
    const r = await fetch(url, {cache: "no-store"});
    return r.ok ? await r.text() : null;
  } catch (e) {
    return null;
  }
}

// -- the review log, keyed by the name of the model's entry (as export.py reads it)
function applyReview(text) {
  for (const line of text.split("\n")) {
    if (!line.trim()) continue;
    let rec;
    try { rec = JSON.parse(line); } catch (e) { continue; }
    if (rec.type === "check") checks[rec.name] = rec;
    else if (rec.type === "fix" && rec.entry) fixes[rec.name] = rec;
    else if (rec.type === "fix") delete fixes[rec.name];
  }
}

async function record(rec) {
  const r = await fetch("review", {method: "POST", headers: {"Content-Type": "application/json"},
                                   body: JSON.stringify(rec)});
  if (!r.ok) throw new Error(await r.text() || r.statusText);
  return r.json();
}

// The answer hash of every page the entry is printed on: what a check or a Fix is made against
function answersOf(entry) {
  const out = {};
  for (const p of entry.pdf_pages) out[p] = PAGES[p] ? PAGES[p].answer_sha1 : null;
  return out;
}

// Whether every page a check or a Fix was made against still has the answer it saw
function fresh(rec) {
  const then = Object.entries(rec.answer_sha1 || {});
  return then.length > 0 && then.every(([p, sha]) => PAGES[p] && PAGES[p].answer_sha1 === sha);
}

function fixOf(entry) {
  const rec = fixes[entry.name];
  return rec ? {rec, stale: !fresh(rec)} : null;
}

function checkedNow(entry) {
  const rec = checks[entry.name];
  return !!rec && rec.checked && fresh(rec);
}

// Reviewed: checked, or given a Fix that is not stale (making a Fix is checking the entry)
function done(entry) {
  const fix = fixOf(entry);
  return checkedNow(entry) || (!!fix && !fix.stale);
}

// -- the Proverb Entries, as printed
function rich(text) {
  const out = [];
  let at = 0;
  for (const m of (text || "").matchAll(ITALIC)) {
    if (m.index > at) out.push(text.slice(at, m.index));
    out.push(h("em", {}, m[1]));
    at = m.index + m[0].length;
  }
  if (at < (text || "").length) out.push(text.slice(at));
  return out;
}

function citeLine(citations) {
  return h("span", {class: "cites"}, (citations || []).map((c, i) => [
    i ? " " : null, h("span", {class: "cite", title: `${c.abbreviation} · pages "${c.pages}"`},
                      h("span", {class: "ab"}, c.abbreviation), c.pages ? " " + c.pages : ""),
  ]));
}

function entryBody(entry) {
  const body = h("div", {class: "body"},
    h("div", {class: "proverb"}, h("span", {class: "num"}, `${entry.number}.`), " ", h("b", {}, entry.proverb)));
  if (entry.citations.length) body.append(h("div", {class: "line"}, citeLine(entry.citations)));
  if (entry.variants.length === 1) {
    const v = entry.variants[0];
    body.append(h("div", {class: "line variant"}, h("span", {class: "bk"}, "BK "), rich(v.text), " ", citeLine(v.citations)));
  } else if (entry.variants.length) {
    body.append(h("div", {class: "line"}, h("span", {class: "bk"}, "BK")));
    for (const v of entry.variants) {
      body.append(h("div", {class: "line variant"}, "- ", rich(v.text), " ", citeLine(v.citations)));
    }
  }
  for (const note of entry.notes) body.append(h("div", {class: "line note"}, note));
  for (const c of entry.corrections) {
    body.append(h("div", {class: "line"}, h("span", {class: "label"}, "Sửa lại: "), c.wrong, " ",
                  h("span", {class: "cites"}, (c.sources || []).map((s, i) => [i ? " " : null, h("span", {class: "ab"}, s)])),
                  " = ", rich(c.right)));
  }
  if (entry.see_also.length) {
    body.append(h("div", {class: "line"}, h("span", {class: "label"}, "Xem thêm: "), entry.see_also.join(", ")));
  }
  return body;
}

// A Warning about one entry is placed "p<page>-<its name>" (see assembly.py), "#2" on if its id repeats
function entryWarnings(entry) {
  return W.filter(w => entry.pdf_pages.includes(w.page) && w.id.replace(/#\d+$/, "").endsWith("-" + entry.name));
}

function warningLine(w) {
  return h("div", {class: "warning"}, h("span", {class: "kind"}, KIND_NAMES[w.kind] || w.kind), " ", w.reason);
}

function pageLink(p, text) {
  return h("button", {class: "link", onclick: () => showPage(p)}, text);
}

function entryCard(entry) {
  const fix = fixOf(entry);
  const applied = fix && !fix.stale;
  const shown = applied ? fix.rec.entry : entry;
  const card = h("article", {class: "entry" + (done(entry) ? " done" : "") + (applied ? " fixed" : "") +
                                   (fix && fix.stale ? " stale" : "")});
  const pages = entry.pdf_pages;
  const at = pages.indexOf(current);
  // The book prints a letter heading above the letter's first entry
  if (entry.number === 1 && at === 0) card.append(h("div", {class: "letter"}, entry.letter));
  const meta = h("div", {class: "meta"}, h("span", {class: "name"}, entry.name),
    at > 0 ? pageLink(pages[at - 1], `◀ begins on p${pages[at - 1]}`) : null,
    at >= 0 && at < pages.length - 1 ? pageLink(pages[at + 1], `continues on p${pages[at + 1]} ▶`) : null,
    applied ? h("span", {class: "tag ok"}, "Fixed") : null,
    checkedNow(entry) ? h("span", {class: "tag ok"}, "✓ checked") : null);
  card.append(meta, entryBody(shown));
  if (applied) {
    card.append(h("details", {}, h("summary", {class: "muted"}, "as transcribed"), entryBody(entry)));
  }
  if (fix && fix.stale) {
    card.append(h("div", {class: "stalebox"},
      h("div", {}, h("b", {}, "Stale Fix: "), `made ${fix.rec.time || ""} against an earlier answer of this entry's ` +
                   "page(s), so it is not applied. Save it again or drop it."),
      h("details", {}, h("summary", {class: "muted"}, "the stale Fix"), entryBody(fix.rec.entry))));
  }
  for (const w of entryWarnings(entry)) card.append(warningLine(w));
  if (WRITABLE) card.append(entryTools(card, entry, fix));
  return card;
}

function entryTools(card, entry, fix) {
  const checked = checkedNow(entry);
  const tools = h("div", {class: "tools"},
    h("button", {class: checked ? "" : "primary", onclick: () => setChecked(entry, !checked)},
      checked ? "Uncheck" : "✓ Mark checked"),
    h("button", {onclick: () => openEditor(card, entry, fix)}, fix && fix.stale ? "✎ Save the Fix again" : "✎ Fix"));
  if (fix) tools.append(h("button", {onclick: () => dropFix(entry)}, "Drop the Fix"));
  return tools;
}

async function setChecked(entry, checked) {
  try {
    checks[entry.name] = await record({type: "check", name: entry.name, checked, answer_sha1: answersOf(entry)});
  } catch (e) {
    toast("Not saved: " + e.message);
  }
  render();
}

// `named`: the entry, or the Fix of an entry no longer transcribed
async function dropFix(named) {
  try {
    await record({type: "fix", name: named.name, entry: null});
    delete fixes[named.name];
  } catch (e) {
    toast("Not saved: " + e.message);
  }
  render();
}

// -- a Fix: a full replacement Proverb Entry, edited as JSON in the shape of entries.json
function isCitations(x) {
  return Array.isArray(x) && x.every(c => c && typeof c.abbreviation === "string" && typeof c.pages === "string");
}

function isStrings(x) { return Array.isArray(x) && x.every(s => typeof s === "string"); }

function entryProblem(x) {
  if (!x || typeof x !== "object" || Array.isArray(x)) return "a Fix is one Proverb Entry, a JSON object";
  if (typeof x.name !== "string" || typeof x.letter !== "string" || typeof x.proverb !== "string")
    return "name, letter and proverb are strings";
  if (!Number.isInteger(x.number)) return "number is a whole number";
  if (!isCitations(x.citations)) return 'citations are [{"abbreviation", "pages"}], both strings';
  if (!Array.isArray(x.variants) || !x.variants.every(v => v && typeof v.text === "string" && isCitations(v.citations)))
    return 'variants are [{"text", "citations"}]';
  if (!isStrings(x.notes) || !isStrings(x.see_also) || !isStrings(x.book_pages))
    return "notes, see_also and book_pages are lists of strings";
  if (!Array.isArray(x.corrections) || !x.corrections.every(c => c && typeof c.wrong === "string" &&
                                                            isStrings(c.sources) && typeof c.right === "string"))
    return 'corrections are [{"wrong", "sources", "right"}]';
  if (!Array.isArray(x.pdf_pages) || !x.pdf_pages.every(Number.isInteger)) return "pdf_pages is a list of whole numbers";
  return null;
}

function openEditor(card, entry, fix) {
  const area = h("textarea", {rows: 18, spellcheck: "false"});
  area.value = JSON.stringify(fix ? fix.rec.entry : entry, null, 2);
  const problem = h("div", {class: "problem"});
  const preview = h("div", {class: "preview"});
  const save = h("button", {class: "primary"}, "Save the Fix");
  const update = () => {
    let parsed = null, why;
    try { parsed = JSON.parse(area.value); why = entryProblem(parsed); } catch (e) { why = "not JSON: " + e.message; }
    problem.textContent = why || "";
    save.disabled = !!why;
    preview.replaceChildren(why ? "" : entryBody(parsed));
    return why ? null : parsed;
  };
  area.addEventListener("input", update);
  save.addEventListener("click", async () => {
    const fixed = update();
    if (!fixed) return;
    save.disabled = true;
    try {
      fixes[entry.name] = await record({type: "fix", name: entry.name, answer_sha1: answersOf(entry), entry: fixed});
      render();
    } catch (e) {
      toast("Not saved: " + e.message);
      save.disabled = false;
    }
  });
  card.replaceChildren(h("div", {class: "editor"},
    h("div", {class: "muted"}, `Fix ${entry.name}: the whole Proverb Entry, italic words between *asterisks*`),
    area, problem, preview,
    h("div", {class: "row"}, save, h("button", {onclick: () => render()}, "Cancel"))));
  update();
  area.focus();
}

// -- the pages
function pageEntries(p) { return E.entries.filter(e => e.pdf_pages.includes(p)); }
function pageWarnings(p) { return W.filter(w => w.page === p); }
function openOn(p) { return pageEntries(p).filter(e => !done(e)).length; }

function pageLabel(p) {
  const page = PAGES[p];
  return `p${p}` + (page ? ` (${page.book_page})` : " (no answer)");
}

function renderPicker() {
  const pick = $("#pick");
  pick.replaceChildren(...PAGE_LIST.map(p => {
    const n = pageWarnings(p).length, open = openOn(p);
    return h("option", {value: p, selected: p === current},
             pageLabel(p) + (n ? ` ⚠${n}` : "") + (open ? ` · ${open} unchecked` : PAGES[p] ? " · ✓" : ""));
  }));
}

function renderProgress() {
  const n = E.entries.length, reviewed = E.entries.filter(done).length;
  let applied = 0, stale = 0;
  for (const e of E.entries) {
    const fix = fixOf(e);
    if (fix && fix.stale) stale++;
    else if (fix) applied++;
  }
  const lost = Object.keys(fixes).filter(k => !ENTRIES[k]).length;
  $("#progress").textContent = `${reviewed} of ${n} entries checked · ${applied} Fix(es) applied` +
    (stale ? ` · ${stale} stale` : "") + (lost ? ` · ${lost} Fix(es) on entries no longer transcribed` : "");
}

function renderSheet() {
  const sheet = $("#sheet");
  const img = h("img", {src: PAGES[current] ? PAGES[current].image : `pages/p${String(current).padStart(3, "0")}.png`,
                        alt: `Scan of PDF page ${current}`});
  img.addEventListener("error", () => img.replaceWith(h("p", {class: "muted noscan"}, "No scan of this page in the store")));
  sheet.replaceChildren(img);
  sheet.style.width = ZOOMS[zoom] * 100 + "%";
  $("#left").scrollTop = 0;
}

function renderRight() {
  const page = PAGES[current];
  const info = $("#pageinfo");
  const entries = pageEntries(current);
  info.replaceChildren(h("b", {}, `PDF page ${current}`),
    page ? ` · book page ${page.book_page} · printed “${page.printed_page}” · ` : " · no answer for this page",
    page ? h("a", {href: `requests/p${String(current).padStart(3, "0")}.json`, target: "_blank"}, "saved answer") : null);
  if (WRITABLE && entries.some(e => !done(e))) {
    info.append(" ", h("button", {onclick: () => checkAll(entries)}, "✓ Mark every entry on this page checked"));
  }
  const warnings = pageWarnings(current);
  $("#warnings").replaceChildren(...warnings.map(warningLine));
  const box = $("#entries");
  box.replaceChildren(...entries.map(entryCard));
  for (const [name, rec] of Object.entries(fixes)) {
    if (!ENTRIES[name] && firstPage(rec) === current) box.append(lostFixCard(rec));
  }
  if (page && !entries.length) box.append(h("p", {class: "muted"}, "No Proverb Entries on this page."));
}

// A Fix whose entry no rerun has transcribed again: shown on the page it began on, to be dropped
function firstPage(rec) { return Math.min(...Object.keys(rec.answer_sha1).map(Number)); }

function lostFixCard(rec) {
  return h("article", {class: "entry stale"},
    h("div", {class: "stalebox"}, h("b", {}, `Fix of ${rec.name}: `),
      `this page no longer holds ${rec.name}, so the Fix applies to nothing.`),
    h("details", {}, h("summary", {class: "muted"}, "the Fix"), entryBody(rec.entry)),
    WRITABLE ? h("div", {class: "tools"}, h("button", {onclick: () => dropFix(rec)}, "Drop the Fix")) : null);
}

async function checkAll(entries) {
  for (const entry of entries.filter(e => !done(e))) {
    try {
      checks[entry.name] = await record({type: "check", name: entry.name, checked: true,
                                         answer_sha1: answersOf(entry)});
    } catch (e) {
      toast("Not saved: " + e.message);
      break;
    }
  }
  render();
}

function render() {
  renderPicker();
  renderProgress();
  renderRight();
}

function showPage(p) {
  if (p == null || !PAGE_LIST.includes(p)) return;
  current = p;
  history.replaceState(null, "", "#p" + p);
  renderSheet();
  render();
  $("#right").scrollTop = 0;
}

function step(d) {
  const i = PAGE_LIST.indexOf(current) + d;
  if (i >= 0 && i < PAGE_LIST.length) showPage(PAGE_LIST[i]);
}

// The next page after this one that `wanted` holds, from the start again past the last
function nextWhere(wanted, none) {
  const i = PAGE_LIST.indexOf(current);
  const order = PAGE_LIST.slice(i + 1).concat(PAGE_LIST.slice(0, i + 1));
  const p = order.find(wanted);
  if (p == null || (p === current && order.length > 1)) toast(none);
  if (p != null && p !== current) showPage(p);
}

function setZoom(z) {
  zoom = Math.max(0, Math.min(ZOOMS.length - 1, z));
  $("#sheet").style.width = ZOOMS[zoom] * 100 + "%";
}

// -- start
function wire() {
  $("#prev").addEventListener("click", () => step(-1));
  $("#next").addEventListener("click", () => step(1));
  $("#pick").addEventListener("change", e => showPage(Number(e.target.value)));
  $("#next-warn").addEventListener("click", () => nextWhere(p => pageWarnings(p).length > 0,
                                                            "No other page has Warnings"));
  $("#next-open").addEventListener("click", () => nextWhere(p => openOn(p) > 0, "Every other page is checked"));
  $("#smaller").addEventListener("click", () => setZoom(zoom - 1));
  $("#larger").addEventListener("click", () => setZoom(zoom + 1));
  document.addEventListener("keydown", e => {
    if (e.target.closest("textarea, input, select") || e.metaKey || e.ctrlKey || e.altKey) return;
    if (e.key === "ArrowLeft") step(-1);
    else if (e.key === "ArrowRight") step(1);
    else if (e.key === "w") $("#next-warn").click();
    else if (e.key === "u") $("#next-open").click();
  });
}

async function load() {
  wire();
  if (!WRITABLE) $("#readonly").hidden = false;
  try {
    const [entries, warnings] = await Promise.all([getText("entries.json"), getText("warnings.json")]);
    if (entries == null) throw new Error("entries.json is missing");
    E = JSON.parse(entries);
    W = warnings ? JSON.parse(warnings) : [];
  } catch (e) {
    $("#title").textContent = "Couldn't load the store: " + e.message;
    return;
  }
  applyReview((await getText("review.jsonl")) || "");
  for (const page of E.pages) PAGES[page.pdf] = page;
  for (const entry of E.entries) ENTRIES[entry.name] = entry;
  PAGE_LIST = [...new Set(E.pages.map(p => p.pdf).concat(W.map(w => w.page)))].sort((a, b) => a - b);
  const title = `Kho tàng tục ngữ người Việt · ${E.part} review`;
  document.title = title;
  $("#title").textContent = title;
  if (!PAGE_LIST.length) {
    $("#entries").textContent = "No page of this Part has been transcribed yet.";
    return;
  }
  const asked = Number((location.hash.match(/^#p(\d+)$/) || [])[1]);
  showPage(PAGE_LIST.includes(asked) ? asked : PAGE_LIST[0]);
}

load();
