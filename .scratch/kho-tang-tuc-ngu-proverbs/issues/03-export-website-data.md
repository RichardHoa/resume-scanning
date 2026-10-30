# 03: Export website data from the verbatim entries

**What to build:** On the laptop, the developer runs one export command. From the Part's verbatim Proverb Entries, the review log and the transcribed Front Matter, it writes website-ready data into the store's export folder. The developer copies that folder into the website by hand. Spec: `../spec.md`; how the website will use the data: `../../kho-tang-tuc-ngu-website/spec.md`.

- **Fixes applied:** Fixes that are not stale replace the model's Proverb Entries.
- **One file per letter**, one record per Proverb Entry, with:
  - **Anchor:** e.g. "C-484", keeping Ă and Â.
  - **Sources:** each Citation keyed to its Source. Source Abbreviations in notes ("Theo VD, …", "VD: …", "(theo CNGN)") are found by whole-word match against the 63 and keyed the same way. "VD" is always the Source Vũ Dung.
  - **Expansions:** the 15 General Abbreviations of Bảng chữ tắt part II, on whole-word, case-sensitive matches only. "BK"/"bk" become the Variant's "Bản khác" label instead of inline text.
  - **Corrections:** the structured fields plus the sentence _Sách {sources} in sai thành "{wrong}". Nhóm biên soạn cho đây là lỗi in, không phải dị bản, và sửa lại thành "{right}"._, with the italic words of `right` in bold.
  - **See-also:** a preview (the first few words of the entry it names) and its anchor. An Unresolved See-also keeps its name alone. Names are looked up across every Part exported so far.
  - **Filter fields:**
    - letter;
    - first syllable;
    - Sources cited;
    - has notes / Variants / Correction;
    - earliest attestation year, from the dated Sources of Phàm lệ II.2. It is empty when no cited Source is dated, and KSK counts as undated.
- **`sources.json`:** the 63 Source Abbreviations, each with title, author, kind, year where known and the full text of its Source Note. It is parsed from the transcribed Front Matter's derived table and Phàm lệ I.B. Multi-volume Sources share one note.
- **`intro.md`:** the Front Matter without HTML comments, ⚠ markers or the derived table, with its headings kept.
- **Expansion list:** every Expansion made, with its entry and the text around it.
- **Unresolved See-also list:** every Unresolved See-also, for information.

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] The command runs locally with no GPU and writes only to the store's export folder
- [ ] One file per letter present in the store, each record carrying its anchor and filter fields
- [ ] A non-stale Fix appears in place of the model's entry; a stale Fix does not
- [ ] Every Citation's abbreviation resolves to an entry in `sources.json`; NASL I–IV share one Source Note
- [ ] A note "Theo VD, …" carries a Source mention for VD
- [ ] "Nb", "tr", "H" are expanded only as whole words; no expansion inside a longer word
- [ ] A Variant carries a "Bản khác" label and no inline "BK"
- [ ] A Correction carries its plain-language sentence with the corrected words in bold
- [ ] A See-also to an entry in the store gets a preview and anchor; one to M 526 (Part 1 only) keeps its name alone and is listed as an Unresolved See-also
- [ ] An entry cited only by undated Sources has an empty attestation year; one cited by NNCC has 1918
- [ ] `intro.md` has no HTML comments, ⚠ markers or derived table, and keeps the Front Matter's headings
