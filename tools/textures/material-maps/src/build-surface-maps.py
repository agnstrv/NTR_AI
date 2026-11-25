"""Generate binary material maps aligned to an existing atlas."""

import argparse
import json
from pathlib import Path

from PIL import Image, ImageChops


def glass_mask(atlas, regions):
    mask = Image.new("L", atlas.size)
    for region in regions:
        box = tuple(region["box"])
        x0, y0, x1, y1 = box
        if any(type(v) is not int for v in box) or not (
            0 <= x0 < x1 <= atlas.width and 0 <= y0 < y1 <= atlas.height
        ):
            raise ValueError(f"Region is outside the atlas or is empty: {box}")
        colors = region["colors"]
        if not colors:
            raise ValueError(f"No glass colors provided for region {box}")
        pane = Image.new("L", (x1 - x0, y1 - y0))
        channels = atlas.crop(box).split()
        for color in colors:
            if len(color) != 3 or any(type(v) is not int or not 0 <= v <= 255 for v in color):
                raise ValueError("Glass colors must contain three integer RGB values")
            match = Image.new("L", pane.size, 255)
            for channel, value in zip(channels, color):
                exact = channel.point([255 if i == value else 0 for i in range(256)])
                match = ImageChops.darker(match, exact)
            if match.getbbox() is None:
                raise ValueError(f"Glass color {color} is absent from region {box}")
            pane = ImageChops.lighter(pane, match)
        mask.paste(255, box, pane)
    if mask.getbbox() is None:
        raise ValueError("No glass pixels marked")
    return mask


def build_maps(atlas_path, plan_path, output, opacity_path=None):
    plan = json.loads(plan_path.read_text(encoding="utf-8-sig"))
    with Image.open(atlas_path) as atlas:
        if atlas.mode != "RGB":
            raise ValueError("The color atlas must be an RGB image")
        metallic = glass_mask(atlas, plan["glass_regions"])
    maps = {
        "roughness.png": ImageChops.invert(metallic),
        "metallic.png": metallic,
    }
    if opacity_path:
        with Image.open(opacity_path) as opacity:
            if opacity.size != metallic.size or opacity.mode not in ("1", "L", "RGB"):
                raise ValueError("Opacity must be a same-size binary image in mode 1, L or RGB")
            channels = opacity.convert("RGB").split()
            if any(ImageChops.difference(channels[0], ch).getbbox() for ch in channels[1:]):
                raise ValueError("Opacity RGB channels must be identical")
            if any(channels[0].histogram()[1:255]):
                raise ValueError("Opacity must contain only 0 and 255")
            maps["opacity.png"] = channels[0]
    output.mkdir()
    for name, image in maps.items():
        with (output / name).open("xb") as destination:
            image.convert("RGB").save(destination, format="PNG")
    return metallic.histogram()[255]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--atlas", required=True, type=Path)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path, help="New output directory")
    parser.add_argument("--opacity", type=Path, help="Existing binary opacity, optional")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("--output must be a new directory")
    count = build_maps(args.atlas, args.plan, args.output, args.opacity)
    print(f"Glass pixels: {count}")


if __name__ == "__main__":
    main()
