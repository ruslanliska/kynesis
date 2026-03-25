from pathlib import Path

import fitz  # pymupdf
from docx import Document


def parse_pdf(content: bytes) -> str:
    doc = fitz.open(stream=content, filetype="pdf")
    text_parts = []
    for page in doc:
        text_parts.append(page.get_text())
    doc.close()
    return "\n".join(text_parts)


def parse_docx(content: bytes) -> str:
    import io

    doc = Document(io.BytesIO(content))
    return "\n".join(para.text for para in doc.paragraphs if para.text.strip())


def parse_txt(content: bytes) -> str:
    return content.decode("utf-8", errors="replace")


def parse_markdown(content: bytes) -> str:
    return content.decode("utf-8", errors="replace")


SUPPORTED_EXTENSIONS = {".pdf", ".txt", ".docx", ".md"}

PARSERS = {
    ".pdf": parse_pdf,
    ".txt": parse_txt,
    ".docx": parse_docx,
    ".md": parse_markdown,
}


def extract_text(filename: str, content: bytes) -> str:
    ext = Path(filename).suffix.lower()
    parser = PARSERS.get(ext)
    if parser is None:
        supported = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        raise ValueError(
            f"Unsupported file format '{ext}'. Supported: {supported}."
        )
    return parser(content)
