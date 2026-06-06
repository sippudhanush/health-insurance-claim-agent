from schemas.document import LightExtractionResult, ValidationResult, ValidationError
from core.enums import ClaimCategory, DocumentType


class ValidationAgent:
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

    def validate(
        self, category: str, extracted_docs: list[LightExtractionResult | dict]
    ) -> ValidationResult:
        errors: list[ValidationError] = []
        category_enum = ClaimCategory(category)
        requirements = self.DOC_REQUIREMENTS[category_enum]

        detected_types = []
        file_map = {}

        for doc in extracted_docs:
            if isinstance(doc, LightExtractionResult):
                d_type = doc.detected_type
                quality = doc.quality
                f_id = doc.file_id
            else:
                d_type = doc.get("detected_type") or doc.get("actual_type")
                quality = doc.get("quality", "GOOD")
                f_id = doc.get("file_id")

            if d_type:
                detected_types.append(d_type)
            doc_dict = (
                doc.model_dump()
                if isinstance(doc, LightExtractionResult)
                else dict(doc)
            )
            file_map[f_id] = {"type": d_type, "quality": quality, **doc_dict}

        required_types = [r.value for r in requirements["required"]]
        optional_types = [o.value for o in requirements["optional"]]

        for file_id, info in file_map.items():
            d_type = info.get("type") or info.get("detected_type")
            quality = info.get("quality", "GOOD")

            if quality == "UNREADABLE":
                errors.append(
                    ValidationError(
                        code="UNREADABLE_DOCUMENT",
                        message=f"Your {d_type or 'document'} ({file_id}) is unreadable. Please upload a clearer photo.",
                        details={"file_id": file_id, "document_type": d_type},
                    )
                )
                continue

            if d_type not in required_types and d_type not in optional_types:
                errors.append(
                    ValidationError(
                        code="WRONG_DOCUMENT_TYPE",
                        message=(
                            f"You uploaded a {d_type} ({file_id}). "
                            f"A {required_types[0] if required_types else 'different document'} is required "
                            f"for {category} claims."
                        ),
                        details={
                            "file_id": file_id,
                            "uploaded_type": d_type,
                            "required_types": required_types,
                        },
                    )
                )

        missing = [rt for rt in required_types if rt not in detected_types]
        if missing:
            errors.append(
                ValidationError(
                    code="MISSING_REQUIRED_DOCUMENT",
                    message=f"Missing required document(s): {', '.join(missing)}. Please upload the missing documents.",
                    details={"missing_types": missing},
                )
            )

        if not errors:
            patient_names = set()
            for info in file_map.values():
                pn = None
                if isinstance(info, dict):
                    pn = info.get("patient_name_on_doc") or info.get("patient_name")
                if pn:
                    patient_names.add(pn.strip().lower())

            if len(patient_names) > 1:
                name_details = {}
                for file_id, info in file_map.items():
                    pn = None
                    if isinstance(info, dict):
                        pn = info.get("patient_name_on_doc") or info.get("patient_name")
                    if pn:
                        name_details[file_id] = pn
                errors.append(
                    ValidationError(
                        code="PATIENT_NAME_MISMATCH",
                        message=(
                            "The documents appear to belong to different patients. "
                            + " ".join(
                                f"{file_id}: '{name}'"
                                for file_id, name in name_details.items()
                            )
                        ),
                        details={"names_found": name_details},
                    )
                )

        return ValidationResult(valid=len(errors) == 0, errors=errors)
