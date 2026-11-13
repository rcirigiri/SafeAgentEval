"""Generate the author card shown at the bottom of the README.

Renders docs/assets/brand/author-card.png (1600x560) in the brand
colours. Re-run after changing the author name or contact address.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "assets" / "brand" / "author-card.png"
ICON = ROOT / "docs" / "assets" / "brand" / "safeagenteval-icon-dark.png"

W, H = 1600, 560
NAVY = (11, 60, 108)       # #0B3C6C
DARK = (8, 32, 56)         # #082038
TEAL = (15, 163, 168)      # #0FA3A8
WHITE = (255, 255, 255)
MUTED = (178, 205, 228)


def font(name: str, size: int) -> ImageFont.FreeTypeFont:
    candidates = [
        Path(r"C:\Windows\Fonts") / name,
        Path("/usr/share/fonts/truetype/dejavu") / name.replace("arial", "DejaVuSans"),
    ]
    for path in candidates:
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default(size=size)


def main() -> None:
    img = Image.new("RGB", (W, H), DARK)
    draw = ImageDraw.Draw(img, "RGBA")

    # Teal ledger block accent along the left edge.
    draw.rectangle([0, 0, 18, H], fill=TEAL)

    # Project mark.
    if ICON.exists():
        icon = Image.open(ICON).convert("RGBA")
        icon.thumbnail((220, 220))
        img.paste(icon, (90, (H - icon.height) // 2), icon)

    x = 380
    draw.text((x, 92), "AUTHOR", font=font("arialbd.ttf", 34), fill=TEAL)
    draw.text(
        (x, 148),
        "Rammohan Srikanth Cirigiri",
        font=font("arialbd.ttf", 68),
        fill=WHITE,
    )
    draw.text(
        (x, 248),
        "Creator & maintainer, SafeAgentEval",
        font=font("arial.ttf", 40),
        fill=MUTED,
    )
    draw.rounded_rectangle([x, 330, x + 660, 404], radius=18, outline=TEAL, width=3)
    draw.text(
        (x + 28, 348),
        "ram.cirigiri@gmail.com",
        font=font("arial.ttf", 38),
        fill=WHITE,
    )
    draw.text(
        (x, 452),
        "SafeAgentEval - State-Verified Agent Safety",
        font=font("arial.ttf", 34),
        fill=MUTED,
    )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT, optimize=True)
    print(f"wrote {OUT} ({W}x{H})")


if __name__ == "__main__":
    main()
