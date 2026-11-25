import os
from pathlib import Path
from typing import List, Optional
from PIL import Image, ImageDraw, ImageFont
import pypdf
from app.core.config import settings


def _make_info_placeholder(
    output_path: str,
    pdf_filename: str,
    page_num: int,
    total_pages: int,
    width: int = 1200,
    height: int = 1600,
) -> None:
    """
    Generates an informative placeholder PNG when pdf2image/Poppler is unavailable
    or the PDF is a stub. Shows the paper name, page number, and a clear message
    instead of a blank white image that confuses users.
    """
    # Background: dark navy to distinguish from real content
    bg_color = (15, 23, 42)      # slate-950
    accent    = (34, 211, 238)   # cyan-400
    text_col  = (226, 232, 240)  # slate-200
    muted     = (100, 116, 139)  # slate-500
    border    = (30, 41, 59)     # slate-800

    img = Image.new("RGB", (width, height), color=bg_color)
    draw = ImageDraw.Draw(img)

    # Try to load a system font; fall back to default if unavailable
    def _font(size: int):
        for name in ["arial.ttf", "DejaVuSans.ttf", "LiberationSans-Regular.ttf"]:
            try:
                return ImageFont.truetype(name, size)
            except Exception:
                pass
        return ImageFont.load_default()

    title_font  = _font(42)
    label_font  = _font(28)
    small_font  = _font(22)

    # Border frame
    margin = 60
    draw.rectangle([margin, margin, width - margin, height - margin],
                   outline=border, width=3)

    # Top accent bar
    draw.rectangle([margin, margin, width - margin, margin + 6], fill=accent)

    # Document icon area
    icon_y = 200
    icon_x = width // 2 - 60
    draw.rectangle([icon_x, icon_y, icon_x + 120, icon_y + 150],
                   outline=accent, width=3, fill=(22, 33, 62))
    # Folded corner
    draw.polygon(
        [icon_x + 80, icon_y, icon_x + 120, icon_y + 40, icon_x + 80, icon_y + 40],
        fill=accent,
    )
    # Lines inside icon
    for li, ly in enumerate(range(icon_y + 60, icon_y + 140, 18)):
        lw = 80 if li % 3 != 2 else 50
        draw.rectangle([icon_x + 15, ly, icon_x + 15 + lw, ly + 6], fill=muted)

    # "Page Preview Unavailable" label
    msg = "Page Preview Unavailable"
    draw.text((width // 2, icon_y + 190), msg, fill=accent,
              font=title_font, anchor="mm")

    # Separator line
    sep_y = icon_y + 240
    draw.line([(margin + 40, sep_y), (width - margin - 40, sep_y)], fill=border, width=2)

    # Paper filename
    clean_name = pdf_filename.replace("_", " ").replace("-", " ").title()
    # Wrap long names
    max_chars = 48
    if len(clean_name) > max_chars:
        clean_name = clean_name[:max_chars].rsplit(" ", 1)[0] + "…"
    draw.text((width // 2, sep_y + 50), clean_name, fill=text_col,
              font=label_font, anchor="mm")

    # Page info
    page_info = f"Page {page_num} of {total_pages}"
    draw.text((width // 2, sep_y + 100), page_info, fill=muted,
              font=small_font, anchor="mm")

    # Explanation box
    box_y = sep_y + 160
    draw.rectangle([margin + 40, box_y, width - margin - 40, box_y + 180],
                   fill=(22, 33, 62), outline=border, width=1)
    explanation = (
        "PDF rendering requires Poppler.\n"
        "Install: https://github.com/oschwartz10612/poppler-windows\n"
        "Then add Poppler bin/ to PATH and re-run:\n"
        "  python scripts/ingest_papers_lightweight.py"
    )
    draw.text((width // 2, box_y + 90), explanation, fill=muted,
              font=small_font, anchor="mm", align="center")

    # Bottom footer
    footer_y = height - margin - 40
    draw.text((width // 2, footer_y),
              "DiaDoc AI · ColPali Vision · PaliGemma 2 Late-Interaction Retrieval",
              fill=border, font=small_font, anchor="mm")

    img.save(output_path, "PNG")


def render_pdf_to_images(pdf_path: str, output_dir: Optional[str] = None, dpi: int = 200) -> List[str]:
    """
    Renders PDF pages as high-resolution images for ColPali indexing and VLM evaluation.
    Returns a list of absolute file paths to the generated image files.

    Rendering priority:
      1. PyMuPDF (fitz) — already installed, NO Poppler required, fast, high quality
      2. pdf2image + Poppler — fallback if fitz somehow fails
      3. Informative placeholder image — dark-themed card with paper name + instructions
    """
    if output_dir is None:
        output_dir = settings.RENDERED_PAGES_DIR

    os.makedirs(output_dir, exist_ok=True)
    pdf_filename = Path(pdf_path).stem
    image_paths = []

    # ── Primary: PyMuPDF (fitz) — no external dependency ────────────────────
    try:
        import fitz  # type: ignore  (PyMuPDF — already in requirements.txt)
        doc = fitz.open(pdf_path)
        mat = fitz.Matrix(dpi / 72, dpi / 72)  # scale from 72dpi baseline

        for page_idx in range(len(doc)):
            page_num = page_idx + 1
            img_name = f"{pdf_filename}_page_{page_num}.png"
            img_path = os.path.join(output_dir, img_name)
            pix = doc[page_idx].get_pixmap(matrix=mat, alpha=False)
            pix.save(img_path)
            image_paths.append(os.path.abspath(img_path))

        doc.close()
        if image_paths:
            return image_paths

    except Exception as fitz_err:
        print(f"[Warning] PyMuPDF render failed ({fitz_err}). Trying pdf2image...")

    # ── Secondary: pdf2image via Poppler ─────────────────────────────────────
    try:
        from pdf2image import convert_from_path
        images = convert_from_path(pdf_path, dpi=dpi)

        for idx, img in enumerate(images):
            page_num = idx + 1
            img_name = f"{pdf_filename}_page_{page_num}.png"
            img_path = os.path.join(output_dir, img_name)
            img.save(img_path, "PNG")
            image_paths.append(os.path.abspath(img_path))

        if image_paths:
            return image_paths

    except Exception as pdf2img_err:
        print(f"[Warning] pdf2image also failed ({pdf2img_err}). Using placeholder.")

    # ── Last resort: informative placeholder (never blank white) ─────────────
    try:
        reader = pypdf.PdfReader(pdf_path)
        total_pages = len(reader.pages)
    except Exception:
        total_pages = 1

    for idx in range(total_pages):
        page_num = idx + 1
        img_name = f"{pdf_filename}_page_{page_num}.png"
        img_path = os.path.join(output_dir, img_name)
        _make_info_placeholder(
            output_path=img_path,
            pdf_filename=pdf_filename,
            page_num=page_num,
            total_pages=total_pages,
        )
        image_paths.append(os.path.abspath(img_path))

    return image_paths



def get_pdf_page_count(pdf_path: str) -> int:
    """Returns total number of pages in a PDF file."""
    reader = pypdf.PdfReader(pdf_path)
    return len(reader.pages)

