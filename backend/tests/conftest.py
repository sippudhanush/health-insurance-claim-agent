import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool

from core.database import Base


TEST_POLICY = {
    "policy_id": "PLUM_GHI_2024",
    "coverage": {
        "sum_insured_per_employee": 500000,
        "per_claim_limit": 5000,
    },
    "opd_categories": {
        "consultation": {
            "sub_limit": 2000,
            "copay_percent": 10,
            "network_discount_percent": 20,
            "requires_prescription": True,
            "requires_pre_auth": False,
            "covered": True,
        },
        "diagnostic": {
            "sub_limit": 10000,
            "copay_percent": 0,
            "requires_prescription": True,
            "requires_pre_auth": False,
            "pre_auth_threshold": 10000,
            "high_value_tests_requiring_pre_auth": ["MRI", "CT Scan", "PET Scan"],
            "covered": True,
        },
        "pharmacy": {
            "sub_limit": 15000,
            "copay_percent": 0,
            "requires_prescription": True,
            "covered": True,
        },
        "dental": {
            "sub_limit": 10000,
            "copay_percent": 0,
            "covered": True,
            "covered_procedures": [
                "Root Canal Treatment",
                "Tooth Extraction",
                "Dental Filling",
            ],
            "excluded_procedures": [
                "Teeth Whitening",
                "Veneers",
                "Orthodontic Treatment (Braces)",
            ],
        },
        "vision": {
            "sub_limit": 5000,
            "copay_percent": 0,
            "covered": True,
        },
        "alternative_medicine": {
            "sub_limit": 8000,
            "copay_percent": 0,
            "covered": True,
        },
    },
    "waiting_periods": {
        "initial_waiting_period_days": 30,
        "pre_existing_conditions_days": 365,
        "specific_conditions": {
            "diabetes": 90,
            "hypertension": 90,
            "thyroid_disorders": 90,
            "maternity": 270,
        },
    },
    "exclusions": {
        "conditions": [
            "Self-inflicted injuries",
            "Obesity and weight loss programs",
            "Bariatric surgery",
            "Cosmetic or aesthetic procedures",
        ],
        "dental_exclusions": [
            "Teeth whitening",
            "Orthodontic treatment",
            "Cosmetic dental procedures",
        ],
        "vision_exclusions": ["LASIK", "Refractive surgery"],
    },
    "pre_authorization": {
        "required_for": [
            "MRI scan (amount > ₹10,000)",
            "CT scan (amount > ₹10,000)",
            "PET scan",
            "Major surgical procedures",
            "Planned hospitalization",
        ],
        "validity_days": 30,
    },
    "network_hospitals": [
        "Apollo Hospitals",
        "Fortis Healthcare",
        "Max Healthcare",
        "Manipal Hospitals",
        "Narayana Health",
        "Medanta",
        "Kokilaben Dhirubhai Ambani Hospital",
        "Aster CMI Hospital",
        "Columbia Asia",
        "Sakra World Hospital",
    ],
    "submission_rules": {
        "deadline_days_from_treatment": 30,
        "minimum_claim_amount": 500,
        "currency": "INR",
    },
    "document_requirements": {
        "CONSULTATION": {
            "required": ["PRESCRIPTION", "HOSPITAL_BILL"],
            "optional": ["LAB_REPORT", "DIAGNOSTIC_REPORT"],
        },
        "DIAGNOSTIC": {
            "required": ["PRESCRIPTION", "LAB_REPORT", "HOSPITAL_BILL"],
            "optional": ["DISCHARGE_SUMMARY"],
        },
        "PHARMACY": {"required": ["PRESCRIPTION", "PHARMACY_BILL"], "optional": []},
        "DENTAL": {
            "required": ["HOSPITAL_BILL"],
            "optional": ["PRESCRIPTION", "DENTAL_REPORT"],
        },
        "VISION": {"required": ["PRESCRIPTION", "HOSPITAL_BILL"], "optional": []},
        "ALTERNATIVE_MEDICINE": {
            "required": ["PRESCRIPTION", "HOSPITAL_BILL"],
            "optional": [],
        },
    },
    "fraud_thresholds": {
        "same_day_claims_limit": 2,
        "monthly_claims_limit": 6,
        "high_value_claim_threshold": 25000,
        "fraud_score_manual_review_threshold": 0.80,
    },
    "members": [
        {
            "member_id": "EMP001",
            "name": "Rajesh Kumar",
            "join_date": "2024-04-01",
            "relationship": "SELF",
        },
        {
            "member_id": "EMP005",
            "name": "Vikram Joshi",
            "join_date": "2024-09-01",
            "relationship": "SELF",
        },
    ],
}


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_factory() as session:
        yield session

    await engine.dispose()


@pytest.fixture
def mock_policy_path(monkeypatch, tmp_path):
    import json

    p = tmp_path / "policy_terms.json"
    p.write_text(json.dumps(TEST_POLICY))
    monkeypatch.setattr("agents.policy_agent.POLICY_PATH", p)
    return p
