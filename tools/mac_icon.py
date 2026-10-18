"""Icon-mac.png (1024×1024, Apple macOS icon grid) from Icon.png: python tools/mac_icon.py

Icon.png has the rounded square at 72 % of the canvas with a hard, jagged edge; macOS icons use an
824×824 body centred on 1024×1024 with a smooth continuous-corner outline and a soft shadow below.
The body is cropped from Icon.png, scaled up and cut by an antialiased superellipse mask.
build_mac.sh builds the .icns from Icon-mac.png. Needs Pillow (dev only, not in the program).
"""
import os

from PIL import Image, ImageChops, ImageDraw, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CANVAS, BODY = 1024, 824
SRC_BOX = (147, 147, 878, 878)  # the rounded square in Icon.png (opaque pixels), a few px inside its edge
INSET = 10  # px of Icon.png's own rim (light bevel + jagged edge) cut off by the new mask
SS = 4  # supersampling of the mask


def superellipse_mask(size, n=5.0):
    """Apple-like continuous-corner rounded square, antialiased."""
    big = size * SS
    mask = Image.new("L", (big, big), 0)
    half = big / 2
    points = []
    steps = 2000
    import math
    for i in range(steps):
        t = 2 * math.pi * i / steps
        c, s = math.cos(t), math.sin(t)
        x = half + half * (abs(c) ** (2 / n)) * (1 if c >= 0 else -1)
        y = half + half * (abs(s) ** (2 / n)) * (1 if s >= 0 else -1)
        points.append((x, y))
    ImageDraw.Draw(mask).polygon(points, fill=255)
    return mask.resize((size, size), Image.LANCZOS)


def main():
    src = Image.open(os.path.join(ROOT, "Icon.png")).convert("RGBA")
    x0, y0, x1, y1 = SRC_BOX
    body = src.crop((x0 + INSET, y0 + INSET, x1 - INSET, y1 - INSET)).resize((BODY, BODY), Image.LANCZOS)
    mask = superellipse_mask(BODY)
    body.putalpha(ImageChops.multiply(mask, body.getchannel("A")))

    offset = (CANVAS - BODY) // 2
    shadow_alpha = Image.new("L", (CANVAS, CANVAS), 0)
    shadow_alpha.paste(mask, (offset, offset + 12))
    shadow_alpha = shadow_alpha.filter(ImageFilter.GaussianBlur(14)).point(lambda a: a * 0.35)
    out = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    out.putalpha(shadow_alpha)
    out = Image.composite(Image.new("RGBA", out.size, (0, 0, 0, 255)), out, shadow_alpha)
    out.putalpha(shadow_alpha)
    out.alpha_composite(body, (offset, offset))
    out.save(os.path.join(ROOT, "Icon-mac.png"))
    print("Icon-mac.png")


if __name__ == "__main__":
    main()
