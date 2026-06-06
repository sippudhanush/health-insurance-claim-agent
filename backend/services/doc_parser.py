from pathlib import Path


async def parse_document(file_path: Path) -> str:
    ext = file_path.suffix.lower()
    if ext == ".pdf":
        return _parse_pdf(file_path)
    elif ext in {".jpg", ".jpeg", ".png", ".bmp", ".tiff"}:
        return _parse_image(file_path)
    else:
        return file_path.name


def _parse_pdf(file_path: Path) -> str:
    try:
        import fitz

        doc = fitz.open(str(file_path))
        text = ""
        for page in doc:
            text += page.get_text()
        doc.close()
        return (
            text if text.strip() else f"[PDF: {file_path.name} - no extractable text]"
        )
    except ImportError:
        return f"[PDF: {file_path.name} - fitz not available]"


def _parse_image(file_path: Path) -> str:
    return f"[Image: {file_path.name}]"
