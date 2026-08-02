#!/usr/bin/env python3
"""Build Graphify favicon and social metadata images from brand sources."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
PUBLIC = ROOT / "public"
DESIGN_ASSETS = ROOT / "design-assets"

BACKGROUND_PATH = DESIGN_ASSETS / "og-graph-background.png"
MARK_PATH = PUBLIC / "graphify-mark.png"

OG_SIZE = (1200, 630)
ICON_SIZE = (512, 512)
APPLE_ICON_SIZE = (180, 180)
FAVICON_SIZES = (16, 32, 48)

INK = "#FFFFFF"
BACKGROUND = "#09090B"


def font(size: int, *, mono: bool = False) -> ImageFont.FreeTypeFont:
    # Next bundles Geist locally, keeping this generator portable and offline-safe.
    # The mono flag is retained to document the eyebrow's intended typographic role.
    _ = mono
    path = ROOT / "node_modules/next/dist/compiled/@vercel/og/Geist-Regular.ttf"
    return ImageFont.truetype(path, size=size)


def contain(image: Image.Image, bounds: tuple[int, int]) -> Image.Image:
    copy = image.copy()
    copy.thumbnail(bounds, Image.Resampling.LANCZOS)
    return copy


def build_icon_canvas() -> Image.Image:
    canvas = Image.new("RGBA", ICON_SIZE, BACKGROUND)

    glow = Image.new("RGBA", ICON_SIZE, (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)
    glow_draw.ellipse((86, 126, 426, 466), fill=(16, 185, 129, 54))
    glow = glow.filter(ImageFilter.GaussianBlur(74))
    canvas.alpha_composite(glow)

    mark = Image.open(MARK_PATH).convert("RGBA")
    alpha_box = mark.getchannel("A").getbbox()
    if alpha_box:
        mark = mark.crop(alpha_box)
    mark = contain(mark, (408, 408))
    position = ((ICON_SIZE[0] - mark.width) // 2, (ICON_SIZE[1] - mark.height) // 2)
    canvas.alpha_composite(mark, position)
    return canvas


def build_icons() -> None:
    icon = build_icon_canvas()
    icon.save(APP / "icon.png", optimize=True)
    icon.resize(APPLE_ICON_SIZE, Image.Resampling.LANCZOS).convert("RGB").save(
        APP / "apple-icon.png", format="PNG", optimize=True
    )
    icon.save(
        APP / "favicon.ico",
        format="ICO",
        sizes=[(size, size) for size in FAVICON_SIZES],
    )


def fit_cover(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    scale = max(size[0] / image.width, size[1] / image.height)
    resized = image.resize(
        (round(image.width * scale), round(image.height * scale)),
        Image.Resampling.LANCZOS,
    )
    left = (resized.width - size[0]) // 2
    top = (resized.height - size[1]) // 2
    return resized.crop((left, top, left + size[0], top + size[1]))


def build_open_graph() -> None:
    background = Image.open(BACKGROUND_PATH).convert("RGB")
    canvas = fit_cover(background, OG_SIZE)
    canvas = ImageEnhance.Contrast(canvas).enhance(1.06)

    # Preserve the generated graph while guaranteeing readable copy on every card crop.
    veil = Image.new("RGBA", OG_SIZE, (0, 0, 0, 0))
    pixels = veil.load()
    for x in range(760):
        strength = round(184 * (1 - (x / 760) ** 2.3))
        for y in range(OG_SIZE[1]):
            pixels[x, y] = (9, 9, 11, strength)
    canvas = Image.alpha_composite(canvas.convert("RGBA"), veil)

    draw = ImageDraw.Draw(canvas)
    margin_x = 72

    mark = Image.open(MARK_PATH).convert("RGBA")
    alpha_box = mark.getchannel("A").getbbox()
    if alpha_box:
        mark = mark.crop(alpha_box)
    mark = contain(mark, (90, 64))
    canvas.alpha_composite(mark, (margin_x, 65))
    draw.text((margin_x + 108, 72), "graphify", font=font(37), fill=INK)

    draw.text(
        (margin_x, 206),
        "GRAPH-AWARE CLOUD ENGINEERING",
        font=font(16, mono=True),
        fill=INK,
        stroke_width=0,
    )
    draw.text((margin_x, 249), "Understand your code.", font=font(54), fill=INK)
    draw.text((margin_x, 313), "Ship with confidence.", font=font(54), fill=INK)
    draw.text(
        (margin_x, 411),
        "Explore architecture, edit source, and turn agent proposals",
        font=font(23),
        fill=INK,
    )
    draw.text(
        (margin_x, 445),
        "into reviewable pull requests — in one cloud workspace.",
        font=font(23),
        fill=INK,
    )

    # JPEG is broadly supported and keeps the social payload comfortably small.
    canvas.convert("RGB").save(
        APP / "opengraph-image.jpg",
        format="JPEG",
        quality=88,
        optimize=True,
        progressive=True,
        subsampling="4:2:0",
    )


def main() -> None:
    if not BACKGROUND_PATH.exists():
        raise FileNotFoundError(f"Missing Imagen background: {BACKGROUND_PATH}")
    build_icons()
    build_open_graph()
    print("Generated Graphify favicon, app icons, and Open Graph image.")


if __name__ == "__main__":
    main()
