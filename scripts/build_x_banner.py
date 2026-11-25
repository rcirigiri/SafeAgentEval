"""Generate the X (Twitter) profile banner (3000x1000, 2x of 1500x500).

Why not reuse the LinkedIn banner? X banners are 3:1, LinkedIn's is 4:1,
so X centre-crops it and cuts text at the right edge. X also overlaps a
large profile photo at the bottom left (proportionally larger on mobile),
so every essential element here sits right of x=400 in the 1500-wide
logical layout; only a faint watermark mark occupies the overlap zone.

Leads with the two facts a visitor should get in one glance: the project
is open source (Apache-2.0), and it grades agents against recorded system
state rather than their own statements.
Re-run after changing the tagline or repository address.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
BRAND = ROOT / "docs" / "assets" / "brand"
OUT = BRAND / "agenticsafetyeval-x-banner.png"  # 3000x1000, upload this one
OUT_1X = BRAND / "agenticsafetyeval-x-banner-1500.png"  # 1500x500 fallback
PREVIEW = BRAND / "agenticsafetyeval-x-banner-preview.png"  # avatar mock, do not upload
ICON = BRAND / "agenticsafetyeval-icon-dark.png"

S = 2  # supersample: logical canvas is 1500x500
W, H = 1500 * S, 500 * S
NAVY = (11, 60, 108)  # #0B3C6C
DARK = (6, 26, 46)  # deeper than brand #082038, for the right-hand falloff
TEAL = (53, 196, 200)  # brightened #0FA3A8 for dark backgrounds
TEAL_DEEP = (15, 163, 168)  # #0FA3A8
WHITE = (255, 255, 255)
MUTED = (178, 205, 228)


def font(name: str, size: int) -> ImageFont.FreeTypeFont:
    candidates = [
        Path(r"C:\Windows\Fonts") / name,
        Path("/usr/share/fonts/truetype/dejavu") / name.replace("arial", "DejaVuSans"),
        Path("/usr/share/fonts/truetype/dejavu") / name.replace("arialbd", "DejaVuSans-Bold"),
    ]
    for path in candidates:
        if path.exists():
            return ImageFont.truetype(str(path), size * S)
    return ImageFont.load_default(size=size * S)


def gradient() -> Image.Image:
    """Navy (left) to dark (right), with a soft teal glow at top right."""
    base = Image.new("RGB", (W, H))
    px = base.load()
    for x in range(W):
        t = x / W
        r = round(NAVY[0] + (DARK[0] - NAVY[0]) * t)
        g = round(NAVY[1] + (DARK[1] - NAVY[1]) * t)
        b = round(NAVY[2] + (DARK[2] - NAVY[2]) * t)
        for y in range(H):
            px[x, y] = (r, g, b)
    glow = Image.new("RGB", (W, H), (0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse([W * 0.62, -H * 0.55, W * 1.15, H * 0.45], fill=(10, 70, 74))
    glow = glow.filter(ImageFilter.GaussianBlur(180 * S // 2))
    return Image.blend(base, Image.blend(base, glow, 0.55), 0.6)


def paste_icon(img: Image.Image, box: tuple[int, int, int], alpha: int = 255) -> None:
    icon = Image.open(ICON).convert("RGBA")
    icon = icon.crop(icon.getbbox())
    size = box[2]
    icon.thumbnail((size * S, size * S), Image.LANCZOS)
    if alpha < 255:
        a = icon.getchannel("A").point(lambda v: v * alpha // 255)
        icon.putalpha(a)
    img.paste(icon, (box[0] * S, box[1] * S), icon)


def main() -> None:
    img = gradient()
    draw = ImageDraw.Draw(img, "RGBA")

    # --- Decoration that is safe to be covered / cropped -----------------
    # Faint watermark mark in the profile-photo overlap zone (bottom left).
    paste_icon(img, (-55, 118, 330), alpha=26)
    # Dot grid, top-left corner.
    for row in range(5):
        for col in range(9):
            cx, cy = (26 + col * 26) * S, (26 + row * 26) * S
            draw.ellipse([cx - 3 * S, cy - 3 * S, cx + 3 * S, cy + 3 * S],
                         fill=(*TEAL, 70))
    # Faint ledger lines, far right edge (pure decoration).
    for i, y in enumerate((64, 104, 144)):
        draw.rounded_rectangle(
            [(1332) * S, y * S, (1468 - (i % 2) * 34) * S, (y + 13) * S],
            radius=6 * S, fill=(*WHITE, 26))
    # Teal baseline.
    draw.rectangle([0, H - 6 * S, W, H], fill=TEAL_DEEP)

    # --- Main lockup, right of the profile-photo safe zone (x >= 400) ----
    paste_icon(img, (412, 143, 214))
    x = 668

    # Open-source pill: the first thing read, before the wordmark.
    pill_font = font("arialbd.ttf", 20)
    pill_text = "OPEN SOURCE  ·  APACHE-2.0"
    tw = draw.textbbox((0, 0), pill_text, font=pill_font)[2]
    draw.rounded_rectangle(
        [x * S, 94 * S, x * S + tw + 42 * S, 138 * S],
        radius=22 * S, outline=TEAL, width=2 * S)
    draw.text(((x + 21) * S, 105 * S), pill_text, font=pill_font, fill=TEAL)

    # Wordmark: white, with "Record" in teal (matches the horizontal logo).
    title_font = font("arialbd.ttf", 64)
    draw.text((x * S, 156 * S), "AgentSafety", font=title_font, fill=WHITE)
    w1 = draw.textbbox((0, 0), "AgentSafety", font=title_font)[2]
    draw.text((x * S + w1, 156 * S), "Record", font=title_font, fill=TEAL)

    draw.text(
        (x * S, 246 * S),
        "State-verified agent safety evaluation",
        font=font("arialbd.ttf", 30),
        fill=TEAL,
    )
    # Accent rule.
    draw.rounded_rectangle(
        [x * S, 300 * S, (x + 58) * S, 306 * S], radius=3 * S, fill=TEAL)
    draw.text(
        (x * S, 320 * S),
        "Grading what the system recorded, not what the agent said.",
        font=font("arial.ttf", 24),
        fill=WHITE,
    )
    draw.text(
        (x * S, 372 * S),
        "github.com/rcirigiri/agentic-safety-eval",
        font=font("arial.ttf", 22),
        fill=MUTED,
    )

    BRAND.mkdir(parents=True, exist_ok=True)
    img.save(OUT, optimize=True)
    img.resize((1500, 500), Image.LANCZOS).save(OUT_1X, optimize=True)

    # --- Preview: simulate the X profile-photo overlap (do not upload) ---
    prev = img.resize((1500, 500), Image.LANCZOS)
    pd = ImageDraw.Draw(prev, "RGBA")
    # Desktop/mobile profile photo sits bottom-left, overlapping the banner.
    cx, cy, r = 148, 468, 108
    pd.ellipse([cx - r - 5, cy - r - 5, cx + r + 5, cy + r + 5], fill=(0, 0, 0))
    pd.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(210, 220, 230))
    pd.text((cx, cy - 14), "PROFILE", font=font("arialbd.ttf", 13), fill=NAVY, anchor="ma")
    pd.text((cx, cy + 12), "PHOTO", font=font("arialbd.ttf", 13), fill=NAVY, anchor="ma")
    prev.convert("RGB").save(PREVIEW, optimize=True)

    print(f"wrote {OUT} ({W}x{H})")
    print(f"wrote {OUT_1X} (1500x500)")
    print(f"wrote {PREVIEW} (preview only)")


if __name__ == "__main__":
    main()
