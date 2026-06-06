from pydantic import BaseModel


class LightExtractionResult(BaseModel):
    file_id: str
    detected_type: str | None = None
    quality: str = "GOOD"
    patient_name_on_doc: str | None = None
    confidence: float = 1.0
    error: str | None = None


class ValidationError(BaseModel):
    code: str
    message: str
    details: dict | None = None


class ValidationResult(BaseModel):
    valid: bool
    errors: list[ValidationError] = []
