import streamlit as st
import httpx
import json
import uuid
from pathlib import Path
from datetime import date
import os

API_BASE = os.getenv("API_BASE", "http://backend:8000")
BASE_DIR = Path(__file__).resolve().parent.parent
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", str(BASE_DIR / "files")))


def save_uploaded_file(uploaded_file) -> str:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    ext = Path(uploaded_file.name).suffix
    stored_name = f"{uuid.uuid4().hex}{ext}"
    path = UPLOAD_DIR / stored_name
    path.write_bytes(uploaded_file.getvalue())
    return stored_name


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
        uploaded_files = {}

        if category_req:
            for doc_type in category_req.get("required", []):
                st.markdown(f"##### {doc_type} *(Required)*")
                uploaded = st.file_uploader(f"Upload {doc_type}", key=f"req_{doc_type}_upload")
                uploaded_files[doc_type] = uploaded
                if uploaded:
                    st.caption(f"Uploaded: {uploaded.name} ({uploaded.size:,} bytes)")
                st.divider()

            for doc_type in category_req.get("optional", []):
                st.markdown(f"##### {doc_type} *(Optional)*")
                uploaded = st.file_uploader(f"Upload {doc_type}", key=f"opt_{doc_type}_upload")
                uploaded_files[doc_type] = uploaded
                if uploaded:
                    st.caption(f"Uploaded: {uploaded.name} ({uploaded.size:,} bytes)")
                st.divider()
        else:
            st.info("No document requirements defined for this category.")

        submitted = st.form_submit_button("Submit Claim")

    if submitted:
        documents = []
        for doc_type, uploaded in uploaded_files.items():
            doc = {
                "file_id": str(uuid.uuid4()),
                "actual_type": doc_type,
            }
            if uploaded:
                stored_name = save_uploaded_file(uploaded)
                doc["file_id"] = stored_name
                doc["file_name"] = uploaded.name
            documents.append(doc)

        payload = {
            "member_id": member_id,
            "policy_id": policy_id,
            "claim_category": claim_category,
            "treatment_date": treatment_date.isoformat(),
            "claimed_amount": claimed_amount,
            "documents": documents,
        }

        progress_bar = st.progress(0, text="Starting...")
        status_text = st.empty()
        result_container = st.empty()
        error_container = st.empty()
        result_data = None

        try:
            with httpx.stream("POST", f"{API_BASE}/api/claims", json=payload, timeout=120.0, headers={"Accept": "text/event-stream"}) as resp:
                event = None
                data_parts = []
                steps = ["extraction", "validation", "deep_extraction", "policy", "fraud", "decision"]
                step_idx = 0

                for line in resp.iter_lines():
                    if line.startswith("event: "):
                        event = line[7:]
                    elif line.startswith("data: "):
                        data_parts.append(line[6:])
                    elif line == "" and event is not None:
                        data_str = "\n".join(data_parts)
                        if data_str:
                            parsed = json.loads(data_str)
                            if event == "start":
                                progress_bar.progress(0, text=f"Claim {parsed.get('claim_id', '')} — processing...")
                                status_text.info(parsed.get("status", "PROCESSING"))

                            elif event == "progress":
                                step = parsed.get("step", "")
                                status = parsed.get("status", "")
                                files = parsed.get("files")
                                score = parsed.get("score")
                                reasons = parsed.get("reasons")
                                msg = f"[{step}] {status}"
                                if files is not None:
                                    msg += f" ({files} files)"
                                if score is not None:
                                    msg += f" score={score}"
                                if reasons:
                                    msg += f" reasons={reasons}"

                                if status == "running":
                                    step_idx = steps.index(step) if step in steps else step_idx
                                    progress_bar.progress(step_idx / len(steps), text=msg)
                                    status_text.info(msg)
                                elif status in ("done", "passed"):
                                    progress_bar.progress((step_idx + 1) / len(steps), text=msg)
                                    status_text.success(msg)
                                    step_idx += 1
                                elif status in ("failed", "rejected", "degraded"):
                                    progress_bar.progress(1.0, text=msg)
                                    status_text.warning(msg)
                                elif status == "flagged":
                                    progress_bar.progress((step_idx + 1) / len(steps), text=msg)
                                    status_text.warning(msg)
                                    step_idx += 1

                            elif event == "error":
                                code = parsed.get("code", "")
                                message = parsed.get("message", "Unknown error")
                                details = parsed.get("details")
                                progress_bar.progress(1.0, text="Failed")
                                status_text.error(f"[{code}] {message}")
                                if details:
                                    error_container.json(details)

                            elif event == "result":
                                result_data = parsed

                            elif event == "done":
                                progress_bar.progress(1.0, text="Complete")
                                if result_data:
                                    decision = result_data.get("decision", "")
                                    css_class = {
                                        "APPROVED": "approved", "PARTIAL": "partial",
                                        "REJECTED": "rejected", "MANUAL_REVIEW": "manual",
                                    }.get(decision, "")
                                    with result_container.container():
                                        st.markdown(f"### Decision: <span class='{css_class}'>{decision}</span>", unsafe_allow_html=True)
                                        st.session_state["last_claim_id"] = result_data.get("claim_id", "")
                                        col1, col2, col3 = st.columns(3)
                                        with col1:
                                            st.metric("Approved Amount", f"₹{result_data.get('approved_amount', 0):,.2f}" if result_data.get('approved_amount') else "₹0.00")
                                        with col2:
                                            st.metric("Confidence", f"{result_data.get('confidence_score', 0):.2%}")
                                        with col3:
                                            if result_data.get("rejection_reasons"):
                                                st.metric("Rejection Reasons", ", ".join(result_data["rejection_reasons"]))
                                        if result_data.get("line_item_breakdown"):
                                            st.subheader("Line Item Breakdown")
                                            breakdown = result_data["line_item_breakdown"]
                                            if breakdown and isinstance(breakdown, list):
                                                st.table(breakdown)
                                        if result_data.get("trace"):
                                            st.subheader("Full Trace")
                                            with st.expander("View decision trace", expanded=True):
                                                st.json(result_data["trace"])
                                        if result_data.get("degradation_notes"):
                                            st.warning("Degradation Notes:")
                                            for note in result_data["degradation_notes"]:
                                                st.write(f"- {note}")
                                break

                        event = None
                        data_parts = []

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
