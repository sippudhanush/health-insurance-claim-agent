import streamlit as st
import httpx
import json
import base64
import uuid
from pathlib import Path
from datetime import date
import os

API_BASE = os.getenv("API_BASE", "http://localhost:8000")
BASE_DIR = Path(__file__).resolve().parent.parent


def fetch_policy():
    try:
        resp = httpx.get(f"{API_BASE}/api/policy", timeout=10.0)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return {}


def file_to_base64(uploaded_file) -> str:
    return base64.b64encode(uploaded_file.getvalue()).decode()


if "policy" not in st.session_state:
    st.session_state.policy = fetch_policy()

policy = st.session_state.policy
members = policy.get("members", [])
doc_req = policy.get("document_requirements", {})

st.set_page_config(page_title="Health Insurance Claim Agent", layout="wide")

st.markdown("""
<style>
    .trace-box { background-color: #f0f2f6; border-radius: 8px; padding: 16px; margin: 8px 0; font-family: monospace; font-size: 13px; }
    .approved { color: #0a7d3e; font-weight: bold; }
    .rejected { color: #c41e3a; font-weight: bold; }
    .partial  { color: #b8860b; font-weight: bold; }
    .manual   { color: #d4a017; font-weight: bold; }
</style>
""", unsafe_allow_html=True)

st.title("Health Insurance Claim Agent")
st.markdown("Upload medical documents → AI extracts data → checks policy → detects fraud → final decision")

tab1, tab2 = st.tabs(["Submit Claim", "View Claim"])

with tab1:
    claim_category = st.selectbox(
        "Claim Category",
        ["CONSULTATION", "DIAGNOSTIC", "PHARMACY", "DENTAL", "VISION", "ALTERNATIVE_MEDICINE"],
    )

    with st.form("claim_form"):
        col1, col2 = st.columns(2)
        with col1:
            if members:
                member_options = {f"{m['member_id']} — {m['name']}": m["member_id"] for m in members}
                selected_label = st.selectbox("Member", options=list(member_options.keys()))
                member_id = member_options[selected_label]
            else:
                member_id = st.text_input("Member ID", value="EMP001")
            policy_id = st.text_input("Policy ID", value="PLUM_GHI_2024")
            hospital_name = st.text_input("Hospital Name", value="")
        with col2:
            treatment_date = st.date_input("Treatment Date", value=date(2024, 11, 1))
            claimed_amount = st.number_input("Claimed Amount (₹)", min_value=0, value=1500, step=100)
            simulate_failure = st.checkbox("Simulate Component Failure (TC011)")

        st.subheader("Upload Documents")
        category_req = doc_req.get(claim_category, {})
        uploaded_files = {}

        if category_req:
            for doc_type in category_req.get("required", []):
                st.markdown(f"**{doc_type}** *(Required)*")
                uploaded = st.file_uploader(f"Upload {doc_type}", key=f"req_{doc_type}", type=["pdf", "png", "jpg", "jpeg"])
                uploaded_files[doc_type] = uploaded

            for doc_type in category_req.get("optional", []):
                st.markdown(f"**{doc_type}** *(Optional)*")
                uploaded = st.file_uploader(f"Upload {doc_type}", key=f"opt_{doc_type}", type=["pdf", "png", "jpg", "jpeg"])
                uploaded_files[doc_type] = uploaded
        else:
            st.info("No document requirements defined for this category.")

        submitted = st.form_submit_button("Submit Claim", type="primary")

    if submitted:
        documents = []
        for doc_type, uploaded in uploaded_files.items():
            doc = {
                "file_id": str(uuid.uuid4()),
                "file_name": uploaded.name if uploaded else f"{doc_type}.pdf",
                "actual_type": doc_type,
                "base64_content": file_to_base64(uploaded) if uploaded else "",
            }
            documents.append(doc)

        payload = {
            "member_id": member_id,
            "policy_id": policy_id,
            "claim_category": claim_category,
            "treatment_date": treatment_date.isoformat(),
            "claimed_amount": claimed_amount,
            "hospital_name": hospital_name or None,
            "claims_history": [],
            "simulate_component_failure": simulate_failure,
            "documents": documents,
        }

        with st.spinner("Running AI agents (verification → extraction → policy → fraud → decision)..."):
            try:
                resp = httpx.post(f"{API_BASE}/api/claims", json=payload, timeout=180.0)
                if resp.status_code == 200:
                    result = resp.json()
                    decision = result.get("decision", "ERROR")
                    css_class = {"APPROVED": "approved", "PARTIAL": "partial", "REJECTED": "rejected", "MANUAL_REVIEW": "manual"}.get(decision, "")

                    st.markdown(f"## Decision: <span class='{css_class}'>{decision}</span>", unsafe_allow_html=True)
                    st.session_state["last_claim_id"] = result.get("claim_id", "")

                    col1, col2, col3 = st.columns(3)
                    with col1:
                        amt = result.get("approved_amount")
                        st.metric("Approved Amount", f"₹{amt:,.2f}" if amt else "₹0.00")
                    with col2:
                        st.metric("Confidence", f"{result.get('confidence_score', 0):.2%}")
                    with col3:
                        reasons = result.get("rejection_reasons", [])
                        if reasons:
                            st.metric("Rejection Reasons", ", ".join(reasons))

                    if result.get("line_item_breakdown"):
                        st.subheader("Line Item Breakdown")
                        st.table(result["line_item_breakdown"])

                    if result.get("degradation_notes"):
                        st.warning("Degradation Notes:")
                        for note in result["degradation_notes"]:
                            st.write(f"- {note}")

                    st.subheader("Reasoning")
                    st.markdown(result.get("reasoning", ""))

                    if result.get("trace"):
                        st.subheader("Full Trace")
                        with st.expander("View decision trace", expanded=True):
                            st.json(result["trace"])
                else:
                    st.error(f"API error: {resp.status_code} — {resp.text}")
            except Exception as e:
                st.error(f"Connection error: {e}")

with tab2:
    claim_id = st.text_input("Enter Claim ID", value=st.session_state.get("last_claim_id", ""))
    if st.button("Fetch Claim"):
        if claim_id:
            with st.spinner("Fetching..."):
                try:
                    resp = httpx.get(f"{API_BASE}/api/claims/{claim_id}", timeout=10.0)
                    if resp.status_code == 200:
                        data = resp.json()
                        decision = data.get("decision", "")
                        css_class = {"APPROVED": "approved", "PARTIAL": "partial", "REJECTED": "rejected", "MANUAL_REVIEW": "manual"}.get(decision, "")
                        st.markdown(f"### Decision: <span class='{css_class}'>{decision}</span>", unsafe_allow_html=True)
                        col1, col2 = st.columns(2)
                        with col1:
                            amt = data.get("approved_amount")
                            st.metric("Approved Amount", f"₹{amt:,.2f}" if amt else "₹0.00")
                        with col2:
                            st.metric("Confidence", f"{data.get('confidence_score', 0):.2%}")
                        if data.get("rejection_reasons"):
                            st.write("Reasons:", ", ".join(data["rejection_reasons"]))
                        if data.get("line_item_breakdown"):
                            st.table(data["line_item_breakdown"])
                        if data.get("trace"):
                            with st.expander("Trace", expanded=True):
                                st.json(data["trace"])
                    else:
                        st.error("Claim not found")
                except Exception as e:
                    st.error(f"Error: {e}")
