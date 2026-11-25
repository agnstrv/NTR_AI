"""Build repeatable color and binary control maps from a measured tile plan."""
import argparse
import json
import math
from pathlib import Path
import re

from PIL import Image, ImageDraw, ImageOps, PngImagePlugin

from atlas_packing import pack_rectangles


SIZE = 2048


def integer(value, minimum, maximum, label):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{label}: expected an integer in [{minimum}, {maximum}]")
    return value


def rgb(value, label):
    if not isinstance(value, list) or len(value) != 3:
        raise ValueError(f"{label}: expected three sRGB channels")
    return tuple(integer(channel, 0, 255, label) for channel in value)


def bounds(value, count, label):
    if (not isinstance(value, list) or len(value) != count
            or any(type(x) not in (int, float) or not 0 <= x <= 1 for x in value)
            or any(lo >= hi for lo, hi in zip(value[:count // 2], value[count // 2:]))):
        raise ValueError(f"{label}: expected ordered normalized bounds within [0, 1]")
    return value


def overlaps(a, b):
    return max(a[0], b[0]) < min(a[2], b[2]) and max(a[1], b[1]) < min(a[3], b[3])


def load_mask(path, size, label):
    with Image.open(path) as source:
        if source.format != "PNG" or source.size != size:
            raise ValueError(f"{label}: mask PNG must have content size {size}")
        if source.mode in ("LA", "RGBA"):
            mask = source.getchannel("A")
        elif source.mode in ("1", "L"):
            mask = source.convert("L")
        elif source.mode == "RGB":
            left, middle, right = source.split()
            if left.tobytes() != middle.tobytes() or middle.tobytes() != right.tobytes():
                raise ValueError(f"{label}: RGB mask channels must be identical")
            mask = left
        else:
            raise ValueError(f"{label}: use grayscale, grayscale RGB, or explicit alpha")
    if any(mask.histogram()[1:255]):
        raise ValueError(f"{label}: mask coverage must be binary (0 or 255)")
    return mask


def load_tiles(config, root):
    tiles = []
    seen = set()
    for kind in ("windows", "swatches", "balconies"):
        rows = config.get(kind, [])
        if not isinstance(rows, list):
            raise ValueError(f"{kind}: expected a list")
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError(f"{kind}: expected objects")
            key = row["id"]
            if not isinstance(key, str) or not key.strip() or key in seen:
                raise ValueError(f"{kind}: duplicate or invalid ID {key!r}")
            seen.add(key)
            if kind == "windows":
                meters = [row["width_m"], row["height_m"]]
                if any(type(x) not in (int, float) or not 0 < x <= SIZE for x in meters):
                    raise ValueError(f"{key}: expected positive width_m and height_m")
                tile = dict(id=key, kind="window", meters=meters, frame=rgb(row["frame_rgb"], key), panes=[])
                panes = row["panes"]
                if not isinstance(panes, list) or any(not isinstance(pane, dict) for pane in panes):
                    raise ValueError(f"{key}: expected a list of pane objects")
                for pane in panes:
                    category = pane.get("kind", "glass")
                    if category not in ("glass", "opaque"):
                        raise ValueError(f"{key}: pane kind must be glass or opaque")
                    edges = bounds(pane["bounds"], 4, key)
                    if any(overlaps(edges, prior["bounds"]) for prior in tile["panes"]):
                        raise ValueError(f"{key}: pane rectangles overlap")
                    tile["panes"].append(dict(bounds=edges, kind=category, rgb=rgb(pane["rgb"], key)))
            else:
                size = row["size_px"]
                if not isinstance(size, list) or len(size) != 2:
                    raise ValueError(f"{key}: expected [width, height] in pixels")
                size = tuple(integer(x, 1, SIZE, key) for x in size)
                tile = dict(id=key, kind="swatch" if kind == "swatches" else "balcony",
                            pixels=size, rgb=rgb(row["rgb"], key))
                if kind == "balconies":
                    if ("bars" in row) == ("mask_png" in row):
                        raise ValueError(f"{key}: specify either bars or mask_png")
                    if "bars" in row:
                        bars = [bounds(bar, 2, key) for bar in row["bars"]]
                        if not bars or any(a[1] >= b[0] for a, b in zip(bars, bars[1:])):
                            raise ValueError(f"{key}: bars must be ordered with positive gaps")
                        tile["bars"] = bars
                    else:
                        tile["mask"] = load_mask(root / row["mask_png"], size, key)
            tiles.append(tile)
    if not tiles:
        raise ValueError("supply at least one window, swatch or balcony tile")
    return tiles


def pixel_range(lo, hi, size):
    return math.ceil(lo * size - .5), math.ceil(hi * size - .5)


def pane_rect(pane, width, height):
    u, v, right, top = pane["bounds"]
    x0, x1 = pixel_range(u, right, width)
    y0, y1 = pixel_range(1 - top, 1 - v, height)
    return x0, y0, x1, y1


def fit_tiles(tiles, padding, maximum, minimum):
    for density in range(maximum, minimum - 1, -1):
        sizes = [tuple(max(1, round(value * density)) for value in tile["meters"])
                 if tile["kind"] == "window" else tile["pixels"] for tile in tiles]
        if any(x0 >= x1 or y0 >= y1
               for tile, (w, h) in zip(tiles, sizes)
               for x0, y0, x1, y1 in (pane_rect(pane, w, h) for pane in tile.get("panes", []))):
            continue
        origins = pack_rectangles(sizes, width=SIZE, height=SIZE, padding=padding)
        if origins is not None:
            return density, sizes, origins
    raise ValueError("tiles do not fit with the requested padding and density range")


def extend_edges(image, padding):
    if padding == 0:
        return image
    w, h = image.size
    strip = Image.new(image.mode, (w + 2 * padding, h))
    strip.paste(image, (padding, 0))
    for column, x in ((0, 0), (w - 1, w + padding)):
        edge = image.crop((column, 0, column + 1, h))
        strip.paste(edge.resize((padding, h), Image.Resampling.NEAREST), (x, 0))
    W = strip.width
    result = Image.new(image.mode, (W, h + 2 * padding))
    result.paste(strip, (0, padding))
    for row, y in ((0, 0), (h - 1, h + padding)):
        edge = strip.crop((0, row, W, row + 1))
        result.paste(edge.resize((W, padding), Image.Resampling.NEAREST), (0, y))
    return result


def build_maps(config, root, pbr):
    tiles = load_tiles(config, root)
    padding = integer(config.get("padding_px", 16), 0, SIZE // 2 - 1, "padding_px")
    density = config.get("density_px_per_m", {})
    if not isinstance(density, dict):
        raise ValueError("density_px_per_m: expected an object")
    maximum = integer(density.get("maximum", 128), 1, SIZE, "maximum density")
    minimum = integer(density.get("minimum", 40), 1, maximum, "minimum density")
    used_density, sizes, origins = fit_tiles(tiles, padding, maximum, minimum)
    diffuse = Image.new("RGB", (SIZE, SIZE), rgb(config.get("background_rgb", [255, 255, 255]), "background"))
    opacity = Image.new("L", (SIZE, SIZE), 255) if any(tile["kind"] == "balcony" for tile in tiles) else None
    metallic = Image.new("L", (SIZE, SIZE), 0) if pbr else None
    entries = []
    for tile, (w, h), (u_x, u_y) in zip(tiles, sizes, origins):
        # The packer returns content origins measured from the bottom-left.
        x, y = u_x, SIZE - u_y - h
        padded_x, padded_y = x - padding, y - padding
        entry = {"id": tile["id"], "kind": tile["kind"],
                 "content_xywh": [x, y, w, h],
                 "padded_xywh": [padded_x, padded_y, w + 2 * padding, h + 2 * padding],
                 "uv_min": [u_x / SIZE, u_y / SIZE], "uv_max": [(u_x + w) / SIZE, (u_y + h) / SIZE]}
        if tile["kind"] == "window":
            color = Image.new("RGB", (w, h), tile["frame"])
            glass = Image.new("L", (w, h), 0) if pbr else None
            color_draw = ImageDraw.Draw(color)
            glass_draw = ImageDraw.Draw(glass) if pbr else None
            for pane in tile["panes"]:
                a, b, c, d = pane_rect(pane, w, h)
                box = (a, b, c - 1, d - 1)
                color_draw.rectangle(box, fill=pane["rgb"])
                if pbr and pane["kind"] == "glass":
                    glass_draw.rectangle(box, fill=255)
            if pbr:
                metallic.paste(extend_edges(glass, padding), (padded_x, padded_y))
            entry.update(width_m=tile["meters"][0], height_m=tile["meters"][1],
                         frame_rgb=tile["frame"], panes=tile["panes"])
        else:
            color = Image.new("RGB", (w, h), tile["rgb"])
            entry["rgb"] = tile["rgb"]
            if tile["kind"] == "balcony":
                mask = tile.get("mask")
                if mask is None:
                    mask = Image.new("L", (w, h), 0)
                    ranges = [pixel_range(lo, hi, w) for lo, hi in tile["bars"]]
                    if (any(a >= b for a, b in ranges)
                            or any(a[1] >= b[0] for a, b in zip(ranges, ranges[1:]))):
                        raise ValueError(f"{tile['id']}: content width does not resolve all bars and gaps")
                    mask_draw = ImageDraw.Draw(mask)
                    for a, b in ranges:
                        mask_draw.rectangle((a, 0, b - 1, h - 1), fill=255)
                    entry["bars"] = tile["bars"]
                    entry["bar_pixel_intervals"] = ranges
                opacity.paste(extend_edges(mask, padding), (padded_x, padded_y))
        diffuse.paste(extend_edges(color, padding), (padded_x, padded_y))
        entries.append(entry)
    maps = {"d": diffuse}
    if opacity is not None:
        maps["o"] = opacity.convert("RGB")
    if pbr:
        maps["m"] = metallic.convert("RGB")
        maps["r"] = ImageOps.invert(metallic).convert("RGB")
    layout = dict(size=[SIZE, SIZE], padding_pixels=padding, window_density_px_per_m=used_density, entries=entries)
    return maps, layout


def save_maps(output, prefix, maps, layout):
    names = {suffix: f"{prefix}_{suffix}_1.png" for suffix in maps}
    spaces = {suffix: "sRGB" if suffix == "d" else "Non-Color" for suffix in maps}
    manifest = output / f"{prefix}-layout.json"
    output.mkdir(parents=True, exist_ok=True)
    files = [*(output / name for name in names.values()), manifest]
    collision = next((file for file in files if file.exists()), None)
    if collision is not None:
        raise FileExistsError(f"output already exists: {collision}")
    for suffix, image in maps.items():
        png = PngImagePlugin.PngInfo()
        png.add_text("intended_color_space", spaces[suffix])
        if suffix == "d":
            png.add(b"sRGB", b"\x00")
        with (output / names[suffix]).open("xb") as stream:
            image.save(stream, format="PNG", pnginfo=png, optimize=True)
    layout.update(maps=names, color_spaces=spaces)
    with manifest.open("x", encoding="utf-8") as stream:
        json.dump(layout, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True, help="tile plan JSON")
    parser.add_argument("--output", type=Path, required=True, help="directory for output maps")
    parser.add_argument("--pbr", action="store_true", help="emit binary glass metallic and roughness maps")
    args = parser.parse_args()
    try:
        config = json.loads(args.config.read_text(encoding="utf-8"))
        if not isinstance(config, dict):
            raise ValueError("config: expected a JSON object")
        prefix = config.get("prefix", "atlas")
        if not isinstance(prefix, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", prefix):
            raise ValueError("prefix must be a plain ASCII filename stem")
        maps, layout = build_maps(config, args.config.resolve().parent, args.pbr)
        manifest = save_maps(args.output, prefix, maps, layout)
    except (KeyError, TypeError, ValueError, OSError) as error:
        parser.exit(2, f"{parser.prog}: {error}\n")
    print(f"{len(layout['entries'])} regions at {layout['window_density_px_per_m']} px/m: {manifest}")


if __name__ == "__main__":
    main()
