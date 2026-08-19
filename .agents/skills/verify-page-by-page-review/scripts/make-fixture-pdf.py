#!/usr/bin/env python3
"""Create a deterministic two-page image-only PDF for local UI verification."""

from pathlib import Path
import sys

from PIL import Image, ImageDraw


def page(number: int, title: str, lines: list[str]) -> Image.Image:
    image = Image.new("RGB", (1000, 1400), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((55, 55, 945, 1345), outline="black", width=4)
    draw.text((90, 90), f"Verification paper — page {number}", fill="black")
    draw.text((90, 160), title, fill="black")
    y = 250
    for line in lines:
        draw.text((100, y), line, fill="black")
        y += 70
    draw.text((90, 1260), "Generated locally; no personal or external data.", fill="black")
    return image


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: make-fixture-pdf.py OUTPUT.pdf")
    output = Path(sys.argv[1]).resolve()
    if output.suffix.lower() != ".pdf":
        raise SystemExit("output must end in .pdf")
    output.parent.mkdir(parents=True, exist_ok=True)
    pages = [
        page(1, "Summary", ["Sample size: 12", "Reported total: 13", "Purpose: test streamed review output."]),
        page(2, "Results", ["Sample size: 12", "Table total: 12", "Purpose: test cross-page findings and navigation."]),
    ]
    pages[0].save(output, "PDF", save_all=True, append_images=pages[1:], resolution=100.0)
    print(output)


if __name__ == "__main__":
    main()
