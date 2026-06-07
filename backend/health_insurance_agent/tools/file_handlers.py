from __future__ import annotations

import base64
import io
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Optional

import fitz
from PIL import Image
from openai import AsyncOpenAI

from health_insurance_agent.config import OPENAI_API_KEY

logger = logging.getLogger("file_handlers")


def get_openai_client() -> AsyncOpenAI:
    return AsyncOpenAI(api_key=OPENAI_API_KEY)


async def upload_file(raw_bytes: bytes, suffix: str = ".pdf") -> str:
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(raw_bytes)
        tmp_path = tmp.name
    try:
        client = get_openai_client()
        up = await client.files.create(file=Path(tmp_path), purpose="user_data")
        return up.id
    finally:
        os.unlink(tmp_path)


async def delete_uploaded_file(file_id: str) -> None:
    try:
        client = get_openai_client()
        await client.files.delete(file_id)
    except Exception as e:
        logger.warning("Failed to delete uploaded file %s: %s", file_id, e)


def is_pdf(content: str) -> bool:
    try:
        raw = base64.b64decode(content)
        return raw.startswith(b"%PDF")
    except Exception:
        return False


def pdf_first_page_as_image(content: str, dpi: int = 120) -> str:
    raw = base64.b64decode(content)
    doc = fitz.open(stream=raw, filetype="pdf")
    page = doc[0]
    pix = page.get_pixmap(dpi=dpi)
    img_bytes = pix.tobytes("png")
    doc.close()
    return base64.b64encode(img_bytes).decode()


def flatten_xfa_pdf_to_pdf(content: str) -> bytes:
    raw = base64.b64decode(content)
    doc = fitz.open(stream=raw, filetype="pdf")
    images = []
    for page_num in range(len(doc)):
        page = doc[page_num]
        pix = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
        img_data = pix.tobytes("png")
        img = Image.open(io.BytesIO(img_data))
        images.append(img)
    doc.close()
    if not images:
        raise ValueError("No pages extracted from PDF")
    output = io.BytesIO()
    images[0].save(
        output,
        "PDF",
        save_all=True,
        append_images=images[1:] if len(images) > 1 else [],
    )
    return output.getvalue()


async def build_content_items(
    base64_content: str = "",
    prefix_text: str = "",
    file_id: Optional[str] = None,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []

    if prefix_text:
        items.append({"type": "input_text", "text": prefix_text})

    if file_id:
        items.append({"type": "input_file", "file_id": file_id})
    elif base64_content and is_pdf(base64_content):
        raw = base64.b64decode(base64_content)
        fid = await upload_file(raw)
        items.append({"type": "input_file", "file_id": fid})
    elif base64_content:
        items.append(
            {
                "type": "input_image",
                "image_url": f"data:image/png;base64,{base64_content}",
            }
        )

    return items
