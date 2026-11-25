"""Convert explicit belt cross-sections into closed stepped mesh plans."""

import argparse
import json
from math import isfinite
from pathlib import Path

from shapely import Polygon, constrained_delaunay_triangles, polygonize, set_precision, union_all
from shapely.geometry.polygon import orient


def polygon(points, grid, name):
    shape = Polygon(points)
    if shape.is_empty or not shape.is_valid or not isfinite(shape.area):
        raise ValueError(f"{name}: expected a valid polygon")
    shape = set_precision(shape, grid)
    if shape.geom_type != "Polygon" or shape.is_empty:
        raise ValueError(f"{name}: expected one polygon after precision rounding")
    return shape


def offset(shape, distance, grid):
    return set_precision(shape.buffer(distance, join_style="mitre", mitre_limit=4.0), grid)


def get_section(layer, grid, projection, embed, wrap):
    source = polygon(layer["source_xy"], grid, "source_xy")
    shell = polygon(layer["body_xy"], grid, "body_xy")
    front = offset(source, projection, grid)
    rear = offset(shell, -embed, grid)
    if rear.geom_type != "Polygon" or rear.is_empty or not front.intersects(shell):
        raise ValueError("section lost its body offset or does not touch the body")
    if wrap:
        buried = offset(shell, -min(grid * 5, embed / 2), grid)
        front = union_all([front, buried], grid_size=grid)
    section = set_precision(front.difference(rear), grid)
    if section.geom_type != "Polygon" or section.is_empty or len(section.interiors) != int(wrap):
        raise ValueError("section must be a single polygon with the expected number of holes")
    if section.boundary.intersection(rear.boundary).length <= grid:
        raise ValueError("section does not reach the intended embedded boundary")
    return section


def layered_mesh(sections, heights, grid):
    vertices = []
    faces = []
    vertex_indices = {}

    def add_face(points):
        face = []
        for point in points:
            if point not in vertex_indices:
                vertex_indices[point] = len(vertices)
                vertices.append(point)
            face.append(vertex_indices[point])
        if len(set(face)) != len(face):
            raise ValueError("layer arrangement yielded a degenerate face")
        faces.append(face)

    def cap(cell, height, top):
        for triangle in constrained_delaunay_triangles(cell).geoms:
            ring = orient(triangle, sign=1 if top else -1).exterior
            add_face([(*xy, height) for xy in list(ring.coords)[:-1]])

    # A common planar arrangement ensures adjacent layers share the same edge splits.
    network = union_all([section.boundary for section in sections], grid_size=grid)
    cells = [orient(cell, sign=1) for cell in polygonize([network]).geoms]
    occupancy = [
        [section.covers(cell.representative_point()) for section in sections]
        for cell in cells
    ]
    for layer, (low, high) in enumerate(zip(heights, heights[1:])):
        perimeter = {}
        for cell, occupied in zip(cells, occupancy):
            if not occupied[layer]:
                continue
            for ring in (cell.exterior, *cell.interiors):
                points = list(ring.coords)
                for start, end in zip(points, points[1:]):
                    key = tuple(sorted((start, end)))
                    if key in perimeter:
                        del perimeter[key]
                    else:
                        perimeter[key] = (start, end)
            if layer == 0 or not occupied[layer - 1]:
                cap(cell, low, top=False)
            if layer == len(sections) - 1 or not occupied[layer + 1]:
                cap(cell, high, top=True)
        for start, end in perimeter.values():
            add_face([(*start, low), (*end, low), (*end, high), (*start, high)])
    if not faces:
        raise ValueError("layer arrangement did not produce faces")
    return {"vertices": vertices, "faces": faces}


def plan_belt(row, grid):
    projection = row.get("projection_m", 0.01)
    embed = row.get("embed_m", 0.05)
    if not all(isfinite(v) for v in (projection, embed)) or projection < 0 or embed < grid * 2:
        raise ValueError("expected projection >= 0 and embed >= 2 * grid")
    if row["mode"] not in ("wrap", "local"):
        raise ValueError("expected mode wrap or local")
    layers = row["layers"]
    if not layers:
        raise ValueError("expected at least one layer")
    heights = [layers[0]["z"][0]]
    sections = []
    for layer in layers:
        low, high = layer["z"]
        if not isfinite(low) or not isfinite(high) or low != heights[-1] or high <= low:
            raise ValueError("expected contiguous ascending layer intervals")
        heights.append(high)
        section = get_section(layer, grid, projection, embed, row["mode"] == "wrap")
        if sections and section.intersection(sections[-1]).area <= grid ** 2:
            raise ValueError("adjacent layers require an overlapping cross-section")
        sections.append(section)
    return layered_mesh(sections, heights, grid)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists() or not args.output.parent.is_dir():
        parser.error("output must be a new file in an existing directory")
    source = json.loads(args.input.read_text(encoding="utf-8-sig"))
    grid = source.get("grid_m", 0.0001)
    if not isfinite(grid) or grid <= 0:
        parser.error("grid_m must be finite and positive")
    if not source["belts"]:
        parser.error("expected at least one belt")
    meshes = []
    for index, row in enumerate(source["belts"]):
        try:
            meshes.append(plan_belt(row, grid))
        except (IndexError, KeyError, TypeError, ValueError) as error:
            raise ValueError(f"belts[{index}]: {error}") from error
    with args.output.open("x", encoding="utf-8") as output:
        json.dump({"belts": meshes}, output, allow_nan=False)


if __name__ == "__main__":
    main()
