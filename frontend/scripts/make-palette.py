"""Derive the whole theme from the brand mark, and prove every pairing is legible.

    ../../env/bin/python frontend/scripts/make-palette.py

`docs/DESIGN.md` requires 4.5:1 on all text because the app is read one-handed in direct
sunlight. That is a measurement, not a matter of taste, so the palette is derived and checked
here rather than picked by eye.

Two brand colours come out of `frontend/brand/app-icon.png`: the navy ground and the green
pin. The navy is an excellent primary at 14.9:1 on white. The green is **not** usable as text
at 2.4:1 - it is kept as a fill and icon accent, and a darkened version of the same hue becomes
the success colour so the family still reads as one.

Neutrals are tinted toward the navy rather than left pure grey, so they look chosen rather
than inherited.
"""

import colorsys
import os
from collections import Counter

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
SOURCE = os.path.join(HERE, "..", "brand", "app-icon.png")

AA = 4.5          # body text
AA_LARGE = 3.0    # 18px+ bold, and non-text boundaries such as borders


# --------------------------------------------------------------------------- colour maths


def to_hex(rgb):
    return "#" + "".join(f"{max(0, min(255, round(c))):02x}" for c in rgb)


def from_hex(value):
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def relative_luminance(rgb):
    channels = []
    for c in rgb:
        c = c / 255
        channels.append(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
    r, g, b = channels
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    la, lb = sorted([relative_luminance(a), relative_luminance(b)], reverse=True)
    return (la + 0.05) / (lb + 0.05)


def with_lightness(rgb, lightness):
    h, _, s = colorsys.rgb_to_hls(*[c / 255 for c in rgb])
    return tuple(c * 255 for c in colorsys.hls_to_rgb(h, lightness, s))


def darken_until(rgb, against, target):
    """Walk a colour's lightness down until it is legible against `against`.

    Keeps the brand's hue and saturation, so the result still belongs to the same family
    rather than being a different colour that happens to pass.
    """
    lightness = colorsys.rgb_to_hls(*[c / 255 for c in rgb])[1]
    while lightness > 0.02:
        candidate = with_lightness(rgb, lightness)
        if contrast(candidate, against) >= target:
            return candidate
        lightness -= 0.005
    return (0, 0, 0)


def tint(toward, amount, base=(255, 255, 255)):
    """Pull a neutral a little toward the brand colour."""
    return tuple(b + (t - b) * amount for b, t in zip(base, toward, strict=True))


def desaturate(rgb, saturation):
    h, l, _ = colorsys.rgb_to_hls(*[c / 255 for c in rgb])
    return tuple(c * 255 for c in colorsys.hls_to_rgb(h, l, saturation))


def semantic(seed, tint_amount):
    """A status colour and the tinted card it sits on.

    Darkened against its **own tint**, not against white. Every one of these is used as text
    inside a card of the same hue - an amber warning on an amber card - and that pairing is
    strictly harder than the same text on white. Checking only against white passed three
    colours here that were illegible where they are actually used.
    """
    soft = tint(seed, tint_amount)
    return darken_until(seed, soft, AA), soft


# --------------------------------------------------------------------------- brand


def brand_colours():
    img = Image.open(SOURCE).convert("RGB")
    w, h = img.size

    pixels = img.load()
    navy = pixels[w // 2, int(h * 0.06)]

    greens = Counter()
    for y in range(h):
        for x in range(w):
            r, g, b = pixels[x, y]
            if g > r + 30 and g > b + 30:
                greens[(r, g, b)] += 1
    return navy, greens.most_common(1)[0][0]


# --------------------------------------------------------------------------- palette


def build():
    navy, green = brand_colours()
    white = (255, 255, 255)

    bg = tint(navy, 0.045)                       # page ground, faintly navy
    surface = white
    line = tint(navy, 0.26)                      # visible as a hairline in sunlight
    ink = with_lightness(navy, 0.10)             # near-black carrying the brand hue

    # Secondary text is a neutral that leans navy, not a blue, and it has to be *lighter*
    # than ink or it is not secondary. Two mistakes to avoid, both made on the way here:
    # keeping the brand's saturation gave a bright #155cb7 that read as a link, and
    # inheriting the navy's own lightness gave #232b36, indistinguishable from body text.
    # So lightness is set deliberately, then only darkened if the page ground demands it.
    muted = darken_until(with_lightness(desaturate(navy, 0.24), 0.36), bg, AA)

    ok, ok_soft = semantic(green, 0.14)
    warn, warn_soft = semantic(from_hex("#d98b0a"), 0.16)
    crit, crit_soft = semantic(from_hex("#d93b36"), 0.14)

    palette = {
        "--bg": bg,
        "--surface": surface,
        "--ink": ink,
        "--muted": muted,
        "--line": line,
        "--primary": navy,
        "--primary-soft": tint(navy, 0.10),      # tinted fill behind navy text
        "--on-primary": white,
        "--accent": green,                       # FILLS AND ICONS ONLY
        "--ok": ok,
        "--ok-soft": ok_soft,
        "--warn": warn,
        "--warn-soft": warn_soft,
        "--crit": crit,
        "--crit-soft": crit_soft,
    }
    return palette, navy, green


# --------------------------------------------------------------------------- checking


def audit(p):
    """Every pairing the UI actually renders. A palette that passes in the abstract and
    fails on a real card is not a palette that passes."""
    checks = [
        ("body text on page", p["--ink"], p["--bg"], AA),
        ("body text on card", p["--ink"], p["--surface"], AA),
        ("secondary on page", p["--muted"], p["--bg"], AA),
        ("secondary on card", p["--muted"], p["--surface"], AA),
        ("primary button label", p["--on-primary"], p["--primary"], AA),
        ("navy text on card", p["--primary"], p["--surface"], AA),
        ("navy text on tinted fill", p["--primary"], p["--primary-soft"], AA),
        ("success text on card", p["--ok"], p["--surface"], AA),
        ("success on its own tint", p["--ok"], p["--ok-soft"], AA),
        ("warning text on card", p["--warn"], p["--surface"], AA),
        ("warning on its own tint", p["--warn"], p["--warn-soft"], AA),
        ("critical text on card", p["--crit"], p["--surface"], AA),
        ("critical on its own tint", p["--crit"], p["--crit-soft"], AA),
        ("accent fill on navy", p["--accent"], p["--primary"], AA_LARGE),
        ("border against page", p["--line"], p["--bg"], 1.3),
        ("card edge against page", p["--surface"], p["--bg"], 1.05),
    ]

    failures = 0
    print(f"  {'pairing':<30} {'ratio':>7}  need")
    print("  " + "-" * 50)
    for label, fg, bg, need in checks:
        ratio = contrast(fg, bg)
        ok = ratio >= need
        failures += 0 if ok else 1
        mark = " " if ok else "  <-- FAILS"
        print(f"  {label:<30} {ratio:>6.2f}:1  {need}{mark}")
    return failures


def main():
    palette, navy, green = build()

    print("Palette derived from the brand mark")
    print("=" * 56)
    print(f"  brand navy   {to_hex(navy)}")
    print(f"  brand green  {to_hex(green)}   "
          f"{contrast(green, (255, 255, 255)):.2f}:1 on white - accent only, never text")
    print()

    for token, rgb in palette.items():
        print(f"  {token:<16} {to_hex(rgb)}")

    print()
    print("Contrast audit")
    print("=" * 56)
    failures = audit(palette)

    print()
    if failures:
        print(f"  {failures} pairing(s) fail. The palette is not usable as it stands.")
        raise SystemExit(1)
    print("  Every pairing passes.")

    print()
    print("CSS block")
    print("=" * 56)
    for token, rgb in palette.items():
        print(f"  {token}: {to_hex(rgb)};")


if __name__ == "__main__":
    main()
