"use strict";
// The review page of one PDF Part's store: serve.py's docstring gives what it serves, review.py the Fixes it saves
const WRITABLE = document.documentElement.dataset.writable === "true";
const KIND_NAMES = {
  number_gap: "Number gap", number_duplicate: "Duplicate number", letter_order: "Letter out of order",
  page_number: "Page number", page_missing: "Missing page", no_owner: "Leading Block with no owner",
  unknown_abbreviation: "Unknown Source Abbreviation", citation_no_pages: "Citation with no pages",
  citation_unsplit: "Citation not split",
};
const BLOCK_NAMES = {
  letter: "Letter heading", proverb: "Proverb", citations: "Citations", variant: "Variant (BK)", note: "Note",
  correction: "Sửa lại", see_also: "Xem thêm",
};
const ZOOMS = [1, 1.5, 2, 3];
const ITALIC = /\*([^*]+)\*/g;

let MODEL = null;                   // entries.json: the model's Proverb Entries and pages
let ANSWERS = {};                   // answers.json: PDF page -> the model's answer
let SOURCES = {};                   // sources.json: Source Abbreviation -> its Source
let VIEW = null;                    // /assembled: the entries rebuilt with the Fixes, and the Fixes
const PAGES = {};                   // PDF page -> its page of entries.json (the model's answer hash)
let PAGE_LIST = [];                 // every PDF page with an answer, a Warning or a Fix, in order
let current = null, zoom = 0, showingEdits = false;

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

// -- the Fixes: a page's corrected Blocks, applied unless stale
function fixOf(p) { return VIEW.fixes[p] || null; }
function isStale(p) { return VIEW.stale.includes(p); }
function isApplied(p) { return VIEW.applied.includes(p); }

// The page's printed number and Blocks as the entries are now built from them: its applied Fix, or the model's
function pageNow(p) {
  const fix = isApplied(p) ? fixOf(p) : null;
  const answer = ANSWERS[p] || {};
  return {printed_page: fix ? fix.printed_page : String(answer.printed_page ?? ""),
          blocks: (fix ? fix.blocks : answer.blocks) || []};
}

function blockKey(b) { return JSON.stringify([b.kind, b.number || 0, b.text || "", b.citations || ""]); }

// The edit from Blocks `a` to Blocks `b`: [{op: "same" | "add" | "del" | "chg", a, b}], a and b their indexes. A run
// of deleted Blocks followed by added ones is paired into changed Blocks
function blockDiff(a, b) {
  const ka = a.map(blockKey), kb = b.map(blockKey);
  const n = a.length, m = b.length;
  const L = Array.from({length: n + 1}, () => new Array(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) L[i][j] = ka[i] === kb[j] ? L[i + 1][j + 1] + 1 : Math.max(L[i + 1][j], L[i][j + 1]);
  }
  const raw = [];
  let i = 0, j = 0;
  while (i < n || j < m) {
    if (i < n && j < m && ka[i] === kb[j]) raw.push({op: "same", a: i++, b: j++});
    else if (j < m && (i === n || L[i][j + 1] >= L[i + 1][j])) raw.push({op: "add", b: j++});
    else raw.push({op: "del", a: i++});
  }
  const ops = [];
  for (let k = 0; k < raw.length;) {
    if (raw[k].op !== "del") { ops.push(raw[k++]); continue; }
    const dels = [], adds = [];
    while (k < raw.length && raw[k].op === "del") dels.push(raw[k++]);
    while (k < raw.length && raw[k].op === "add") adds.push(raw[k++]);
    for (let x = 0; x < Math.max(dels.length, adds.length); x++) {
      if (x < dels.length && x < adds.length) ops.push({op: "chg", a: dels[x].a, b: adds[x].b});
      else ops.push(x < dels.length ? dels[x] : adds[x]);
    }
  }
  return ops;
}

// The model's Blocks of page `p` against its Fix, worked out once per fetch of the store
const DIFFS = new Map();
function pageDiff(p) {
  if (!DIFFS.has(p)) DIFFS.set(p, blockDiff((ANSWERS[p] || {}).blocks || [], fixOf(p).blocks));
  return DIFFS.get(p);
}

// The changes on page `p` that fall in its Blocks [from, to): a deleted Block belongs with the Block before it
function changesIn(p, from, to) {
  if (!isApplied(p) || !ANSWERS[p]) return [];
  let last = -1;
  return pageDiff(p).filter(o => {
    const at = o.b ?? last;
    if (o.b != null) last = o.b;
    return at >= from && at < to;
  });
}

// An entry's changes against the model's transcription, over every page it is printed on, by page
function entryChanges(entry) {
  const out = [];
  for (const p of entry.pdf_pages) {
    const [from, to] = entry.blocks[p] || [0, 0];
    const ops = changesIn(p, from, to);
    if (ops.some(o => o.op !== "same")) out.push({p, ops});
  }
  return out;
}

function edited(entry) { return entryChanges(entry).length > 0; }

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

// Citations as the book prints them: "HT 63 NL 7 bk VD"
function citeLine(citations) {
  return h("span", {class: "cites"}, (citations || []).map((c, i) => [
    i ? " " : null, c.variant ? "bk " : null,
    h("span", {class: "cite" + (SOURCES[c.abbreviation] ? "" : " unknown")},
      h("span", {class: "ab"}, c.abbreviation), c.pages ? " " + c.pages : ""),
  ]));
}

// One Citation written out: "VD · 12 — title, author (year)", or why it matches none of the 63 Sources
function citeExpanded(c) {
  const s = SOURCES[c.abbreviation];
  const where = c.variant ? ` · bản khác${c.pages ? " · " + c.pages : " (no page)"}` : c.pages ? ` · ${c.pages}` : "";
  return h("li", {class: s ? "" : "unknown"}, h("span", {class: "ab"}, c.abbreviation), where, " — ",
    s ? [h("i", {}, s.title), s.author ? `, ${s.author}` : "", s.year ? ` (${s.year})` : ""]
      : "not among the 63 Sources");
}

function sourcesList(entry) {
  const groups = [];
  if (entry.citations.length) groups.push(["", entry.citations]);
  entry.variants.forEach((v, i) => {
    if (v.citations.length) groups.push([entry.variants.length > 1 ? `BK ${i + 1}` : "BK", v.citations]);
  });
  if (!groups.length) return null;
  return h("details", {class: "sources", open: true}, h("summary", {}, "Sources"),
    groups.map(([label, citations]) => [label ? h("div", {class: "muted small"}, label) : null,
                                        h("ul", {}, citations.map(citeExpanded))]));
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

// -- the changes, word by word
function wordDiff(a, b) {
  const x = a.split(/(\s+)/), y = b.split(/(\s+)/);
  const L = Array.from({length: x.length + 1}, () => new Array(y.length + 1).fill(0));
  for (let i = x.length - 1; i >= 0; i--) {
    for (let j = y.length - 1; j >= 0; j--) L[i][j] = x[i] === y[j] ? L[i + 1][j + 1] + 1 : Math.max(L[i + 1][j], L[i][j + 1]);
  }
  const out = [];
  let i = 0, j = 0;
  while (i < x.length || j < y.length) {
    if (i < x.length && j < y.length && x[i] === y[j]) out.push(x[i++]), j++;
    else if (j < y.length && (i === x.length || L[i][j + 1] >= L[i + 1][j])) out.push(h("ins", {}, y[j++]));
    else out.push(h("del", {}, x[i++]));
  }
  return out;
}

function blockText(b) {
  if (!b) return "";
  if (b.kind === "proverb") return `${b.number}. ${b.text}`;
  return b.kind === "variant" && b.citations ? `${b.text} ${b.citations}` : b.text;
}

function diffLines(p, ops) {
  const before = (ANSWERS[p] || {}).blocks || [], after = fixOf(p).blocks;
  return ops.map(o => {
    const a = before[o.a], b = after[o.b];
    const kind = h("span", {class: "kindname"}, BLOCK_NAMES[(b || a).kind] || (b || a).kind);
    if (o.op === "same") return h("div", {class: "dl same"}, kind, blockText(b));
    if (o.op === "add") return h("div", {class: "dl"}, kind, h("ins", {}, blockText(b)));
    if (o.op === "del") return h("div", {class: "dl"}, kind, h("del", {}, blockText(a)));
    const kinds = a.kind === b.kind ? kind : h("span", {class: "kindname"}, h("del", {}, BLOCK_NAMES[a.kind]), " ",
                                                h("ins", {}, BLOCK_NAMES[b.kind]));
    return h("div", {class: "dl"}, kinds, wordDiff(blockText(a), blockText(b)));
  });
}

function changesBox(changes) {
  return h("details", {class: "changes"}, h("summary", {class: "muted"}, "changes against the transcription"),
    changes.map(({p, ops}) => [changes.length > 1 ? h("div", {class: "muted small"}, `PDF page ${p}`) : null,
                               diffLines(p, ops)]));
}

// -- the right side
// A Warning about one entry is placed "p<page>-<its name>" (see assembly.py), "#2" on if its id repeats
function warningOf(w, entry) {
  return entry.pdf_pages.includes(w.page) && w.id.replace(/#\d+$/, "").endsWith("-" + entry.name);
}

function warningLine(w) {
  return h("div", {class: "warning"}, h("span", {class: "kind"}, KIND_NAMES[w.kind] || w.kind), " ", w.reason);
}

function pageLink(p, text) {
  return h("button", {class: "link", onclick: () => showPage(p)}, text);
}

function entryCard(entry, warnings) {
  const changes = entryChanges(entry);
  const card = h("article", {class: "entry" + (changes.length ? " edited" : "")});
  const pages = entry.pdf_pages;
  const at = pages.indexOf(current);
  // The book prints a letter heading above the letter's first entry
  if (entry.number === 1 && at === 0) card.append(h("div", {class: "letter"}, entry.letter));
  const meta = h("div", {class: "meta"}, h("span", {class: "name"}, entry.name),
    at > 0 ? pageLink(pages[at - 1], `◀ begins on p${pages[at - 1]}`) : null,
    at >= 0 && at < pages.length - 1 ? pageLink(pages[at + 1], `continues on p${pages[at + 1]} ▶`) : null,
    changes.length ? h("span", {class: "tag ok"}, "Edited") : null);
  if (WRITABLE && ANSWERS[current] && entry.blocks[current]) {
    meta.append(h("button", {class: "edit", title: `Edit ${entry.name} on this page`,
                             onclick: () => openEditor(card, current, entry.blocks[current], entry.name)}, "✎ Edit"));
  }
  card.append(meta, entryBody(entry));
  for (const w of warnings) card.append(warningLine(w));
  const sources = sourcesList(entry);
  if (sources) card.append(sources);
  if (changes.length) card.append(changesBox(changes));
  return card;
}

function pageInfo(p) {
  const page = PAGES[p], now = pageNow(p), fix = fixOf(p);
  const info = h("div", {}, h("b", {}, `PDF page ${p}`),
    page ? ` · book page ${page.book_page} · printed “${now.printed_page}” · ` : " · no answer for this page",
    page ? h("a", {href: `requests/p${String(p).padStart(3, "0")}.json`, target: "_blank"}, "saved answer") : null);
  if (WRITABLE && ANSWERS[p]) {
    info.append(" ", h("button", {class: "small-btn", title: "Edit every Block of this page and its printed number",
                                  onclick: () => openEditor($("#entries"), p, null, `PDF page ${p}`)}, "✎ Edit the page"));
  }
  if (fix && isApplied(p)) {
    info.append(h("div", {class: "fixline"}, `This page has a Fix, saved ${fix.time || ""}. `,
      WRITABLE ? h("button", {class: "small-btn", onclick: () => dropFix(p)}, "Drop the Fix") : null));
  }
  return info;
}

function staleBox(p) {
  const fix = fixOf(p);
  const ops = ANSWERS[p] ? pageDiff(p).filter(o => o.op !== "same") : [];
  const before = (ANSWERS[p] || {}).blocks || [];
  const lines = ops.map(o => {
    const a = before[o.a], b = fix.blocks[o.b];
    if (o.op === "add") return h("div", {class: "dl"}, h("ins", {}, blockText(b)));
    if (o.op === "del") return h("div", {class: "dl"}, h("del", {}, blockText(a)));
    return h("div", {class: "dl"}, wordDiff(blockText(a), blockText(b)));
  });
  return h("div", {class: "stalebox"},
    h("div", {}, h("b", {}, "Stale Fix: "), `saved ${fix.time || ""} against an earlier answer of this page, which a ` +
                 "rerun has changed, so it is not applied. Edit the page again from it, or drop it."),
    h("details", {}, h("summary", {class: "muted"}, "the stale Fix against the current answer"), lines),
    WRITABLE ? h("div", {class: "tools"},
      ANSWERS[p] ? h("button", {onclick: () => openEditor($("#entries"), p, null, `PDF page ${p}`, fix)},
                     "✎ Edit the page from the stale Fix") : null,
      h("button", {onclick: () => dropFix(p)}, "Drop the Fix")) : null);
}

function renderRight() {
  const right = $("#entries");
  if (showingEdits) {
    $("#pageinfo").replaceChildren(h("b", {}, "Edits"), " · every page with a Fix · ",
                                   h("button", {class: "small-btn", onclick: () => toggleEdits(false)}, "Back to the page"));
    $("#warnings").replaceChildren();
    right.replaceChildren(editsList());
    return;
  }
  $("#pageinfo").replaceChildren(pageInfo(current));
  const entries = VIEW.entries.filter(e => e.pdf_pages.includes(current));
  const warnings = VIEW.warnings.filter(w => w.page === current);
  const owned = new Set();
  const cards = entries.map(entry => {
    const own = warnings.filter(w => warningOf(w, entry));
    own.forEach(w => owned.add(w));
    return entryCard(entry, own);
  });
  // The page's own Warnings, about no entry of it: its number, a missing answer, Blocks with no owner
  $("#warnings").replaceChildren(...warnings.filter(w => !owned.has(w)).map(warningLine));
  right.replaceChildren(...(fixOf(current) && isStale(current) ? [staleBox(current)] : []), ...cards);
  if (PAGES[current] && !entries.length) right.append(h("p", {class: "muted"}, "No Proverb Entries on this page."));
}

function editsList() {
  const pages = Object.keys(VIEW.fixes).map(Number).sort((a, b) => a - b);
  if (!pages.length) return h("p", {class: "muted"}, "No Fixes yet: edit an entry where you see the model got it wrong.");
  return h("ul", {class: "edits"}, pages.map(p => {
    const fix = fixOf(p);
    const names = VIEW.entries.filter(e => e.pdf_pages.includes(p) && entryChanges(e).some(c => c.p === p))
                              .map(e => e.name);
    const changed = isApplied(p) ? pageDiff(p).filter(o => o.op !== "same").length : 0;
    return h("li", {}, h("button", {class: "link", onclick: () => { toggleEdits(false); showPage(p); }}, pageLabel(p)),
      isStale(p) ? h("span", {class: "tag stale"}, "stale") : ` · ${changed} Block(s) changed`,
      names.length ? ` · ${names.join(", ")}` : "", h("span", {class: "muted"}, ` · saved ${fix.time || ""}`));
  }));
}

function toggleEdits(on) {
  showingEdits = on;
  render();
  $("#right").scrollTop = 0;
}

// -- editing: the Blocks [from, to) of page `p` (or all of them, with its printed number), as rows of printed text
function blockRow(block, rows, changed) {
  const kind = h("select", {class: "kind"}, Object.entries(BLOCK_NAMES).map(([k, name]) =>
    h("option", {value: k, selected: k === block.kind}, name)));
  const number = h("input", {class: "number", type: "number", min: "1", value: block.number || "",
                             title: "The proverb's printed number"});
  const text = h("textarea", {class: "text", rows: "1", spellcheck: "false"});
  text.value = block.text || "";
  const cites = h("input", {class: "cites-in", placeholder: "Citations, as printed: NNCC 27", spellcheck: "false",
                            value: block.citations || ""});
  const row = h("div", {class: "brow"});
  const sync = () => {
    number.hidden = kind.value !== "proverb";
    // Only a Variant has Citations of its own; any the model put on another Block are shown, to keep or clear
    cites.hidden = kind.value !== "variant" && !cites.value;
    text.placeholder = kind.value === "citations" ? "As printed: HT 63 NL 7 TNLG II 7, 25" :
                       kind.value === "correction" ? "Wrong wording SOURCE = right *wording*" : "As printed, italics between *asterisks*";
    text.style.height = "auto";
    text.style.height = text.scrollHeight + "px";
  };
  const move = d => {
    const i = rows.indexOf(row), j = i + d;
    if (j < 0 || j >= rows.length) return;
    [rows[i], rows[j]] = [rows[j], rows[i]];
    changed();
  };
  row.read = () => ({kind: kind.value, number: kind.value === "proverb" ? Number(number.value) || 0 : 0,
                     text: text.value.trim(), citations: cites.value.trim()});
  for (const el of [kind, number, text, cites]) el.addEventListener("input", () => { sync(); changed(); });
  row.append(kind, number, h("div", {class: "fields"}, text, cites),
    h("div", {class: "rowtools"},
      h("button", {title: "Up", onclick: () => move(-1)}, "↑"),
      h("button", {title: "Down", onclick: () => move(1)}, "↓"),
      h("button", {title: "Add a Block below", onclick: () => {
        rows.splice(rows.indexOf(row) + 1, 0, blockRow({kind: "note", number: 0, text: "", citations: ""}, rows, changed));
        changed();
      }}, "+"),
      h("button", {title: "Delete this Block", onclick: () => { rows.splice(rows.indexOf(row), 1); changed(); }}, "✕")));
  requestAnimationFrame(sync);
  return row;
}

// `range`: [from, to) of the page's current Blocks, or null for the whole page; `from`: a stale Fix to start from
function openEditor(container, p, range, title, from) {
  const now = from ? {printed_page: from.printed_page, blocks: from.blocks} : pageNow(p);
  const [start, end] = range || [0, now.blocks.length];
  const rows = [];
  const list = h("div", {class: "rows"});
  const printed = h("input", {class: "printed", value: now.printed_page, title: "The page number printed on the page"});
  const problem = h("div", {class: "problem"});
  const preview = h("div", {class: "preview"});
  const save = h("button", {class: "primary"}, "Save the Fix");
  let timer = null, seq = 0;
  const blocks = () => now.blocks.slice(0, start).concat(rows.map(r => r.read()), now.blocks.slice(end));
  const request = () => ({page: p, printed_page: range ? now.printed_page : printed.value.trim(), blocks: blocks()});
  const refresh = async () => {
    const mine = ++seq;
    try {
      const view = await post("preview", request());
      if (mine !== seq) return;
      const to = start + rows.length;
      const shown = range ? view.entries.filter(e => {
        const [a, b] = e.blocks[p] || [0, 0];
        return a < to && b > start;
      }) : view.entries;
      problem.textContent = "";
      save.disabled = false;
      preview.replaceChildren(...shown.map(e => [entryBody(e), ...view.warnings.filter(w => warningOf(w, e)).map(warningLine),
                                                 sourcesList(e)]).flat().filter(Boolean),
                              ...view.warnings.filter(w => !view.entries.some(e => warningOf(w, e))).map(warningLine));
      if (!shown.length) preview.append(h("p", {class: "muted"}, "No Proverb Entry: saving removes it from the page."));
    } catch (e) {
      if (mine !== seq) return;
      problem.textContent = e.message;
      save.disabled = true;
    }
  };
  const changed = () => {
    list.replaceChildren(...rows);
    clearTimeout(timer);
    timer = setTimeout(refresh, 250);
  };
  for (const b of now.blocks.slice(start, end)) rows.push(blockRow(b, rows, changed));
  save.addEventListener("click", async () => {
    save.disabled = true;
    try {
      const {printed_page, blocks} = request();
      await post("review", {type: "fix", page: p, printed_page, blocks});
      await reload();
    } catch (e) {
      toast("Not saved: " + e.message);
      save.disabled = false;
    }
  });
  container.replaceChildren(h("div", {class: "editor"},
    h("div", {class: "muted"}, `Edit ${title}: each Block as printed, italic words between *asterisks*`),
    range ? null : h("label", {class: "row"}, "Printed page number ", printed),
    list,
    h("div", {class: "row"}, h("button", {onclick: () => {
      rows.push(blockRow({kind: "note", number: 0, text: "", citations: ""}, rows, changed));
      changed();
    }}, "+ Add a Block")),
    problem, h("div", {class: "muted small"}, "Preview"), preview,
    h("div", {class: "row"}, save, h("button", {onclick: () => render()}, "Cancel"))));
  if (!range) printed.addEventListener("input", changed);
  list.replaceChildren(...rows);
  refresh();
}

async function dropFix(p) {
  try {
    await post("review", {type: "fix", page: p, blocks: null});
    await reload();
  } catch (e) {
    toast("Not saved: " + e.message);
  }
}

// -- the pages
function pageLabel(p) {
  const page = PAGES[p];
  return `p${p}` + (page ? ` (${page.book_page})` : " (no answer)");
}

function renderPicker() {
  const pick = $("#pick");
  pick.replaceChildren(...PAGE_LIST.map(p => {
    const n = VIEW.warnings.filter(w => w.page === p).length;
    const fix = fixOf(p) ? (isStale(p) ? " · stale Fix" : " · edited") : "";
    return h("option", {value: p, selected: p === current}, pageLabel(p) + (n ? ` ⚠${n}` : "") + fix);
  }));
}

function renderProgress() {
  const n = VIEW.entries.filter(edited).length;
  const pages = Object.keys(VIEW.fixes).length;
  $("#progress").textContent = `${VIEW.entries.length} entries · ${n} edited on ${pages - VIEW.stale.length} page(s)` +
    (VIEW.stale.length ? ` · ${VIEW.stale.length} stale Fix(es)` : "");
  $("#edits").textContent = `Edits (${pages})`;
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

function render() {
  renderPicker();
  renderProgress();
  renderRight();
}

function showPage(p) {
  if (p == null || !PAGE_LIST.includes(p)) return;
  current = p;
  showingEdits = false;
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
  $("#next-warn").addEventListener("click", () => nextWhere(p => VIEW.warnings.some(w => w.page === p),
                                                            "No other page has Warnings"));
  $("#next-edit").addEventListener("click", () => nextWhere(p => !!fixOf(p), "No other page has a Fix"));
  $("#edits").addEventListener("click", () => toggleEdits(!showingEdits));
  $("#smaller").addEventListener("click", () => setZoom(zoom - 1));
  $("#larger").addEventListener("click", () => setZoom(zoom + 1));
  document.addEventListener("keydown", e => {
    // Not while editing: changing page would drop the unsaved edit
    if (e.target.closest("textarea, input, select") || $(".editor") || e.metaKey || e.ctrlKey || e.altKey) return;
    if (e.key === "ArrowLeft") step(-1);
    else if (e.key === "ArrowRight") step(1);
    else if (e.key === "w") $("#next-warn").click();
    else if (e.key === "e") $("#next-edit").click();
  });
}

function pageList() {
  return [...new Set(MODEL.pages.map(p => p.pdf).concat(VIEW.warnings.map(w => w.page),
                                                        Object.keys(VIEW.fixes).map(Number)))].sort((a, b) => a - b);
}

// The store read afresh, as a rerun may have rewritten it since the page loaded, and its entries rebuilt with the Fixes
async function fetchStore() {
  [MODEL, ANSWERS, SOURCES, VIEW] = await Promise.all([getJSON("entries.json"), getJSON("answers.json"),
                                                       getJSON("sources.json"), getJSON("assembled")]);
  for (const k of Object.keys(PAGES)) delete PAGES[k];
  for (const page of MODEL.pages) PAGES[page.pdf] = page;
  DIFFS.clear();
  PAGE_LIST = pageList();
}

// After a save or a drop
async function reload() {
  await fetchStore();
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
  const title = `Kho tàng tục ngữ người Việt · ${MODEL.part} review`;
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
