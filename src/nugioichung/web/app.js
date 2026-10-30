"use strict";
const WRITABLE = document.documentElement.dataset.writable === "true";
const KIND_NAMES = {
  no_layout: "No layout", left_out: "Region left out", not_transcribed: "Not transcribed",
  lines: "Lines not matched", unformatted: "Format answer not used", unpaired_call: "Unpaired call",
  unpaired_footnote: "Unpaired Footnote", outside: "Text outside every Region",
};
const OUTSIDE_VERDICTS = ["not printed text", "picture", "missed text"];
const OTHER_VERDICTS = ["false alarm", "real problem"];
const ZOOMS = [1, 1.5, 2, 3];
const CALL = /\[\^(\d+)-(\d+)\]/g;

let V = null;                       // viewer.json
const PAGES = {}, CUTS = {}, BLOCKS = {}, WARN_CARDS = {};
const STRETCHES = [];               // every placed stretch rendered, by its data-i
let resolutions = {}, corrections = {};
let current = null, zoom = 0, onlyOpen = false, formSeq = 0, drawerSeq = 0;

const $ = sel => document.querySelector(sel);

function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "style") el.style.cssText = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) if (kid != null && kid !== false) el.append(kid);
  return el;
}

function pct(box) {
  return `left:${box[0] / 10}%;top:${box[1] / 10}%;width:${(box[2] - box[0]) / 10}%;height:${(box[3] - box[1]) / 10}%`;
}

function toast(message) {
  const t = $("#toast");
  t.textContent = message;
  t.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { t.hidden = true; }, 3500);
}

function flash(els) {
  for (const el of els) {
    if (!el) continue;
    el.classList.remove("flash");
    void el.offsetWidth;
    el.classList.add("flash");
  }
}

function pageName(p) {
  const page = PAGES[p];
  return `PDF page ${p}` + (page && page.printed ? ` (printed ${page.printed})` : "");
}

// -- review.jsonl: a later line on the same Warning or block replaces an earlier one
function applyReview(text) {
  for (const line of text.split("\n")) {
    if (!line.trim()) continue;
    let entry;
    try { entry = JSON.parse(line); } catch (e) { continue; }
    if (entry.type === "resolution") resolutions[entry.warning] = entry;
    else if (entry.type === "correction") corrections[entry.item + ":" + entry.block] = entry;
  }
}

async function record(entry) {
  const r = await fetch("review", {method: "POST", headers: {"Content-Type": "application/json"},
                                   body: JSON.stringify(entry)});
  if (!r.ok) throw new Error(await r.text() || r.statusText);
  return r.json();
}

// -- the text
function shape(text) {
  if (/^#{1,6}\s/.test(text)) return "heading";
  if (/^\|/.test(text)) return "table";
  if (/^> /.test(text)) return "verse";
  if (/^(\s*[-*] |\s*\d+\. )/.test(text)) return "list";
  return "para";
}

function appendWithCalls(span, text) {
  let at = 0;
  for (const m of text.matchAll(CALL)) {
    if (m.index > at) span.append(text.slice(at, m.index));
    span.append(h("a", {class: "call", href: "#", "data-label": `${m[1]}-${m[2]}`, title: `Footnote ${m[2]}`},
                  `(${m[2]})`));
    at = m.index + m[0].length;
  }
  if (at < text.length) span.append(text.slice(at));
}

function renderStretches(body, item, block, stretches, skip) {
  for (const s of stretches) {
    let text = s.text;
    if (skip > 0) {
      const n = Math.min(skip, text.length);
      text = text.slice(n);
      skip -= n;
    }
    if (!text) continue;
    const span = h("span", {class: "st"});
    if (s.cut) {
      span.dataset.i = STRETCHES.push({...s, item: item.n, block: block.id}) - 1;
      span.dataset.cut = s.cut;
      if (s.line != null) span.dataset.line = s.line;
    }
    appendWithCalls(span, text);
    body.append(span);
  }
}

function blockKey(item, block) { return item.n + ":" + block.id; }

// A continued run rebuilds viewer.json and may number Items and paragraphs differently, so a Correction counts only
// while the text it corrected is still the text at its place
function correctionOf(item, block) {
  const fix = corrections[blockKey(item, block)];
  return fix && fix.before === block.text ? fix : null;
}

function fillBlock(el, item, block) {
  const fix = correctionOf(item, block);
  const corrected = !!fix && fix.after !== block.text;
  const shown = corrected ? fix.after : block.text;
  el.className = `block ${block.kind} ${shape(shown)}` + (corrected ? " corrected" : "");
  el.replaceChildren();
  const body = h("div", {class: "body"});
  let skip = 0;
  const heading = shown.match(/^#{1,6}\s+/);
  const label = shown.match(/^\[\^\d+-(\d+)\]:\s*/);
  if (heading) skip = heading[0].length;
  if (label) {
    skip = label[0].length;
    body.append(h("span", {class: "fnlabel"}, `(${label[1]})`));
  }
  renderStretches(body, item, block, corrected ? [{text: shown}] : block.stretches, skip);
  el.append(body);
  if (corrected) {
    el.append(h("span", {class: "tag", title: fix.note || ""}, "corrected" + (fix.note ? ": " + fix.note : "")),
              h("details", {}, h("summary", {class: "muted"}, "as transcribed"), h("div", {class: "original"}, block.text)));
  }
  if (WRITABLE) {
    el.append(h("div", {class: "tools"},
      h("button", {onclick: e => { e.stopPropagation(); openEditor(el, item, block); }}, "✎ Correct")));
  }
}

function renderText() {
  const box = $("#text");
  box.replaceChildren();
  for (const item of V.items) {
    const section = h("section", {class: "item", id: "item-" + item.n},
                      h("h2", {}, item.heading), h("p", {class: "byline"}, item.byline));
    for (const block of item.blocks) {
      const el = h("div", {id: `b-${item.n}-${block.id}`, "data-label": block.label});
      BLOCKS[el.id] = {item, block, el};
      fillBlock(el, item, block);
      section.append(el);
    }
    box.append(section);
  }
  if (!V.items.length) box.append(h("p", {class: "muted"}, "No text has been transcribed in this run yet."));
}

function openEditor(el, item, block) {
  const key = blockKey(item, block);
  const fix = correctionOf(item, block);
  const area = h("textarea", {rows: Math.min(18, Math.max(3, Math.ceil(block.text.length / 55)))});
  area.value = fix ? fix.after : block.text;
  const note = h("input", {type: "text", placeholder: "Note (optional): why"});
  note.value = fix ? fix.note || "" : "";
  const save = h("button", {class: "primary", type: "button"}, "Save Correction");
  const cancel = h("button", {type: "button", onclick: () => fillBlock(el, item, block)}, "Cancel");
  save.addEventListener("click", async () => {
    save.disabled = true;
    const placed = block.stretches.filter(s => s.cut);
    const entry = {
      type: "correction", item: item.n, heading: item.heading, block: block.id, block_kind: block.kind,
      pages: [...new Set(placed.map(s => s.page))],
      cuts: [...new Set(placed.map(s => s.cut))],
      boxes: uniqueBoxes(placed).map(s => ({page: s.page, cut: s.cut, line: s.line, box: s.box})),
      before: block.text, after: area.value, note: note.value.trim(),
    };
    try {
      corrections[key] = await record(entry);
      fillBlock(el, item, block);
    } catch (e) {
      toast("Not saved: " + e.message);
      save.disabled = false;
    }
  });
  el.replaceChildren(h("div", {class: "editor", onclick: e => e.stopPropagation()},
    h("span", {class: "muted"}, `Correct this ${block.kind === "footnote" ? "Footnote" : "block"} as plain Markdown:`),
    area, note, h("div", {class: "row"}, save, cancel)));
  area.focus();
}

function uniqueBoxes(stretches) {
  const seen = new Set(), out = [];
  for (const s of stretches) {
    if (!s.box) continue;
    const k = s.page + ":" + s.box.join(",");
    if (!seen.has(k)) { seen.add(k); out.push(s); }
  }
  return out;
}

function firstPlaced(block) { return block.stretches.find(s => s.box) || null; }

// -- highlighting on the page
function highlight(stretches, one) {
  const layer = $("#hl");
  if (!layer) return;
  layer.querySelectorAll(".hl:not(.flashbox)").forEach(el => el.remove());
  for (const s of uniqueBoxes(stretches)) {
    if (s.page === current) layer.append(h("div", {class: "hl para", style: pct(s.box)}));
  }
  if (one && one.box && one.page === current) layer.append(h("div", {class: "hl line", style: pct(one.box)}));
}

function flashBoxes(boxes) {
  const layer = $("#hl");
  if (!layer || !boxes.length) return;
  let first = null;
  for (const box of boxes) {
    const el = h("div", {class: "hl flashbox", style: pct(box)});
    layer.append(el);
    first = first || el;
    setTimeout(() => el.remove(), 2500);
  }
  first.scrollIntoView({block: "center", inline: "center", behavior: "smooth"});
}

function goTo(stretch) {
  if (!stretch || !stretch.box) return;
  showPage(stretch.page);
  flashBoxes([stretch.box]);
}

function lightText(cut, line, on) {
  const sel = `#text .st[data-cut="${CSS.escape(cut)}"]` + (line != null ? `[data-line="${line}"]` : "");
  document.querySelectorAll(sel).forEach(el => el.classList.toggle("lit", on));
}

function scrollTextTo(cut, line) {
  setTab("text");
  const sel = `#text .st[data-cut="${CSS.escape(cut)}"]`;
  let els = [...document.querySelectorAll(sel + (line != null ? `[data-line="${line}"]` : ""))];
  if (!els.length) els = [...document.querySelectorAll(sel)];
  if (!els.length) {
    // a corrected block shows no stretches: find it by what it was transcribed from
    els = Object.values(BLOCKS).filter(b => b.block.stretches.some(s => s.cut === cut && (line == null || s.line === line)))
                                .map(b => b.el);
  }
  if (!els.length) { toast(`No text from ${CUTS[cut] ? CUTS[cut].label : cut}`); return; }
  els[0].scrollIntoView({block: "center", behavior: "smooth"});
  flash(els);
}

function jumpToFootnote(link) {
  const note = document.querySelector(`#text .block.footnote[data-label="${CSS.escape(link.dataset.label)}"]`);
  if (!note) { toast("Its Footnote isn't in the text"); return; }
  const callSpan = link.closest(".st[data-i]");
  const call = callSpan ? STRETCHES[callSpan.dataset.i] : null;
  note.scrollIntoView({block: "center", behavior: "smooth"});
  flash([note, callSpan]);
  const placed = BLOCKS[note.id].block.stretches.filter(s => s.box);
  const page = placed.length ? placed[0].page : call ? call.page : current;
  showPage(page);
  flashBoxes(uniqueBoxes(placed.concat(call && call.box ? [call] : [])).filter(s => s.page === page).map(s => s.box));
}

// -- the pages
function openCount(p) {
  return V.warnings.filter(w => w.page === p && !resolutions[w.id]).length;
}

function renderPageBar() {
  const bar = $("#pagebar");
  bar.replaceChildren();
  for (const page of V.pages) {
    const n = openCount(page.page);
    bar.append(h("button", {class: page.page === current ? "on" : "", title: pageName(page.page),
                            onclick: () => showPage(page.page)},
                 `p${page.page}` + (page.printed ? ` (${page.printed})` : ""), n ? h("span", {class: "w"}, ` ⚠${n}`) : null));
  }
  bar.append(h("span", {class: "zoom"},
    h("button", {title: "Smaller", onclick: () => setZoom(zoom - 1)}, "−"),
    h("button", {title: "Larger", onclick: () => setZoom(zoom + 1)}, "+")));
}

function setZoom(z) {
  zoom = Math.max(0, Math.min(ZOOMS.length - 1, z));
  $("#sheet").style.width = ZOOMS[zoom] * 100 + "%";
}

function hiddenWarning(w) { return onlyOpen && !!resolutions[w.id]; }

function showPage(p) {
  if (p == null || !PAGES[p]) return;
  if (p !== current) {
    current = p;
    renderSheet();
  }
  renderPageBar();
}

function renderSheet() {
  const page = PAGES[current];
  if (!page) return;
  const sheet = $("#sheet");
  sheet.replaceChildren();
  setZoom(zoom);
  const overlay = h("div", {class: "overlay"});
  sheet.append(h("img", {src: page.image, alt: pageName(page.page)}), overlay);
  if (!page.laid_out) overlay.append(h("div", {class: "nolayout"}, "This page has no layout answer"));
  for (const r of page.regions) {
    const kind = V.kinds[r.kind];
    overlay.append(h("div", {class: "region", style: pct(r.box) + `;border-color:${kind.colour}`}));
    for (const c of r.cuts) {
      const what = `${c.label}: ${kind.label}${r.title ? " · " + r.title : ""}`;
      overlay.append(h("div", {class: "cut" + (c.strip > 1 ? " strip" : "") + (c.matched ? "" : " unmatched"),
                               style: pct(c.box) + `;--kind:${kind.colour}`, title: what,
                               onclick: () => scrollTextTo(c.key, null)}));
      if (c.matched) {
        c.lines.forEach((line, i) => overlay.append(h("div", {
          class: "pline", style: pct(line.box),
          onclick: e => { e.stopPropagation(); scrollTextTo(c.key, i); },
          onmouseenter: () => lightText(c.key, i, true), onmouseleave: () => lightText(c.key, i, false),
        })));
      }
      overlay.append(h("button", {class: "badge", title: "Open " + what,
                                  style: `left:${c.box[0] / 10}%;top:${c.box[1] / 10}%;background:${kind.colour}`,
                                  onclick: e => { e.stopPropagation(); openDrawer(c.key); }},
                       c.strip ? `${r.n}·${c.strip}` : String(r.n)));
    }
  }
  const whole = [];
  for (const w of V.warnings) {
    if (w.page !== current || hiddenWarning(w)) continue;
    if (!w.box) { whole.push(w); continue; }
    overlay.append(h("div", {class: "warn" + (resolutions[w.id] ? " resolved" : ""), style: pct(w.box), title: w.reason,
                             onclick: e => { e.stopPropagation(); showWarning(w.id); }},
                     h("span", {class: "warnsign"}, "⚠")));
  }
  sheet.classList.toggle("whole-warn", whole.some(w => !resolutions[w.id]));
  if (whole.length) {
    overlay.append(h("button", {class: "wholewarn", onclick: () => showWarning(whole[0].id)},
                     `⚠ ${whole.length} Warning${whole.length > 1 ? "s" : ""} about this whole page`));
  }
  overlay.append(h("div", {id: "hl"}));
}

// -- Warnings
function renderWarnings() {
  const list = $("#warnings");
  list.replaceChildren();
  const open = V.warnings.filter(w => !resolutions[w.id]).length;
  $("#tab-warnings").textContent = `Warnings (${open} of ${V.warnings.length} unresolved)`;
  let page = null;
  for (const w of V.warnings) {
    delete WARN_CARDS[w.id];
    if (hiddenWarning(w)) continue;
    if (w.page !== page) {
      page = w.page;
      list.append(h("h3", {class: "page"}, pageName(page)));
    }
    const card = warningCard(w);
    WARN_CARDS[w.id] = card;
    list.append(card);
  }
  if (!list.children.length) {
    list.append(h("p", {class: "muted"}, V.warnings.length ? "Every Warning is resolved." : "This run has no Warnings."));
  }
}

function warningCard(w) {
  const res = resolutions[w.id];
  const card = h("div", {class: "card" + (res ? " resolved" : "")},
    h("div", {class: "reason", title: "Show it on its page",
              onclick: () => { showPage(w.page); if (w.box) flashBoxes([w.box]); else flash([$("#sheet")]); }},
      h("span", {class: "kind"}, KIND_NAMES[w.kind] || w.kind), " ", w.reason));
  if (res) {
    card.append(h("div", {class: "verdict"}, "Resolved as ", h("b", {}, res.verdict),
                  res.says ? ` — it says “${res.says}”` : "", res.note ? ` — ${res.note}` : "",
                  h("span", {class: "muted"}, ` · ${res.time || ""}`)));
    if (WRITABLE) {
      const change = h("button", {type: "button"}, "Change");
      change.addEventListener("click", () => { change.replaceWith(resolveForm(w)); });
      card.append(h("div", {class: "row"}, change));
    }
  } else if (WRITABLE) {
    card.append(resolveForm(w));
  }
  return card;
}

function resolveForm(w) {
  const name = "verdict-" + (++formSeq);
  const verdicts = w.kind === "outside" ? OUTSIDE_VERDICTS : OTHER_VERDICTS;
  const res = resolutions[w.id];
  const says = h("textarea", {rows: 2, placeholder: "What the missed text says", hidden: true});
  const note = h("input", {type: "text", placeholder: "Note (optional)"});
  const save = h("button", {class: "primary", type: "submit", disabled: true}, "Resolve");
  if (res) { says.value = res.says || ""; note.value = res.note || ""; }
  const form = h("form", {},
    h("div", {class: "row"}, verdicts.map(v => h("label", {},
      h("input", {type: "radio", name, value: v, checked: res && res.verdict === v}), " " + v))),
    says, note, h("div", {class: "row"}, save));
  const update = () => {
    const chosen = form.querySelector(`input[name="${name}"]:checked`);
    says.hidden = !chosen || chosen.value !== "missed text";
    save.disabled = !chosen || (chosen.value === "missed text" && !says.value.trim());
  };
  form.addEventListener("input", update);
  update();
  form.addEventListener("submit", async e => {
    e.preventDefault();
    const verdict = form.querySelector(`input[name="${name}"]:checked`).value;
    save.disabled = true;
    try {
      resolutions[w.id] = await record({
        type: "resolution", warning: w.id, kind: w.kind, reason: w.reason, page: w.page, box: w.box, verdict,
        note: note.value.trim(), says: verdict === "missed text" ? says.value.trim() : "",
      });
      renderWarnings();
      renderPageBar();
      renderSheet();
    } catch (err) {
      toast("Not saved: " + err.message);
      save.disabled = false;
    }
  });
  return form;
}

function showWarning(id) {
  setTab("warnings");
  if (!WARN_CARDS[id]) {
    onlyOpen = false;
    $("#only-open").checked = false;
    renderWarnings();
    renderSheet();
  }
  const card = WARN_CARDS[id];
  if (!card) return;
  card.scrollIntoView({block: "center", behavior: "smooth"});
  flash([card]);
}

function setTab(which) {
  $("#tab-text").classList.toggle("on", which === "text");
  $("#tab-warnings").classList.toggle("on", which === "warnings");
  $("#text").hidden = which !== "text";
  $("#warnings").hidden = which !== "warnings";
}

// -- the drawer: what one Region or Strip's requests sent and got back
async function getText(url) {
  try {
    const r = await fetch(url, {cache: "no-store"});
    return r.ok ? await r.text() : null;
  } catch (e) {
    return null;
  }
}

function lineFlags(line) {
  return ["indented", "short", "centred", "picture"].filter(f => line[f]).join(", ") || "·";
}

function readTable(cut, answer) {
  const lines = (answer.lines || []).map(l => (l || "").trim()).filter(Boolean);
  const flags = [answer.starts_mid_paragraph && "starts mid-paragraph", answer.ends_mid_paragraph && "ends mid-paragraph"]
    .filter(Boolean).join(", ") || "starts and ends with whole paragraphs";
  const rows = [];
  for (let i = 0; i < Math.max(lines.length, cut.lines.length); i++) {
    const printed = cut.lines[i];
    rows.push(h("tr", {onmouseenter: () => printed && highlight([{page: cut.page, box: printed.box}], null),
                       onmouseleave: () => highlight([], null)},
      h("td", {class: "num"}, String(i + 1)), h("td", {class: "flags"}, printed ? lineFlags(printed) : "—"),
      h("td", {}, i < lines.length ? lines[i] : "—")));
  }
  return h("div", {}, h("h4", {}, "Read answer"), h("p", {class: "muted"}, flags),
           h("table", {class: "lines"}, h("thead", {}, h("tr", {}, h("th", {}, "#"), h("th", {}, "printed line"),
                                                         h("th", {}, "read line"))), h("tbody", {}, rows)));
}

async function requestView(cut, req) {
  const section = h("section", {class: "req"},
    h("h3", {}, req.pass === "read" ? "Read request" : "Format request",
      h("span", {class: "status" + (req.status === "ok" ? " ok" : "")}, req.status || "never ran")));
  if (req.pass === "read") {
    for (const f of req.files.filter(f => f.startsWith("image"))) {
      const src = `${req.folder}/${f}`;
      section.append(h("p", {class: "muted"}, "Its crop as sent (the format request sends the same):"),
                     h("a", {href: src, target: "_blank"}, h("img", {class: "crop", src, alt: "Crop as sent"})));
    }
  }
  const [system, user, saved] = await Promise.all([
    getText(`${req.folder}/system.txt`), getText(`${req.folder}/user.txt`), getText(req.result)]);
  if (user != null) section.append(h("details", {}, h("summary", {}, "Prompt"), h("pre", {}, user)));
  if (system != null) section.append(h("details", {}, h("summary", {}, "System prompt"), h("pre", {}, system)));
  let result = null;
  try { result = saved ? JSON.parse(saved) : null; } catch (e) { result = null; }
  if (!result) {
    section.append(h("p", {class: "muted"}, "No saved answer."));
  } else {
    if (req.status !== "ok" && result.status === "ok") {
      section.append(h("p", {class: "muted"}, "This answer was made from other input (an earlier box, setting or " +
                                              "prompt), so the run doesn't use it."));
    }
    if (result.error) section.append(h("pre", {class: "error"}, result.error));
    if (result.status === "ok" && req.pass === "read") section.append(readTable(cut, result.answer));
    else if (result.status === "ok") section.append(h("h4", {}, "Format answer"), h("pre", {}, result.answer.text || ""));
    else if (result.content) section.append(h("pre", {}, result.content));
  }
  return section;
}

async function openDrawer(key) {
  const cut = CUTS[key], seq = ++drawerSeq;
  const kind = V.kinds[cut.region.kind];
  showPage(cut.page);
  $("#drawer").hidden = false;
  $("#drawer-title").textContent = `${cut.label}: ${kind.label}` + (cut.region.title ? ` · ${cut.region.title}` : "");
  const body = $("#drawer-body");
  body.replaceChildren(h("p", {class: "muted"}, "Loading…"));
  const found = cut.lines.length;
  const lines = cut.read_lines == null ? `${found} printed line(s) found; no read answer`
    : cut.matched ? `${found} printed line(s) found, matched one for one to the lines read`
    : `${found} printed line(s) found, ${cut.read_lines} read: not matched, so the read flags and the format ` +
      "request decide its paragraphs, and its text is highlighted as a whole";
  const parts = [
    h("p", {class: "muted"}, `Box ${JSON.stringify(cut.box)}` + (cut.region.continues ? " · continues its Item" : "")),
    h("p", {}, lines),
  ];
  for (const req of cut.requests) parts.push(await requestView(cut, req));
  if (!cut.requests.length) parts.push(h("p", {class: "muted"}, "No requests."));
  if (seq === drawerSeq) body.replaceChildren(...parts);
}

// -- start
function wire() {
  $("#tab-text").addEventListener("click", () => setTab("text"));
  $("#tab-warnings").addEventListener("click", () => setTab("warnings"));
  $("#only-open").addEventListener("change", e => {
    onlyOpen = e.target.checked;
    renderWarnings();
    renderSheet();
  });
  $("#drawer-close").addEventListener("click", () => { $("#drawer").hidden = true; });
  const text = $("#text");
  text.addEventListener("mouseover", e => {
    const blockEl = e.target.closest(".block");
    if (!blockEl || !BLOCKS[blockEl.id] || blockEl.querySelector(".editor")) { highlight([], null); return; }
    const span = e.target.closest(".st[data-i]");
    highlight(BLOCKS[blockEl.id].block.stretches, span ? STRETCHES[span.dataset.i] : null);
  });
  text.addEventListener("mouseleave", () => highlight([], null));
  text.addEventListener("click", e => {
    const call = e.target.closest("a.call");
    if (call) { e.preventDefault(); jumpToFootnote(call); return; }
    if (e.target.closest("button, textarea, input, details, .editor")) return;
    if (String(window.getSelection())) return;
    const span = e.target.closest(".st[data-i]");
    const blockEl = e.target.closest(".block");
    goTo(span ? STRETCHES[span.dataset.i] : blockEl && BLOCKS[blockEl.id] ? firstPlaced(BLOCKS[blockEl.id].block) : null);
  });
}

async function load() {
  wire();
  if (!WRITABLE) $("#readonly").hidden = false;
  try {
    const r = await fetch("viewer.json", {cache: "no-store"});
    if (!r.ok) throw new Error(`viewer.json: ${r.status}`);
    V = await r.json();
  } catch (e) {
    $("#title").textContent = "Couldn't load viewer.json: " + e.message;
    return;
  }
  applyReview((await getText("review.jsonl")) || "");
  for (const page of V.pages) {
    PAGES[page.page] = page;
    for (const region of page.regions) {
      for (const cut of region.cuts) CUTS[cut.key] = {...cut, region, page: page.page};
    }
  }
  document.title = V.title;
  $("#title").textContent = V.title;
  renderText();
  renderWarnings();
  if (V.pages.length) showPage(V.pages[0].page);
}

load();
