import pytest
from datetime import date

from agents.validation_agent import ValidationAgent
from agents.policy_agent import PolicyAgent
from agents.fraud_agent import FraudAgent

from schemas.document import LightExtractionResult
from core.enums import RejectionReason


class TestTC001_WrongDocumentUploaded:
    def test_validation_fails_for_wrong_doc_type(self):
        agent = ValidationAgent()
        extracted = [
            LightExtractionResult(file_id="F001", detected_type="PRESCRIPTION"),
            LightExtractionResult(file_id="F002", detected_type="PRESCRIPTION"),
        ]
        result = agent.validate("CONSULTATION", extracted)
        assert not result.valid
        codes = [e.code for e in result.errors]
        assert "WRONG_DOCUMENT_TYPE" in codes or "MISSING_REQUIRED_DOCUMENT" in codes


class TestTC002_UnreadableDocument:
    def test_validation_fails_for_unreadable(self):
        agent = ValidationAgent()
        extracted = [
            LightExtractionResult(
                file_id="F003", detected_type="PRESCRIPTION", quality="GOOD"
            ),
            LightExtractionResult(
                file_id="F004", detected_type="PHARMACY_BILL", quality="UNREADABLE"
            ),
        ]
        result = agent.validate("PHARMACY", extracted)
        assert not result.valid
        assert "UNREADABLE_DOCUMENT" in [e.code for e in result.errors]


class TestTC003_DifferentPatients:
    def test_validation_fails_patient_mismatch(self):
        agent = ValidationAgent()
        extracted = [
            LightExtractionResult(
                file_id="F005",
                detected_type="PRESCRIPTION",
                patient_name_on_doc="Rajesh Kumar",
            ),
            LightExtractionResult(
                file_id="F006",
                detected_type="HOSPITAL_BILL",
                patient_name_on_doc="Arjun Mehta",
            ),
        ]
        result = agent.validate("CONSULTATION", extracted)
        assert not result.valid
        assert "PATIENT_NAME_MISMATCH" in [e.code for e in result.errors]


class TestTC004_CleanApproval:
    @pytest.mark.asyncio
    async def test_full_approval(self, db_session, mock_policy_path):
        import json
        from agents.policy_agent import POLICY_PATH

        with open(POLICY_PATH) as f:
            policy = json.load(f)
        policy["members"].append(
            {"member_id": "EMP001", "name": "Rajesh Kumar", "join_date": "2024-04-01"}
        )
        with open(POLICY_PATH, "w") as f:
            json.dump(policy, f)

        pa = PolicyAgent(db_session)
        result = await pa.evaluate(
            claim_id="CLM_TEST004",
            member_id="EMP001",
            category="CONSULTATION",
            claimed_amount=1500,
            treatment_date=date(2024, 11, 1),
            hospital_name="City Clinic",
            extracted_docs=[
                {
                    "file_id": "F007",
                    "detected_type": "PRESCRIPTION",
                    "content": {
                        "diagnosis": "Viral Fever",
                        "doctor_name": "Dr. Sharma",
                        "line_items": [{"description": "Consultation", "amount": 1500}],
                    },
                    "confidence": 0.95,
                    "quality": "GOOD",
                },
                {
                    "file_id": "F008",
                    "detected_type": "HOSPITAL_BILL",
                    "content": {
                        "patient_name": "Rajesh Kumar",
                        "total": 1500,
                        "line_items": [
                            {"description": "Consultation Fee", "amount": 1000},
                            {"description": "CBC Test", "amount": 300},
                            {"description": "Dengue NS1 Test", "amount": 200},
                        ],
                    },
                    "confidence": 0.95,
                    "quality": "GOOD",
                },
            ],
        )
        assert result.eligible
        assert result.approved_amount_estimate == 1350
        assert result.copay_percent == 10


class TestTC005_WaitingPeriod:
    @pytest.mark.asyncio
    async def test_waiting_period_rejection(self, db_session, mock_policy_path):
        import json
        from agents.policy_agent import POLICY_PATH

        with open(POLICY_PATH) as f:
            policy = json.load(f)

        pa = PolicyAgent(db_session)
        result = await pa.evaluate(
            claim_id="CLM_TEST005",
            member_id="EMP005",
            category="CONSULTATION",
            claimed_amount=3000,
            treatment_date=date(2024, 10, 15),
            extracted_docs=[
                {
                    "file_id": "F009",
                    "detected_type": "PRESCRIPTION",
                    "content": {
                        "diagnosis": "Type 2 Diabetes Mellitus",
                        "doctor_name": "Dr. Sunil Mehta",
                    },
                    "confidence": 0.95,
                    "quality": "GOOD",
                },
            ],
        )
        assert not result.eligible
        assert RejectionReason.WAITING_PERIOD.value in result.rejection_reasons


class TestTC006_DentalPartial:
    @pytest.mark.asyncio
    async def test_dental_partial_approval(self, db_session, mock_policy_path):
        import json
        from agents.policy_agent import POLICY_PATH

        with open(POLICY_PATH) as f:
            policy = json.load(f)

        pa = PolicyAgent(db_session)
        result = await pa.evaluate(
            claim_id="CLM_TEST006",
            member_id="EMP001",
            category="DENTAL",
            claimed_amount=12000,
            treatment_date=date(2024, 10, 15),
            extracted_docs=[
                {
                    "file_id": "F011",
                    "detected_type": "HOSPITAL_BILL",
                    "content": {
                        "patient_name": "Priya Singh",
                        "line_items": [
                            {"description": "Root Canal Treatment", "amount": 8000},
                            {"description": "Teeth Whitening", "amount": 4000},
                        ],
                        "total": 12000,
                    },
                    "confidence": 0.95,
                    "quality": "GOOD",
                },
            ],
        )
        assert not result.eligible
        has_valid_reason = any(
            r in result.rejection_reasons
            for r in [
                RejectionReason.EXCLUDED_CONDITION.value,
                RejectionReason.SUB_LIMIT_EXCEEDED.value,
                RejectionReason.PER_CLAIM_EXCEEDED.value,
            ]
        )
        assert has_valid_reason


class TestTC007_MRIWithoutPreAuth:
    @pytest.mark.asyncio
    async def test_pre_auth_rejection(self, db_session, mock_policy_path):
        pa = PolicyAgent(db_session)
        result = await pa.evaluate(
            claim_id="CLM_TEST007",
            member_id="EMP001",
            category="DIAGNOSTIC",
            claimed_amount=15000,
            treatment_date=date(2024, 11, 2),
            extracted_docs=[
                {
                    "file_id": "F012",
                    "detected_type": "PRESCRIPTION",
                    "content": {
                        "diagnosis": "Suspected Lumbar Disc Herniation",
                        "tests_ordered": ["MRI Lumbar Spine"],
                    },
                    "confidence": 0.95,
                },
                {
                    "file_id": "F013",
                    "detected_type": "LAB_REPORT",
                    "content": {"test_name": "MRI Lumbar Spine"},
                    "confidence": 0.95,
                },
                {
                    "file_id": "F014",
                    "detected_type": "HOSPITAL_BILL",
                    "content": {
                        "line_items": [
                            {"description": "MRI Lumbar Spine", "amount": 15000}
                        ],
                        "total": 15000,
                    },
                    "confidence": 0.95,
                },
            ],
        )
        assert not result.eligible
        assert RejectionReason.PRE_AUTH_MISSING.value in result.rejection_reasons


class TestTC008_PerClaimLimitExceeded:
    @pytest.mark.asyncio
    async def test_per_claim_limit(self, db_session, mock_policy_path):
        pa = PolicyAgent(db_session)
        result = await pa.evaluate(
            claim_id="CLM_TEST008",
            member_id="EMP001",
            category="CONSULTATION",
            claimed_amount=7500,
            treatment_date=date(2024, 10, 20),
            extracted_docs=[
                {
                    "file_id": "F015",
                    "detected_type": "PRESCRIPTION",
                    "content": {"diagnosis": "Gastroenteritis"},
                    "confidence": 0.95,
                },
                {
                    "file_id": "F016",
                    "detected_type": "HOSPITAL_BILL",
                    "content": {"total": 7500},
                    "confidence": 0.95,
                },
            ],
        )
        assert not result.eligible
        assert RejectionReason.PER_CLAIM_EXCEEDED.value in result.rejection_reasons


class TestTC009_FraudSignal:
    @pytest.mark.asyncio
    async def test_fraud_manual_review(self, db_session):
        fa = FraudAgent(db_session)
        claims_history = [
            {"claim_id": "CLM_0081", "date": "2024-10-30", "amount": 1200},
            {"claim_id": "CLM_0082", "date": "2024-10-30", "amount": 1800},
            {"claim_id": "CLM_0083", "date": "2024-10-30", "amount": 2100},
        ]
        result = await fa.detect(
            claim_id="CLM_TEST009",
            member_id="EMP008",
            claimed_amount=4800,
            treatment_date=date(2024, 10, 30),
            claims_history=claims_history,
        )
        assert result.fraud_score >= 0.5
        assert any("SAME_DAY" in s for s in result.signals)


class TestTC010_NetworkDiscount:
    @pytest.mark.asyncio
    async def test_network_discount_before_copay(self, db_session, mock_policy_path):
        import json
        from agents.policy_agent import POLICY_PATH

        with open(POLICY_PATH) as f:
            policy = json.load(f)

        pa = PolicyAgent(db_session)
        result = await pa.evaluate(
            claim_id="CLM_TEST010",
            member_id="EMP001",
            category="CONSULTATION",
            claimed_amount=4500,
            treatment_date=date(2024, 11, 3),
            hospital_name="Apollo Hospitals",
            extracted_docs=[
                {
                    "file_id": "F019",
                    "detected_type": "PRESCRIPTION",
                    "content": {
                        "diagnosis": "Acute Bronchitis",
                        "doctor_name": "Dr. S. Iyer",
                    },
                    "confidence": 0.95,
                },
                {
                    "file_id": "F020",
                    "detected_type": "HOSPITAL_BILL",
                    "content": {
                        "hospital_name": "Apollo Hospitals",
                        "line_items": [
                            {"description": "Consultation Fee", "amount": 1500},
                            {"description": "Medicines", "amount": 3000},
                        ],
                        "total": 4500,
                    },
                    "confidence": 0.95,
                },
            ],
        )
        assert result.eligible
        assert result.approved_amount_estimate == 3240
        assert result.network_discount_percent == 20


class TestTC011_GracefulDegradation:
    def test_validation_passes_with_degraded_extraction(self):
        agent = ValidationAgent()
        results = [
            LightExtractionResult(
                file_id="F021",
                detected_type="PRESCRIPTION",
                quality="GOOD",
                confidence=0.5,
            ),
            LightExtractionResult(
                file_id="F022",
                detected_type="HOSPITAL_BILL",
                quality="GOOD",
                confidence=0.5,
            ),
        ]
        result = agent.validate("ALTERNATIVE_MEDICINE", results)
        assert result.valid


class TestTC012_ExcludedTreatment:
    @pytest.mark.asyncio
    async def test_excluded_treatment_rejection(self, db_session, mock_policy_path):
        pa = PolicyAgent(db_session)
        result = await pa.evaluate(
            claim_id="CLM_TEST012",
            member_id="EMP001",
            category="CONSULTATION",
            claimed_amount=8000,
            treatment_date=date(2024, 10, 18),
            extracted_docs=[
                {
                    "file_id": "F023",
                    "detected_type": "PRESCRIPTION",
                    "content": {
                        "diagnosis": "Morbid Obesity — BMI 37",
                        "treatment": "Bariatric Consultation and Customised Diet Plan",
                    },
                    "confidence": 0.95,
                },
                {
                    "file_id": "F024",
                    "detected_type": "HOSPITAL_BILL",
                    "content": {
                        "line_items": [
                            {"description": "Bariatric Consultation", "amount": 3000},
                            {"description": "Diet Program", "amount": 5000},
                        ],
                        "total": 8000,
                    },
                    "confidence": 0.95,
                },
            ],
        )
        assert not result.eligible
        assert RejectionReason.EXCLUDED_CONDITION.value in result.rejection_reasons
