from core.tool import Tool
from core.enums import ClaimCategory, DocumentType


class ValidateDocumentsTool(Tool):
    DOC_REQUIREMENTS = {
        ClaimCategory.CONSULTATION: {
            "required": [DocumentType.PRESCRIPTION, DocumentType.HOSPITAL_BILL],
            "optional": [DocumentType.LAB_REPORT, DocumentType.DIAGNOSTIC_REPORT],
        },
        ClaimCategory.DIAGNOSTIC: {
            "required": [
                DocumentType.PRESCRIPTION,
                DocumentType.LAB_REPORT,
                DocumentType.HOSPITAL_BILL,
            ],
            "optional": [DocumentType.DISCHARGE_SUMMARY],
        },
        ClaimCategory.PHARMACY: {
            "required": [DocumentType.PRESCRIPTION, DocumentType.PHARMACY_BILL],
            "optional": [],
        },
        ClaimCategory.DENTAL: {
            "required": [DocumentType.HOSPITAL_BILL],
            "optional": [DocumentType.PRESCRIPTION, DocumentType.DENTAL_REPORT],
        },
        ClaimCategory.VISION: {
            "required": [DocumentType.PRESCRIPTION, DocumentType.HOSPITAL_BILL],
            "optional": [],
        },
        ClaimCategory.ALTERNATIVE_MEDICINE: {
            "required": [DocumentType.PRESCRIPTION, DocumentType.HOSPITAL_BILL],
            "optional": [],
        },
    }

    def __init__(self, db=None):
        self.db = db

    @property
    def name(self) -> str:
        return "validate_documents"

    @property
    def description(self) -> str:
        return "Validate extracted documents against the claim category requirements. Checks for unreadable docs, wrong types, missing required docs, and patient name mismatches. Returns errors that block processing."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "enum": [c.value for c in ClaimCategory],
                    "description": "The claim category",
                },
                "documents": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "file_id": {"type": "string"},
                            "detected_type": {"type": "string"},
                            "quality": {"type": "string"},
                            "patient_name_on_doc": {"type": "string"},
                        },
                    },
                    "description": "List of extracted documents with detected types and quality",
                },
            },
            "required": ["category", "documents"],
        }

    async def run(self, category: str, documents: list[dict]) -> dict:
        errors = []
        category_enum = ClaimCategory(category)
        requirements = self.DOC_REQUIREMENTS[category_enum]
        required_types = [r.value for r in requirements["required"]]
        optional_types = [o.value for o in requirements["optional"]]

        detected_types = []
        file_map = {}

        for doc in documents:
            d_type = doc.get("detected_type")
            quality = doc.get("quality", "GOOD")
            f_id = doc.get("file_id")

            if d_type:
                detected_types.append(d_type)
            file_map[f_id] = dict(doc)

        for file_id, info in file_map.items():
            d_type = info.get("detected_type")
            quality = info.get("quality", "GOOD")

            if quality == "UNREADABLE":
                errors.append({
                    "code": "UNREADABLE_DOCUMENT",
                    "message": f"Your {d_type or 'document'} ({file_id}) is unreadable. Please upload a clearer photo.",
                    "details": {"file_id": file_id, "document_type": d_type},
                })
                continue

            if d_type and d_type not in required_types and d_type not in optional_types:
                errors.append({
                    "code": "WRONG_DOCUMENT_TYPE",
                    "message": (
                        f"You uploaded a {d_type} ({file_id}). "
                        f"A {required_types[0] if required_types else 'different document'} is required "
                        f"for {category} claims."
                    ),
                    "details": {
                        "file_id": file_id,
                        "uploaded_type": d_type,
                        "required_types": required_types,
                    },
                })

        missing = [rt for rt in required_types if rt not in detected_types]
        if missing:
            errors.append({
                "code": "MISSING_REQUIRED_DOCUMENT",
                "message": f"Missing required document(s): {', '.join(missing)}. Please upload the missing documents.",
                "details": {"missing_types": missing},
            })

        if not errors:
            patient_names = set()
            name_details = {}
            for file_id, info in file_map.items():
                pn = info.get("patient_name_on_doc") or info.get("patient_name")
                if pn:
                    pn_clean = pn.strip().lower()
                    patient_names.add(pn_clean)
                    name_details[file_id] = pn

            if len(patient_names) > 1:
                errors.append({
                    "code": "PATIENT_NAME_MISMATCH",
                    "message": (
                        "The documents appear to belong to different patients. "
                        + " ".join(f"{file_id}: '{name}'" for file_id, name in name_details.items())
                    ),
                    "details": {"names_found": name_details},
                })

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "error_count": len(errors),
        }
