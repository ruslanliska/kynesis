import base64

import logfire

from app.core.ai_provider import get_openai_client

SUPPORTED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}

MAX_PDF_OCR_PAGES = 30

_MIME_TYPES: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}

_OCR_PROMPT = (
    "Extract all text from this image exactly as it appears. "
    "Preserve the structure and layout as much as possible. "
    "Return only the extracted text, no commentary."
)

# PDFs with fewer characters than this per page are treated as image-based
_MIN_CHARS_PER_PAGE = 50


async def _ocr_base64(b64: str, mime: str) -> str:
    client = get_openai_client()
    response = await client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": _OCR_PROMPT},
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                ],
            }
        ],
        max_tokens=4096,
    )
    return (response.choices[0].message.content or "").strip()


async def ocr_image(filename: str, content: bytes) -> str:
    """OCR a standalone image file using GPT-4o Vision."""
    from pathlib import Path

    ext = Path(filename).suffix.lower()
    mime = _MIME_TYPES.get(ext, "image/jpeg")
    b64 = base64.b64encode(content).decode()

    with logfire.span("ocr_image", filename=filename, size_bytes=len(content)):
        return await _ocr_base64(b64, "image/png" if mime == "image/gif" else mime)


async def ocr_pdf(content: bytes) -> str:
    """OCR an image-based PDF by rendering each page to a PNG and sending to Vision."""
    import fitz  # pymupdf

    doc = fitz.open(stream=content, filetype="pdf")
    page_count = min(len(doc), MAX_PDF_OCR_PAGES)
    pages_text: list[str] = []

    with logfire.span("ocr_pdf", page_count=page_count):
        for i in range(page_count):
            page = doc[i]
            pix = page.get_pixmap(dpi=200)
            img_bytes = pix.tobytes("png")
            b64 = base64.b64encode(img_bytes).decode()
            text = await _ocr_base64(b64, "image/png")
            if text:
                pages_text.append(text)

    doc.close()
    return "\n\n".join(pages_text)


def is_sparse_pdf(text: str, page_count: int) -> bool:
    """Return True when a PDF yielded too little text to be considered text-based."""
    threshold = max(100, page_count * _MIN_CHARS_PER_PAGE)
    return len(text.strip()) < threshold
