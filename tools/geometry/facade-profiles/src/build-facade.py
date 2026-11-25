"""Build façade meshes from explicit XY contours in Blender."""

import argparse
import json
from math import isfinite
from pathlib import Path
import sys

import bmesh
import bpy
from mathutils import Vector


SUFFIXES = ("lower-rails", "upper-rails", "infill")


def points_2d(raw, minimum, name):
    points = [tuple(point) for point in raw]
    if len(points) < minimum or len(set(points)) != len(points):
        raise ValueError(f"{name}: insufficient points or repeated coordinates")
    if any(len(point) != 2 or not all(isfinite(v) for v in point) for point in points):
        raise ValueError(f"{name}: expected finite XY coordinates")
    return points


def cross(a, b, c):
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def segments_cross(a, b, c, d):
    tolerance = 1e-9
    for x, y in zip(zip(a, b), zip(c, d)):
        if max(x) < min(y) - tolerance or max(y) < min(x) - tolerance:
            return False
    tests = ((cross(a, b, c), cross(a, b, d)), (cross(c, d, a), cross(c, d, b)))
    return all(min(u, v) <= tolerance and max(u, v) >= -tolerance for u, v in tests)


def simple_contour(points, closed, name):
    segments = list(zip(points, points[1:]))
    if closed:
        segments.append((points[-1], points[0]))
    for i, (a, b) in enumerate(segments):
        for j in range(i + 2, len(segments)):
            if closed and i == 0 and j == len(segments) - 1:
                continue
            if segments_cross(a, b, *segments[j]):
                raise ValueError(f"{name}: intersecting outline segments {i} and {j}")


def prism(profile, low, high):
    n = len(profile)
    vertices = [(x, y, z) for z in (low, high) for x, y in profile]
    faces = [tuple(reversed(range(n))), tuple(range(n, n * 2))]
    for i in range(n):
        j = (i + 1) % n
        faces.append((i, j, j + n, i + n))
    return vertices, faces


def surface(path, low, high):
    n = len(path)
    vertices = [(x, y, z) for z in (low, high) for x, y in path]
    # Directed path with the exterior on its right.
    faces = [(i, i + 1, i + 1 + n, i + n) for i in range(n - 1)]
    return vertices, faces


def balcony_parts(row):
    profile = points_2d(row["rail_xy"], 3, "rail_xy")
    simple_contour(profile, True, "rail_xy")
    twice_area = sum(cross(profile[0], a, b) for a, b in zip(profile[1:], profile[2:]))
    if abs(twice_area) <= 1e-9:
        raise ValueError("rail_xy: degenerate polygon")
    if twice_area < 0:
        profile.reverse()

    path = points_2d(row["infill_xy"], 2, "infill_xy")
    simple_contour(path, False, "infill_xy")
    low, lower_top = row["lower_z"]
    upper_base, high = row["upper_z"]
    overlap = row.get("overlap_m", 0.001)
    if not all(isfinite(v) for v in (low, lower_top, upper_base, high, overlap)):
        raise ValueError("expected finite heights and overlap")
    if not low < lower_top < upper_base < high:
        raise ValueError("expected separated lower and upper rail intervals")
    if not 0 <= overlap < min(lower_top - low, high - upper_base):
        raise ValueError("overlap_m must be nonnegative and less than both rail thicknesses")
    return (
        prism(profile, low, lower_top),
        prism(profile, upper_base, high),
        surface(path, lower_top - overlap, upper_base + overlap),
    )


def balcony_meshes(plan, prefix):
    batches = [([], [], []) for _ in SUFFIXES]
    rows = plan["balconies"]
    if not rows:
        raise ValueError("balconies must contain at least one row")
    for index, row in enumerate(rows):
        try:
            parts = balcony_parts(row)
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"balconies[{index}]: {error}") from error
        for (vertices, faces, ids), (new_vertices, new_faces) in zip(batches, parts):
            offset = len(vertices)
            vertices.extend(new_vertices)
            faces.extend(tuple(i + offset for i in face) for face in new_faces)
            ids.extend([index] * len(new_faces))
    return [
        (f"{prefix}-{suffix}", *batch, suffix != "infill", "balcony_index")
        for suffix, batch in zip(SUFFIXES, batches)
    ]


def belt_meshes(plan, prefix):
    belts = plan["belts"]
    if not belts:
        raise ValueError("belts must contain at least one row")
    return [
        (f"{prefix}-{index + 1:03}", row["vertices"], row["faces"], None, True, None)
        for index, row in enumerate(belts)
    ]


def check_mesh(mesh, closed):
    if mesh.validate(verbose=True):
        raise ValueError(f"{mesh.name}: Blender repaired invalid input geometry")
    bm = bmesh.new()
    try:
        bm.from_mesh(mesh)
        if any(face.calc_area() <= 1e-12 for face in bm.faces):
            raise ValueError(f"{mesh.name}: faces with zero area")
        if closed:
            if any(not edge.is_manifold or not edge.is_contiguous for edge in bm.edges):
                raise ValueError(f"{mesh.name}: open or non-manifold edge or inconsistent winding")
            if any(not vertex.is_manifold for vertex in bm.verts):
                raise ValueError(f"{mesh.name}: non-manifold vertex")
            if bm.calc_volume(signed=True) <= 0:
                raise ValueError(f"{mesh.name}: expected positive signed volume")
        elif any(not (edge.is_manifold or edge.is_boundary) for edge in bm.edges):
            raise ValueError(f"{mesh.name}: non-manifold infill edge")
    finally:
        bm.free()


def add_mesh(collection, name, vertices, faces, ids, closed, index_attribute):
    origin = Vector(vertices[0])
    # Subtract before conversion to Blender's float coordinates.
    local_vertices = [tuple(a - b for a, b in zip(vertex, vertices[0])) for vertex in vertices]
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(local_vertices, [], faces)
    mesh.update()
    check_mesh(mesh, closed)
    if index_attribute:
        attribute = mesh.attributes.new(index_attribute, "INT", "FACE")
        attribute.data.foreach_set("value", ids)
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    obj.location = origin
    print(f"{name}: {len(mesh.vertices)} vertices, {len(mesh.polygons)} faces", flush=True)


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=("balconies", "belts"))
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--prefix", required=True)
    parser.add_argument("--collection", help="existing collection in the active scene")
    args = parser.parse_args(argv)
    output = args.output.resolve()
    if output.suffix.lower() != ".blend" or output.exists() or not output.parent.is_dir():
        parser.error("output must be a new .blend in an existing directory")
    scene = bpy.context.scene
    collection = scene.collection
    if args.collection:
        collection = next((c for c in scene.collection.children_recursive if c.name == args.collection), None)
        if collection is None:
            parser.error(f"collection not found in active scene: {args.collection}")
    if abs(scene.unit_settings.scale_length - 1.0) > 1e-6:
        parser.error("scene unit scale must be 1.0 (one Blender unit per metre)")
    plan = json.loads(args.plan.read_text(encoding="utf-8-sig"))
    build = balcony_meshes if args.kind == "balconies" else belt_meshes
    meshes = build(plan, args.prefix)
    for name, *_ in meshes:
        if name in bpy.data.objects or name in bpy.data.meshes:
            parser.error(f"object or mesh name already in use: {name}")
    for mesh in meshes:
        add_mesh(collection, *mesh)
    bpy.ops.wm.save_as_mainfile(filepath=str(output), compress=True)


if __name__ == "__main__":
    main(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
