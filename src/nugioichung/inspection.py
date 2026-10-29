"""
Inspection: each page drawn with its Regions outlined and numbered, its Strip cuts dashed and ⚠ on any printed text
outside every Region, and one offline inspect.html that goes page → Regions → Strips, showing the drawn page, then
each request's image as sent, its prompt and its answer side by side (a read and a format request per Region or
Strip). Both are built from the saved requests and
answers only.
"""
import html
import json
import os
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont

from src.nugioichung.layout import page_stamp
from src.nugioichung.regions import KINDS, page_key
from src.nugioichung.transcribe import format_stamp, needs_format, read_stamp
from src.providers.vlm_requests import is_current, read_result

WARNING = (204, 0, 0)


def drawn_page(page):
    """Where a page drawn with its Regions goes, relative to the run folder."""
    return os.path.join("layout", f"{page_key(page)}.png")


def _warning_sign(draw, x, y, size, font):
    """A ⚠ drawn as a red triangle with "!" in it, its top left at (x, y)."""
    draw.polygon([(x, y + size), (x + size / 2, y), (x + size, y + size)], fill=WARNING)
    draw.text((x + size / 2, y + size * 0.62), "!", fill=(255, 255, 255), font=font, anchor="mm")


def draw_layout(png, layout, out_path):
    """
    Writes the layout image `png` with each Region's snapped box outlined in its kind's colour and its number, the
    cuts between its Strips dashed, and each patch of printed text outside every Region boxed in red with a ⚠.
    """
    img = Image.open(BytesIO(png)).convert("RGB")
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default(size=max(16, img.height // 60))
    w, h = img.size

    def px(box):
        left, top, right, bottom = box
        return left * w / 1000, top * h / 1000, right * w / 1000, bottom * h / 1000

    for r in layout.regions:
        colour = KINDS[r.kind].colour
        box = px(r.box)
        draw.rectangle(box, outline=colour, width=4)
        for strip in r.strips[1:]:
            y = strip[1] * h / 1000
            for x in range(int(box[0]), int(box[2]), 24):
                draw.line((x, y, min(x + 12, box[2]), y), fill=colour, width=3)
        label = str(r.n)
        tl, tt, tr, tb = draw.textbbox((box[0] + 6, box[1] + 4), label, font=font)
        draw.rectangle((tl - 4, tt - 3, tr + 4, tb + 3), fill=colour)
        draw.text((box[0] + 6, box[1] + 4), label, fill=(255, 255, 255), font=font)
    for outside in layout.outside:
        box = px(outside)
        draw.rectangle(box, outline=WARNING, width=4)
        _warning_sign(draw, box[0] + 4, box[1] + 4, font.size * 1.4, font)
    img.save(out_path)


def _read(path):
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return f.read()


def _pre(text, cls=""):
    return f'<pre class="{cls}">{html.escape(text)}</pre>'


def _request_row(run_dir, results_dir, key, stamp, title, answer_view, heading="h3"):
    """One request: its image as sent, its prompt and its answer, side by side. An answer not made against `stamp`
    is marked as not used."""
    folder = os.path.join(results_dir, key)
    rel = os.path.relpath(folder, run_dir)
    images = sorted(n for n in os.listdir(folder) if n.startswith("image")) if os.path.isdir(folder) else []
    image_cells = "".join(f'<a href="{html.escape(rel)}/{n}"><img loading="lazy" src="{html.escape(rel)}/{n}"></a>'
                          for n in images) or '<p class="muted">no saved request</p>'
    system, user = _read(os.path.join(folder, "system.txt")), _read(os.path.join(folder, "user.txt"))
    prompt = ""
    if user is not None:
        prompt = _pre(user) + f"<details><summary>System prompt</summary>{_pre(system or '')}</details>"
    result = read_result(results_dir, key)
    if result is None:
        answer = '<p class="muted">never ran</p>'
    else:
        answer = ""
        if result.get("status") == "ok" and not is_current(result, stamp):
            answer = ('<p class="status">made from other input (an earlier box, setting or prompt): not used, and '
                      'the image and prompt here may be that earlier one\'s</p>')
        answer += f'<p class="status {html.escape(result.get("status", ""))}">{html.escape(result.get("status", ""))}' \
                 f' · {result.get("attempts", "?")} attempt(s)</p>'
        if result.get("error"):
            answer += _pre(result["error"], "error")
        if result.get("status") == "ok":
            answer += answer_view(result["answer"])
        elif result.get("content"):
            answer += _pre(result["content"])
        if result.get("reasoning"):
            answer += f"<details><summary>Reasoning</summary>{_pre(result['reasoning'])}</details>"
    return (f'<section class="request"><{heading}>{html.escape(title)}</{heading}><div class="row">'
            f'<div class="cell image">{image_cells}</div><div class="cell">{prompt}</div>'
            f'<div class="cell">{answer}</div></div></section>')


def _layout_answer(answer):
    return _pre(json.dumps(answer, ensure_ascii=False, indent=1))


def _read_answer(answer):
    flags = [f for f in ("starts_mid_paragraph", "ends_mid_paragraph") if answer.get(f)]
    return (f'<p class="muted">{html.escape(", ".join(flags) or "whole paragraphs")}</p>'
            + _pre("\n".join(line or "" for line in answer.get("lines") or [])))


def _format_answer(answer):
    return _pre(answer.get("text") or "")


def _cut_rows(run_dir, r, cut, reads, read_dir, format_dir, read_pass_stamp, format_pass_stamp):
    """A Region's or Strip's read request and, if it has one, its format request."""
    title = f"Region {r.n}, Strip {cut.strip} of {cut.of}" if cut.strip else f"Region {r.n}"
    heading = "h4" if cut.strip else "h3"
    rows = [_request_row(run_dir, read_dir, cut.key, {**read_pass_stamp, **read_stamp(r, cut)},
                         f"{title} · read", _read_answer, heading)]
    read, _ = reads.get(cut.key, (None, None))
    if read is not None and needs_format(r, read):
        rows.append(_request_row(run_dir, format_dir, cut.key, {**format_pass_stamp, **format_stamp(r, cut, read)},
                                 f"{title} · format", _format_answer, heading))
    return rows


def write_inspect(run_dir, title, pages, layouts, reads, layout_dir, read_dir, format_dir, layout_stamp,
                  read_pass_stamp, format_pass_stamp):
    """
    Writes <run-dir>/inspect.html for `pages` (PDF page numbers), from the drawn pages in <run-dir>/layout/ and the
    saved requests and answers. `layouts`: {pdf page: checked layout}, for the pages that have one; `reads`: {cut
    key: (checked read answer or None, why)}, which say what each format request was sent. The stamps are the
    passes' own, so an answer the outputs don't use is shown as such.
    """
    body = []
    for page in pages:
        layout = layouts.get(page)
        regions = layout.regions if layout else []
        printed = f" (printed {html.escape(layout.printed_page)})" if layout and layout.printed_page else ""
        drawn = drawn_page(page)
        outside = layout.outside if layout else []
        parts = [f'<h2>PDF page {page}{printed} · {len(regions)} Region(s)</h2>']
        if os.path.exists(os.path.join(run_dir, drawn)):
            parts.append(f'<a href="{drawn}"><img class="drawn" loading="lazy" src="{drawn}"></a>')
        parts += [f'<p class="status">⚠ text outside any Region at {box} (boxed in red on the drawn page)</p>'
                  for box in outside]
        parts.append(_request_row(run_dir, layout_dir, page_key(page), {**layout_stamp, **page_stamp(page)},
                                  "Layout request", _layout_answer))
        for r in regions:
            what = KINDS[r.kind].label + (f" · {r.title}" if r.title else "") + (" · continues" if r.continues else "")
            box = f"box {r.box}" + (f" (layout pass gave {r.layout_box})" if r.box != r.layout_box else "")
            strips = f" · {len(r.strips)} Strips" if r.strips else ""
            parts.append(f'<h3>Region {r.n}: {html.escape(what)}{strips}</h3><p class="muted">{html.escape(box)}</p>')
            for cut in r.cuts:
                if cut.strip:
                    parts.append(f'<p class="muted">Strip {cut.strip} of {cut.of} · box {cut.box}</p>')
                parts += _cut_rows(run_dir, r, cut, reads, read_dir, format_dir, read_pass_stamp, format_pass_stamp)
        flag = " ⚠" if outside else ""
        body.append(f'<details class="page" id="p{page}"><summary>PDF page {page}{printed}{flag}</summary>'
                    f'{"".join(parts)}</details>')
    nav = " ".join(f'<a href="#p{p}">{p}</a>' for p in pages)
    with open(os.path.join(run_dir, "inspect.html"), "w", encoding="utf-8") as f:
        f.write(_PAGE.format(title=html.escape(title), nav=nav, body="\n".join(body)))


_PAGE = """<!doctype html>
<html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
body {{ font: 14px/1.45 system-ui, sans-serif; margin: 16px; background: #fafafa; color: #222; }}
nav a {{ margin-right: 6px; }}
details.page {{ background: #fff; border: 1px solid #ddd; border-radius: 6px; margin: 10px 0; padding: 6px 12px; }}
details.page > summary {{ font-weight: 600; cursor: pointer; font-size: 16px; }}
img.drawn {{ max-width: 100%; max-height: 90vh; border: 1px solid #ccc; }}
.request {{ border-top: 1px solid #eee; padding-top: 6px; }}
.request h4 {{ margin-left: 16px; }}
.row {{ display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) minmax(0, 1fr); gap: 12px; }}
.cell img {{ max-width: 100%; border: 1px solid #ccc; }}
.cell.image {{ max-height: 80vh; overflow: auto; }}
pre {{ white-space: pre-wrap; word-break: break-word; background: #f4f4f4; padding: 8px; margin: 4px 0;
       max-height: 80vh; overflow: auto; }}
pre.error {{ background: #fdecec; }}
.status.ok {{ color: #070; }} .status {{ color: #a00; font-weight: 600; }}
.muted {{ color: #777; }}
@media (max-width: 900px) {{ .row {{ grid-template-columns: 1fr; }} }}
</style></head><body>
<h1>{title}</h1>
<nav>PDF pages: {nav}</nav>
{body}
<script>
// A page link opens its page, which is folded away like the others
function openLinkedPage() {{
  var page = document.getElementById(location.hash.slice(1));
  if (page && page.tagName === "DETAILS") {{ page.open = true; page.scrollIntoView(); }}
}}
addEventListener("hashchange", openLinkedPage);
openLinkedPage();
</script>
</body></html>
"""
