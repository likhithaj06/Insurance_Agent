# FNOL Claims Routing Agent

A lightweight agent that extracts key fields from FNOL (First Notice of Loss)
documents, detects missing/inconsistent data, and routes the claim to the
correct workflow with a human-readable explanation.

## Why this counts as an "agent"

Field extraction uses a local LLM (Ollama, `gpt-oss` model) rather than fixed
templates — this lets it understand FNOL documents with varying wording and
layout, not just one exact format. That's the "understanding" part of the
agent.

**Routing itself is deterministic Python, not the LLM.** This is a deliberate
design choice:
- Same input always produces the same route (no randomness/hallucination in
  a business-critical decision).
- The system keeps working correctly even if Ollama is down — it falls back
  to regex-based extraction automatically, and the demo never breaks.
- Every routing decision is traceable to one exact rule, which is what makes
  the "reasoning" output trustworthy rather than a vague LLM guess.

## Excel Claims Log

Every processed claim is automatically logged to `claims_log.xlsx` (created
in the project folder on first run). Each row is keyed by **Policy Number**:

- New policy number → a new row is appended.
- Same policy number processed again → the existing row is **updated**, not duplicated.

Columns include every extracted field plus Missing Fields, Recommended
Route, Reasoning, Extraction Method (llm/regex_fallback), and a timestamp —
giving a full audit trail of every routing decision and why it was made.

Logging failures (e.g. the file is open in Excel and locked) never break
the agent — the JSON result is always returned regardless.

## Project Structure

```
fnol_agent/
├── schema.py         # Pydantic schema for all required fields
├── llm_client.py      # Ollama Cloud API wrapper (with timeout + failure handling)
├── extractor.py       # LLM extraction + regex fallback
├── router.py          # Missing-field detection + routing rule engine
├── excel_logger.py    # Logs every processed claim to claims_log.xlsx (upsert by policy number)
├── pipeline.py         # Orchestrates the full flow, CLI entry point
├── app.py             # Streamlit UI for demoing
├── requirements.txt
├── .env.example        # Template for your OLLAMA_API_KEY
└── sample_fnols/       # 4 dummy FNOL docs, one per routing outcome
    ├── claim1_fasttrack.txt
    ├── claim2_missingfields.txt
    ├── claim3_investigation.txt
    └── claim4_injury.txt
```

## 📖 Full Guide

See **`GUIDE.md`** for a complete walkthrough: architecture diagram, what
each file does, why routing never depends on the LLM, the full routing
priority table, and verified test results for all 10 sample cases.

## Running Tests

```bash
python3 test_runner.py
```
Runs all 10 sample FNOL documents and prints a pass/fail table comparing
actual vs. expected routing — useful to run right before a demo.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

This project uses **Ollama Cloud API** for extraction (no local model download
or `ollama serve` needed):

1. Get an API key from https://ollama.com/settings/keys
2. Copy `.env.example` to `.env` and fill in your values:
   ```bash
   cp .env.example .env
   ```
3. Update the values in `.env` before running the app.
4. Check `llm_client.py` — `MODEL_NAME` is set to `"gpt-oss:120b-cloud"`. Update
   this to match the exact cloud model tag available in your account if different.

If the key isn't set, or the API call fails for any reason, extraction
automatically falls back to regex parsing — the pipeline never crashes.

## Running via CLI

```bash
python pipeline.py sample_fnols/claim1_fasttrack.txt
```

## Running the UI

```bash
streamlit run app.py
```

Then upload any file from `sample_fnols/` (or a real FNOL .txt/.pdf) and
click "Process Claim".

## Routing Rules (priority order, first match wins)

1. **Manual Review** — any mandatory field is missing.
2. **Investigation Flag** — description contains "fraud", "inconsistent", or "staged".
3. **Specialist Queue** — claim type is "injury".
4. **Fast-track** — estimated damage < ₹25,000.
5. **Standard Review** — fallback if none of the above apply.

## Output Format

```json
{
  "extractedFields": {},
  "missingFields": [],
  "recommendedRoute": "",
  "reasoning": ""
}
```

## Reliability Notes

- If the API key is missing, the Ollama Cloud API is unreachable, or it
  returns invalid JSON, extraction automatically falls back to regex
  parsing — the pipeline never crashes or returns empty output.
- Routing and missing-field detection never call the LLM, so they are 100%
  deterministic and testable.
