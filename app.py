"""
app.py
------
Minimal Streamlit UI to demo the FNOL agent.

Flow: upload a .txt or .pdf FNOL document -> click "Process Claim" ->
see extracted fields, missing fields, recommended route, and reasoning.

Kept deliberately simple: one page, one button, no extra screens.
"""

import json
import streamlit as st
from pipeline import run_fnol_agent

st.set_page_config(page_title="FNOL Claims Routing Agent", page_icon="📋", layout="centered")

st.title("📋 FNOL Claims Routing Agent")
st.caption(
    "Upload a First Notice of Loss document. The agent extracts key fields, "
    "checks for missing/inconsistent data, and routes the claim automatically."
)

# Colors for each possible route, used to render a status badge
ROUTE_COLORS = {
    "Fast-track": "🟢",
    "Manual Review": "🟡",
    "Investigation Flag": "🔴",
    "Specialist Queue": "🔵",
    "Standard Review": "⚪",
}

uploaded_file = st.file_uploader("Upload FNOL document", type=["txt", "pdf"])

if uploaded_file is not None:
    # --- Read file content depending on type ---
    if uploaded_file.name.lower().endswith(".pdf"):
        try:
            import pdfplumber
            with pdfplumber.open(uploaded_file) as pdf:
                document_text = "\n".join(page.extract_text() or "" for page in pdf.pages)
        except Exception as e:
            st.error(f"Could not read PDF file: {e}")
            document_text = None
    else:
        document_text = uploaded_file.read().decode("utf-8", errors="ignore")

    if document_text:
        with st.expander("View raw extracted text"):
            st.text(document_text)

        if st.button("Process Claim", type="primary"):
            with st.spinner("Running extraction and routing..."):
                try:
                    result = run_fnol_agent(document_text)
                except Exception as e:
                    # Last-resort safety net: even if something unexpected happens,
                    # show a clear error instead of crashing the whole app.
                    st.error(f"Agent pipeline failed unexpectedly: {e}")
                    result = None

            if result:
                route = result["recommendedRoute"]
                badge = ROUTE_COLORS.get(route, "⚪")

                st.subheader(f"{badge} Recommended Route: {route}")
                st.info(result["reasoning"])

                if result["_extractionMethod"] == "regex_fallback":
                    st.caption(
                        "⚠️ Extraction used the regex fallback (LLM was unavailable). "
                        "Routing logic is unaffected -- it never depends on the LLM."
                    )

                log_status = result.get("_excelLogStatus")
                if log_status == "appended":
                    st.caption("📊 Logged as a new row in claims_log.xlsx")
                elif log_status == "updated":
                    st.caption("📊 Updated existing row in claims_log.xlsx (same policy number)")
                elif log_status == "failed":
                    st.caption("⚠️ Could not write to claims_log.xlsx -- check file isn't open elsewhere.")

                st.markdown("### Extracted Fields")
                st.table(
                    [{"Field": k, "Value": v if v else "—"} for k, v in result["extractedFields"].items()]
                )

                if result["missingFields"]:
                    st.markdown("### ⚠️ Missing Mandatory Fields")
                    st.write(", ".join(result["missingFields"]))
                else:
                    st.markdown("### ✅ No Missing Fields")

                with st.expander("View raw JSON output"):
                    # Drop internal diagnostic keys so the displayed JSON matches
                    # the exact required schema from the problem statement.
                    internal_keys = {"_extractionMethod", "_excelLogStatus"}
                    clean_result = {k: v for k, v in result.items() if k not in internal_keys}
                    st.code(json.dumps(clean_result, indent=2, ensure_ascii=False), language="json")
