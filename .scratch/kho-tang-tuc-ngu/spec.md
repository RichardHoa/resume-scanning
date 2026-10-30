Status: ready-for-agent

# Kho tàng tục ngữ người Việt: transcribe the Front Matter

## Problem Statement

`vsc-project/khoTangTucNguoiNguoiViet/kho tàng tục ngữ người việt tập 1 - p1.pdf` is the first PDF Part of _Kho tàng tục ngữ người Việt_ (Nguyễn Xuân Kính chủ biên, NXB Văn hóa-Thông tin, Hà Nội 2002). The work has two Volumes (Tập I, Tập II), uploaded as 4 PDF Parts. The PDF is 865 page images with no text layer.

PDF pages 2–35 are the Front Matter: the title page, the Mục lục for the whole work (to book p. 3242), Lời nói đầu, Bảng chữ tắt và nghĩa các kí hiệu, and Phàm lệ biên soạn. These define every Source Abbreviation and the conventions of a Proverb Entry, so they are the key for parsing the proverbs later.

## Decisions

- Scope: PDF pages 2–35 only. PDF page 1 (cover) is skipped. PDF page 36 (book p. 35, first Proverb Entries A1–A4) is the start of the proverb body and out of scope.
- The Mục lục covers both Volumes and is transcribed once; later PDF Parts get no Front Matter file of their own.
- Everything on pages 2–35 is transcribed verbatim in reading order, not only the TOC, abbreviations and Source Notes.
- Text is kept exactly as printed. Suspected misprints are kept and marked with ⚠ plus a short HTML comment; never silently corrected. Subscripts (VNP₂, VNP₁₁) use Unicode subscripts.
- The Bảng chữ tắt and the Source Notes are each kept in printed order and form. One derived table is added that joins each Source Abbreviation to its title, author, kind of Source and its Source Note. Multi-volume Sources (NASL I–IV, TNLG I–III, …) share one Source Note.
- Output: `vsc-project/khoTangTucNguoiNguoiViet/front-matter.md`, following `vsc-project/truyen-co-dan-gian-cham/book.raw.md`: headings mirror the book, each section opens with `<!-- pdf N · book p. M -->`, the Mục lục is a nested list keeping the book's page numbers.
- Transcribed by Claude directly from the page images in one session, not by the vLLM model: 34 pages is a one-off where accuracy outweighs cost. A vLLM pipeline is a separate decision for the ~3000 proverb pages.

## Out of Scope

- Proverb Entries (book p. 35 onward), the Hệ thống tra cứu theo chủ đề, the indexes and the Thư mục.
- Any code or pipeline.
