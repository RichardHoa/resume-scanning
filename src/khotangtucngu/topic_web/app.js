"use strict";
// The review page of the Topic Index's store: serve.py's docstring gives what it serves, topics.py the lines it saves
const WRITABLE = document.documentElement.dataset.writable === "true";
// In the order the Warning list groups them: the reads' first, as the server lists them
const KIND_NAMES = {
  index_disagreement: "Reads disagree", index_single_read: "Single read",
  index_unclassified: "Unclassified line", index_kind_mismatch: "Kind contradicted by the model",
  index_count: "Item count differs", index_no_entry: "Names no Proverb Entry", index_not_ascending: "Not ascending",
  index_letter_order: "Letter out of order", index_heading_number: "Heading number", index_no_owner: "No owner",
  index_part_missing: "Part with no answers.json", page_missing: "Missing page", ink_outside: "Ink outside the lines",
};
const KIND_ORDER = Object.keys(KIND_NAMES);
const READ_KINDS = ["index_disagreement", "index_single_read"];
// A Confirmed Line's kinds, which the editor offers, and the kinds only code gives a line
const LINE_KINDS = {
  chu_de: "Chủ đề", tieu_chu_de: "Tiểu chủ đề", title: "Title, continued", row_start: "Topic Row",
  row_continuation: "Topic Row, continued", not_index: "Not of the index",
};
const CODE_KINDS = {unclassified: "Unclassified", unread: "Unread"};
const ROW_KINDS = ["row_start", "row_continuation", "unread"];
const TEXT_KINDS = ["chu_de", "tieu_chu_de", "title", "not_index"];
const STATE_NAMES = {agreed: "Agreed", warned: "Warned", confirmed: "Confirmed"};
// The page images' long side, as pages.review_image draws them: a line's crop is shown at their scale
const PAGE_IMAGE_LONG_SIDE = 2000;
const ZOOMS = [1, 1.5, 2, 3];

let VIEW = null;                    // /assembled: the index rebuilt with the review log, each page's lines, every Warning
const PAGES = {};                   // PDF page -> its page of /assembled
let PAGE_LIST = [];                 // every PDF page with an answer or a Warning, in order
const ROWS = new Map();             // a number line's key -> {letter, from}: its Topic Row's letter and first page
const OPEN = {};                    // PDF page -> {chu, sub}: the headings open at its top, {text, title} each
let current = null, selected = null, zoom = 0, showingList = false;

const $ = sel => document.querySelector(sel);

function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat(Infinity)) if (kid != null && kid !== false) el.append(kid);
  return el;
}

function toast(message) {
  const t = $("#toast");
  t.textContent = message;
  t.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { t.hidden = true; }, 3500);
}

async function getJSON(url) {
  const r = await fetch(url, {cache: "no-store"});
  if (!r.ok) throw new Error(`${url}: ${r.status} ${r.statusText}`);
  return r.json();
}

async function post(url, body) {
  const r = await fetch(url, {method: "POST", headers: {"Content-Type": "application/json"},
                              body: JSON.stringify(body)});
  if (!r.ok) throw new Error(await r.text() || r.statusText);
  return r.json();
}

// -- lines: a line is known by its band, which stays when Line Numbers change on a rerun
function bandKey(band) { return band.join("-"); }
function lineKey(p, line) { return `${p}:${bandKey(line.band)}`; }
function linesOf(p) { return (PAGES[p] || {}).lines || []; }
// One line per band: a Confirmed Line's, where several lines fall in its band
function distinctLines(p) {
  return linesOf(p).filter((l, i, all) => all.findIndex(m => bandKey(m.band) === bandKey(l.band)) === i);
}
// The line holding `band` on page `p`: a Confirmed Line's first, where several lines fall in its band
function lineAt(p, band) { return band ? linesOf(p).find(l => bandKey(l.band) === band) : null; }
function selectedLine() { return lineAt(current, selected); }
function kindName(kind) { return LINE_KINDS[kind] || CODE_KINDS[kind] || kind; }
function lineName(line) { return line.n ? `Line ${line.n}` : `The line at ${line.band[0]} px`; }
function warningsOf(p, line) {
  return VIEW.warnings.filter(w => w.page === p && w.band && bandKey(w.band) === bandKey(line.band));
}
function valuesOf(line) { return {kind: line.kind, letter: line.letter, numbers: line.numbers, text: line.text}; }

// Each Topic Row's letter and first page, and the headings open at each page's top, walked as topics.rebuild walks
// them: nothing carries across a page with no answer
function walk() {
  ROWS.clear();
  let chu = null, sub = null, row = null, heading = null, previous = null;
  for (const page of VIEW.pages) {
    if (previous !== null && page.pdf !== previous + 1) chu = sub = row = heading = null;
    previous = page.pdf;
    OPEN[page.pdf] = {chu, sub};
    for (const line of page.lines) {
      const k = line.kind;
      if (k === "chu_de") { chu = heading = {text: line.text, title: ""}; sub = row = null; }
      else if (k === "tieu_chu_de") { sub = heading = {text: line.text, title: ""}; row = null; }
      else if (k === "title") { if (heading) heading.title = `${heading.title} ${line.text}`.trim(); }
      else if (k === "row_start") { row = {letter: line.letter, from: page.pdf}; heading = null; }
      else if (k === "row_continuation") heading = null;
      if (k === "row_start" || k === "row_continuation") ROWS.set(lineKey(page.pdf, line), row);
    }
  }
}

// -- the numbers two reads differ on: those outside their longest common run
function common(a, b) {
  const L = Array.from({length: a.length + 1}, () => new Array(b.length + 1).fill(0));
  for (let i = a.length - 1; i >= 0; i--) {
    for (let j = b.length - 1; j >= 0; j--) L[i][j] = a[i] === b[j] ? L[i + 1][j + 1] + 1 : Math.max(L[i + 1][j], L[i][j + 1]);
  }
  const inA = new Set(), inB = new Set();
  for (let i = 0, j = 0; i < a.length && j < b.length;) {
    if (a[i] === b[j]) { inA.add(i++); inB.add(j++); }
    else if (L[i + 1][j] >= L[i][j + 1]) i++;
    else j++;
  }
  return [inA, inB];
}

// A Vision read as printed, its runs of digits not among `numbers` marked
function markedRead(text, numbers) {
  if (!text) return h("span", {class: "muted"}, "no read");
  if (!numbers) return text;
  const parts = text.split(/(\d+)/);
  const digits = parts.filter((_, i) => i % 2).map(Number);
  const [kept] = common(digits, numbers);
  return parts.map((part, i) => i % 2 && !kept.has((i - 1) / 2) ? h("mark", {}, part) : part);
}

// The model's numbers, those not among `numbers` marked
function markedNumbers(letter, mine, numbers, otherLetter) {
  const [kept] = numbers ? common(mine, numbers) : [new Set(mine.map((_, i) => i))];
  return [letter ? [letter !== otherLetter && otherLetter != null ? h("mark", {}, letter) : h("b", {}, letter), " "] : null,
          mine.map((x, i) => [i ? ", " : "", kept.has(i) ? String(x) : h("mark", {}, String(x))])];
}

// -- the scan, with each line tinted by its state
function lineLayer(p) {
  const page = PAGES[p];
  const [w, hh] = page.size;
  const pct = x => (x * 100).toFixed(3) + "%";
  return h("div", {class: "lines"}, distinctLines(p).map(l => {
    const [left, , right] = l.crop || [0, 0, w];
    const key = bandKey(l.band);
    return h("div", {class: `ln state-${l.state} kind-${l.kind}` + (key === selected ? " selected" : ""), "data-band": key,
                     title: `${lineName(l)} · ${kindName(l.kind)} · ${STATE_NAMES[l.state]}`,
                     style: `left: ${pct(left / w)}; top: ${pct(l.band[0] / hh)}; width: ${pct((right - left) / w)}; ` +
                            `height: ${pct((l.band[1] - l.band[0]) / hh)}`,
                     onclick: () => select(key)});
  }));
}

function renderSheet() {
  const sheet = $("#sheet");
  const page = PAGES[current];
  const img = h("img", {src: page ? page.image : `pages/p${String(current).padStart(3, "0")}.png`,
                        alt: `Scan of PDF page ${current}`});
  img.addEventListener("error", () => sheet.replaceChildren(h("p", {class: "muted noscan"}, "No scan of this page in the store")));
  sheet.replaceChildren(img);
  renderLineLayer();
  sheet.style.width = ZOOMS[zoom] * 100 + "%";
}

// The lines over the scan alone, so that a confirmation or a new selection recolours them without loading the scan again
function renderLineLayer() {
  const sheet = $("#sheet");
  sheet.querySelector(".lines")?.remove();
  const page = PAGES[current];
  if (page && page.size && sheet.querySelector("img")) sheet.append(lineLayer(current));
}

// -- the line panel
// The line's crop, cut from the page image by CSS at the page image's scale, so no PDF is needed
function cropView(page, line) {
  const [w, hh] = page.size;
  const [l, t, r, b] = line.crop || [0, line.band[0], w, line.band[1]];
  const scale = PAGE_IMAGE_LONG_SIDE / Math.max(w, hh);
  const pct = x => (x * 100).toFixed(3) + "%";
  return h("div", {class: "cropwrap"},
    h("div", {class: "crop", style: `width: ${Math.round((r - l) * scale)}px; height: ${Math.round((b - t) * scale)}px`},
      h("img", {src: page.image, alt: `${lineName(line)} of PDF page ${current}`,
                style: `width: ${pct(w / (r - l))}; left: ${pct(-l / (r - l))}; top: ${pct(-t / (b - t))}`})));
}

function readsTable(line) {
  const vision = line.vision, vlm = line.vlm;
  const rows = [];
  if (vision && "numbers" in vision || vlm && "numbers" in vlm || ROW_KINDS.includes(line.kind)) {
    const theirs = vlm && vlm.numbers;
    rows.push(["Vision, line read", markedRead(line.line_read, theirs)],
              ["Vision, page read", markedRead(line.page_read, theirs)],
              ["Model", vlm ? markedNumbers(vlm.letter, vlm.numbers, vision && vision.numbers, vision && vision.letter)
                            : h("span", {class: "muted"}, `no read${line.vlm_why ? ": " + line.vlm_why : ""}`)]);
    rows.push(["", h("span", {class: "muted small"}, vision
      ? `Vision's ${vision.read} read parsed as ${vision.letter ? `letter ${vision.letter}, ` : ""}${vision.numbers.length} ` +
        `number(s) in ${vision.items} comma-separated item(s)`
      : "Neither Vision read parses as numbers")]);
  } else {
    rows.push(["Vision, line read", line.line_read || h("span", {class: "muted"}, "no read")],
              ["Vision, page read", line.page_read || h("span", {class: "muted"}, "no read")],
              ["Model", vlm ? vlm.text : h("span", {class: "muted"}, `no read${line.vlm_why ? ": " + line.vlm_why : ""}`)]);
  }
  if (line.edited && line.model) {
    const m = line.model;
    rows.push(["Model's values", `${kindName(m.kind)}: ${[m.letter, m.numbers.join(", "), m.text].filter(Boolean).join(" ")}`]);
  }
  return h("table", {class: "reads"}, rows.map(([name, value]) => h("tr", {}, h("th", {}, name), h("td", {}, value))));
}

function warningLine(w, cleared) {
  return h("div", {class: "warning" + (cleared ? " cleared" : "")},
           h("span", {class: "kind"}, KIND_NAMES[w.kind] || w.kind), " ", w.reason);
}

// Saving never waits on the preview's Warnings: the developer is the final judge
function editor(p, line) {
  const kind = h("select", {class: "kind"},
    line.kind in LINE_KINDS ? null : h("option", {value: "", selected: true}, `${kindName(line.kind)}: choose a kind`),
    Object.entries(LINE_KINDS).map(([k, name]) => h("option", {value: k, selected: k === line.kind}, name)));
  const letter = h("input", {class: "letter", value: line.letter, spellcheck: "false", title: "The row's letter, as printed"});
  const numbers = h("input", {class: "numbers", value: line.numbers.join(", "), spellcheck: "false",
                              title: "The line's numbers, as printed, separated by commas"});
  const text = h("input", {class: "text", value: line.text, spellcheck: "false",
                           title: "The heading as printed: \"I\", \"17. Tiền bạc, của cải\", or a title's line"});
  const fields = {letter: h("label", {}, "Letter", letter), numbers: h("label", {}, "Numbers", numbers),
                  text: h("label", {}, "Text", text)};
  const problem = h("div", {class: "problem"});
  const preview = h("div", {class: "preview"});
  const save = h("button", {class: "primary", title: "Confirm the line with these values (Enter)"}, "Save and confirm");
  const read = () => {
    const k = kind.value;
    return {kind: k, letter: k === "row_start" ? letter.value.trim() : "",
            numbers: ROW_KINDS.includes(k) ? (numbers.value.match(/\d+/g) || []).map(Number) : [],
            text: TEXT_KINDS.includes(k) ? text.value.trim() : ""};
  };
  const same = () => JSON.stringify(read()) === JSON.stringify(valuesOf(line));
  const sync = () => {
    fields.letter.hidden = kind.value !== "row_start";
    fields.numbers.hidden = !ROW_KINDS.includes(kind.value);
    fields.text.hidden = !TEXT_KINDS.includes(kind.value);
  };
  let timer = null, seq = 0;
  // The Warnings these values would raise and clear on this page and the pages either side
  const refresh = async () => {
    const mine = ++seq;
    if (!kind.value) return;
    try {
      const view = await post("preview", {page: p, band: line.band, values: read()});
      if (mine !== seq) return;
      const key = w => `${w.id}|${w.reason}`;
      const before = VIEW.warnings.filter(w => Math.abs(w.page - p) <= 1);
      const had = new Set(before.map(key)), has = new Set(view.warnings.map(key));
      const raised = view.warnings.filter(w => !had.has(key(w))), cleared = before.filter(w => !has.has(key(w)));
      problem.textContent = "";
      save.disabled = false;
      preview.replaceChildren(h("div", {class: "muted small"}, "Confirmed with these values:"),
        raised.length ? raised.map(w => warningLine(w)) : h("div", {class: "small"}, "no new Warnings"),
        cleared.map(w => warningLine(w, true)));
    } catch (e) {
      if (mine !== seq) return;
      problem.textContent = e.message;
      preview.replaceChildren();
      save.disabled = true;
    }
  };
  const changed = () => {
    sync();
    save.hidden = same();
    clearTimeout(timer);
    timer = setTimeout(refresh, 250);
  };
  for (const el of [kind, letter, numbers, text]) {
    el.addEventListener("input", changed);
    el.addEventListener("keydown", e => {
      if (e.key === "Enter") { e.preventDefault(); same() ? confirmLine(p, line) : saveLine(p, line, read()); }
      else if (e.key === "Escape") { e.preventDefault(); renderPanel(); }
    });
  }
  save.addEventListener("click", () => saveLine(p, line, read()));
  save.hidden = true;
  sync();
  return h("div", {class: "editor"}, h("div", {class: "row"}, h("label", {}, "Kind", kind), fields.letter, fields.numbers),
           fields.text, problem, preview, h("div", {class: "row"}, save));
}

function renderPanel() {
  const panel = $("#panel");
  const line = selectedLine();
  if (!line) {
    panel.replaceChildren(h("p", {class: "muted"}, "Pick a line on the scan or in the index (↑/↓), or go to the next open Warning (n)."));
    return;
  }
  const page = PAGES[current];
  // An unclassified or unread line has no values to confirm as it stands: its kind is chosen in the editor
  const acts = WRITABLE && (line.confirmed || line.kind in LINE_KINDS) ? [
    line.confirmed
      ? h("button", {title: "Put the model's read and its Warnings back (u)", onclick: () => undoLine(current, line)}, "Undo")
      : h("button", {class: "primary", title: "Confirm the line as it stands, and go to the next open Warning (c)",
                     onclick: () => confirmLine(current, line)}, "✓ Confirm"),
  ] : null;
  panel.replaceChildren(
    h("div", {class: "panelhead"}, h("b", {}, `${lineName(line)} · ${kindName(line.kind)}`),
      h("span", {class: `tag ${line.state}`}, STATE_NAMES[line.state]), line.edited ? h("span", {class: "tag edited"}, "Edited") : null,
      h("span", {class: "acts"}, acts)),
    cropView(page, line), readsTable(line),
    warningsOf(current, line).map(w => warningLine(w)),
    WRITABLE ? editor(current, line) : null);
}

// -- the page's index as assembled, one row per line
function indexLine(p, line) {
  const k = line.kind;
  const row = ROWS.get(lineKey(p, line));
  let body;
  if (k === "chu_de") body = h("div", {class: "ix-chu"}, `Chủ đề ${line.text}`);
  else if (k === "tieu_chu_de") body = h("div", {class: "ix-sub"}, line.text);
  else if (k === "title") body = h("div", {class: "ix-title"}, line.text);
  else if (k === "row_start" || k === "row_continuation") {
    body = h("div", {class: "ix-row"},
      h("span", {class: "letter" + (k === "row_start" ? "" : " carried")}, row ? row.letter : "?"),
      k === "row_continuation" && row && row.from !== p ? h("span", {class: "muted small"}, `from p${row.from} · `) : null,
      line.numbers.join(", "));
  } else if (k === "not_index") body = h("div", {class: "ix-not"}, line.text || line.line_read || "not of the index");
  else body = h("div", {class: "ix-odd"}, `${kindName(k)}: `, line.line_read || line.page_read || "no read");
  const n = warningsOf(p, line).length;
  const key = bandKey(line.band);
  return h("div", {class: `ix state-${line.state}` + (key === selected ? " selected" : ""), "data-band": key,
                   onclick: () => select(key)},
           body, n ? h("span", {class: "count"}, `⚠${n}`) : line.confirmed ? h("span", {class: "tag confirmed"}, "✓") : null);
}

function heading(open) {
  return open ? `${open.text}${open.title ? " " + open.title : ""}` : null;
}

function renderIndex() {
  const index = $("#index");
  if (showingList) {
    $("#pageinfo").replaceChildren(h("b", {}, `Every Warning (${VIEW.warnings.length})`), " · grouped by kind · ",
      h("button", {class: "link", onclick: () => toggleList(false)}, "back to the page"));
    index.replaceChildren(warningList());
    return;
  }
  const page = PAGES[current];
  const own = VIEW.warnings.filter(w => w.page === current && !w.band);
  $("#pageinfo").replaceChildren(h("b", {}, `PDF page ${current}`),
    page ? ` · book page ${page.book_page} · ${page.lines.length} Index Lines` : " · no answer for this page",
    own.map(w => warningLine(w)));
  if (!page) { index.replaceChildren(); return; }
  const open = OPEN[current] || {};
  const lines = distinctLines(current);
  const first = lines.find(l => l.kind !== "not_index");
  const carried = first && first.kind !== "chu_de" && open.chu
    ? h("div", {class: "carry"}, "Continued: Chủ đề ", heading(open.chu),
        open.sub && first.kind !== "tieu_chu_de" ? [" › ", heading(open.sub)] : null)
    : null;
  index.replaceChildren(carried || "", ...lines.map(l => indexLine(current, l)));
  if (!lines.length) index.append(h("p", {class: "muted"}, "No Index Lines on this page."));
}

function warningList() {
  const groups = new Map();
  for (const w of VIEW.warnings) {
    if (!groups.has(w.kind)) groups.set(w.kind, []);
    groups.get(w.kind).push(w);
  }
  const order = k => KIND_ORDER.includes(k) ? KIND_ORDER.indexOf(k) : KIND_ORDER.length;
  const kinds = [...groups.keys()].sort((a, b) => order(a) - order(b));
  if (!kinds.length) return h("p", {class: "muted"}, "No Warnings.");
  return kinds.map(k => h("details", {class: "group", open: READ_KINDS.includes(k) || kinds.length === 1},
    h("summary", {}, `${KIND_NAMES[k] || k} (${groups.get(k).length})`),
    h("ul", {}, groups.get(k).map(w => {
      const line = w.band ? lineAt(w.page, bandKey(w.band)) : null;
      return h("li", {class: line && line.confirmed ? "done" : ""},
        h("button", {class: "link", onclick: () => { toggleList(false); go(w.page, w.band && bandKey(w.band)); }}, `p${w.page}`),
        " ", w.reason);
    }))));
}

function toggleList(on) {
  showingList = on;
  $("#list").setAttribute("aria-pressed", String(on));
  renderIndex();
  $("#index").scrollTop = 0;
}

// -- saving: a line for the review log, and the store rebuilt with it
async function change(line) {
  try {
    await post("review", line);
    await reload();
    return true;
  } catch (e) {
    toast("Not saved: " + e.message);
    return false;
  }
}

// Confirmed as it stands: on to the next open Warning
async function confirmLine(p, line) {
  if (await change({type: "confirmed_line", page: p, band: line.band, values: null})) nextOpen(1);
}

// Corrected: the line stays shown, with its Warnings now
async function saveLine(p, line, values) {
  await change({type: "confirmed_line", page: p, band: line.band, values});
}

async function undoLine(p, line) {
  await change({type: "unconfirmed_line", page: p, band: line.band});
}

// -- moving about
function pageLabel(p) {
  const page = PAGES[p];
  if (!page) return `p${p} (no answer)`;
  const warned = page.lines.filter(l => l.state === "warned").length;
  const held = page.lines.filter(l => l.confirmed).length;
  return `p${p} (${page.book_page})` + (warned ? ` ⚠${warned}` : "") + (held ? ` ✓${held}` : "");
}

function renderPicker() {
  $("#pick").replaceChildren(...PAGE_LIST.map(p => h("option", {value: p, selected: p === current}, pageLabel(p))));
}

function renderProgress() {
  const lines = VIEW.pages.flatMap(p => p.lines);
  const open = lines.filter(l => l.state === "warned").length;
  $("#progress").textContent = `${lines.filter(l => l.confirmed).length} lines confirmed · ${open} with open Warnings · ` +
                               `${VIEW.warnings.length} Warnings`;
  $("#next-open").textContent = `Next open ⚠ (${open})`;
  $("#list").textContent = `Warnings (${VIEW.warnings.length})`;
}

function render() {
  renderPicker();
  renderProgress();
  renderLineLayer();
  renderPanel();
  renderIndex();
}

function remember() {
  history.replaceState(null, "", `#p${current}` + (selected ? `:${selected}` : ""));
}

function select(band) {
  selected = band;
  remember();
  renderLineLayer();
  renderPanel();
  if (!showingList) renderIndex();
  for (const where of ["#sheet", "#index"]) {
    document.querySelector(`${where} [data-band="${band}"]`)?.scrollIntoView({block: "nearest"});
  }
}

function showPage(p, band) {
  if (p == null || !PAGE_LIST.includes(p)) return;
  current = p;
  selected = band && lineAt(p, band) ? band : null;
  remember();
  renderSheet();
  $("#left").scrollTop = 0;
  render();
  $("#index").scrollTop = 0;
  if (selected) select(selected);
}

function go(p, band) {
  if (p === current) select(band && lineAt(p, band) ? band : null);
  else showPage(p, band);
}

function step(d) {
  const i = PAGE_LIST.indexOf(current) + d;
  if (i >= 0 && i < PAGE_LIST.length) showPage(PAGE_LIST[i]);
}

// The line `d` (1 or -1) from the selected one on this page
function stepLine(d) {
  const lines = distinctLines(current);
  if (!lines.length) return;
  const i = lines.findIndex(l => bandKey(l.band) === selected);
  const j = i < 0 ? (d > 0 ? 0 : lines.length - 1) : Math.max(0, Math.min(lines.length - 1, i + d));
  select(bandKey(lines[j].band));
}

// The next line (d = 1) or the one before (d = -1) with an open Warning, across pages, from the start again past the last
function nextOpen(d) {
  const open = VIEW.pages.flatMap(page => page.lines.filter(l => l.state === "warned").map(line => ({p: page.pdf, line})));
  if (!open.length) { toast("No line has an open Warning"); return; }
  const here = selectedLine();
  const top = here ? here.band[0] : d > 0 ? -1 : Infinity;
  const after = x => x.p > current || x.p === current && x.line.band[0] > top;
  const before = x => x.p < current || x.p === current && x.line.band[0] < top;
  const pick = d > 0 ? open.find(after) || open[0] : [...open].reverse().find(before) || open[open.length - 1];
  go(pick.p, bandKey(pick.line.band));
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
  $("#next-open").addEventListener("click", () => nextOpen(1));
  $("#list").addEventListener("click", () => toggleList(!showingList));
  $("#smaller").addEventListener("click", () => setZoom(zoom - 1));
  $("#larger").addEventListener("click", () => setZoom(zoom + 1));
  document.addEventListener("keydown", e => {
    // Not while editing: the editor's fields take Enter and Escape themselves
    if (e.target.closest("textarea, input, select") || e.metaKey || e.ctrlKey || e.altKey) return;
    const line = selectedLine();
    if (e.key === "ArrowLeft") step(-1);
    else if (e.key === "ArrowRight") step(1);
    else if (e.key === "ArrowDown" || e.key === "j") { e.preventDefault(); stepLine(1); }
    else if (e.key === "ArrowUp" || e.key === "k") { e.preventDefault(); stepLine(-1); }
    else if (e.key === "n") nextOpen(1);
    else if (e.key === "N") nextOpen(-1);
    else if (e.key === "w") toggleList(!showingList);
    else if (!WRITABLE || !line) return;
    else if (e.key === "c" && !line.confirmed && line.kind in LINE_KINDS) confirmLine(current, line);
    else if (e.key === "u" && line.confirmed) undoLine(current, line);
    else if (e.key === "e") {
      e.preventDefault();
      $("#panel .editor label:not([hidden]) input")?.focus();
    }
  });
}

// The store read afresh, as a rerun may have rewritten it since the page loaded, and the index rebuilt with the log
async function fetchStore() {
  VIEW = await getJSON("assembled");
  for (const k of Object.keys(PAGES)) delete PAGES[k];
  for (const page of VIEW.pages) PAGES[page.pdf] = page;
  walk();
  PAGE_LIST = [...new Set(VIEW.pages.map(p => p.pdf).concat(VIEW.warnings.map(w => w.page)))].sort((a, b) => a - b);
}

// After a line is saved: the same page and line, rebuilt
async function reload() {
  await fetchStore();
  if (selected && !lineAt(current, selected)) selected = null;
  render();
}

async function load() {
  wire();
  if (!WRITABLE) $("#readonly").hidden = false;
  try {
    await fetchStore();
  } catch (e) {
    $("#title").textContent = "Couldn't load the store: " + e.message;
    return;
  }
  const title = "Kho tàng tục ngữ người Việt · Hệ thống tra cứu theo chủ đề review";
  document.title = title;
  $("#title").textContent = title;
  if (!PAGE_LIST.length) {
    $("#index").textContent = "No page of the Topic Index has been read yet.";
    return;
  }
  const [, asked, band] = location.hash.match(/^#p(\d+)(?::(\d+-\d+))?$/) || [];
  if (PAGE_LIST.includes(Number(asked))) { showPage(Number(asked), band); return; }
  // With no page asked for, the first line with an open Warning
  current = PAGE_LIST[0];
  showPage(current);
  nextOpen(1);
}

load();
