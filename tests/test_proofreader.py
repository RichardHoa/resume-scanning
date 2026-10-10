"""
Applying AI Proofreading Pass results to book.raw.md blocks: Phase 1 (one task per page) and Phase 2
(one task per Note).
"""
from src.pipelines.proofreader import apply_note_results, apply_page_results

BOOK = [
    "## 1. Sự tích gà gáy sáng",
    "<!-- pdf 10-14 · heading: SỰ TÍCH GÀ GÁY SÁNG -->",
    "Cứ theo truyền thuyết ngày xưa, At Mưhẽkat kể lại. ⚠",
    "Sau đó Pô Kuk niệm thần chú hoa thành cây nến, rồi hoá",
    "N nnn nh lửa đốt để thắp sáng. ⚠",
    "người vợ lại đội pụ1) ra suối lấy nước.",
    "[^pu]: Pụ : một loại vò bằng gốm. <!-- note pdf 11 · call not found -->",
]
# block -> the pages it is on; the first is the page whose task owns it
PAGES = {0: [10], 2: [10], 3: [11], 4: [12], 5: [12], 6: [11]}


def test_edit_replaces_an_owned_block_and_records_an_ai_proposal():
    results = {10: [{"block": 2, "action": "edit", "reason": "misread ê",
                     "after": "Cứ theo truyền thuyết ngày xưa, At Mưhêkat kể lại."}]}

    out = apply_page_results(BOOK, PAGES, results)

    assert out.blocks[2] == "Cứ theo truyền thuyết ngày xưa, At Mưhêkat kể lại."
    assert out.blocks[3:] == BOOK[3:]
    assert out.proposals == [{
        "action": "edit", "section": "1. Sự tích gà gáy sáng", "pdf_pages": [10],
        "before": ["Cứ theo truyền thuyết ngày xưa, At Mưhẽkat kể lại. ⚠"],
        "after": ["Cứ theo truyền thuyết ngày xưa, At Mưhêkat kể lại."],
        "reason": "misread ê"
    }]


def test_a_page_cannot_change_a_block_another_page_owns():
    results = {10: [{"block": 4, "action": "edit", "after": "lửa đốt để thắp sáng.", "reason": "junk"}]}

    out = apply_page_results(BOOK, PAGES, results)

    assert out.blocks == BOOK
    assert out.proposals == []
    assert out.dropped == [{"task": "page 10", "item": results[10][0], "why": "block 4 is owned by page 12"}]


def test_an_edit_keeps_the_comment_the_model_never_saw():
    results = {11: [{"block": 6, "action": "edit", "after": "[^pu]: Pụ : một loại vò bằng gốm sứ.", "reason": "ocr"}]}

    out = apply_page_results(BOOK, PAGES, results)

    assert out.blocks[6] == "[^pu]: Pụ : một loại vò bằng gốm sứ. <!-- note pdf 11 · call not found -->"


def test_delete_removes_the_block():
    results = {10: [{"block": 2, "action": "delete", "after": "", "reason": "page header"}]}

    out = apply_page_results(BOOK, PAGES, results)

    assert out.blocks == BOOK[:2] + BOOK[3:]
    assert out.proposals[0]["action"] == "delete"
    assert (out.proposals[0]["before"], out.proposals[0]["after"]) == ([BOOK[2]], [])


def test_merge_next_joins_a_paragraph_split_by_a_page_after_the_next_page_fixed_its_half():
    results = {
        11: [{"block": 3, "action": "merge_next", "reason": "split by the page",
              "after": "Sau đó Pô Kuk niệm thần chú hoa thành cây nến, rồi hoá"}],
        12: [{"block": 4, "action": "edit", "reason": "junk letters", "after": "lửa đốt để thắp sáng."}],
    }

    out = apply_page_results(BOOK, PAGES, results)

    joined = "Sau đó Pô Kuk niệm thần chú hoa thành cây nến, rồi hoá lửa đốt để thắp sáng."
    assert out.blocks == BOOK[:3] + [joined] + BOOK[5:]
    assert [(p["action"], p["before"], p["after"]) for p in out.proposals] == [
        ("edit", [BOOK[4]], ["lửa đốt để thắp sáng."]),
        ("merge", [BOOK[3], "lửa đốt để thắp sáng."], [joined]),
    ]
    assert out.proposals[1]["pdf_pages"] == [11, 12]


def test_the_applied_book_knows_the_pages_of_each_block_for_phase_2():
    results = {11: [{"block": 3, "action": "merge_next", "after": BOOK[3], "reason": "split by the page"}],
               10: [{"block": 2, "action": "delete", "after": "", "reason": "junk"}]}

    out = apply_page_results(BOOK, PAGES, results)

    # 0 heading, 1 comment, 2 merged 3+4, 3 = old 5, 4 = old 6
    assert out.pages == {0: [10], 2: [11, 12], 3: [12], 4: [11]}


def test_a_note_task_places_the_call_and_the_definition_stops_saying_call_not_found():
    results = {"pu": {"replacements": [{"block": 5, "find": "pụ1)", "replace": "pụ[^pu]"}],
                      "definition": None, "reason": "the call is the 1) after pụ"}}

    out = apply_note_results(BOOK, PAGES, results)

    assert out.blocks[5] == "người vợ lại đội pụ[^pu] ra suối lấy nước."
    assert out.blocks[6] == "[^pu]: Pụ : một loại vò bằng gốm. <!-- note pdf 11 -->"
    assert [(p["action"], p["before"], p["after"], p["pdf_pages"]) for p in out.proposals] == [
        ("edit", [BOOK[5]], ["người vợ lại đội pụ[^pu] ra suối lấy nước."], [12]),
        ("edit", [BOOK[6]], ["[^pu]: Pụ : một loại vò bằng gốm. <!-- note pdf 11 -->"], [11]),
    ]


def test_a_replacement_whose_find_is_not_in_its_block_exactly_once_is_dropped():
    book = BOOK[:5] + ["Pụ đầy nước, pụ1) nặng, pụ1) vỡ."] + BOOK[6:]
    results = {"pu": {"replacements": [{"block": 5, "find": "pụ1)", "replace": "pụ[^pu]"},
                                       {"block": 5, "find": "pụ2)", "replace": "pụ[^pu]"}],
                      "definition": None, "reason": "call"}}

    out = apply_note_results(book, PAGES, results)

    assert out.blocks == book
    assert out.proposals == []
    assert [d["why"] for d in out.dropped] == ["'pụ1)' is in block 5 2 times, not once",
                                              "'pụ2)' is in block 5 0 times, not once"]
    assert out.dropped[0]["task"] == "note pu"


def test_two_notes_in_one_paragraph_combine_and_a_definition_gets_its_new_text():
    book = BOOK[:5] + ["P'Tao-lu-pu\") bắt nàng, đội pụ1) đi.", BOOK[6],
                       "[^tao]: P Tao-lu-pu : thần bão. <!-- note pdf 12 · call not found -->"]
    results = {
        "pu": {"replacements": [{"block": 5, "find": "pụ1)", "replace": "pụ[^pu]"}],
               "definition": None, "reason": "pụ"},
        "tao": {"replacements": [{"block": 5, "find": "P'Tao-lu-pu\")", "replace": "P'Tao-lu-pu[^tao]"}],
                "definition": "P'Tao-lu-pu : thần bão.", "reason": "tao"},
    }

    out = apply_note_results(book, PAGES, results)

    assert out.blocks[5] == "P'Tao-lu-pu[^tao] bắt nàng, đội pụ[^pu] đi."
    assert out.blocks[7] == "[^tao]: P'Tao-lu-pu : thần bão. <!-- note pdf 12 -->"


def test_a_note_task_cannot_write_another_notes_call():
    results = {"pu": {"replacements": [{"block": 5, "find": "pụ1)", "replace": "pụ[^pu-2]"}],
                      "definition": None, "reason": "call"}}

    out = apply_note_results(BOOK, PAGES, results)

    assert out.blocks == BOOK
    assert out.dropped[0]["why"] == "the replacement adds a call to [^pu-2], not [^pu]"
