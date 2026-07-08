# FNOL Claims Routing Agent — Complete Guide

A lightweight AI agent that reads First Notice of Loss (FNOL) documents,
extracts the required fields, flags missing or inconsistent data, decides
which workflow queue the claim belongs to, and explains its reasoning in
plain language.

---

## 1. Why This Counts as an "Agent"

A basic script that reads fixed-format text is a **parser**. What makes
this project an **agent** is that field extraction is powered by an LLM
(Ollama Cloud, `gpt-oss` model), which can understand FNOL documents even
when wording, layout, or field order varies between insurers or forms —
not just one exact fixed template.

The one deliberate exception: **the routing decision itself is never made
by the LLM.** Routing is plain, deterministic Python. This is explained
fully in Section 4.

---

## 2. End-to-End Flow

```
                     ┌─────────────────────┐
                     │  Upload FNOL doc     │
                     │  (.txt / .pdf)       │
                     └──────────┬───────────┘
                                │
                     ┌──────────▼───────────┐
                     │  Text Extraction     │   (pdfplumber for PDFs)
                     └──────────┬───────────┘
                                │
                     ┌──────────▼────────────────────┐
                     │  Field Extraction              │
                     │  1. Try Ollama Cloud LLM        │
                     │  2. If it fails/invalid →        │
                     │     regex fallback (always works)│
                     └──────────┬────────────────────┘
                                │
                     ┌──────────▼───────────┐
                     │  Schema Validation    │   (Pydantic)
                     └──────────┬───────────┘
                                │
                     ┌──────────▼───────────┐
                     │  Missing-Field Check  │   (pure Python)
                     └──────────┬───────────┘
                                │
                     ┌──────────▼───────────┐
                     │  Routing Engine        │   (pure Python,
                     │  (priority-ordered)     │    rule-based)
                     └──────────┬───────────┘
                                │
                     ┌──────────▼───────────┐
                     │  Reasoning generated   │
                     │  from the fired rule    │
                     └──────────┬───────────┘
                                │
                 ┌──────────────┴───────────────┐
                 │                               │
        ┌────────▼─────────┐           ┌─────────▼──────────┐
        │  JSON Output       │           │  Excel Log Update    │
        │  (shown in UI/CLI)  │           │  (claims_log.xlsx,    │
        └────────────────────┘           │   upsert by policy #) │
                                          └───────────────────────┘
```

---

## 3. What Each File Does

| File | Role |
|---|---|
| `schema.py` | Defines every field the agent must extract, using Pydantic. Single source of truth for the 16 mandatory fields. |
| `llm_client.py` | Talks to Ollama Cloud. Has a timeout and try/except around every call — if the API fails, it returns `None` instead of crashing anything. |
| `extractor.py` | Tries LLM extraction first. If that fails or returns invalid data, falls back to regex parsing so the pipeline always produces a result. |
| `router.py` | Detects missing mandatory fields and applies the 4 routing rules from the problem statement, in priority order. Never touches the LLM. |
| `excel_logger.py` | Logs every processed claim into `claims_log.xlsx`, one row per policy number (updates existing rows instead of duplicating). |
| `pipeline.py` | Wires everything together. Can be run from the command line directly. |
| `app.py` | Streamlit UI — upload a document, click a button, see the result. |
| `test_runner.py` | Runs all sample documents and checks actual vs. expected routing outcomes (see Section 6). |

---

## 4. Why Routing Is Never Left to the LLM

This is the single most important design decision in the project, so it's
worth explaining clearly:

- **LLMs are not deterministic.** The same input can occasionally produce a
  different output. That's fine for *understanding* a document, but
  unacceptable for a *business decision* like which queue a claim goes to.
- **LLMs can be temporarily unavailable.** If routing depended on an API
  call and that call failed, the whole agent would stop working. By
  keeping routing as plain Python, the agent keeps making correct decisions
  even when the LLM (or the internet) is down — extraction just falls back
  to regex, and routing continues exactly as normal.
- **Auditability.** Every routing decision in this system can be traced to
  one exact `if` condition in `router.py`. There's no "the model decided
  this" — there's always a specific, inspectable, testable reason.

---

## 5. Routing Rules (Priority Order)

The problem statement gives four rules but doesn't specify what happens if
more than one applies to the same claim at once. This project resolves
that with an explicit priority order, checked top to bottom — **first
match wins**:

| Priority | Rule | Reasoning for this position |
|---|---|---|
| 1 | **Manual Review** — any mandatory field is missing | Can't trust any other decision if the underlying data is incomplete. |
| 2 | **Investigation Flag** — description contains "fraud", "inconsistent", or "staged" | Fraud risk outweighs speed or specialist handling. |
| 3 | **Specialist Queue** — claim type is "injury" | Needs specialist handling regardless of amount, but only if not already flagged for fraud. |
| 4 | **Fast-track** — estimated damage < ₹25,000 | Only applies to clean, low-value, non-flagged claims. |
| 5 | **Standard Review** *(fallback, not in original spec)* | Used only when a claim is complete, non-fraudulent, non-injury, but damage is ≥ ₹25,000 — a case the original 4 rules don't cover. |

---

## 6. Test Cases & Verified Results

10 sample FNOL documents are included in `sample_fnols/`, each designed to
exercise a specific rule or edge case. All were run through
`test_runner.py` and verified to produce the correct route:

| # | Test Case | What It Checks | Expected Route | Result |
|---|---|---|---|---|
| 1 | `claim1_fasttrack.txt` | Clean claim, low damage | Fast-track | ✅ PASS |
| 2 | `claim2_missingfields.txt` | Two mandatory fields blank | Manual Review | ✅ PASS |
| 3 | `claim3_investigation.txt` | "inconsistent" + "staged" in description | Investigation Flag | ✅ PASS |
| 4 | `claim4_injury.txt` | Claim type = Injury | Specialist Queue | ✅ PASS |
| 5 | `claim5_boundary_exact25000.txt` | Damage exactly ₹25,000 (edge of threshold) | Standard Review | ✅ PASS |
| 6 | `claim6_boundary_just_under25000.txt` | Damage ₹24,999 (one rupee under threshold) | Fast-track | ✅ PASS |
| 7 | `claim7_multiple_missing.txt` | Five mandatory fields blank at once | Manual Review | ✅ PASS |
| 8 | `claim8_injury_and_fraud.txt` | Both Injury AND fraud keyword present — tests priority order | Investigation Flag | ✅ PASS |
| 9 | `claim9_clean_highvalue_standard.txt` | Clean claim, high damage, no flags | Standard Review | ✅ PASS |
| 10 | `claim10_case_insensitivity.txt` | Keywords in ALL CAPS ("INJURY", "STAGED") | Investigation Flag | ✅ PASS |

**Result: 10/10 passed.**

Test cases #5, #6, #8, and #10 are the ones worth highlighting in a demo
or presentation — they specifically prove the boundary logic (`<` not
`≤`), the priority ordering between competing rules, and case-insensitive
keyword matching all work correctly, not just the "happy path" cases.

### Re-running the tests yourself
```bash
python3 test_runner.py
```
This prints a pass/fail table for all 10 cases in one command — useful to
run right before a live demo to confirm nothing broke.

---

## 7. Reliability Guarantees (What Can't Break)

| Failure Scenario | What Happens |
|---|---|
| Ollama Cloud API key missing/invalid | Extraction falls back to regex automatically; a clear message is logged, nothing crashes. |
| Ollama Cloud is down/times out | Same as above — regex fallback kicks in. |
| LLM returns malformed JSON | Caught by Pydantic validation; falls back to regex. |
| LLM returns a number instead of a string for a field (e.g. `12500` instead of `"12500"`) | Automatically coerced to string before validation — doesn't fail. |
| `claims_log.xlsx` is open in Excel (file locked) | Logging fails gracefully with a warning; the JSON result is still returned and shown. |
| Uploaded PDF can't be parsed | Error shown in the UI; app doesn't crash. |

---

## 8. Output Format

Every processed claim produces exactly this structure, matching the
problem statement's required schema:

```json
{
  "extractedFields": { "...": "..." },
  "missingFields": ["field_name", "..."],
  "recommendedRoute": "Fast-track | Manual Review | Investigation Flag | Specialist Queue | Standard Review",
  "reasoning": "Plain-language explanation of which rule fired and why."
}
```

---

## 9. Future Scope (Not Implemented — Deliberately Out of Scope for This Submission)

- **Image/attachment verification** — cross-checking damage photos against
  the claimed description using a vision-capable LLM, to catch mismatched
  or implausible photo evidence. Not included here because reliable
  severity/fraud judgment from images is an open research problem and
  would introduce untested failure modes right before submission.
- **Policy date validity check** — flagging incidents that fall outside
  the policy's effective date range.
- **Dashboard view** — aggregate stats (claims by route, by day, average
  damage) computed from `claims_log.xlsx`.
- **Duplicate claim detection** — cross-referencing the Excel log for
  similar claims from the same policyholder.

These are natural next steps if this project continues past the initial
submission.
