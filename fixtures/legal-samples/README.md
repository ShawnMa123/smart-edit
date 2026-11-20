# Legal document-check samples

Plain text, meant to be **pasted into the editor** (the app edits one document, `demo-document`).
Copy the text, wait for the draft to autosave (the panel shows `Draft rev N`), then
`Legal → Document check → Scan document`.

| File | What it proves | Expected on a healthy deployment |
|---|---|---|
| `sanctions-export.txt` / `sanctions-export-zh.txt` | **substantive compliance**: controlled goods + a sanctioned destination + circumvention wording | `Gate: Blocked`; `Sensitive goods destined for a sanctioned country` (Critical/hard_block, anchors on the goods and the destination), plus export-control / sanctions / evasion findings |
| `hard-block.txt` | deterministic rules can block | `Gate: Blocked`; 3 Critical/hard_block (amount, currency, expiry before issue) + 1 Warning (automatic extension) |
| `statute-zh.txt` | RAGFlow evidence + Doubao composition | `Gate: Needs human review`; 2 deterministic markers + 2 statute-backed findings with 第一条/第三条 citations and draft anchors |
| `clean.txt` | honest coverage | no findings, but `Outcome: Unable to assess` — the English clauses come back `low_confidence`, so the legal leg says "could not assess" rather than "no risk" |

Notes:

- The scan runs without `applicable_on` from the panel, so `not_expired` is `not_applicable`
  (`no_assessment_date`) — that is expected.
- English clauses currently hit `low_confidence` from the statute corpus; that is why only the
  Chinese sample produces statute-backed findings. It is a corpus-coverage fact, not a bug.
- These are synthetic texts for testing only, not legal advice.