"use strict";
// The review page of one PDF Part's store: serve.py's docstring gives what it serves, review.py the lines it saves
const WRITABLE = document.documentElement.dataset.writable === "true";
const KIND_NAMES = {
  number_gap: "Number gap", number_duplicate: "Duplicate number", letter_order: "Letter out of order",
  page_number: "Page number", page_missing: "Missing page", no_owner: "Leading Block with no owner",
  unnumbered_proverb: "Proverb with no number",
  unknown_abbreviation: "Unknown Source Abbreviation", citation_no_pages: "Citation with no pages",
  citation_unsplit: "Citation not split", ink_outside: "Ink outside the lines",
  diacritic_disagreement: "Diacritics differ from OCR", model_edit: "Model Edit",
  stable_model_edit: "Priority · Model Edit of a stable read",
  confirmed_overlap: "Overlaps a Confirmed Span",
};
const PRIORITY = "stable_model_edit";
const BLOCK_NAMES = {
  letter: "Letter heading", proverb: "Proverb", citations: "Citations", variant: "Variant (BK)", note: "Note",
  correction: "Sửa lại", see_also: "Xem thêm",
};
const ZOOMS = [1, 1.5, 2, 3];
const ITALIC = /\*([^*]+)\*/g;

let MODEL = null;                   // entries.json: each page's images
let SOURCES = {};                   // sources.json: Source Abbreviation -> its Source
let VIEW = null;                    // /assembled: the entries rebuilt with the review log, each page's Blocks and spans, every Confirmed Span
const PAGES = {};                   // PDF page -> its page of entries.json and of /assembled
let PAGE_LIST = [];                 // every PDF page with an answer, a Warning or a Confirmed Span, in order
let current = null, zoom = 0, showingConfirmed = false, showAllConfirmed = false;
let showSpans = true, showNumbered = false;  // the Entry Spans drawn on the scan; the layout image in place of the scan

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

// -- a page's spans, each model's or confirmed
function spansOf(p) { return (PAGES[p] || {}).spans || []; }
function spanBlocks(p, span) { return PAGES[p].blocks.slice(span.blocks[0], span.blocks[1]); }

// The spans of page `p` holding any of its Blocks [from, to)
function spansIn(p, from, to) {
  return spansOf(p).filter(s => s.blocks[0] < s.blocks[1] && s.blocks[0] < to && s.blocks[1] > from);
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

// The model's Blocks of an edited span against its Blocks now, worked out once per fetch of the store
const DIFFS = new Map();
function spanDiff(p, span) {
  const key = `${p}:${span.band}`;
  if (!DIFFS.has(key)) DIFFS.set(key, blockDiff(span.model_blocks, spanBlocks(p, span)));
  return DIFFS.get(key);
}

// The changes of `span` that fall in page `p`'s Blocks [from, to): a deleted Block belongs with the Block before it
function changesIn(p, span, from, to) {
  let last = 0;
  return spanDiff(p, span).filter(o => {
    const at = span.blocks[0] + (o.b ?? last);
    if (o.b != null) last = o.b;
    return at >= from && at < to;
  });
}

// An entry's changes against the model's transcription, over every edited span holding it
function entryChanges(entry) {
  const out = [];
  for (const p of entry.pdf_pages) {
    const [from, to] = entry.blocks[p] || [0, 0];
    for (const span of spansIn(p, from, to)) {
      const ops = span.edited ? changesIn(p, span, from, to) : [];
      if (ops.some(o => o.op !== "same")) out.push({p, span, ops});
    }
  }
  return out;
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

function diffLines(p, span, ops) {
  const before = span.model_blocks, after = spanBlocks(p, span);
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
    changes.map(({p, span, ops}) => [changes.length > 1 ? h("div", {class: "muted small"}, `PDF page ${p}, L${span.first}`) : null,
                                     diffLines(p, span, ops)]));
}

// -- the right side
// A Warning about one entry is placed "p<page>-<its name>" (see assembly.py), "#2" on if its id repeats
function warningOf(w, entry) {
  return entry.pdf_pages.includes(w.page) && w.id.replace(/#\d+$/, "").endsWith("-" + entry.name);
}

function isPriority(w) { return w.kind === PRIORITY; }

function warningLine(w) {
  return h("div", {class: "warning" + (isPriority(w) ? " priority" : "")},
           h("span", {class: "kind"}, KIND_NAMES[w.kind] || w.kind), " ", w.reason);
}

function pageLink(p, text) {
  return h("button", {class: "link", onclick: () => showPage(p)}, text);
}

// A span's tags and what can be done to it, for the card in `card`. `several`: the card has more than one span to tell
// apart. A span cut across a band has no buttons: its lines are partly the Confirmed Span's
function spanTools(p, span, card, several) {
  return h("span", {class: "spantools"},
    several ? h("span", {class: "muted"}, `L${span.first}–${span.last}`) : null,
    span.confirmed ? h("span", {class: "tag ok"}, "Confirmed") : null,
    span.edited ? h("span", {class: "tag ok"}, "Edited") : null,
    WRITABLE && !span.overlap ? [
      h("button", {class: "act", title: `Edit the whole Entry Span, Line Numbers ${span.first}-${span.last}`,
                   onclick: () => openEditor(card, p, span)}, "✎ Edit"),
      span.confirmed
        ? h("button", {class: "act", title: "Put the model's Blocks and their Warnings back",
                       onclick: () => change({type: "unconfirmed", page: p, band: span.band})}, "Undo")
        : h("button", {class: "act", title: `Confirm the whole Entry Span as it stands, Line Numbers ${span.first}-${span.last}`,
                       onclick: () => change({type: "confirmed", page: p, band: span.band, blocks: null})}, "✓ Confirm"),
    ] : null);
}

function entryCard(entry, warnings) {
  const changes = entryChanges(entry);
  const card = h("article", {class: "entry" + (changes.length ? " edited" : "")});
  const pages = entry.pdf_pages;
  const at = pages.indexOf(current);
  // The book prints a letter heading above the letter's first entry
  if (entry.number === 1 && at === 0) card.append(h("div", {class: "letter"}, entry.letter));
  const spans = spansIn(current, ...(entry.blocks[current] || [0, 0]));
  const meta = h("div", {class: "meta"}, h("span", {class: "name"}, entry.name),
    at > 0 ? pageLink(pages[at - 1], `◀ begins on p${pages[at - 1]}`) : null,
    at >= 0 && at < pages.length - 1 ? pageLink(pages[at + 1], `continues on p${pages[at + 1]} ▶`) : null,
    h("span", {class: "holders"}, spans.map(s => spanTools(current, s, card, spans.length > 1))));
  card.append(meta, entryBody(entry));
  for (const w of warnings) card.append(warningLine(w));
  const sources = sourcesList(entry);
  if (sources) card.append(sources);
  if (changes.length) card.append(changesBox(changes));
  return card;
}

// A span holding no Proverb Entry's Blocks on this page: a letter heading, Leading Blocks with no owner, or nothing
function spanCard(p, span) {
  const card = h("article", {class: "entry" + (span.edited ? " edited" : "")});
  card.append(h("div", {class: "meta"}, h("span", {class: "name"}, span.label),
                h("span", {class: "holders"}, spanTools(p, span, card, false))),
    h("div", {class: "body"}, spanBlocks(p, span).map(b => h("div", {class: "dl"},
      h("span", {class: "kindname"}, BLOCK_NAMES[b.kind] || b.kind), blockText(b)))));
  if (span.edited) card.append(changesBox([{p, span, ops: spanDiff(p, span)}]));
  return card;
}

// The printed number with what can be done to it: the developer's number settles the Page number Warning for good
function printedNumber(p, page) {
  const box = h("span", {class: "printedline"});
  const edit = () => {
    const input = h("input", {class: "printed", value: page.printed_page, title: "The page number printed on the page",
                              onkeydown: e => { if (e.key === "Enter") save.click(); }});
    const save = h("button", {class: "small-btn", onclick: () => change({type: "printed_page", page: p,
                                                                         printed_page: input.value.trim()})}, "Save");
    box.replaceChildren("printed ", input, " ", save, " ",
                        h("button", {class: "small-btn", onclick: show}, "Cancel"));
    input.focus();
  };
  const show = () => box.replaceChildren(`printed “${page.printed_page}”`, h("span", {},
    page.printed_confirmed ? [" ", h("span", {class: "tag ok"}, "Confirmed")] : null,
    WRITABLE ? [" ", h("button", {class: "small-btn", title: "Edit and confirm the printed number", onclick: edit}, "✎ Edit"), " ",
      page.printed_confirmed
        ? h("button", {class: "small-btn", onclick: () => change({type: "printed_page", page: p, printed_page: null})}, "Undo")
        : h("button", {class: "small-btn", onclick: () => change({type: "printed_page", page: p, printed_page: page.printed_page})}, "✓ Confirm"),
    ] : null));
  show();
  return box;
}

function pageInfo(p) {
  const page = PAGES[p];
  return h("div", {}, h("b", {}, `PDF page ${p}`),
    page ? [` · book page ${page.book_page} · `, printedNumber(p, page), " · ",
            h("a", {href: `requests/p${String(p).padStart(3, "0")}.json`, target: "_blank"}, "saved answer")]
         : " · no answer for this page");
}

function renderRight() {
  const right = $("#entries");
  if (showingConfirmed) {
    $("#pageinfo").replaceChildren(h("b", {}, "Confirmed"), showAllConfirmed ? " · every Confirmed Span · " : " · the spans you edited · ",
      h("button", {class: "small-btn", onclick: () => { showAllConfirmed = !showAllConfirmed; renderRight(); }},
        showAllConfirmed ? "Only edited" : "Show all"), " ",
      h("button", {class: "small-btn", onclick: () => toggleConfirmed(false)}, "Back to the page"));
    $("#warnings").replaceChildren();
    right.replaceChildren(confirmedList());
    return;
  }
  $("#pageinfo").replaceChildren(pageInfo(current));
  const entries = VIEW.entries.filter(e => e.pdf_pages.includes(current));
  const warnings = VIEW.warnings.filter(w => w.page === current);
  const owned = new Set(), held = new Set();
  const cards = entries.map(entry => {
    const own = warnings.filter(w => warningOf(w, entry));
    own.forEach(w => owned.add(w));
    const range = entry.blocks[current] || [0, 0];
    spansIn(current, ...range).forEach(s => held.add(s));
    return {at: range[0], card: entryCard(entry, own)};
  });
  for (const span of spansOf(current)) {
    if (!held.has(span)) cards.push({at: span.blocks[0], card: spanCard(current, span)});
  }
  // At the top, the page's priority Warnings, also on their entries' cards, then its own, about no entry of it: its
  // number, a missing answer, Blocks with no owner
  $("#warnings").replaceChildren(...warnings.filter(w => isPriority(w) || !owned.has(w)).map(warningLine));
  right.replaceChildren(...cards.sort((a, b) => a.at - b.at).map(c => c.card));
  if (PAGES[current] && !entries.length) right.append(h("p", {class: "muted"}, "No Proverb Entries on this page."));
}

function confirmedList() {
  const rows = VIEW.confirmed.filter(c => showAllConfirmed || c.edited);
  if (!rows.length) {
    return h("p", {class: "muted"}, showAllConfirmed ? "Nothing confirmed yet: edit or confirm a span where you choose to."
                                                     : "No span edited yet.");
  }
  return h("ul", {class: "confirmed-list"}, rows.map(c => {
    const span = spansOf(c.page).find(s => String(s.band) === String(c.band));
    return h("li", {}, h("button", {class: "link", onclick: () => { toggleConfirmed(false); showPage(c.page); }}, pageLabel(c.page)),
      ` · L${c.first}–${c.last}`, span ? ` · ${span.label} ` : " ",
      h("span", {class: "tag ok"}, c.edited ? "Edited" : "Confirmed"), h("span", {class: "muted"}, ` · saved ${c.time || ""}`));
  }));
}

function toggleConfirmed(on) {
  showingConfirmed = on;
  render();
  $("#right").scrollTop = 0;
}

// -- editing: the whole of one Entry Span, as rows of printed text
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
    // A Variant has Citations of its own, and a proverb's are its entry's; any the model put on another Block are
    // shown, to keep or clear
    cites.hidden = kind.value !== "variant" && kind.value !== "proverb" && !cites.value;
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

// Saving an edit confirms the span, and the preview's Warnings never stop it: the developer is the final judge
function openEditor(container, p, span) {
  const start = span.blocks[0];
  const rows = [];
  const list = h("div", {class: "rows"});
  const problem = h("div", {class: "problem"});
  const preview = h("div", {class: "preview"});
  const save = h("button", {class: "primary"}, "Save and confirm");
  let timer = null, seq = 0;
  const request = () => ({page: p, band: span.band, blocks: rows.map(r => r.read())});
  const refresh = async () => {
    const mine = ++seq;
    try {
      const view = await post("preview", request());
      if (mine !== seq) return;
      const to = start + rows.length;
      const shown = view.entries.filter(e => {
        const [a, b] = e.blocks[p] || [0, 0];
        return a < to && b > start;
      });
      problem.textContent = "";
      save.disabled = false;
      preview.replaceChildren(...shown.map(e => [entryBody(e), ...view.warnings.filter(w => warningOf(w, e)).map(warningLine),
                                                 sourcesList(e)]).flat().filter(Boolean),
                              ...view.warnings.filter(w => !view.entries.some(e => warningOf(w, e))).map(warningLine));
      if (!shown.length) preview.append(h("p", {class: "muted"}, "No Proverb Entry in these Blocks."));
    } catch (e) {
      if (mine !== seq) return;
      problem.textContent = e.message;
      save.disabled = true;
    }
  };
  const changed = () => {
    // Only when a row is added, moved or deleted: re-adding the rows on every keystroke drops the typing's focus
    if (rows.length !== list.children.length || rows.some((r, i) => list.children[i] !== r)) list.replaceChildren(...rows);
    clearTimeout(timer);
    timer = setTimeout(refresh, 250);
  };
  for (const b of spanBlocks(p, span)) rows.push(blockRow(b, rows, changed));
  save.addEventListener("click", async () => {
    save.disabled = true;
    try {
      await post("review", {type: "confirmed", ...request()});
      await reload();
    } catch (e) {
      toast("Not saved: " + e.message);
      save.disabled = false;
    }
  });
  container.replaceChildren(h("div", {class: "editor"},
    h("div", {class: "muted"}, `Edit the Entry Span of Line Numbers ${span.first}-${span.last}, ${span.label}: each Block as printed, italic words between *asterisks*`),
    list,
    h("div", {class: "row"}, h("button", {onclick: () => {
      rows.push(blockRow({kind: "note", number: 0, text: "", citations: ""}, rows, changed));
      changed();
    }}, "+ Add a Block")),
    problem, h("div", {class: "muted small"}, "Preview"), preview,
    h("div", {class: "row"}, save, h("button", {onclick: () => render()}, "Cancel"))));
  list.replaceChildren(...rows);
  refresh();
}

// A line for the review log, and the page rebuilt with it
async function change(line) {
  try {
    await post("review", line);
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
    const onPage = VIEW.warnings.filter(w => w.page === p);
    const n = onPage.length, urgent = onPage.filter(isPriority).length;
    const held = VIEW.confirmed.filter(c => c.page === p).length;
    return h("option", {value: p, selected: p === current},
             pageLabel(p) + (urgent ? ` ‼${urgent}` : "") + (n ? ` ⚠${n}` : "") + (held ? ` ✓${held}` : ""));
  }));
}

function renderProgress() {
  $("#progress").textContent = `${VIEW.confirmed.length} spans confirmed`;
  $("#confirmed").textContent = `Confirmed (${VIEW.confirmed.length})`;
  $("#next-priority").textContent = `Next priority ‼ (${VIEW.warnings.filter(isPriority).length})`;
}

// Each Entry Span as cropped for its request, labelled with its first Line Number and what the model made of it
function spanLayer(page, share) {
  const pct = x => (x * 100).toFixed(2) + "%";
  return h("div", {class: "spans", style: `width: ${pct(share)}`}, page.spans.map(s => {
    const [left, top, right, bottom] = s.box;
    return h("div", {class: `span span-${s.kind}${s.confirmed ? " span-confirmed" : ""}`, title: `L${s.first}: ${s.label}`,
                     style: `left: ${pct(left)}; top: ${pct(top)}; width: ${pct(right - left)}; height: ${pct(bottom - top)}`},
             h("span", {class: "tag"}, `L${s.first} · ${s.label}`));
  }));
}

function renderSheet() {
  const sheet = $("#sheet");
  const page = PAGES[current];
  const numbered = showNumbered && page && page.layout_image;
  const img = h("img", {src: numbered ? page.layout_image : page ? page.image : `pages/p${String(current).padStart(3, "0")}.png`,
                        alt: numbered ? `PDF page ${current} with its Line Numbers` : `Scan of PDF page ${current}`});
  img.addEventListener("error", () => sheet.replaceChildren(h("p", {class: "muted noscan"}, "No scan of this page in the store")));
  sheet.replaceChildren(img);
  renderSpanLayer();
  sheet.style.width = ZOOMS[zoom] * 100 + "%";
  $("#spans").setAttribute("aria-pressed", String(showSpans));
  $("#numbered").setAttribute("aria-pressed", String(showNumbered));
}

// The spans over the scan alone, so that a confirmation recolours them without loading the scan again
function renderSpanLayer() {
  const sheet = $("#sheet");
  const page = PAGES[current];
  sheet.querySelector(".spans")?.remove();
  if (showSpans && page && page.spans) {
    sheet.append(spanLayer(page, showNumbered && page.layout_image ? page.layout_page_share : 1));
  }
}

function render() {
  renderPicker();
  renderProgress();
  renderRight();
}

function showPage(p) {
  if (p == null || !PAGE_LIST.includes(p)) return;
  current = p;
  showingConfirmed = false;
  history.replaceState(null, "", "#p" + p);
  renderSheet();
  $("#left").scrollTop = 0;
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
  $("#next-priority").addEventListener("click", () => nextWhere(p => VIEW.warnings.some(w => w.page === p && isPriority(w)),
                                                                "No other page has a priority Warning"));
  $("#next-warn").addEventListener("click", () => nextWhere(p => VIEW.warnings.some(w => w.page === p),
                                                            "No other page has Warnings"));
  $("#next-edit").addEventListener("click", () => nextWhere(p => VIEW.confirmed.some(c => c.page === p && c.edited),
                                                            "No other page has an edited span"));
  $("#confirmed").addEventListener("click", () => toggleConfirmed(!showingConfirmed));
  $("#smaller").addEventListener("click", () => setZoom(zoom - 1));
  $("#larger").addEventListener("click", () => setZoom(zoom + 1));
  $("#spans").addEventListener("click", () => { showSpans = !showSpans; renderSheet(); });
  $("#numbered").addEventListener("click", () => { showNumbered = !showNumbered; renderSheet(); });
  document.addEventListener("keydown", e => {
    // Not while editing: changing page would drop the unsaved edit
    if (e.target.closest("textarea, input, select") || $(".editor") || e.metaKey || e.ctrlKey || e.altKey) return;
    if (e.key === "ArrowLeft") step(-1);
    else if (e.key === "ArrowRight") step(1);
    else if (e.key === "p") $("#next-priority").click();
    else if (e.key === "w") $("#next-warn").click();
    else if (e.key === "e") $("#next-edit").click();
    else if (e.key === "s") $("#spans").click();
    else if (e.key === "n") $("#numbered").click();
  });
}

function pageList() {
  return [...new Set(MODEL.pages.map(p => p.pdf).concat(VIEW.warnings.map(w => w.page),
                                                        VIEW.confirmed.map(c => c.page)))].sort((a, b) => a - b);
}

// The store read afresh, as a rerun may have rewritten it since the page loaded, and its entries rebuilt with the log
async function fetchStore() {
  [MODEL, SOURCES, VIEW] = await Promise.all([getJSON("entries.json"), getJSON("sources.json"), getJSON("assembled")]);
  for (const k of Object.keys(PAGES)) delete PAGES[k];
  for (const page of MODEL.pages) PAGES[page.pdf] = page;
  for (const page of VIEW.pages) PAGES[page.pdf] = {...PAGES[page.pdf], ...page};
  DIFFS.clear();
  PAGE_LIST = pageList();
}

// After a line is saved
async function reload() {
  await fetchStore();
  renderSpanLayer();
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
  // With no page asked for, the first with a priority Warning: the server lists those first
  const urgent = VIEW.warnings.find(isPriority);
  showPage(PAGE_LIST.includes(asked) ? asked : urgent ? urgent.page : PAGE_LIST[0]);
}

load();
