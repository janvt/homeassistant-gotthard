"""Draws the integration's icon: the Gotthard massif with the road tunnel's
portal, the A2 leading into it. Writes custom_components/gotthard/brand/
icon.png (256 px) and icon@2x.png (512 px), on a transparent background.

    .venv/bin/python scripts/make_icon.py
"""

from pathlib import Path

from PIL import Image, ImageDraw

BRAND = (
    Path(__file__).resolve().parent.parent / "custom_components" / "gotthard" / "brand"
)
SIZE = 2048  # drawn large, then scaled down for smooth edges

ROCK = (52, 78, 104, 255)
ROCK_SHADE = (38, 58, 80, 255)
SNOW = (240, 245, 250, 255)
PORTAL = (24, 24, 28, 255)
ROAD = (92, 96, 104, 255)
LINE = (255, 196, 0, 255)
FRAME = (210, 40, 40, 255)  # the portal's frame, Swiss red


def draw() -> Image.Image:
    s = SIZE / 512
    image = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(image)

    def p(*points):
        return [(x * s, y * s) for x, y in points]

    # Two peaks, the right one lower, the massif down to the road.
    d.polygon(p((16, 400), (190, 70), (262, 170), (330, 110), (496, 400)), fill=ROCK)
    d.polygon(p((190, 70), (262, 170), (230, 400), (150, 400)), fill=ROCK_SHADE)
    # Snow on the peaks.
    d.polygon(
        p((190, 70), (232, 128), (214, 122), (198, 140), (180, 118), (148, 132)),
        fill=SNOW,
    )
    d.polygon(
        p((330, 110), (366, 158), (350, 152), (336, 166), (318, 150), (296, 160)),
        fill=SNOW,
    )
    # The portal, an arch with a flat floor: a red frame around the dark mouth.
    d.pieslice(p((172, 246), (340, 414)), 180, 360, fill=FRAME)
    d.rectangle(p((172, 329), (340, 400)), fill=FRAME)
    d.pieslice(p((196, 270), (316, 390)), 180, 360, fill=PORTAL)
    d.rectangle(p((196, 329), (316, 400)), fill=PORTAL)
    # The road out of the mouth, widening towards us, with its centre line.
    d.polygon(p((196, 399), (316, 399), (452, 496), (60, 496)), fill=ROAD)
    for top, bottom in ((408, 428), (442, 466), (480, 496)):
        w0, w1 = 3 + (top - 400) * 0.09, 3 + (bottom - 400) * 0.09
        d.polygon(
            p((256 - w0, top), (256 + w0, top), (256 + w1, bottom), (256 - w1, bottom)),
            fill=LINE,
        )
    return image


def main() -> None:
    BRAND.mkdir(exist_ok=True)
    image = draw()
    for name, size in (("icon.png", 256), ("icon@2x.png", 512)):
        image.resize((size, size), Image.LANCZOS).save(BRAND / name, optimize=True)
        print(BRAND / name)


if __name__ == "__main__":
    main()
