"""Derive every app icon from the one brand file.

    ../../env/bin/python frontend/scripts/make-icons.py

Source of truth is `frontend/brand/app-icon.png`. Nothing here is drawn by hand, so the icon
on a rep's home screen and the icon in the brand folder can never drift apart - replace that
one file, re-run this, rebuild, and every size follows.

Why each output exists:

  icon-192 / icon-512      Chrome will not offer "Install" without both. Missing them is why
                           the app could only ever be a browser shortcut.
  icon-maskable-*          Android crops icons to the launcher's own shape. A non-maskable
                           icon gets a white box drawn behind it first; a maskable one must
                           keep its artwork inside the middle 80%, because the corners will
                           be cut off. So these are full-bleed navy with the mark shrunk in.
  apple-touch-icon         iOS ignores the manifest completely and applies its own rounding,
                           so this one is flattened onto navy with no transparency - a
                           transparent PNG renders black on an iPhone home screen.
  favicon                  The browser tab.
"""

import os

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
FRONTEND = os.path.abspath(os.path.join(HERE, ".."))
SOURCE = os.path.join(FRONTEND, "brand", "app-icon.png")
OUT = os.path.join(FRONTEND, "public")

# Android's maskable safe zone is a circle across the middle of the canvas - guaranteed only
# to the inner two thirds. Launchers crop to their own shape, so a mark sized to the very edge
# of the allowance gets clipped on the roundest of them, and a clipped logo reads as a broken
# app. 70% is the usual compromise: comfortably inside the circle, still filling the tile.
SAFE_ZONE = 0.70

# Band around the canvas edge ignored when locating the mark. See mark_only().
EDGE_BAND = 0.06


def load():
    if not os.path.exists(SOURCE):
        raise SystemExit(
            f"No brand icon at {SOURCE}.\n"
            f"Put the master PNG there (square, at least 512x512) and run this again."
        )
    img = Image.open(SOURCE).convert("RGBA")
    if img.width != img.height:
        raise SystemExit(f"The brand icon must be square; this one is {img.width}x{img.height}.")
    if img.width < 512:
        raise SystemExit(f"The brand icon must be at least 512px; this one is {img.width}px.")
    return img


def brand_colour(img):
    """The mark's own background, read from the art rather than hard-coded.

    Sampled just inside the top edge at the horizontal centre - past the rounded corner, but
    above the lettering. Replacing the brand file therefore also updates the colour the
    maskable icons bleed to.
    """
    w, h = img.size
    r, g, b, a = img.getpixel((w // 2, int(h * 0.06)))
    return (r, g, b) if a > 250 else (9, 41, 82)


def resized(img, size):
    return img.resize((size, size), Image.LANCZOS)


def luminance(r, g, b):
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def mark_only(img, background, margin=45):
    """Just the F and the pin, cut away from the rounded square they sit on.

    Pasting the whole source onto a flat field leaves a visible seam - the brand navy carries
    a slight gradient and a soft shadow, so the original rounded square reads as an icon
    inside an icon. That is precisely the artefact maskable icons exist to avoid. Cropping to
    the artwork's own bounding box removes the square entirely and lets the launcher supply
    the only shape on screen.

    Brightness is what separates mark from ground here, not colour distance: the square's own
    edge shading and drop shadow sit far from the sampled navy in RGB terms and were dragging
    the bounding box back out to the full canvas. The mark is white and green on a dark
    ground, so everything that belongs to it is markedly *lighter* than the ground.

    The outer few percent is skipped too. The square is drawn with an anti-aliased highlight
    along its edge, bright enough to pass the luminance test and close enough to the green pin
    that no threshold separates them. No app icon puts its artwork against the bleed, so
    ignoring that band costs nothing and is simpler than trying to describe the highlight.
    """
    pixels = img.load()
    w, h = img.size
    floor = luminance(*background) + margin
    border_x, border_y = int(w * EDGE_BAND), int(h * EDGE_BAND)
    left, top, right, bottom = w, h, 0, 0

    for y in range(border_y, h - border_y):
        for x in range(border_x, w - border_x):
            r, g, b, a = pixels[x, y]
            if a < 128 or luminance(r, g, b) < floor:
                continue
            left, top = min(left, x), min(top, y)
            right, bottom = max(right, x), max(bottom, y)

    if right <= left or bottom <= top:
        return img          # nothing stood out from the ground; use the art as it is
    return img.crop((left, top, right + 1, bottom + 1))


def maskable(mark, size, background):
    """Full-bleed background with the mark centred inside the safe zone."""
    canvas = Image.new("RGBA", (size, size), (*background, 255))
    budget = int(size * SAFE_ZONE)
    scale = budget / max(mark.size)
    inner = mark.resize(
        (max(1, round(mark.width * scale)), max(1, round(mark.height * scale))), Image.LANCZOS
    )
    canvas.paste(inner, ((size - inner.width) // 2, (size - inner.height) // 2), inner)
    return canvas


def flattened(img, size, background):
    """No alpha channel: iOS renders a transparent home-screen icon as black."""
    canvas = Image.new("RGB", (size, size), background)
    scaled = resized(img, size)
    canvas.paste(scaled, (0, 0), scaled)
    return canvas


def main():
    source = load()
    background = brand_colour(source)
    mark = mark_only(source, background)
    os.makedirs(OUT, exist_ok=True)

    print(f"  source     {os.path.relpath(SOURCE, FRONTEND)}  "
          f"{source.width}x{source.height}")
    print(f"  brand      #{''.join(f'{c:02x}' for c in background)}")
    print(f"  mark       {mark.width}x{mark.height} cut from the square")
    print()

    written = []

    def save(image, name):
        path = os.path.join(OUT, name)
        image.save(path, "PNG", optimize=True)
        written.append((name, os.path.getsize(path)))

    for size in (192, 512):
        save(resized(source, size), f"icon-{size}.png")
        save(maskable(mark, size, background), f"icon-maskable-{size}.png")

    save(flattened(source, 180, background), "apple-touch-icon.png")
    save(resized(source, 64), "favicon.png")

    for name, size in written:
        print(f"  {size:>7,} B  public/{name}")


if __name__ == "__main__":
    main()
