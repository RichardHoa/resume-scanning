"""
The AI Proofreading Pass's code-only parts: reading a page's transcription against its OCR lines, joining the
pages into the book, pairing notes, the diff against book.raw.md, and Phase 2 (one task per unpaired Note).
"""
import pytest

from src.pipelines.proofreader import (
    MISSED, apply_note_results, assemble, block_diff, enforce_spellings, flag_leftovers, note_tasks, page_names,
    pair_notes, read_page, spelling_rules, story_names
)
from src.prompts.proofread_prompts import transcribe_user_text


def line(n, text, x0=0.10, y=None, role="body", check=False):
    y = 0.05 + 0.033 * n if y is None else y
    return {"n": n, "text": text, "bbox": [x0, y, 0.90, y + 0.03], "check": check, "role": role}


def entry(page, lines, continues=False, first="paragraph"):
    return {"page": page, "printed_page_est": page - 1, "lines": lines,
            "segments": [{"kind": first, "bbox": [0.1, 0.05, 0.9, 0.3], "continues": continues}],
            "column": {"left": 0.10, "right": 0.90, "indent_at": 0.14}}


def answer(blocks, starts_mid=False, footnotes=(), story_notes=(), printed=""):
    return {"printed_page": printed, "starts_mid_paragraph": starts_mid,
            "blocks": [{"text": t, "box": [100, 100, 900, 200]} for t in blocks],
            "story_notes": list(story_notes), "footnotes": list(footnotes), "ends_mid_paragraph": False}


# pdf 42 -> 43: the paragraph about the tusk runs over the page break; "Được Ngà" opens a new one, indented
P42 = entry(42, [
    line(1, "SỰ TÍCH VUA TABÀI", x0=0.3),
    line(2, "Một hôm hai người rủ nhau vào rừng săn bắn, mỗi"),
    line(3, "người đi một nẻo. Hoàng tử TaBài đi theo đường"),
    line(4, "ao Ngà. Đến bờ ao thấy nước trong, ngài lấy"),
], first="heading")
P43 = entry(43, [
    line(1, "làm lạ. Hoàng tử ra lệnh cho quần thần xuống"),
    line(2, "mò và tìm thấy một khúc Ngà. Quần thần tầu"),
    line(3, "tay vào nhấc lên thấy nhẹ bỗng."),
    line(4, "Được Ngà ngài lấy làm thích thú, bèn ra", x0=0.152),
    line(5, "lệnh cho quần thần về, không đi săn bắn nữa."),
    line(6, "42", role="removed"),
], continues=True)
A42 = answer(["## SỰ TÍCH VUA TABÀI",
              "Một hôm hai người rủ nhau vào rừng săn bắn, mỗi người đi một nẻo. Hoàng tử TaBài đi theo "
              "đường ao Ngà. Đến bờ ao thấy nước trong, ngài lấy"], printed="41")
A43 = answer(["làm lạ. Hoàng tử ra lệnh cho quần thần xuống mò và tìm thấy một khúc Ngà. Quần thần tâu "
              "tay vào nhấc lên thấy nhẹ bỗng.",
              "Được Ngà ngài lấy làm thích thú, bèn ra lệnh cho quần thần về, không đi săn bắn nữa."],
             printed="42")

RAW = "\n\n".join([
    "# TRUYỆN CỔ DÂN GIAN CHĂM",
    "<!-- pdf 4 · front -->",
    "## 6. Sự tích Táo quân",
    "<!-- pdf 40-41 -->",
    "Thế rồi các cụ già kể chuyện.",
    "## 7. Sự tích vua TaBài và nàng BìLà",
    "<!-- pdf 42-43 · heading: SỰ TÍCH VUA TABÀI -->",
    "Một hôm hai người rủ nhau vào rừng săn bắn, mỗi người đi một nẻo. Hoàng tử TaBài đi theo đường ao Ngà. "
    "Đến bờ ao thấy nước trong, ngài lấy làm lạ. Hoàng tử ra lệnh cho quần thần xuống mò và tìm thấy một khúc "
    "Ngà. Quần thần tầu tay vào nhấc lên thấy nhẹ bỗng.",
    "Được Ngà ngài lấy làm thích thú, bèn ra lệnh cho quần thần về, không đi săn bắn nữa. ⚠",
]) + "\n"


# -- one page
def test_each_block_gets_the_box_of_the_ocr_lines_it_covers():
    page = read_page(P43, A43)

    assert [u["text"] for u in page["units"]] == [b["text"] for b in A43["blocks"]]
    assert page["units"][0]["boxes"] == [{"page": 43, "bbox": [0.10, 0.083, 0.90, pytest.approx(0.179)],
                                          "approx": False}]
    assert page["units"][1]["boxes"][0]["bbox"][1] == pytest.approx(0.182)
    assert page["report"]["missed"] == [] and page["report"]["added"] == []


def test_an_ocr_line_the_transcription_leaves_out_comes_back_flagged_where_it_was():
    skipped = answer(["làm lạ. Hoàng tử ra lệnh cho quần thần xuống mò và tìm thấy một khúc Ngà. Quần thần tâu",
                      "Được Ngà ngài lấy làm thích thú, bèn ra lệnh cho quần thần về, không đi săn bắn nữa."])

    page = read_page(P43, skipped)

    assert [u["text"] for u in page["units"]] == [
        skipped["blocks"][0]["text"], f"{MISSED} tay vào nhấc lên thấy nhẹ bỗng.", skipped["blocks"][1]["text"]]
    assert page["units"][1]["missed"] and page["units"][1]["boxes"][0]["bbox"][1] == pytest.approx(0.149)
    assert page["report"]["missed"] == [{"n": 3, "text": "tay vào nhấc lên thấy nhẹ bỗng."}]


def test_a_line_left_out_is_found_even_when_its_words_are_all_over_the_page():
    p = entry(43, [line(1, "Hoàng tử ra lệnh cho quần thần xuống ao"),
                   line(2, "lại với Hoàng tử trong ao có Ngà. Hoàng tử"),
                   line(3, "cho quần thần xuống ao có Ngà lại với Hoàng tử.")])

    page = read_page(p, answer(["Hoàng tử ra lệnh cho quần thần xuống ao cho quần thần xuống ao có Ngà lại với "
                                "Hoàng tử."]))

    assert page["report"]["missed"] == [{"n": 2, "text": "lại với Hoàng tử trong ao có Ngà. Hoàng tử"}]


def test_an_ocr_line_the_model_fixed_is_not_missed():
    p = entry(24, [line(1, "Tên vua thầy vậy, lấy làm lạ. Hắn nghĩ"), line(2, "Hại ngưòi vừa đi đưọc lưng chừng")])

    page = read_page(p, answer(["Tên vua thấy vậy, lấy làm lạ. Hắn nghĩ Hai người vừa đi được lưng chừng"]))

    assert page["report"]["missed"] == [] and page["report"]["added"] == []


def test_text_with_no_ocr_line_under_it_is_flagged_and_boxed_where_the_model_says():
    made_up = answer([b["text"] for b in A43["blocks"]] + ["Nàng tiên hiện ra giữa ao sen và hát một bài rất dài."])

    page = read_page(P43, made_up)

    last = page["units"][-1]
    assert last["text"] == "Nàng tiên hiện ra giữa ao sen và hát một bài rất dài. ⚠"
    assert last["boxes"] == [{"page": 43, "bbox": [0.1, 0.1, 0.9, 0.2], "approx": True}]
    assert page["report"]["added"] == [last["text"]]


def test_a_page_whose_first_line_is_not_indented_carries_on_whatever_the_model_says():
    assert read_page(P43, A43)["joins"] is True    # A43 says starts_mid_paragraph: false


def test_an_indented_first_line_starts_a_new_paragraph_whatever_the_model_says():
    indented = dict(P43, segments=[{"kind": "paragraph", "bbox": [0.1, 0.05, 0.9, 0.3], "continues": False}])

    assert read_page(indented, dict(A43, starts_mid_paragraph=True))["joins"] is False


def test_the_models_reading_decides_when_the_ocr_missed_the_pages_first_line():
    no_first_line = dict(P43, lines=P43["lines"][1:])

    assert read_page(no_first_line, dict(A43, starts_mid_paragraph=True))["joins"] is True
    assert read_page(no_first_line, A43)["joins"] is False


def test_dialogue_dashes_are_escaped_and_headings_go_on_one_line():
    page = read_page(entry(60, [line(1, "PÔ RI YAK", x0=0.3), line(2, "(Thần sóng)", x0=0.3),
                                line(3, "- Ngài đi săn sao lại về một mình ?")], first="heading"),
                     answer(["## PÔ RI YAK\n(Thần sóng)", "- Ngài đi săn sao lại về một mình ?"]))

    assert [u["text"] for u in page["units"]] == ["## PÔ RI YAK (Thần sóng)", "\\- Ngài đi săn sao lại về một mình ?"]


def test_scene_breaks_are_left_out():
    page = read_page(P43, answer([A43["blocks"][0]["text"], "* * *", A43["blocks"][1]["text"]]))

    assert [u["text"] for u in page["units"]] == [b["text"] for b in A43["blocks"]]


def test_an_ocr_line_left_out_with_too_few_words_is_noise_not_missed():
    junk = dict(P43, lines=P43["lines"][:5] + [line(7, "N nnn nh Tàn n"), line(8, "Š/о1/2оє1")])

    page = read_page(junk, A43)

    assert [u["text"] for u in page["units"]] == [b["text"] for b in A43["blocks"]]
    assert page["report"]["missed"] == []
    assert page["report"]["left_out"] == [{"n": 7, "text": "N nnn nh Tàn n", "why": "noise"},
                                          {"n": 8, "text": "Š/о1/2оє1", "why": "noise"}]


def test_a_garbled_line_beside_a_block_with_text_no_ocr_line_is_under_is_left_out():
    # pdf 274: the drop cap's line comes out of the OCR as junk, and the model reads the line anew
    p = entry(274, [line(1, "HOÀNG TỬ TÊWA MỪNÔ", x0=0.3),
                    line(2, "I gàc sai xuống để cai tri xử Xn thma.", check=True),
                    line(3, "oàng đế Cuma Rachà là con của thượng"),
                    line(4, "Xri Inra là một cường quốc có đến trăm nước"), line(5, "chư hầu.")], first="heading")
    a = answer(["## HOÀNG TỬ TÊWA MỪNÔ",
                "Hoàng đế Cuma Rachà là con của thượng đế sai xuống để cai trị xứ Xri Inra.",
                "Xri Inra là một cường quốc có đến trăm nước chư hầu."])

    page = read_page(p, a)

    assert [u["text"] for u in page["units"]] == [a["blocks"][0]["text"], a["blocks"][1]["text"] + " ⚠",
                                                  a["blocks"][2]["text"]]
    assert page["report"]["missed"] == []
    assert page["report"]["left_out"] == [
        {"n": 2, "text": "I gàc sai xuống để cai tri xử Xn thma.", "why": "read anew in a ⚠ block"}]


# -- the book
def test_pages_join_into_the_raw_sections_with_a_paragraph_split_by_the_page_made_whole():
    pages = {42: read_page(P42, A42), 43: read_page(P43, A43)}

    book = assemble(RAW, pages, [])

    assert book.blocks[:5] == RAW.split("\n\n")[:5]     # the front and a section with no page read stay as they are
    assert book.blocks[5:] == [
        "## 7. Sự tích vua TaBài và nàng BìLà",
        "<!-- pdf 42-43 · heading: SỰ TÍCH VUA TABÀI -->",
        "Một hôm hai người rủ nhau vào rừng săn bắn, mỗi người đi một nẻo. Hoàng tử TaBài đi theo đường ao Ngà. "
        "Đến bờ ao thấy nước trong, ngài lấy làm lạ. Hoàng tử ra lệnh cho quần thần xuống mò và tìm thấy một khúc "
        "Ngà. Quần thần tâu tay vào nhấc lên thấy nhẹ bỗng.",
        "Được Ngà ngài lấy làm thích thú, bèn ra lệnh cho quần thần về, không đi săn bắn nữa.",
    ]
    assert [b["page"] for b in book.boxes[7]] == [42, 43]
    assert book.pages[7] == [42, 43]


def test_the_book_is_logged_as_a_block_diff_of_book_raw_md():
    pages = {42: read_page(P42, A42), 43: read_page(P43, A43)}

    book = assemble(RAW, pages, [])

    raw = RAW.rstrip("\n").split("\n\n")
    assert book.proposals == [
        {"action": "edit", "section": "7. Sự tích vua TaBài và nàng BìLà", "pdf_pages": [42, 43],
         "before": [raw[7]], "after": [book.blocks[7]], "reason": "transcribed from the scan"},
        {"action": "edit", "section": "7. Sự tích vua TaBài và nàng BìLà", "pdf_pages": [43],
         "before": [raw[8]], "after": [book.blocks[8]], "reason": "transcribed from the scan"},
    ]


def test_text_above_a_storys_heading_on_its_first_page_ends_the_story_before():
    p41 = entry(41, [line(1, "Thế rồi các cụ già kể chuyện cho con cháu nghe.")])
    p42 = entry(42, [line(1, "mãi về sau.")] + [dict(ln, n=ln["n"] + 1) for ln in P42["lines"]], continues=True)
    a41 = answer(["Thế rồi các cụ già kể chuyện cho con cháu nghe"])
    a42 = answer(["mãi về sau."] + [b["text"] for b in A42["blocks"]], starts_mid=True)

    book = assemble(RAW, {41: read_page(p41, a41), 42: read_page(p42, a42)}, [])

    i = book.blocks.index("## 6. Sự tích Táo quân")
    assert book.blocks[i + 2] == "Thế rồi các cụ già kể chuyện cho con cháu nghe mãi về sau."
    assert book.blocks[i + 3] == "## 7. Sự tích vua TaBài và nàng BìLà"


def test_a_slice_of_a_story_is_diffed_only_where_its_pages_are():
    raw = RAW.replace("<!-- pdf 42-43", "<!-- pdf 42-45") + "\nRồi hoàng tử về cung.\n"

    book = assemble(raw, {42: read_page(P42, A42), 43: read_page(P43, A43)}, [])

    assert [p["action"] for p in book.proposals] == ["edit", "edit"]


def test_a_title_printed_over_two_lines_is_one_heading_and_a_heading_inside_a_story_is_a_line():
    p42 = entry(42, [line(1, "SỰ TÍCH VUA TABÀI", x0=0.3), line(2, "VÀ NÀNG BÌLÀ", x0=0.3)] +
                [dict(ln, n=ln["n"] + 1) for ln in P42["lines"][1:]] + [line(9, "Tưởng rằng ông táo thật thà", x0=0.3)],
                first="heading")
    a42 = answer(["## SỰ TÍCH VUA TABÀI", "## VÀ NÀNG BÌLÀ", A42["blocks"][1]["text"],
                  "## Tưởng rằng ông táo thật thà"])

    book = assemble(RAW, {42: read_page(p42, a42)}, [])

    i = book.blocks.index("## 7. Sự tích vua TaBài và nàng BìLà")
    assert book.blocks[i + 1] == "<!-- pdf 42 · heading: SỰ TÍCH VUA TABÀI VÀ NÀNG BÌLÀ -->"
    assert book.blocks[-1] == "Tưởng rằng ông táo thật thà"
    assert [b["page"] for b in book.boxes[i]] == [42]


def test_a_slice_starting_inside_a_story_leaves_out_the_raw_paragraphs_of_its_unread_pages():
    raw_blocks = RAW.rstrip("\n").split("\n\n")
    raw = "\n\n".join(["## 7. Sự tích vua TaBài và nàng BìLà", "<!-- pdf 41-43 -->", "Ngày xưa có hai hoàng tử đi săn."]
                      + raw_blocks[7:]) + "\n"

    book = assemble(raw, {43: read_page(P43, A43)}, [])

    assert book.blocks[1] == "<!-- pdf 43 -->"
    assert all(p["before"] != ["Ngày xưa có hai hoàng tử đi săn."] for p in book.proposals)


def test_noise_at_the_foot_of_a_page_does_not_keep_the_paragraph_from_joining_the_next_page():
    p42 = dict(P42, lines=P42["lines"] + [line(5, "N nnn nh Tàn n")])

    book = assemble(RAW, {42: read_page(p42, A42), 43: read_page(P43, A43)}, [])

    assert book.blocks[7].endswith("ngài lấy làm lạ. Hoàng tử ra lệnh cho quần thần xuống mò và tìm thấy một khúc Ngà. "
                                   "Quần thần tâu tay vào nhấc lên thấy nhẹ bỗng.")


def test_the_heading_loses_marks_the_ocr_read_as_punctuation_and_gains_the_printed_subtitle():
    raw = RAW.replace("## 7. Sự tích vua TaBài và nàng BìLà", "## 7. Sự tích vua TaBài và nàng BìLà (\")[^bila-1]")
    a42 = dict(A42, blocks=[{"text": "## SỰ TÍCH VUA TABÀI (Likay Ruah Kamay)", "box": [100, 100, 900, 200]}]
               + A42["blocks"][1:])

    book = assemble(raw, {42: read_page(P42, a42), 43: read_page(P43, A43)}, [])

    assert "## 7. Sự tích vua TaBài và nàng BìLà (Likay Ruah Kamay)" in book.blocks


def test_a_story_title_is_the_heading_as_set_with_the_passs_note_calls_after_it():
    p42 = dict(P42, lines=P42["lines"] + [line(5, "(1) TaBài : tên vua.", role="footnote", y=0.9)])
    a42 = dict(A42, blocks=[{"text": "## SỰ TÍCH VUA TABÀI[^?1] (Likay Ruah Kamay)", "box": [100, 100, 900, 200]}]
               + A42["blocks"][1:], footnotes=[{"mark": "1", "text": "TaBài : tên vua."}])
    titles = {42: "7. Sự tích vua Tabài và nàng Bìlà (Hai anh em)"}

    book = assemble(RAW, {42: read_page(p42, a42), 43: read_page(P43, A43)}, [], titles)

    # the model's subtitle and letters are not taken; the call it read in the heading goes at the end
    assert book.blocks[5] == "## 7. Sự tích vua Tabài và nàng Bìlà (Hai anh em)[^su-tich-vua-tabai-va-nang-bila-p42-1]"
    assert book.proposals[0]["section"] == "7. Sự tích vua Tabài và nàng Bìlà (Hai anh em)"
    assert book.blocks[2] == "## 6. Sự tích Táo quân"      # a section with no Story Title keeps its raw heading


def test_the_title_page_stays_as_it_is_in_book_raw_md():
    p4 = entry(4, [line(1, "TRUNG TÂM NGHIÊN CỨU VĂN HÓA CHĂM - NINH THUẬN")])
    a4 = answer(["TRUNG TÂM NGHIÊN CỨU VĂN HÓA CHĂM - NINH THUẬN", "## TRUYỆN CỔ DÂN GIAN CHĂM"])

    book = assemble(RAW, {4: read_page(p4, a4), 42: read_page(P42, A42), 43: read_page(P43, A43)}, [])

    assert book.blocks[:2] == RAW.split("\n\n")[:2]
    assert all(p["pdf_pages"] != [4] for p in book.proposals)


# -- notes
def unit(page, text):
    return {"kind": "text", "text": text, "page": page, "boxes": [], "missed": False}


def note(page, mark, text, part="footnote"):
    return {"kind": "note", "part": part, "page": page, "mark": mark, "text": text, "boxes": [], "missed": False}


def test_a_mark_pairs_with_the_note_at_the_foot_of_its_page_and_keeps_its_notes_json_id():
    units = [unit(19, "người vợ lại đội pụ[^?1] ra suối lấy nước.")]
    notes = [note(19, "1", "Pụ : một loại vò bằng gốm.")]

    out = pair_notes(units, notes, "kapin", {(19, "1"): "su-tich-bo-than-kapin-p19-1"}, set())

    assert units[0]["text"] == "người vợ lại đội pụ[^su-tich-bo-than-kapin-p19-1] ra suối lấy nước."
    assert [(n["id"], n["paired"]) for n in out] == [("su-tich-bo-than-kapin-p19-1", True)]


def test_marks_left_over_pair_with_the_end_of_story_notes_by_mark_in_order():
    # "1" restarts on each page: the second page's "1" is the end-of-story list's second "1"
    units = [unit(50, "đội pụ[^?1] đi."), unit(51, "bỏ vào chét[^?1] mang về."), unit(51, "Bà già[^?2] cười.")]
    notes = [note(52, "1", "Pụ : vò gốm.", "story"), note(52, "1", "Chét : giỏ đan.", "story"),
             note(52, "2", "Bà già : người kể.", "story")]

    pair_notes(units, notes, "chang-ran", {}, set())

    assert [u["text"] for u in units] == ["đội pụ[^chang-ran-p52-1] đi.", "bỏ vào chét[^chang-ran-p52-1-2] mang về.",
                                          "Bà già[^chang-ran-p52-2] cười."]
    assert all(n["paired"] for n in notes)


def test_a_note_with_no_mark_and_a_mark_with_no_note_are_left_for_phase_2():
    units = [unit(35, "biếu một bầu linh dược[^?2] cải tử hoàn sinh.")]
    notes = [note(35, "1", "Không long : con rồng.")]

    pair_notes(units, notes, "tao-quan", {(35, "1"): "su-tich-tao-quan-p35-1"}, set())

    assert units[0]["text"] == "biếu một bầu linh dược[^?2] cải tử hoàn sinh."
    assert notes[0]["paired"] is False


def test_the_book_lists_each_storys_notes_at_its_end_and_says_which_call_is_not_found():
    p43 = dict(P43, lines=P43["lines"][:5] + [line(7, "(1) Ngà : ngà voi.", role="footnote", y=0.9),
                                              line(8, "(2) Bỗng : nhẹ tênh.", role="footnote", y=0.93)])
    a43 = dict(A43, blocks=[dict(b) for b in A43["blocks"]],
               footnotes=[{"mark": "1", "text": "Ngà : ngà voi."}, {"mark": "(2)", "text": "(2) Bỗng : nhẹ tênh."}])
    a43["blocks"][0]["text"] = a43["blocks"][0]["text"].replace("khúc Ngà.", "khúc Ngà[^?1].")

    book = assemble(RAW, {42: read_page(P42, A42), 43: read_page(p43, a43)}, [])

    assert "khúc Ngà[^su-tich-vua-tabai-va-nang-bila-p43-1]." in book.blocks[7]
    assert book.blocks[-2:] == [
        "[^su-tich-vua-tabai-va-nang-bila-p43-1]: Ngà : ngà voi. <!-- note pdf 43 -->",
        "[^su-tich-vua-tabai-va-nang-bila-p43-2]: Bỗng : nhẹ tênh. <!-- note pdf 43 · call not found -->",
    ]
    assert book.boxes[-1][0]["page"] == 43


# -- the diff
def test_paragraphs_lined_up_by_their_words_give_edits_merges_deletes_and_inserts():
    before = ["## 1. Gà gáy", "<!-- pdf 10 -->", "Sau đó Pô Kuk niệm thần chú hoa thành cây nến, rồi hoá",
              "lửa đốt để thắp sáng cho cả làng cùng xem.", "N nnn nh ⚠", "Gà gáy sáng từ đó về sau mãi mãi."]
    after = ["## 1. Gà gáy", "<!-- pdf 10 · heading: GÀ GÁY -->",
             "Sau đó Pô Kuk niệm thần chú hoá thành cây nến, rồi hoá lửa đốt để thắp sáng cho cả làng cùng xem.",
             "Gà gáy sáng từ đó về sau mãi mãi.", "Hết truyện."]

    diff = block_diff(before, after, [[10]] * len(after))

    assert [(d["action"], d["before"], d["after"]) for d in diff] == [
        ("merge", before[2:4], [after[2]]), ("delete", [before[4]], []), ("insert", [], [after[4]])]


# -- Phase 2
BOOK = [
    "## 1. Sự tích gà gáy sáng",
    "<!-- pdf 10-14 · heading: SỰ TÍCH GÀ GÁY SÁNG -->",
    "Cứ theo truyền thuyết ngày xưa, At Mưhẽkat kể lại. ⚠",
    "Sau đó Pô Kuk niệm thần chú hoa thành cây nến, rồi hoá",
    "N nnn nh lửa đốt để thắp sáng. ⚠",
    "người vợ lại đội pụ[^?1] ra suối lấy nước.",
    "[^pu]: Pụ : một loại vò bằng gốm. <!-- note pdf 11 · call not found -->",
]
PAGES = {0: [10], 2: [10], 3: [11], 4: [12], 5: [12], 6: [11]}


def test_phase_2_has_a_task_only_for_a_note_whose_call_was_not_found():
    book = BOOK + ["[^gà]: Gà : con gà. <!-- note pdf 10 -->"]

    tasks = note_tasks(book, PAGES)

    assert [t["note_id"] for t in tasks] == ["pu"]
    assert tasks[0]["note_page"] == 11 and tasks[0]["definition"] == "Pụ : một loại vò bằng gốm."


def test_a_note_task_turns_the_mark_into_the_call_and_the_definition_stops_saying_call_not_found():
    results = {"pu": {"replacements": [{"block": 5, "find": "pụ[^?1]", "replace": "pụ[^pu]"}],
                      "definition": None, "reason": "the mark after pụ"}}

    out = apply_note_results(BOOK, PAGES, results)

    assert out.blocks[5] == "người vợ lại đội pụ[^pu] ra suối lấy nước."
    assert out.blocks[6] == "[^pu]: Pụ : một loại vò bằng gốm. <!-- note pdf 11 -->"
    assert [(p["action"], p["pdf_pages"]) for p in out.proposals] == [("edit", [12]), ("edit", [11])]


def test_a_replacement_whose_find_is_not_in_its_block_exactly_once_is_dropped():
    book = BOOK[:5] + ["Pụ đầy nước, pụ1) nặng, pụ1) vỡ."] + BOOK[6:]
    results = {"pu": {"replacements": [{"block": 5, "find": "pụ1)", "replace": "pụ[^pu]"},
                                       {"block": 5, "find": "pụ2)", "replace": "pụ[^pu]"}],
                      "definition": None, "reason": "call"}}

    out = apply_note_results(book, PAGES, results)

    assert out.blocks == book
    assert [d["why"] for d in out.dropped] == ["'pụ1)' is in block 5 2 times, not once",
                                              "'pụ2)' is in block 5 0 times, not once"]


def test_a_note_task_cannot_write_another_notes_call():
    results = {"pu": {"replacements": [{"block": 5, "find": "pụ[^?1]", "replace": "pụ[^pu-2]"}],
                      "definition": None, "reason": "call"}}

    out = apply_note_results(BOOK, PAGES, results)

    assert out.blocks == BOOK
    assert out.dropped[0]["why"] == "the replacement adds a call to [^pu-2], not [^pu]"


def test_what_is_still_unpaired_after_phase_2_is_flagged_where_the_pass_wrote_the_book():
    out = flag_leftovers(BOOK + ["[^old]: a note in a section the pass did not read <!-- note pdf 90 · call not found -->"],
                         PAGES)

    assert out.blocks[5] == "người vợ lại đội pụ[^?1] ra suối lấy nước. ⚠"
    assert out.blocks[6] == "[^pu]: Pụ : một loại vò bằng gốm. ⚠ <!-- note pdf 11 · call not found -->"
    assert "⚠" not in out.blocks[7]
    assert [p["reason"] for p in out.proposals] == ["a note mark is still not paired with a note",
                                                     "the note's call is still not found"]


# -- names and Spelling Rules
NAMES_RAW = "\n\n".join([
    "# TRUYỆN CỔ DÂN GIAN CHĂM",
    "<!-- pdf 4 · front -->",
    "## 33. Hoàng tử TêWa MừNô",
    "<!-- pdf 274-275 -->",
    "Têwa Mừnô gặp Jamưtui bên suối.",
    "## 50. Param Mudit, Parăm MUlak",
    "<!-- pdf 276 -->",
    "Parăm Mưlak và Parăm Mulak về.",
]) + "\n"
NAME_PAGES = {p["page"]: p for p in [
    entry(274, [line(1, "HOÀNG TỬ TỀWA MỪNÔ", x0=0.3),
                line(2, "Hoàng tử Tềwa Mừnô cưỡi ngựa đi săn."),
                line(3, "Tềwa Mừnô gặp Jamưtui bên suối."),
                line(4, "Têwa Mừnô thấy hoàng tử bông - bông", check=True)], first="heading"),
    entry(275, [line(1, "Tềwa Mừnô nói với Jamưtui rằng"),
                line(2, "Jamưtui cười. Tềwa Mừnô về với Ungcăl."),
                line(3, "Hoàng tử Tềwa đi gặp Ungcăl và Ungcăl.")]),
    entry(276, [line(1, "PARĂM MUDIT, PARĂM MƯLAK", x0=0.3), line(2, "Parăm Mưlak và Parăm Mulak về nhà.")],
          first="heading"),
]}
# book.ai.md as assemble writes it: section 33 read from pdf 274-275, section 50 from pdf 276
NAMES_BOOK = [
    "# TRUYỆN CỔ DÂN GIAN CHĂM",
    "<!-- pdf 4 · front -->",
    "## 33. Hoàng tử TêWa MừNô",
    "<!-- pdf 274-275 · heading: HOÀNG TỬ TÊWA MÙNÔ -->",
    "Têwa Mùnô gặp Jamutui[^tewa-p274-1] bên suối.",
    "Hoàng tử Tềwa Mừnô về với Ungcăl.",
    "[^tewa-p274-1]: Jamutui: tên một cô gái. <!-- note pdf 274 -->",
    "## 50. Param Mudit, Parăm MUlak",
    "<!-- pdf 276 · heading: PARĀM MŨDIT, PARĀM MŨLAK -->",
    "Parăm Mưlak và Parăm Mulak về nhà.",
]
NAMES_BOOK_PAGES = {4: [274], 5: [275], 6: [274], 7: [276], 9: [276]}    # no page: a heading the model missed


def test_a_storys_names_are_its_capitalised_words_spelled_as_the_ocr_prints_them_most():
    names = story_names(NAMES_RAW, NAME_PAGES, spelling_rules(None))

    # a line the two OCR engines read differently (`check`) does not count; a word also printed in lower case
    # ("hoàng", "tử") is not a name
    assert {n["fold"]: n["spelling"] for n in names[1]} == {
        "tewa": "Tềwa", "muno": "Mừnô", "jamutui": "Jamưtui", "ungcal": "Ungcăl"}
    assert [n["fold"] for n in names[1]][:2] == ["tewa", "muno"]    # most printed first
    # a name the OCR spells two ways, neither clearly the more often, has no spelling
    assert {n["fold"]: n["spelling"] for n in names[2]} == {"param": "Parăm", "mulak": None}
    assert names[0] == []       # the title page


def test_the_phase_1_prompt_gives_the_names_of_the_page_s_story():
    names = page_names(NAMES_RAW, NAME_PAGES, spelling_rules(None))

    assert names[274] == ["Tềwa", "Mừnô", "Jamưtui", "Ungcăl"]
    assert names[276] == ["Parăm"]      # a name with no clear spelling is left out
    text = transcribe_user_text(NAME_PAGES[276], True, names[276])
    assert "Names in this story, as printed (write them with exactly these marks): Parăm" in text
    assert "Names" not in transcribe_user_text(NAME_PAGES[276], False, names[276])


def test_a_name_the_model_misspells_takes_the_ocr_spelling_with_its_own_case_and_is_logged():
    rules = spelling_rules(None)

    out = enforce_spellings(NAMES_BOOK, NAMES_BOOK_PAGES, NAMES_RAW, NAME_PAGES, rules)

    assert out.blocks[2] == "## 33. Hoàng tử TềWa MừNô"
    assert out.blocks[3] == NAMES_BOOK[3]       # the model's reading of the heading stays in its comment
    assert out.blocks[4] == "Tềwa Mừnô gặp Jamưtui[^tewa-p274-1] bên suối."     # not inside a note call
    assert out.blocks[6] == "[^tewa-p274-1]: Jamưtui: tên một cô gái. <!-- note pdf 274 -->"
    assert out.blocks[7] == "## 50. Parăm Mudit, Parăm MUlak"
    assert out.blocks[:2] == NAMES_BOOK[:2]     # the title page is not the pass's
    assert out.proposals[0]["pdf_pages"] == [274]
    assert out.proposals[1] == {
        "action": "edit", "section": "33. Hoàng tử TềWa MừNô", "pdf_pages": [274],
        "before": [NAMES_BOOK[4]], "after": [out.blocks[4]],
        "reason": "names as the OCR prints them in this story: Têwa → Tềwa, Mùnô → Mừnô, Jamutui → Jamưtui"}


def test_a_name_still_spelled_two_ways_in_a_story_is_flagged():
    rules = spelling_rules(None)

    out = enforce_spellings(NAMES_BOOK, NAMES_BOOK_PAGES, NAMES_RAW, NAME_PAGES, rules)

    assert out.blocks[9] == "Parăm Mưlak và Parăm Mulak về nhà. ⚠"
    assert out.proposals[-1]["reason"] == "a name spelled differently in this story: Mưlak 1, Mulak 1"


def test_a_spelling_rule_beats_the_ocr_keeps_the_case_and_is_skipped_in_its_excepted_stories():
    rules = spelling_rules({
        "words": [{"spelling": "Ưngcăl", "except": ["50. Parăm Mudit, Parăm Mulak"]}],
        "phrases": [{"spelling": "bồng - bồng", "except": []}],
        "depends": [["thầy", "thấy"]],
    })
    book = list(NAMES_BOOK)
    book[5] = "UNGCĂL ôm con bông - bông, thấy bông đẹp, rồi Ungcăl về với Ungcăl."
    book[7] = "## 50. Param Mudit, Parăm MUlak (Hai anh em)"      # a subtitle assemble added to the raw heading
    book[9] = "Ungcăl đi."

    out = enforce_spellings(book, NAMES_BOOK_PAGES, NAMES_RAW, NAME_PAGES, rules)

    assert out.blocks[5] == "ƯNGCĂL ôm con bồng - bồng, thấy bông đẹp, rồi Ưngcăl về với Ưngcăl."
    assert out.blocks[9] == "Ungcăl đi."     # "50. Param Mudit, ..." is the excepted story, whatever its marks
    p = next(p for p in out.proposals if p["before"] == [book[5]])
    assert p["rule"] == ["Ưngcăl", "bồng - bồng"]
    assert p["reason"] == "Spelling Rule: UNGCĂL → ƯNGCĂL, bông - bông → bồng - bồng, Ungcăl → Ưngcăl (2×)"
    names = story_names(NAMES_RAW, NAME_PAGES, rules)
    assert next(n for n in names[1] if n["fold"] == "ungcal")["spelling"] == "Ưngcăl"


def test_a_story_title_is_never_respelled_and_story_exceptions_name_story_titles():
    rules = spelling_rules({"words": [{"spelling": "Ưngcăl", "except": ["50. Hai anh em Parăm"]},
                                      {"spelling": "Mừnô", "except": []}]})
    titles = {274: "33. Hoàng tử TêWa MunÔ", 276: "50. Hai anh em Parăm"}
    book = list(NAMES_BOOK)
    book[2] = "## 33. Hoàng tử TêWa MunÔ"
    book[7] = "## 50. Hai anh em Parăm"
    book[9] = "Ungcăl đi."

    out = enforce_spellings(book, NAMES_BOOK_PAGES, NAMES_RAW, NAME_PAGES, rules, titles)

    assert out.blocks[2] == book[2]         # neither a Spelling Rule nor the OCR's names touch it
    assert out.blocks[5] == "Hoàng tử Tềwa Mừnô về với Ưngcăl."
    assert out.blocks[9] == "Ungcăl đi."     # the excepted story, named by its Story Title
    assert all(p["before"] != [book[2]] for p in out.proposals)
    pages = {**NAME_PAGES, 276: dict(NAME_PAGES[276], lines=NAME_PAGES[276]["lines"] + [line(3, "Ungcăl đi.")])}
    assert "ungcal" not in [n["fold"] for n in story_names(NAMES_RAW, pages, rules, titles)[2]]   # not ruled there


def test_a_ruled_name_goes_in_the_prompt_even_where_the_ocr_never_prints_it_clean():
    pages = {**NAME_PAGES, 276: entry(276, [line(1, "Parăm Mưlak gặp ungcal", check=True)])}
    rules = spelling_rules({"words": [{"spelling": "Ưngcăl", "except": []}]})

    assert "Ưngcăl" in page_names(NAMES_RAW, pages, rules)[276]


def test_with_ocr_marks_a_word_the_model_reads_with_other_marks_keeps_those_both_ocr_engines_agree_on():
    p = entry(28, [line(1, "người vợ ôm con bồng - bồng ra suối."),
                   line(2, "Tên vua thầy vậy, lấy làm lạ.", check=True),
                   line(3, "Vua thầy thế bèn đi.")])
    a = answer(["Người vợ ôm con bông - bông ra suối. Tên vua thấy vậy, lấy làm lạ. Vua thấy thế bèn đi."])

    assert read_page(p, a)["units"][0]["text"] == a["blocks"][0]["text"]     # off unless asked for
    page = read_page(p, a, ocr_marks=True, depends={"thay"})

    # the model's case stays; a line marked `check` and a word decided per place (Depends) keep the model's marks
    assert page["units"][0]["text"] == ("Người vợ ôm con bồng - bồng ra suối. Tên vua thấy vậy, lấy làm lạ. "
                                        "Vua thấy thế bèn đi.")
    assert page["report"]["ocr_marks"] == [{"n": 1, "ai": "bông", "ocr": "bồng"},
                                           {"n": 1, "ai": "bông", "ocr": "bồng"}]
