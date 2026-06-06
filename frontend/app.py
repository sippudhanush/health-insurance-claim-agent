import streamlit as st
import httpx
import json
from datetime import date
import os

API_BASE = os.getenv("API_BASE", "http://backend:8000")

st.set_page_config(page_title="Plum Claims Processing", layout="wide")

st.markdown("""
<style>
    .trace-box {
        background-color: #f0f2f6;
        border-radius: 8px;
        padding: 16px;
        margin: 8px 0;
        font-family: monospace;
        font-size: 13px;
    }
    .approved { color: #0a7d3e; font-weight: bold; }
    .rejected { color: #c41e3a; font-weight: bold; }
    .partial  { color: #b8860b; font-weight: bold; }
    .manual   { color: #d4a017; font-weight: bold; }
    .error-msg { color: #c41e3a; background: #ffe0e0; padding: 10px; border-radius: 6px; }
</style>
""", unsafe_allow_html=True)

st.title("Plum Health Insurance Claims Processing")
st.markdown("Submit a health insurance claim and get an automated decision with full traceability.")

tab1, tab2 = st.tabs(["Submit Claim", "View Claim"])

with tab1:
    with st.form("claim_form"):
        col1, col2 = st.columns(2)
        with col1:
            member_id = st.text_input("Member ID", value="EMP001")
            policy_id = st.text_input("Policy ID", value="PLUM_GHI_2024")
            claim_category = st.selectbox(
                "Claim Category",
                ["CONSULTATION", "DIAGNOSTIC", "PHARMACY", "DENTAL", "VISION", "ALTERNATIVE_MEDICINE"],
            )
            claimed_amount = st.number_input("Claimed Amount (₹)", min_value=0, value=1500, step=100)
        with col2:
            treatment_date = st.date_input("Treatment Date", value=date(2024, 11, 1))
            hospital_name = st.text_input("Hospital Name (optional)")
            ytd_amount = st.number_input("YTD Claims (₹, optional)", min_value=0, value=0, step=100)
            simulate_failure = st.checkbox("Simulate Component Failure")

        st.subheader("Documents")
        doc_count = st.number_input("Number of documents", min_value=1, max_value=5, value=2)

        documents = []
        for i in range(doc_count):
            st.markdown(f"**Document {i+1}**")
            c1, c2, c3, c4 = st.columns(4)
            with c1:
                file_id = st.text_input(f"File ID", value=f"F00{i+1}", key=f"fid_{i}")
            with c2:
                actual_type = st.selectbox(
                    f"Document Type",
                    ["", "PRESCRIPTION", "HOSPITAL_BILL", "LAB_REPORT", "PHARMACY_BILL", "DISCHARGE_SUMMARY", "DENTAL_REPORT"],
                    key=f"type_{i}",
                )
            with c3:
                quality = st.selectbox(f"Quality", ["GOOD", "PARTIAL", "UNREADABLE"], key=f"qual_{i}")
            with c4:
                patient_name = st.text_input(f"Patient Name", key=f"pat_{i}")

            use_json = st.checkbox(f"Provide structured content for doc {i+1}", key=f"json_{i}")
            content_str = ""
            if use_json:
                content_str = st.text_area(
                    f"Content (JSON)", value='{"diagnosis": "Viral Fever", "doctor_name": "Dr. Sharma"}',
                    key=f"content_{i}", height=80,
                )

            doc = {"file_id": file_id}
            if actual_type:
                doc["actual_type"] = actual_type
            if quality:
                doc["quality"] = quality
            if patient_name:
                doc["patient_name_on_doc"] = patient_name
            if content_str:
                try:
                    doc["content"] = json.loads(content_str)
                except json.JSONDecodeError:
                    st.error(f"Invalid JSON in document {i+1}")
            documents.append(doc)
            st.divider()

        submitted = st.form_submit_button("Submit Claim")

    if submitted:
        payload = {
            "member_id": member_id,
            "policy_id": policy_id,
            "claim_category": claim_category,
            "treatment_date": treatment_date.isoformat(),
            "claimed_amount": claimed_amount,
            "hospital_name": hospital_name or None,
            "ytd_claims_amount": ytd_amount or None,
            "simulate_component_failure": simulate_failure or None,
            "documents": documents,
        }

        with st.spinner("Processing claim through pipeline..."):
            try:
                resp = httpx.post(f"{API_BASE}/api/claims", json=payload, timeout=60.0)
                if resp.status_code == 422:
                    err = resp.json()["detail"]
                    st.markdown(f'<div class="error-msg"><strong>{err["code"]}</strong><br>{err["message"]}</div>', unsafe_allow_html=True)
                    if err.get("details"):
                        st.json(err["details"])
                elif resp.status_code == 200:
                    result = resp.json()
                    st.success(f"Claim {result['claim_id']} processed successfully!")
                    st.session_state["last_claim_id"] = result["claim_id"]
                else:
                    st.error(f"Error: {resp.status_code} - {resp.text}")
            except Exception as e:
                st.error(f"Connection error: {e}")

with tab2:
    claim_id = st.text_input("Enter Claim ID", value=st.session_state.get("last_claim_id", ""))
    if st.button("Fetch Claim"):
        if claim_id:
            with st.spinner("Fetching claim..."):
                try:
                    resp = httpx.get(f"{API_BASE}/api/claims/{claim_id}", timeout=10.0)
                    if resp.status_code == 200:
                        data = resp.json()
                        decision = data["decision"]
                        css_class = {
                            "APPROVED": "approved", "PARTIAL": "partial",
                            "REJECTED": "rejected", "MANUAL_REVIEW": "manual",
                        }.get(decision, "")
                        st.markdown(f"### Decision: <span class='{css_class}'>{decision}</span>", unsafe_allow_html=True)

                        col1, col2, col3 = st.columns(3)
                        with col1:
                            st.metric("Approved Amount", f"₹{data['approved_amount']:,.2f}" if data['approved_amount'] else "₹0.00")
                        with col2:
                            st.metric("Confidence", f"{data['confidence_score']:.2%}")
                        with col3:
                            if data.get("rejection_reasons"):
                                st.metric("Rejection Reasons", ", ".join(data["rejection_reasons"]))

                        if data.get("line_item_breakdown"):
                            st.subheader("Line Item Breakdown")
                            st.table(data["line_item_breakdown"])

                        if data.get("trace"):
                            st.subheader("Full Trace")
                            with st.expander("View decision trace", expanded=True):
                                st.json(data["trace"])

                        if data.get("degradation_notes"):
                            st.warning("Degradation Notes:")
                            for note in data["degradation_notes"]:
                                st.write(f"- {note}")
                    else:
                        st.error(f"Claim not found: {resp.status_code}")
                except Exception as e:
                    st.error(f"Error: {e}")
