from datetime import date
from pydantic import BaseModel


class DocumentInput(BaseModel):
    file_id: str
    file_name: str | None = None
    actual_type: str | None = None
    quality: str | None = None
    patient_name_on_doc: str | None = None
    content: dict | None = None


class ClaimInput(BaseModel):
    member_id: str
    policy_id: str
    claim_category: str
    treatment_date: date
    claimed_amount: float
    hospital_name: str | None = None
    ytd_claims_amount: float | None = None
    claims_history: list[dict] | None = None
    simulate_component_failure: bool | None = None
    documents: list[DocumentInput]


class ClaimResponse(BaseModel):
    claim_id: str
    status: str
    message: str = "Claim received"
