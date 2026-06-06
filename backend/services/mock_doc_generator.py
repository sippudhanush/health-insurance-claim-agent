from pathlib import Path
from fpdf import FPDF

FIXTURES_DIR = Path(__file__).parent.parent / "tests" / "fixtures"


class MockPrescriptionPDF(FPDF):
    def generate(
        self,
        doctor_name: str,
        reg_no: str,
        patient_name: str,
        diagnosis: str,
        medicines: list,
        filename: str,
    ):
        self.add_page()
        self.set_font("Helvetica", size=12)
        self.cell(200, 10, text=doctor_name, align="C", new_x="LMARGIN", new_y="NEXT")
        self.set_font("Helvetica", size=10)
        self.cell(
            200, 8, text=f"Reg: {reg_no}", align="C", new_x="LMARGIN", new_y="NEXT"
        )
        self.ln(5)
        self.cell(
            200, 8, text=f"Patient: {patient_name}", new_x="LMARGIN", new_y="NEXT"
        )
        self.cell(200, 8, text=f"Diagnosis: {diagnosis}", new_x="LMARGIN", new_y="NEXT")
        self.ln(3)
        for m in medicines:
            if isinstance(m, dict):
                self.cell(
                    200,
                    8,
                    text=f" - {m.get('name', m.get('description', str(m)))}",
                    new_x="LMARGIN",
                    new_y="NEXT",
                )
            else:
                self.cell(200, 8, text=f" - {m}", new_x="LMARGIN", new_y="NEXT")
        self.output(str(FIXTURES_DIR / filename))


class MockBillPDF(FPDF):
    def generate(
        self,
        hospital_name: str,
        patient_name: str,
        line_items: list,
        total: float,
        filename: str,
    ):
        self.add_page()
        self.set_font("Helvetica", size=12)
        self.cell(200, 10, text=hospital_name, align="C", new_x="LMARGIN", new_y="NEXT")
        self.set_font("Helvetica", size=10)
        self.cell(
            200, 8, text=f"Patient: {patient_name}", new_x="LMARGIN", new_y="NEXT"
        )
        self.ln(3)
        for item in line_items:
            desc = item.get("description", item.get("name", str(item)))
            amt = item.get("amount", 0)
            self.cell(200, 8, text=f"{desc}  Rs. {amt}", new_x="LMARGIN", new_y="NEXT")
        self.ln(5)
        self.set_font("Helvetica", size=12, style="B")
        self.cell(200, 10, text=f"Total: Rs. {total}", new_x="LMARGIN", new_y="NEXT")
        self.output(str(FIXTURES_DIR / filename))


def generate_all_mock_docs():
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)

    MockPrescriptionPDF().generate(
        doctor_name="Dr. Arun Sharma",
        reg_no="KA/45678/2015",
        patient_name="Rajesh Kumar",
        diagnosis="Viral Fever",
        medicines=[
            {"name": "Paracetamol 650mg", "dosage": "1-1-1"},
            {"name": "Vitamin C 500mg", "dosage": "0-0-1"},
        ],
        filename="prescription_rajesh.pdf",
    )
    MockPrescriptionPDF().generate(
        doctor_name="Dr. Sunil Mehta",
        reg_no="GJ/56789/2014",
        patient_name="Vikram Joshi",
        diagnosis="Type 2 Diabetes Mellitus",
        medicines=[
            {"name": "Metformin 500mg", "dosage": "1-0-1"},
            {"name": "Glimepiride 1mg", "dosage": "0-0-1"},
        ],
        filename="prescription_vikram.pdf",
    )
    MockBillPDF().generate(
        hospital_name="City Clinic, Bengaluru",
        patient_name="Rajesh Kumar",
        line_items=[
            {"description": "Consultation Fee", "amount": 1000},
            {"description": "CBC Test", "amount": 300},
            {"description": "Dengue NS1 Test", "amount": 200},
        ],
        total=1500,
        filename="bill_rajesh.pdf",
    )
    MockBillPDF().generate(
        hospital_name="Smile Dental Clinic",
        patient_name="Priya Singh",
        line_items=[
            {"description": "Root Canal Treatment", "amount": 8000},
            {"description": "Teeth Whitening", "amount": 4000},
        ],
        total=12000,
        filename="bill_priya_dental.pdf",
    )
    print(f"Mock documents generated in {FIXTURES_DIR}")


if __name__ == "__main__":
    generate_all_mock_docs()
