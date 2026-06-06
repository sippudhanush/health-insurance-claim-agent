import streamlit as st
import httpx
import json
from datetime import date
import os

API_BASE = os.getenv("API_BASE", "http://backend:8000")


def fetch_policy():
    try:
        resp = httpx.get(f"{API_BASE}/api/policy", timeout=10.0)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return {}


if "policy" not in st.session_state:
    st.session_state.policy = fetch_policy()

policy = st.session_state.policy
members = policy.get("members", [])
doc_req = policy.get("document_requirements", {})

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
    claim_category = st.selectbox(
        "Claim Category",
        ["CONSULTATION", "DIAGNOSTIC", "PHARMACY", "DENTAL", "VISION", "ALTERNATIVE_MEDICINE"],
        key="claim_category_select",
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
                st.caption("Members not loaded — enter manually.")
            policy_id = st.text_input("Policy ID", value="PLUM_GHI_2024")
        with col2:
            treatment_date = st.date_input("Treatment Date", value=date(2024, 11, 1))
            claimed_amount = st.number_input("Claimed Amount (₹)", min_value=0, value=1500, step=100)

        st.subheader("Documents")

        category_req = doc_req.get(claim_category, {})
        documents = []

        if category_req:
            for doc_type in category_req.get("required", []):
                st.markdown(f"##### {doc_type} *(Required)*")
                c1, c2 = st.columns(2)
                with c1:
                    fid = st.text_input("File ID", value=f"{doc_type[:4]}_001", key=f"req_{doc_type}_fid")
                    st.markdown(f"**Type:** {doc_type}")
                with c2:
                    pname = st.text_input("Patient Name", key=f"req_{doc_type}_pname")

                use_json = st.checkbox("Add structured content", key=f"req_{doc_type}_json")
                content_str = ""
                if use_json:
                    content_str = st.text_area("Content (JSON)", key=f"req_{doc_type}_content", height=80)

                doc = {"file_id": fid, "actual_type": doc_type}
                if pname:
                    doc["patient_name_on_doc"] = pname
                if content_str:
                    doc["content"] = json.loads(content_str)
                documents.append(doc)
                st.divider()

            for doc_type in category_req.get("optional", []):
                st.markdown(f"##### {doc_type} *(Optional)*")
                c1, c2 = st.columns(2)
                with c1:
                    fid = st.text_input("File ID", value=f"{doc_type[:4]}_001", key=f"opt_{doc_type}_fid")
                    st.markdown(f"**Type:** {doc_type}")
                with c2:
                    pname = st.text_input("Patient Name", key=f"opt_{doc_type}_pname")

                use_json = st.checkbox("Add structured content", key=f"opt_{doc_type}_json")
                content_str = ""
                if use_json:
                    content_str = st.text_area("Content (JSON)", key=f"opt_{doc_type}_content", height=80)

                doc = {"file_id": fid, "actual_type": doc_type}
                if pname:
                    doc["patient_name_on_doc"] = pname
                if content_str:
                    doc["content"] = json.loads(content_str)
                documents.append(doc)
                st.divider()
        else:
            st.info("No document requirements defined for this category.")

        submitted = st.form_submit_button("Submit Claim")

    if submitted:
        payload = {
            "member_id": member_id,
            "policy_id": policy_id,
            "claim_category": claim_category,
            "treatment_date": treatment_date.isoformat(),
            "claimed_amount": claimed_amount,
            "hospital_name": hospital_name or None,
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
