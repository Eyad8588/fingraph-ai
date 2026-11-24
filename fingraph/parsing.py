"""Turn an uploaded file into pages of text.

PDF pages with a real text layer are read directly; pages without one (scans) are rendered and OCR'd.
Each page records HOW it was read (text / ocr) and the OCR confidence, so the UI can warn the user.
"""

from __future__ import annotations

import io
import platform
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps

from .config import Settings
from .models import ChatModel

SUPPORTED = {".pdf", ".docx", ".png", ".jpg", ".jpeg", ".txt", ".md", ".csv"}


class ParseError(ValueError):
    pass


@dataclass
class Page:
    page: int
    text: str
    method: str  # text | ocr | docx | plain
    confidence: float | None = None


# ---------------------------------------------------------------- OCR engines
class OcrEngine:
    name = "none"

    def read(self, image: Image.Image) -> tuple[str, float | None]:
        raise NotImplementedError


class AppleVisionOcr(OcrEngine):
    """macOS Vision framework: offline, fast, accurate on printed documents."""

    name = "apple-vision"

    def read(self, image):
        from ocrmac import ocrmac

        obs = ocrmac.OCR(image, recognition_level="accurate", language_preference=["en-US"]).recognize()
        if not obs:
            return "", 0.0
        return rebuild_lines(obs), sum(c for _, c, _ in obs) / len(obs)


class LlmVisionOcr(OcrEngine):
    """Fallback for non-macOS hosts: a multimodal LLM transcribes the page. Slower and less trustworthy."""

    name = "llm-vision"

    def __init__(self, model: ChatModel):
        self.model = model

    def read(self, image):
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        text = self.model.complete(
            "You are an OCR engine. Transcribe ALL text in the image exactly as written, line by line. "
            "Keep table rows on one line with cells separated by two spaces. Do not summarise, translate, "
            "correct or add anything.", "Transcribe this page.", images=[buf.getvalue()], temperature=0)
        return text, None


def make_ocr(s: Settings, vision_model: ChatModel) -> OcrEngine:
    if s.ocr == "llm" or (s.ocr == "auto" and platform.system() != "Darwin"):
        return LlmVisionOcr(vision_model)
    return AppleVisionOcr()


def rebuild_lines(observations) -> str:
    """Vision returns text boxes; group boxes on the same baseline into one line, left to right.

    Without this, a table row like 'Total    14,260.00' comes back as two separate lines.
    bbox = (x, y, w, h) normalised, origin bottom-left.
    """
    boxes = sorted(((t, b) for t, _, b in observations), key=lambda tb: -(tb[1][1] + tb[1][3] / 2))
    lines: list[list] = []
    for text, (x, y, w, h) in boxes:
        yc = y + h / 2
        if lines and abs(lines[-1][0] - yc) < max(h, lines[-1][1]) * 0.55:
            lines[-1][2].append((x, w, text))
        else:
            lines.append([yc, h, [(x, w, text)]])
    out = []
    for _, _, parts in lines:
        parts.sort()
        line, prev_end = "", None
        for x, w, text in parts:
            if prev_end is not None:
                line += "    " if x - prev_end > 0.03 else " "
            line += text
            prev_end = x + w
        out.append(line)
    return "\n".join(out)


def prepare_image(img: Image.Image) -> Image.Image:
    img = ImageOps.exif_transpose(img).convert("RGB")
    longest = max(img.size)
    if longest > 3000:
        img.thumbnail((3000, 3000))
    return deskew(img)


def deskew(img: Image.Image, max_angle: float = 4.0) -> Image.Image:
    """Phone photos are slightly rotated, which splits table rows ('Subtotal' ... '20,000.00') into separate
    lines. Find the angle whose horizontal ink profile is sharpest (projection-profile method) and undo it."""
    import numpy as np

    small = img.convert("L")
    small.thumbnail((800, 800))
    ink = Image.fromarray(((np.asarray(small) < 150) * 255).astype("uint8"))
    best_angle, best_score = 0.0, -1.0
    for angle in np.arange(-max_angle, max_angle + 0.01, 0.2):
        profile = np.asarray(ink.rotate(float(angle), resample=Image.NEAREST)).sum(axis=1, dtype=np.float64)
        score = float(np.var(profile))
        if score > best_score:
            best_angle, best_score = float(angle), score
    if abs(best_angle) < 0.3:
        return img
    return img.rotate(best_angle, resample=Image.BICUBIC, expand=True, fillcolor=(255, 255, 255))


# ---------------------------------------------------------------- per format
def parse_file(path: Path, s: Settings, ocr: OcrEngine, on_stage=lambda stage: None) -> list[Page]:
    ext = path.suffix.lower()
    if ext not in SUPPORTED:
        raise ParseError(f"Unsupported file type {ext}")
    if ext == ".pdf":
        return parse_pdf(path, s, ocr, on_stage)
    if ext == ".docx":
        return parse_docx(path)
    if ext in {".png", ".jpg", ".jpeg"}:
        on_stage("ocr")
        try:
            img = prepare_image(Image.open(path))
        except Exception as e:
            raise ParseError(f"Could not open image: {e}") from e
        text, conf = ocr.read(img)
        return [Page(1, text, "ocr", conf)]
    return [Page(1, path.read_text(errors="replace"), "plain")]


def parse_pdf(path: Path, s: Settings, ocr: OcrEngine, on_stage) -> list[Page]:
    import pypdfium2 as pdfium

    try:
        pdf = pdfium.PdfDocument(str(path))
    except Exception as e:
        raise ParseError(f"Could not read PDF (corrupt or password-protected): {e}") from e
    if len(pdf) > s.max_pages:
        raise ParseError(f"PDF has {len(pdf)} pages; the limit is {s.max_pages}")
    pages: list[Page] = []
    for i in range(len(pdf)):
        page = pdf[i]
        text = page.get_textpage().get_text_range().replace("\r\n", "\n").replace("\r", "\n")
        if len(text.strip()) >= s.min_text_chars_per_page:
            pages.append(Page(i + 1, text, "text"))
            continue
        on_stage("ocr")
        img = page.render(scale=200 / 72).to_pil()
        ocr_text, conf = ocr.read(prepare_image(img))
        pages.append(Page(i + 1, ocr_text, "ocr", conf))
    pdf.close()
    return pages


def parse_docx(path: Path) -> list[Page]:
    """Paragraphs and tables in document order. Headings become '## ' lines (used for sections)."""
    import docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    try:
        d = docx.Document(str(path))
    except Exception as e:
        raise ParseError(f"Could not read DOCX: {e}") from e
    lines: list[str] = []
    for block in d.element.body.iterchildren():
        tag = block.tag.rsplit("}", 1)[-1]
        if tag == "p":
            p = Paragraph(block, d)
            text = p.text.strip()
            if not text:
                continue
            style = (p.style.name or "").lower() if p.style is not None else ""
            lines.append(f"## {text}" if style.startswith(("heading", "title")) else text)
        elif tag == "tbl":
            table = Table(block, d)
            lines.append("")
            for row in table.rows:
                cells = []
                for c in row.cells:
                    t = c.text.strip()
                    if not cells or cells[-1] != t:  # merged cells repeat
                        cells.append(t)
                lines.append(" | ".join(cells))
            lines.append("")
    return [Page(1, "\n".join(lines), "docx")]
