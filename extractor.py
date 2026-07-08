"""
extractor.py
------------
Extracts structured fields from raw FNOL text.

Strategy: try the LLM first (it understands varied phrasing/layout, which is
what makes this an "agent" rather than a rigid parser). If the LLM is
unavailable or returns something that fails schema validation, fall back to
regex extraction so the demo never produces an empty/broken result.
"""

import re
import json
from llm_client import call_ollama_json
from schema import FNOLExtraction

# ---------------------------------------------------------------------------
# 1. LLM-based extraction (primary path)
# ---------------------------------------------------------------------------

EXTRACTION_PROMPT_TEMPLATE = """You are an insurance claims data extraction assistant.
Extract the following fields from the FNOL (First Notice of Loss) document below.
Return ONLY a valid JSON object with this exact structure (use null for anything
not found in the document -- do NOT guess or invent values):

{{
  "policy_number": null,
  "policyholder_name": null,
  "effective_dates": null,
  "date": null,
  "time": null,
  "location": null,
  "description": null,
  "claimant": null,
  "third_parties": null,
  "contact_details": null,
  "asset_type": null,
  "asset_id": null,
  "estimated_damage": null,
  "claim_type": null,
  "attachments": null,
  "initial_estimate": null
}}

Document:
\"\"\"
{document_text}
\"\"\"

Return only the JSON object, no extra commentary.
"""


def extract_with_llm(document_text: str) -> dict | None:
    """Ask the LLM to extract all fields as flat JSON. Returns None on failure."""
    prompt = EXTRACTION_PROMPT_TEMPLATE.format(document_text=document_text)
    result = call_ollama_json(prompt)
    if result is None:
        return None
    # Basic sanity check: make sure it's a dict, not a list or string
    if not isinstance(result, dict):
        return None
    return result


# ---------------------------------------------------------------------------
# 2. Regex-based extraction (fallback path)
# ---------------------------------------------------------------------------
# These patterns match the common "Label: value" style used in FNOL forms.
# Only used if the LLM call fails, so the pipeline always produces output.

# NOTE: patterns intentionally match only within a single line (no \s* that can
# swallow a newline). This prevents a blank field from "stealing" the next
# line's text, which was a real bug caught during testing (e.g. an empty
# "Time:" line matching all the way into the following "Location:" line).
REGEX_PATTERNS = {
    "policy_number": r"^Policy\s*Number\s*[:\-][ \t]*(.*)$",
    "policyholder_name": r"^Policyholder\s*Name\s*[:\-][ \t]*(.*)$",
    "effective_dates": r"^Effective\s*Dates?\s*[:\-][ \t]*(.*)$",
    "date": r"^(?:Incident\s*Date|Date\s*of\s*Loss)\s*[:\-][ \t]*(.*)$",
    "time": r"^Time\s*[:\-][ \t]*(.*)$",
    "location": r"^Location\s*[:\-][ \t]*(.*)$",
    "description": r"^Description\s*[:\-][ \t]*(.*)$",
    "claimant": r"^Claimant\s*[:\-][ \t]*(.*)$",
    "third_parties": r"^Third\s*Part(?:y|ies)\s*[:\-][ \t]*(.*)$",
    "contact_details": r"^Contact\s*Details?\s*[:\-][ \t]*(.*)$",
    "asset_type": r"^Asset\s*Type\s*[:\-][ \t]*(.*)$",
    "asset_id": r"^Asset\s*ID\s*[:\-][ \t]*(.*)$",
    "estimated_damage": r"^Estimated\s*Damage\s*[:\-][ \t]*(.*)$",
    "claim_type": r"^Claim\s*Type\s*[:\-][ \t]*(.*)$",
    "attachments": r"^Attachments?\s*[:\-][ \t]*(.*)$",
    "initial_estimate": r"^Initial\s*Estimate\s*[:\-][ \t]*(.*)$",
}


def extract_with_regex(document_text: str) -> dict:
    """
    Deterministic fallback extractor. Always returns a full dict (values may
    be None). Matches line-by-line (re.MULTILINE) so an empty field on one
    line can never accidentally capture text from a following line.
    """
    extracted = {}
    for field_name, pattern in REGEX_PATTERNS.items():
        match = re.search(pattern, document_text, re.IGNORECASE | re.MULTILINE)
        if match:
            value = match.group(1).strip()
            extracted[field_name] = value if value else None
        else:
            extracted[field_name] = None
    return extracted


# ---------------------------------------------------------------------------
# 3. Public entry point -- combines both with graceful fallback
# ---------------------------------------------------------------------------

def extract_fields(document_text: str) -> tuple[FNOLExtraction, str]:
    """
    Runs LLM extraction first, falls back to regex if the LLM is unavailable
    or returns invalid data. Returns (validated_schema, method_used) so the
    caller/UI can be transparent about which path was used.
    """
    llm_result = extract_with_llm(document_text)

    if llm_result is not None:
        try:
            flat = _to_flat_schema_dict(llm_result)
            validated = _build_schema(flat)
            return validated, "llm"
        except Exception as e:
            print(f"[extractor] LLM output failed validation, falling back. Reason: {e}")

    # Fallback path -- always succeeds since regex extraction can't "fail"
    flat = extract_with_regex(document_text)
    validated = _build_schema(flat)
    return validated, "regex_fallback"


def _to_flat_schema_dict(raw: dict) -> dict:
    """
    Ensures every expected key exists, filling missing keys with None.

    Also coerces non-string values to strings. This matters because the LLM
    sometimes returns numeric fields (e.g. estimated_damage: 12500) as a
    JSON number rather than a string, even though the prompt asks for a
    fixed schema -- LLMs don't always respect type hints strictly. Without
    this coercion, Pydantic would reject the whole extraction over a single
    int-vs-string mismatch and silently drop into the regex fallback path,
    which is wasteful given the LLM actually extracted the data correctly.
    """
    from schema import MANDATORY_FIELDS
    result = {}
    for key in MANDATORY_FIELDS:
        value = raw.get(key)
        if value is None:
            result[key] = None
        elif isinstance(value, str):
            result[key] = value
        else:
            # int, float, bool, etc. -- stringify rather than reject
            result[key] = str(value)
    return result


def _build_schema(flat: dict) -> FNOLExtraction:
    """Maps a flat dict into the nested Pydantic schema."""
    return FNOLExtraction(
        policy_info={
            "policy_number": flat.get("policy_number"),
            "policyholder_name": flat.get("policyholder_name"),
            "effective_dates": flat.get("effective_dates"),
        },
        incident_info={
            "date": flat.get("date"),
            "time": flat.get("time"),
            "location": flat.get("location"),
            "description": flat.get("description"),
        },
        involved_parties={
            "claimant": flat.get("claimant"),
            "third_parties": flat.get("third_parties"),
            "contact_details": flat.get("contact_details"),
        },
        asset_details={
            "asset_type": flat.get("asset_type"),
            "asset_id": flat.get("asset_id"),
            "estimated_damage": flat.get("estimated_damage"),
        },
        other_fields={
            "claim_type": flat.get("claim_type"),
            "attachments": flat.get("attachments"),
            "initial_estimate": flat.get("initial_estimate"),
        },
    )
