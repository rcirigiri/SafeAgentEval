"""Generate the LinkedIn banner (1584x396).

Leads with the two facts a visitor should get in one glance: the project
is open source (Apache-2.0), and it grades agents against recorded system
state rather than their own statements. Text starts right of x=330 so
LinkedIn's profile-photo overlap (bottom left) never covers it.
Re-run after changing the tagline or repository address.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "assets" / "brand" / "agenticsafetyeval-linkedin-banner.png"
ICON = ROOT / "docs" / "assets" / "brand" / "agenticsafetyeval-icon-dark.png"

W, H = 1584, 396
NAVY = (11, 60, 108)  # #0B3C6C
TEAL = (53, 196, 200)  # brightened #0FA3A8 for dark backgrounds
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
    img = Image.new("RGB", (W, H), NAVY)
    draw = ImageDraw.Draw(img, "RGBA")

    # Project mark, right of the LinkedIn profile-photo safe zone.
    if ICON.exists():
        icon = Image.open(ICON).convert("RGBA")
        icon.thumbnail((256, 256))
        img.paste(icon, (350, (H - icon.height) // 2), icon)

    x = 650
    # Open-source pill: the first thing read, before the wordmark.
    pill_font = font("arialbd.ttf", 22)
    pill_text = "OPEN SOURCE  ·  APACHE-2.0"
    tw = draw.textbbox((0, 0), pill_text, font=pill_font)[2]
    draw.rounded_rectangle([x, 52, x + tw + 44, 98], radius=23, outline=TEAL, width=2)
    draw.text((x + 22, 62), pill_text, font=pill_font, fill=TEAL)

    draw.text((x, 116), "AgenticSafetyEval", font=font("arialbd.ttf", 66), fill=WHITE)
    draw.text(
        (x, 204),
        "Open-source, state-verified agent safety evaluation",
        font=font("arialbd.ttf", 31),
        fill=TEAL,
    )
    draw.text(
        (x, 252),
        "State-verified safety evaluation for black-box AI agents.",
        font=font("arial.ttf", 27),
        fill=WHITE,
    )
    draw.text(
        (x, 312),
        "github.com/rcirigiri/agentic-safety-eval",
        font=font("arial.ttf", 24),
        fill=MUTED,
    )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT, optimize=True)
    print(f"wrote {OUT} ({W}x{H})")


if __name__ == "__main__":
    main()
