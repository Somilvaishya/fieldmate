"""Check the app against the constraints in docs/DESIGN.md.

    ../../env/bin/python frontend/scripts/check-design.py

Design tools produce attractive screens that quietly break field constraints - icon fonts,
smaller text, colours outside the audited palette, animation that never stops, and copy that
claims things the software does not do. This greps source and build for the ones that can be
checked mechanically, so a regression shows up here rather than on a phone in a market.

Run it after translating every screen that comes back from a design tool.
"""

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
FRONTEND = os.path.abspath(os.path.join(HERE, ".."))
SRC = os.path.join(FRONTEND, "src")
DIST = os.path.abspath(os.path.join(FRONTEND, "..", "fieldmate", "public", "pwa"))

# Everything in the audited palette, plus the two shorthands.
ALLOWED_LITERALS = {
    "#f4f5f7", "#ffffff", "#05172e", "#465972", "#bfc7d2",
    "#092850", "#e6eaee", "#3bbf62",
    "#277d40", "#e4f6e9", "#955f07", "#f9ecd8", "#c62a25", "#fae4e3",
    "#fff", "#000",
}

# Security words the UI must not use, because nothing in the app does them. The Dexie store
# is plain IndexedDB; SECURITY.md calls mirrored device data a disclosure surface. A design
# export offered "All 4 records stored locally and encrypted", which would be a lie told to
# a rep about their own data.
FALSE_CLAIMS = ("encrypted", "encryption", "end-to-end", "bank-grade", "military")

failures = []


def check(label, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    if detail:
        print(f"         {detail}")
    if not ok:
        failures.append(label)


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def without_comments(text):
    """Strip comments before checking what the UI says.

    The checks below are about text a rep can see. A comment explaining *why* the app avoids
    a word is not the app using it, and flagging it trains people to ignore the checker.
    """
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"(?m)^\s*//.*$", "", text)


def sources():
    out = []
    for root, _dirs, names in os.walk(SRC):
        out += [os.path.join(root, n) for n in names if n.endswith((".vue", ".css", ".js"))]
    return out


def main():
    print("App vs docs/DESIGN.md")
    print("=" * 62)

    files = sources()
    source = "\n".join(read(p) for p in files)
    index_html = read(os.path.join(FRONTEND, "index.html"))
    markup = source + index_html

    # 1. No web fonts. An icon font also fails invisibly - the glyph is a ligature, so a
    #    blocked request leaves the literal word "visibility_off" in the UI.
    fonts = re.findall(r"fonts\.googleapis\.com|fonts\.gstatic\.com|Material\+Symbols"
                       r"|material-symbols", markup)
    check("no web font or icon font", not fonts,
          f"{len(fonts)} reference(s)" if fonts else "system stack only")

    # 2. Tailwind is not our stack.
    check("no Tailwind", "cdn.tailwindcss.com" not in markup)

    # 3. Pinch zoom stays available.
    check("pinch zoom not disabled",
          "user-scalable=no" not in index_html and "maximum-scale" not in index_html)

    # 4. Colours come from tokens.
    literals = {h.lower() for h in re.findall(r"#[0-9a-fA-F]{3,8}\b", source)} - ALLOWED_LITERALS
    check("no colours outside the audited palette", not literals,
          f"stray: {sorted(literals)}" if literals else "all tokens")

    # 5. Nothing under 14px. DESIGN.md says 16px body; 14px is the established secondary
    #    label size across the app. Anything below that is unreadable in sunlight.
    sizes = [int(m) for m in re.findall(r"font-size:\s*(\d+)px", source)]
    too_small = sorted({s for s in sizes if s < 14})
    check("no text under 14px", not too_small,
          f"found {too_small}" if too_small else f"smallest is {min(sizes)}px")

    # 6. No credentials in markup. An export shipped a real-looking password.
    #    Only unbound attributes count - `:value="expr"` is a Vue binding, not a literal.
    seeded = []
    for path in files:
        if "screens" not in path:
            continue
        if re.search(r'(?<![:\w-])value="[^"{}]{6,}"', without_comments(read(path))):
            seeded.append(os.path.basename(path))
    check("no seeded credentials", not seeded, f"{seeded}" if seeded else "fields start empty")

    # 7. Interactive elements keep the 48px floor.
    under = sorted({int(s) for s in re.findall(r"min-height:\s*(\d+)px", source)
                    if 20 < int(s) < 48})
    check("tap targets at least 48px", not under, f"found {under}" if under else "48px floor held")

    # 8. No endless animation. Transitions are capped at 150ms.
    endless = re.findall(r"animation:[^;]*infinite|animate-pulse|animate-spin", source)
    slow = [int(m) for m in re.findall(r"transition:[^;]*?(\d{3,})ms", source) if int(m) > 150]
    check("no endless or slow animation", not endless and not slow,
          f"endless={len(endless)} slow={slow}" if (endless or slow) else "none over 150ms")

    # 9. The UI never claims security the app does not provide.
    visible = without_comments(source)
    claimed = [w for w in FALSE_CLAIMS if re.search(rf"\b{w}\b", visible, re.I)]
    check("no false security claims", not claimed,
          f"found {claimed}" if claimed else "copy matches what the app does")

    # 10. The built bundle fetches nothing from a third party at runtime.
    built = os.path.join(DIST, "index.html")
    if os.path.exists(built):
        external = re.findall(r'(?:src|href)="(https?://[^"]+)"', read(built))
        check("build fetches nothing external", not external,
              f"{external}" if external else "self-contained")

    print()
    if failures:
        print(f"  {len(failures)} check(s) failed.")
        sys.exit(1)
    print("  All checks passed.")


if __name__ == "__main__":
    main()
