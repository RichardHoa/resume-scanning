Status: needs-triage

# Must-have gate: a missing Must-have rejects the candidate

Requirement collection only. Nothing here is implemented yet. Some questions are still open (see the end).

## Problem Statement

Today a Must-have Criterion is just a heavier weight (×3, against Standard ×2 and Nice-to-have ×1). When a Must-have gets No Evidence, the evaluation records a Missing Must-Have flag, but the candidate is still scored, ranked and given Candidate Feedback, and can still reach STRONG (ADR 0006). This doesn't match what "must-have" means to HR: it is a requirement, not a preference. A candidate who lacks one should be out. Using Must-haves as weights also makes scoring harder to reason about, when only Standard and Nice-to-have actually need weighing.

## Decisions so far

- **Hard gate.** A candidate whose evaluation gives **No Evidence** on **any one** Must-have Criterion is rejected immediately. This reverses the "auto-reject rejected" option in ADR 0006, which needs a superseding ADR when this is built.
- **Partial does not reject.** A Must-have with Partial evidence does not trigger the gate.
- **Rejected candidates stay visible.** A rejected candidate is not deleted or hidden. HR can see them, with the Must-have(s) they lacked, so HR can still rescue a candidate whose resume simply left something out.
- **Answer to ADR 0006's "resumes omit things" concern:** it moves to HR's review of the HR RAG. Marking a Criterion Must-have becomes a deliberate choice with a known consequence.
- **The website must warn HR.** Wherever HR sets Importance (the criteria editor on the Verify step and on the RAG page), an always-visible warning tells HR to choose Must-haves carefully: a candidate who lacks any one of them is rejected immediately, however strong the rest is, and if HR isn't sure they should pick Standard. The Must-have line in the Importance guide changes to match (it currently says "không bị loại tự động").

  Draft wording (Vietnamese):
  > **Cân nhắc kỹ trước khi đánh dấu “Bắt buộc”.** Ứng viên thiếu bằng chứng cho **bất kỳ một** tiêu chí Bắt buộc nào sẽ **bị loại ngay**, dù các tiêu chí khác tốt đến đâu. Chỉ chọn mức này cho yêu cầu thật sự không thể thiếu; nếu không chắc, hãy chọn Tiêu chuẩn.

  Guide line for Must-have:
  > Ứng viên bắt buộc phải có. Nếu CV không cho thấy bằng chứng cho dù chỉ **một** tiêu chí Bắt buộc, ứng viên **bị loại ngay**. CV đáp ứng một phần thì không bị loại.

- **The decomposer stops proposing Importance.** It still splits requirements into Categories and HR Check Items, but every Criterion it produces is Standard. HR alone chooses Must-have and Nice-to-have when reviewing the HR RAG, with no suggestion from the decomposer. The keyword mapping in ADR 0006 ("bắt buộc", "yêu cầu", "phải" → Must-have; "ưu tiên", "là lợi thế" … → Nice-to-have) is removed. So a run with no HR review has no Must-haves and never rejects anyone.
- **A Must-have scores like a Standard.** For a candidate who passes the gate, a Must-have Criterion counts in its Category score at the Standard weight (×2), Partial evidence included. Weights become Must-have ×2, Standard ×2, Nice-to-have ×1. The ×3 weight is gone.
- **A rejected candidate is still fully evaluated.** Every Category is scored, so HR can judge whether to rescue them, but the Review Panel does not run, so there is no Candidate Feedback.
- **No override button.** HR un-rejects a candidate only by changing that Criterion's Importance in the HR RAG and rerunning the candidate.
- **Out of scope:** the bias runner, DSPy and mocks (callers that score without an Importance map).

- **Rejected candidates get their own section** on the results page, "Bị loại – thiếu tiêu chí bắt buộc". It comes after the ranked Evaluation Order tiers and before the Scanned Resume section. Rejected candidates leave their tier, the same way Scanned Resumes do. Each card shows the score greyed out and the Must-have(s) the candidate lacked. A rejected candidate who is in the Tech set's top 10 still shows their Evaluation Order rank (#1–#10).
- **Failed Evaluation wins.** If any Category fails, the candidate is a Failed Evaluation needing a full rerun, even when another Category already gave a Must-have No Evidence. The gate is applied only to an evaluation where every Category was scored.
- **Existing HR RAGs are reset.** Every Importance saved in an existing HR RAG is set back to Standard once, because the decomposer proposed those values and HR may never have reviewed them. HR then marks the real Must-haves again on the RAG page.
- **Renamed: Missing Must-Have → Must-have Rejection.** A Must-have Rejection is an evaluation with No Evidence on at least one Must-have Criterion, recording which ones. The candidate is out. The Vietnamese label "Thiếu yêu cầu bắt buộc" becomes "Bị loại – thiếu tiêu chí bắt buộc". The candidate modal's message (`candidates.js`), which currently says the candidate is not auto-rejected, is rewritten to match.

## To do when this is built

- `CONTEXT.md`: replace **Missing Must-Have** with **Must-have Rejection** (keep "Missing Must-Have" under _Avoid_), and update **Importance** (decided only by HR, Must-have ×2 like Standard, the gate).
- New ADR superseding ADR 0006 on auto-reject, the ×3 weight and decomposer-proposed Importance. The reason: a must-have is a requirement, not a preference, and the "resumes omit things" risk is handled by HR choosing every Must-have themselves, with a warning in the UI.
