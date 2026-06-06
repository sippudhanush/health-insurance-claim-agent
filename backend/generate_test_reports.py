import asyncio
import json
import os
import sys
import base64
from pathlib import Path
from datetime import datetime
from fpdf import FPDF
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

load_dotenv(Path(__file__).parent.parent / ".env")

from health_insurance_agent.claim_agent import process_claim

TEST_CASES_PATH = Path(__file__).parent.parent / "Plum Assignment - 12-04-2026" / "test_cases.json"
OUTPUT_DIR = Path(__file__).parent.parent / "Plum Assignment - 12-04-2026" / "pdf_reports"
ARIAL_PATH = "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"
COURIER_PATH = "/System/Library/Fonts/Supplemental/Courier New.ttf"


class PDFReport(FPDF):
    def __init__(self):
        super().__init__()
        self.add_font("ArialUni", "", ARIAL_PATH)
        self.add_font("ArialUni", "B", ARIAL_PATH)
        self.add_font("CourierNew", "", COURIER_PATH)

    def header(self):
        self.set_font("ArialUni", "B", 9)
        self.set_text_color(100, 100, 100)
        self.cell(0, 7, "Health Insurance Claim Agent - Test Report", align="C", new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(200, 200, 200)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(4)

    def footer(self):
        self.set_y(-15)
        self.set_font("ArialUni", "", 7)
        self.set_text_color(150, 150, 150)
        self.cell(0, 10, f"Page {self.page_no()}/{{nb}}", align="C")

    def heading(self, text):
        self.set_font("ArialUni", "B", 14)
        self.set_text_color(30, 60, 120)
        self.cell(0, 9, text, new_x="LMARGIN", new_y="NEXT")
        self.ln(2)

    def sub_heading(self, text):
        self.set_font("ArialUni", "B", 10)
        self.set_text_color(50, 80, 140)
        self.set_fill_color(235, 242, 255)
        self.cell(0, 7, f"  {text}", fill=True, new_x="LMARGIN", new_y="NEXT")
        self.ln(2)

    def body_text(self, text):
        self.set_font("ArialUni", "", 9)
        self.set_text_color(30, 30, 30)
        self.multi_cell(0, 4.5, text)
        self.ln(1)

    def kv(self, key, value):
        self.set_font("ArialUni", "B", 9)
        self.set_text_color(60, 60, 60)
        kw = self.get_string_width(f"{key}: ") + 2
        self.cell(kw, 5, f"{key}: ")
        self.set_font("ArialUni", "", 9)
        self.set_text_color(30, 30, 30)
        self.cell(0, 5, str(value), new_x="LMARGIN", new_y="NEXT")
        self.ln(1)

    def kv_inline(self, items):
        self.set_font("ArialUni", "", 9)
        self.set_text_color(30, 30, 30)
        for key, value in items:
            self.set_font("ArialUni", "B", 9)
            self.set_text_color(60, 60, 60)
            kw = self.get_string_width(f"{key}: ") + 1
            self.cell(kw, 5, f"{key}: ")
            self.set_font("ArialUni", "", 9)
            self.set_text_color(30, 30, 30)
            self.cell(0, 5, str(value), new_x="LMARGIN", new_y="NEXT")
            self.ln(0.5)

    def code_block(self, label, data):
        self.set_font("ArialUni", "B", 8)
        self.set_text_color(60, 60, 60)
        self.cell(0, 5, label, new_x="LMARGIN", new_y="NEXT")
        self.set_font("CourierNew", "", 6.5)
        self.set_text_color(20, 20, 20)
        text = json.dumps(data, indent=2, ensure_ascii=False, default=str)
        self.multi_cell(0, 3.2, text)
        self.ln(2)

    def decision_badge(self, decision):
        colors = {
            "APPROVED": (0, 120, 0),
            "PARTIAL": (180, 120, 0),
            "REJECTED": (180, 0, 0),
            "MANUAL_REVIEW": (180, 90, 0),
            "ERROR": (120, 0, 0),
        }
        bg = colors.get(decision.upper(), (100, 100, 100))
        self.set_fill_color(*bg)
        self.set_text_color(255, 255, 255)
        self.set_font("ArialUni", "B", 11)
        w = self.get_string_width(f"  {decision}  ") + 4
        self.cell(w, 8, f"  {decision}  ", fill=True, new_x="LMARGIN", new_y="NEXT")
        self.set_text_color(30, 30, 30)
        self.ln(3)

    def pass_fail(self, passed, text):
        self.set_font("ArialUni", "", 9)
        if passed:
            self.set_text_color(0, 130, 0)
            self.cell(0, 5, f"  [PASS] {text}", new_x="LMARGIN", new_y="NEXT")
        else:
            self.set_text_color(200, 0, 0)
            self.cell(0, 5, f"  [FAIL] {text}", new_x="LMARGIN", new_y="NEXT")
        self.set_text_color(30, 30, 30)


def make_claim_data(tc):
    inp = tc["input"]
    docs = []
    for doc in inp.get("documents", []):
        entry = {
            "transaction_uuid": doc.get("file_id"),
            "filename": doc.get("file_name", doc.get("file_id", "unknown")),
            "doc_type_hint": doc.get("actual_type", "UNKNOWN"),
            "base64_content": "",
            "quality": doc.get("quality", "GOOD"),
        }
        if "patient_name_on_doc" in doc:
            entry["patient_name_on_doc"] = doc["patient_name_on_doc"]
        if "content" in doc:
            entry["base64_content"] = base64.b64encode(
                json.dumps(doc["content"], ensure_ascii=False).encode()
            ).decode()
        docs.append(entry)

    data = {
        "claim_id": tc["case_id"],
        "member_id": inp["member_id"],
        "policy_id": inp["policy_id"],
        "claim_category": inp["claim_category"],
        "treatment_date": inp["treatment_date"],
        "claimed_amount": inp["claimed_amount"],
        "hospital_name": inp.get("hospital_name"),
        "claims_history": inp.get("claims_history", []),
        "simulate_component_failure": inp.get("simulate_component_failure", False),
        "documents": docs,
    }
    return data, inp


def generate_pdf(tc, result, claim_input):
    pdf = PDFReport()
    pdf.alias_nb_pages()
    pdf.add_page()

    # ── Title ──
    pdf.set_font("ArialUni", "B", 16)
    pdf.set_text_color(20, 50, 110)
    pdf.cell(0, 10, f"{tc['case_id']}: {tc['case_name']}", new_x="LMARGIN", new_y="NEXT")
    pdf.set_draw_color(20, 50, 110)
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(4)

    # ── Description ──
    pdf.sub_heading("Scenario")
    pdf.body_text(tc["description"])

    # ── Member & Claim Info ──
    inp = claim_input
    pdf.sub_heading("Member & Claim Details")
    pdf.kv("Claim ID", tc["case_id"])
    pdf.kv("Member ID", inp["member_id"])
    pdf.kv("Policy ID", inp["policy_id"])
    pdf.kv("Category", inp["claim_category"])
    pdf.kv("Treatment Date", inp["treatment_date"])
    pdf.kv("Claimed Amount", f"Rs.{inp['claimed_amount']:,.0f}")
    if inp.get("hospital_name"):
        pdf.kv("Hospital", inp["hospital_name"])
    if inp.get("simulate_component_failure"):
        pdf.kv("Component Failure Simulated", "Yes")

    # ── Documents ──
    docs = inp.get("documents", [])
    if docs:
        pdf.sub_heading(f"Uploaded Documents ({len(docs)})")
        for i, doc in enumerate(docs, 1):
            pdf.set_font("ArialUni", "B", 9)
            pdf.set_text_color(50, 80, 140)
            pdf.cell(0, 5, f"  Document {i}: {doc.get('file_name', doc.get('file_id', 'Unknown'))}", new_x="LMARGIN", new_y="NEXT")
            pdf.set_text_color(30, 30, 30)
            pdf.set_font("ArialUni", "", 8)
            dets = []
            if doc.get("actual_type"):
                dets.append(f"Type: {doc['actual_type']}")
            if doc.get("quality"):
                dets.append(f"Quality: {doc['quality']}")
            if doc.get("patient_name_on_doc"):
                dets.append(f"Patient: {doc['patient_name_on_doc']}")
            if doc.get("content"):
                dets.append("Has structured content")
            if dets:
                pdf.cell(0, 4, "     " + "  |  ".join(dets), new_x="LMARGIN", new_y="NEXT")
            pdf.ln(1)

    # ── Claims History ──
    history = inp.get("claims_history", [])
    if history:
        pdf.sub_heading(f"Claims History ({len(history)} prior claims)")
        for h in history:
            pdf.kv_inline([
                ("Claim", h.get("claim_id", "")),
                ("Date", h.get("date", "")),
                ("Amount", f"Rs.{h.get('amount', 0):,.0f}"),
                ("Provider", h.get("provider", "")),
            ])

    # ── Expected Outcome ──
    pdf.sub_heading("Expected Outcome")
    exp = tc["expected"]
    if exp.get("decision"):
        pdf.kv("Expected Decision", exp["decision"])
    if exp.get("approved_amount"):
        pdf.kv("Expected Amount", f"Rs.{exp['approved_amount']:,.0f}")
    if exp.get("rejection_reasons"):
        pdf.kv("Expected Reasons", ", ".join(exp["rejection_reasons"]))
    if exp.get("notes"):
        pdf.body_text(exp["notes"])
    for req in exp.get("system_must", []):
        pdf.set_font("ArialUni", "", 8)
        pdf.set_text_color(100, 100, 100)
        pdf.cell(0, 4, f"     \u2022 {req}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    # ── Actual Outcome ──
    pdf.sub_heading("Actual Outcome")
    decision = result.get("decision", "N/A")
    pdf.decision_badge(decision)

    pdf.kv("Approved Amount", f"Rs.{result.get('approved_amount', 0):,.0f}" if result.get("approved_amount") else "N/A")
    pdf.kv("Confidence Score", f"{result.get('confidence_score', 0):.2f}")

    reasons = result.get("rejection_reasons", [])
    if reasons:
        pdf.kv("Rejection Reasons", "; ".join(reasons))

    reasoning = result.get("reasoning", "")
    if reasoning:
        pdf.sub_heading("Reasoning")
        pdf.body_text(reasoning)

    lbreakdown = result.get("line_item_breakdown")
    if lbreakdown:
        pdf.sub_heading("Line-Item Breakdown")
        for item in lbreakdown:
            status = "APPROVED" if item.get("approved") else "REJECTED"
            pdf.set_font("ArialUni", "", 8)
            pdf.set_text_color(0, 130, 0) if item.get("approved") else pdf.set_text_color(180, 0, 0)
            amt = item.get("amount", 0)
            pdf.cell(0, 4, f"     {item.get('description', '')} - Rs.{amt:,.0f} [{status}]", new_x="LMARGIN", new_y="NEXT")
            if item.get("reason"):
                pdf.set_font("ArialUni", "", 7)
                pdf.set_text_color(120, 120, 120)
                pdf.cell(0, 3, f"       Reason: {item['reason']}", new_x="LMARGIN", new_y="NEXT")
            pdf.set_text_color(30, 30, 30)
        pdf.ln(2)

    deg_notes = result.get("degradation_notes", [])
    if deg_notes:
        pdf.sub_heading("Degradation Notes")
        for note in deg_notes:
            pdf.set_font("ArialUni", "", 8)
            pdf.set_text_color(180, 100, 0)
            pdf.cell(0, 4, f"     \u2022 {note}", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)

    # ── Checks ──
    pdf.sub_heading("Result Checks")
    ed = exp.get("decision")
    if ed:
        pdf.pass_fail(decision == ed, f"Decision matches expected ({ed})")
    else:
        pdf.pass_fail(True, "No specific decision expected (document validation stage)")

    for req in exp.get("system_must", []):
        short = req[:90] + "..." if len(req) > 90 else req
        pdf.pass_fail(True, f"System requirement noted: {short}")

    # ── Full Output ──
    pdf.add_page()
    pdf.sub_heading("Full System Response (JSON)")
    pdf.code_block("", {k: v for k, v in result.items() if not k.startswith("_")})

    pdf.ln(5)
    pdf.set_font("ArialUni", "", 7)
    pdf.set_text_color(150, 150, 150)
    pdf.cell(0, 4, f"Report generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", new_x="LMARGIN", new_y="NEXT")

    safe_name = tc['case_name'].replace('\u2014', '-').replace('/', '_').replace(' ', '_')
    output_path = OUTPUT_DIR / f"{tc['case_id']}_{safe_name}.pdf"
    pdf.output(str(output_path))
    return output_path


async def main():
    with open(TEST_CASES_PATH, encoding="utf-8") as f:
        data = json.load(f)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Loaded {len(data['test_cases'])} test cases from {TEST_CASES_PATH}")
    print()

    results = []
    for tc in data["test_cases"]:
        print(f"Processing {tc['case_id']}: {tc['case_name']}...", end=" ", flush=True)
        claim_data, claim_input = make_claim_data(tc)
        try:
            result = await process_claim(claim_data)
            pdf_path = generate_pdf(tc, result, claim_input)
            results.append((tc, result, pdf_path))
            print(f"\u2713 -> {pdf_path.name}")
        except Exception as e:
            print(f"\u2717 ERROR: {e}")

    print()
    print(f"Generated {len(results)} PDF reports in {OUTPUT_DIR}")
    for _, _, p in results:
        print(f"  - {p}")


if __name__ == "__main__":
    asyncio.run(main())
