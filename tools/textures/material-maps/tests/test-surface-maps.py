"""Synthetic regression for binary maps from an existing atlas."""

import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

from PIL import Image


with TemporaryDirectory() as folder:
    root = Path(folder)
    atlas = Image.new("RGB", (3, 2), (32, 32, 32))
    for coord in ((0, 0), (2, 0), (0, 1)):
        atlas.putpixel(coord, (240, 241, 244))
    atlas.putpixel((1, 1), (235, 236, 240))
    atlas.save(root / "diffuse.png")
    source_opacity = Image.new("L", atlas.size, 255)
    source_opacity.putpixel((2, 1), 0)
    source_opacity.save(root / "source-opacity.png")
    plan = {"glass_regions": [
        {"box": [0, 0, 1, 2], "colors": [[240, 241, 244]]},
        {"box": [0, 1, 2, 2], "colors": [[235, 236, 240]]},
    ]}
    (root / "glass.json").write_text(json.dumps(plan), encoding="utf-8")
    command = [sys.executable, str(Path(__file__).resolve().parents[1] / "src" / "build-surface-maps.py"),
               "--atlas", str(root / "diffuse.png"), "--plan", str(root / "glass.json"),
               "--opacity", str(root / "source-opacity.png"), "--output"]
    subprocess.run([*command, str(root / "maps")], check=True)
    for name, pixels in (
        ("metallic", [255, 0, 0, 255, 255, 0]),
        ("roughness", [0, 255, 255, 0, 0, 255]),
        ("opacity", [255, 255, 255, 255, 255, 0]),
    ):
        with Image.open(root / "maps" / f"{name}.png") as result:
            assert result.mode == "RGB" and result.size == atlas.size
            assert result.tobytes() == bytes(v for pixel in pixels for v in (pixel,) * 3)
    source_opacity.putpixel((1, 1), 128)
    source_opacity.save(root / "source-opacity.png")
    invalid = subprocess.run([*command, str(root / "invalid")], capture_output=True, text=True)
    assert invalid.returncode and "only 0 and 255" in invalid.stderr
    assert not (root / "invalid").exists()
print("PASS: aligned binary RGB maps")
