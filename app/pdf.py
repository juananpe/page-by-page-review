"""Rasterise PDF pages to JPEG and pull the text layer, if there is one."""
from __future__ import annotations

import io
import re
from dataclasses import dataclass, field

import pypdfium2 as pdfium


@dataclass
class RenderedPage:
    number: int          # 1-based
    jpeg: bytes          # for the browser and for the model
    text: str            # text layer, "" for scanned pages
    width: int
    height: int


@dataclass
class RenderResult:
    pages: list[RenderedPage] = field(default_factory=list)
    truncated_at: int | None = None   # set when the PDF was longer than max_pages


def render_pdf(
    data: bytes,
    max_pages: int = 60,
    target_width: int = 1000,
    quality: int = 62,
) -> RenderResult:
    """Render every page to a JPEG about `target_width` px wide.

    pypdfium2 ships its own PDFium binary, so no poppler or system packages
    are needed — `pip install` is the whole setup.
    """
    doc = pdfium.PdfDocument(data)
    try:
        total = len(doc)
        limit = min(total, max_pages)
        out = RenderResult(truncated_at=limit if total > limit else None)

        for i in range(limit):
            page = doc[i]
            # PDF user units are 1/72 inch; scale so the raster lands near target_width.
            scale = max(0.5, min(3.0, target_width / max(1.0, page.get_width())))
            bitmap = page.render(scale=scale)
            pil = bitmap.to_pil().convert("RGB")

            buf = io.BytesIO()
            pil.save(buf, "JPEG", quality=quality, optimize=True, progressive=True)

            text = ""
            try:
                textpage = page.get_textpage()
                text = textpage.get_text_bounded() or ""
                textpage.close()
            except Exception:
                pass  # image-only page: the model still gets the raster

            out.pages.append(
                RenderedPage(
                    number=i + 1,
                    jpeg=buf.getvalue(),
                    text=_tidy(text),
                    width=pil.width,
                    height=pil.height,
                )
            )
            page.close()

        return out
    finally:
        doc.close()


_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _tidy(text: str, limit: int = 12000) -> str:
    # PDFium emits control bytes for some ligatures and soft hyphens.
    text = _CTRL.sub("", text.replace("\r\n", "\n").replace("\u00ad", ""))
    lines = [ln.rstrip() for ln in text.split("\n")]
    cleaned = "\n".join(ln for ln in lines if ln.strip())
    return cleaned[:limit]
