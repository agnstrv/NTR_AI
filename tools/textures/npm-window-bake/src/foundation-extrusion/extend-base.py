"""Extend explicitly identified open base edges in world -Z (Blender 5.0)."""

import argparse
import json
from pathlib import Path
import sys

import bmesh
import bpy
from mathutils import Vector


def extend_base(obj, edge_plan, depth):
    """Append a quad per edge using one explicitly approved atlas strip per UV layer."""
    if obj.type != 'MESH' or obj.mode != 'OBJECT' or obj.data.users != 1:
        raise ValueError("Expected a single-user mesh in Object Mode")
    if obj.data.shape_keys or obj.data.has_custom_normals:
        raise ValueError("Shape keys and custom normals require a separate workflow")
    if not 0 < depth < float('inf') or not edge_plan:
        raise ValueError("Provide a positive finite depth and at least one edge")
    if bpy.context.scene.unit_settings.system != 'NONE':
        depth /= bpy.context.scene.unit_settings.scale_length
    offset = obj.matrix_world.inverted().to_3x3() @ Vector((0, 0, -depth))
    bm = bmesh.new()
    try:
        bm.from_mesh(obj.data)
        bm.edges.ensure_lookup_table()
        layers = {name: bm.loops.layers.uv[name] for name in bm.loops.layers.uv.keys()}
        selected = {}
        degrees = {}
        for item in edge_plan:
            index, bounds = item["edge"], item["uv"]
            if type(index) is not int or not 0 <= index < len(bm.edges) or index in selected:
                raise ValueError(f"Invalid or duplicate edge index {index}")
            edge = bm.edges[index]
            if not edge.is_boundary:
                raise ValueError(f"Edge {index} must have exactly one incident face")
            if set(bounds) != set(layers):
                raise ValueError(f"Edge {index} needs a strip for every UV layer")
            for name, box in bounds.items():
                u0, v0, u1, v1 = box
                if not (0 <= u0 < u1 <= 1 and 0 <= v0 < v1 <= 1):
                    raise ValueError(f"Edge {index}, layer {name}: invalid UV strip")
            selected[index] = edge.link_loops[0], bounds
            for vertex in edge.verts:
                degrees[vertex] = degrees.get(vertex, 0) + 1
        if any(degree > 2 for degree in degrees.values()):
            raise ValueError("The boundary plan branches at a vertex")

        lower = {vertex: bm.verts.new(vertex.co + offset, vertex) for vertex in degrees}
        for loop, bounds in selected.values():
            a, b = loop.vert, loop.link_loop_next.vert
            if (b.co - a.co).cross(offset).length_squared == 0:
                raise ValueError(f"Edge {loop.edge.index} would create a zero-area quad")
            face = bm.faces.new((b, a, lower[a], lower[b]), loop.face)
            face.material_index = loop.face.material_index
            face.smooth = loop.face.smooth
            for name, (u0, v0, u1, v1) in bounds.items():
                coords = {a: (u0, v1), b: (u1, v1), lower[a]: (u0, v0), lower[b]: (u1, v0)}
                for corner in face.loops:
                    corner[layers[name]].uv = coords[corner.vert]

        bm.normal_update()
        bm.to_mesh(obj.data)
        obj.data.update()
    finally:
        bm.free()
    return {"added_vertices": len(degrees), "added_faces": len(selected)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--depth", required=True, type=float, help="Vertical extension in metres")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
    if args.output.suffix.lower() != ".blend" or args.output.exists():
        parser.error("--output must be a new .blend file")
    plan = json.loads(args.plan.read_text(encoding="utf-8-sig"))
    results = {}
    for name, edges in plan.items():
        obj = bpy.context.scene.objects.get(name)
        if obj is None:
            raise ValueError(f"Scene object not found: {name}")
        results[name] = extend_base(obj, edges, args.depth)
    if not results:
        raise ValueError("Plan must name at least one mesh")
    bpy.ops.wm.save_as_mainfile(filepath=str(args.output.resolve()), copy=True)
    print(json.dumps(results))


if __name__ == "__main__":
    main()
