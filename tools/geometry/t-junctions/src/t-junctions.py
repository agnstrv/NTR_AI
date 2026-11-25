"""Find T-junction candidates and stitch explicitly matched boundary chains."""
import argparse
from collections import defaultdict
import json
import math
from pathlib import Path
import sys

import bmesh
import bpy
from mathutils.kdtree import KDTree


def edge_key(a, b):
    return min(a, b), max(a, b)


def pairs(indices):
    return zip(indices, indices[1:] + indices[:1])


def incidence(faces):
    uses = defaultdict(list)
    for i, vertices in faces.items():
        for a, b in pairs(vertices):
            uses[edge_key(a, b)].append((i, a < b))
    return uses


def project(point, start, end):
    direction = end - start
    t = (point - start).dot(direction) / direction.length_squared
    return t, (point - start - t * direction).length


def world_points(obj):
    return [obj.matrix_world @ v.co for v in obj.data.vertices]


def scan(obj, tolerance, clearance):
    points = world_points(obj)
    index = KDTree(len(points))
    for i, xyz in enumerate(points):
        index.insert(xyz, i)
    index.balance()
    faces = {f.index: list(f.vertices) for f in obj.data.polygons}
    uses = incidence(faces)
    for ed in obj.data.edges:
        a, b = edge_key(*ed.vertices)
        start, end = points[a], points[b]
        length = (end - start).length
        if length <= clearance * 2:
            continue
        center = (start + end) * .5
        radius = length * .5 + tolerance
        candidates = []
        for _, i, _ in index.find_range(center, radius):
            if i in (a, b):
                continue
            t, distance = project(points[i], start, end)
            if min(t, 1 - t) * length <= clearance or distance > tolerance:
                continue
            short_faces = [len(uses.get(edge_key(a, i), ())), len(uses.get(edge_key(i, b), ()))]
            candidates.append({
                "vertex": i, "fraction": t, "distance": distance,
                "endpoint_subedge_faces": short_faces,
            })
        if candidates:
            yield {
                "edge": [a, b], "length": length, "faces": len(uses.get((a, b), ())),
                "vertices": sorted(candidates, key=lambda row: (row["fraction"], row["vertex"])),
            }


def read_plan(plan, points, tolerance, clearance):
    records = plan.get("splits")
    if not isinstance(records, list) or not records:
        raise ValueError("The plan must contain a nonempty splits list")
    splits = {}
    for row in records:
        raw = row.get("edge")
        mids = row.get("vertices")
        if not isinstance(raw, list) or len(raw) != 2 or not isinstance(mids, list) or not mids:
            raise ValueError("Each split needs an edge pair and a nonempty vertex list")
        ids = raw + mids
        if any(type(i) is not int or not 0 <= i < len(points) for i in ids) or len(set(ids)) != len(ids):
            raise ValueError(f"Invalid or repeated vertex indices: {ids}")
        a, b = edge_key(*raw)
        if (a, b) in splits:
            raise ValueError(f"Edge repeated in plan: {(a, b)}")
        length = (points[b] - points[a]).length
        if length <= 2 * clearance:
            raise ValueError(f"Edge is too short: {(a, b)}")
        params = []
        for i in mids:
            t, distance = project(points[i], points[a], points[b])
            if min(t, 1 - t) * length <= clearance or distance > tolerance:
                raise ValueError(f"Vertex {i} is outside the permitted span of edge {(a, b)}")
            params.append((t, i))
        params.sort()
        stations = [0.] + [t for t, _ in params] + [1.]
        if min(y - x for x, y in zip(stations, stations[1:])) * length <= clearance:
            raise ValueError(f"Split vertices on {(a, b)} are too close together")
        splits[a, b] = params
    return splits


def geometric_normal(vertices, points):
    anchor = points[vertices[0]]
    ring = [points[i] - anchor for i in vertices]
    normal = anchor * 0
    for a, b in pairs(ring):
        normal += a.cross(b)
    if normal.length_squared == 0:
        raise ValueError("A face incident to the seam has zero geometric area")
    return normal.normalized()


def replacement_loops(faces, splits, points):
    uses = incidence(faces)
    changed = set()
    normals = {}
    opposite_limit = -math.cos(math.radians(2.))

    def normal(face_id):
        if face_id not in normals:
            normals[face_id] = geometric_normal(faces[face_id], points)
        return normals[face_id]

    for (a, b), knots in splits.items():
        old = uses.get((a, b), ())
        if len(old) != 1:
            raise ValueError(f"Long edge {(a, b)} must have exactly one incident face")
        face_index, forward = old[0]
        changed.add(face_index)
        chain = [a, *[i for _, i in knots], b]
        for x, y in zip(chain, chain[1:]):
            sub = edge_key(x, y)
            other = uses.get(sub, ())
            wanted = (x < y) != forward
            if sub in splits or len(other) != 1 or other[0][1] != wanted or other[0][0] == face_index:
                raise ValueError(f"Missing unique opposite boundary subedge {sub} for {(a, b)}")
            if normal(face_index).dot(normal(other[0][0])) <= opposite_limit:
                raise ValueError(f"Possible folded overlap at subedge {sub}: near-opposite face normals")

    rebuilt = {}
    for i in sorted(changed):
        f = faces[i]
        indices = []
        for a, b in pairs(f):
            indices.append(a)
            mids = splits.get(edge_key(a, b), ())
            order = mids if a < b else reversed(mids)
            indices.extend(j for _, j in order)
        if len(set(indices)) != len(indices):
            raise ValueError(f"Face {i} would fold back onto itself")
        rebuilt[i] = indices
    final_faces = faces | rebuilt
    verify_fans(final_faces, {i for edge, rows in splits.items() for i in (*edge, *(i for _, i in rows))})
    return rebuilt


def verify_fans(faces, vertices):
    """Require one connected fan and zero or two boundary edges per seam vertex."""
    uses = incidence(faces)
    vertex_faces = defaultdict(set)
    vertex_edges = defaultdict(list)
    for edge, rows in uses.items():
        for v in vertices.intersection(edge):
            vertex_edges[v].append(rows)
            vertex_faces[v].update(i for i, _ in rows)
    for v in sorted(vertices):
        reach = defaultdict(set)
        boundary = 0
        for rows in vertex_edges[v]:
            if len(rows) == 1:
                boundary += 1
            elif len(rows) == 2 and rows[0][1] != rows[1][1]:
                i, j = rows[0][0], rows[1][0]
                reach[i].add(j)
                reach[j].add(i)
            else:
                raise ValueError(f"Nonmanifold or inconsistent edge at seam vertex {v}")
        if boundary not in (0, 2) or not vertex_faces[v]:
            raise ValueError(f"Invalid number of boundary edges at seam vertex {v}")
        pending = [next(iter(vertex_faces[v]))]
        seen = set(pending)
        for i in pending:
            for j in reach[i] - seen:
                pending.append(j)
                seen.add(j)
        if seen != vertex_faces[v]:
            raise ValueError(f"Disconnected face fan at seam vertex {v}")


BUILTIN_ATTRIBUTES = {
    "position", ".edge_verts", ".corner_vert", ".corner_edge", "material_index",
    "sharp_edge", "sharp_face", "uv_seam",
    ".select_vert", ".select_edge", ".select_poly", ".hide_vert", ".hide_edge", ".hide_poly",
    ".uv_select_vert", ".uv_select_edge", ".uv_select_face",
}


def ensure_supported(obj):
    mesh = obj.data
    if mesh.users != 1 or mesh.library or mesh.shape_keys or mesh.has_custom_normals:
        raise ValueError("Split requires a single-user local mesh without shape keys or custom normals")
    if obj.modifiers or obj.vertex_groups:
        raise ValueError("Split does not support modifiers or vertex groups")
    uv_names = {layer.name for layer in mesh.uv_layers}
    flags = {".pn." + name for name in uv_names}
    extra = {a.name for a in mesh.attributes} - BUILTIN_ATTRIBUTES - uv_names - flags
    if extra:
        raise ValueError(f"Unsupported attributes in split mode: {', '.join(sorted(extra))}")


def split(obj, plan, tolerance, clearance):
    ensure_supported(obj)
    points = world_points(obj)
    mesh = obj.data
    splits = read_plan(plan, points, tolerance, clearance)
    faces = {f.index: list(f.vertices) for f in mesh.polygons}
    rebuilt = replacement_loops(faces, splits, points)
    active_uv = mesh.uv_layers.active.name if mesh.uv_layers.active else None
    render_uv = {uv.name for uv in mesh.uv_layers if uv.active_render}
    clone_uv = {uv.name for uv in mesh.uv_layers if uv.active_clone}
    before_xyz = [tuple(v.co) for v in mesh.vertices]
    bm = bmesh.new()
    try:
        bm.from_mesh(mesh)
        bm.faces.ensure_lookup_table()
        bm.verts.ensure_lookup_table()
        uv_layers = [(layer, mesh.attributes.get(".pn." + layer.name) is not None)
                     for layer in bm.loops.layers.uv.values()]

        def edge_flags(edge):
            return edge.seam, not edge.smooth, edge.hide, edge.select

        verts = list(bm.verts)
        retired = [bm.edges.get((verts[a], verts[b])) for a, b in splits]
        for edge, ((a, b), knots) in zip(retired, splits.items()):
            flags = edge_flags(edge)
            chain = [a, *[j for _, j in knots], b]
            for i, j in zip(chain, chain[1:]):
                short = bm.edges.get((verts[i], verts[j]))
                seam, sharp, hidden, selected = [x or y for x, y in zip(flags, edge_flags(short))]
                short.seam, short.smooth, short.hide, short.select = seam, not sharp, hidden, selected

        old_faces = {i: bm.faces[i] for i in rebuilt}
        for i, indices in rebuilt.items():
            original = old_faces[i]
            uv = {
                lp.vert.index: [(lp[layer].uv.copy(), lp[layer].pin_uv if pinned else False)
                                for layer, pinned in uv_layers]
                for lp in original.loops
            }
            for a, b in pairs(faces[i]):
                a, b = edge_key(a, b)
                for t, j in splits.get((a, b), ()):
                    uv[j] = [(p[0].lerp(q[0], t), *(x and y for x, y in zip(p[1:], q[1:])))
                             for p, q in zip(uv[a], uv[b])]
            replacement = bm.faces.new([verts[j] for j in indices])
            replacement.material_index = original.material_index
            replacement.smooth = original.smooth
            replacement.hide = original.hide
            replacement.select = original.select
            for loop in replacement.loops:
                for (layer, pinned), values in zip(uv_layers, uv[loop.vert.index]):
                    data = loop[layer]
                    data.uv = values[0]
                    if pinned:
                        data.pin_uv = values[1]
            if replacement.calc_area() <= 0:
                raise ValueError(f"Face {i} would have zero area")
        for old in old_faces.values():
            bm.faces.remove(old)
        for edge in retired:
            if edge.link_faces:
                raise RuntimeError("A long edge still has incident faces after replacement")
            bm.edges.remove(edge)
        bm.to_mesh(mesh)
    finally:
        bm.free()
    mesh.update()
    for layer in mesh.uv_layers:
        if layer.name == active_uv:
            mesh.uv_layers.active = layer
        if layer.name in render_uv:
            layer.active_render = True
        if layer.name in clone_uv:
            layer.active_clone = True
    if before_xyz != [tuple(v.co) for v in mesh.vertices]:
        raise RuntimeError("Vertex indices or coordinates changed during the edit")
    return len(splits), len(rebuilt)


def arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("scan", "split"))
    parser.add_argument("--object", required=True, help="Exact mesh object name")
    parser.add_argument("--distance", required=True, type=float, help="Tolerance in world-space Blender units")
    parser.add_argument("--endpoint-clearance", type=float, help="Minimum spacing from endpoints and split knots")
    parser.add_argument("--report", type=Path, help="New JSON file for scan results; defaults to standard output")
    parser.add_argument("--plan", type=Path, help="Explicit JSON split plan")
    parser.add_argument("--output", type=Path, help="New .blend file for the repaired scene")
    return parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])


def main():
    args = arguments()
    tolerance = args.distance
    clearance = tolerance if args.endpoint_clearance is None else args.endpoint_clearance
    if any(not math.isfinite(x) or x <= 0 for x in (tolerance, clearance)):
        raise ValueError("Distance and endpoint clearance must be finite and positive")
    obj = bpy.context.scene.objects.get(args.object)
    if obj is None or obj.type != "MESH" or obj.mode != "OBJECT":
        raise ValueError("Object must be a mesh in Object Mode in the current scene")
    bpy.context.view_layer.update()
    if args.mode == "scan":
        if args.plan or args.output:
            raise ValueError("Scan accepts --report, not --plan or --output")
        rows = list(scan(obj, tolerance, clearance))
        report = {
            "object": obj.name, "vertices": len(obj.data.vertices), "edges": len(obj.data.edges),
            "distance": tolerance, "endpoint_clearance": clearance, "candidates": rows,
        }
        payload = json.dumps(report, indent=2) + "\n"
        if args.report:
            with args.report.open("x", encoding="utf-8") as output:
                output.write(payload)
            print(f"{len(rows)} edges have geometric candidates")
        else:
            print(payload, end="")
        return

    if not args.plan or not args.output or args.report:
        raise ValueError("Split requires --plan and --output")
    dst = args.output.resolve()
    if dst.exists() or dst.suffix.lower() != ".blend" or not dst.parent.is_dir():
        raise ValueError("Output must be an unused .blend path in an existing folder")
    plan = json.loads(args.plan.read_text(encoding="utf-8-sig"))
    edges, faces = split(obj, plan, tolerance, clearance)
    bpy.context.preferences.filepaths.save_version = 0
    bpy.ops.wm.save_as_mainfile(filepath=str(dst), relative_remap=True)
    print(f"Stitched {edges} boundary edges across {faces} faces. Reopen and check the result.")


if __name__ == "__main__":
    main()
