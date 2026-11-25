"""Check the synthetic examples saved in one Blender file."""

from math import isclose

import bmesh
import bpy


def close(actual, expected):
    assert isclose(actual, expected, rel_tol=0, abs_tol=3e-6), (actual, expected)


def volume(name):
    bm = bmesh.new()
    try:
        bm.from_mesh(bpy.data.objects[name].data)
        assert all(edge.is_manifold and edge.is_contiguous for edge in bm.edges)
        assert all(vertex.is_manifold for vertex in bm.verts)
        return bm.calc_volume(signed=True)
    finally:
        bm.free()


for suffix, thickness in (("lower-rails", 0.08), ("upper-rails", 0.05)):
    obj = bpy.data.objects[f"sample-balcony-{suffix}"]
    assert len(obj.data.vertices) == 16
    assert len(obj.data.polygons) == 10
    assert all(row.value == 0 for row in obj.data.attributes["balcony_index"].data)
    close(volume(obj.name), 0.46 * thickness)

infill = bpy.data.objects["sample-balcony-infill"]
assert len(infill.data.vertices) == 8
assert len(infill.data.polygons) == 3
assert all(p.loop_total == 4 for p in infill.data.polygons)
z = [(infill.matrix_world @ vertex.co).z for vertex in infill.data.vertices]
close(min(z), 2.079)
close(max(z), 2.901)
for polygon, (x, y) in zip(infill.data.polygons, [(1, 0), (0, 1), (-1, 0)]):
    close(polygon.normal.x, x)
    close(polygon.normal.y, y)
    close(polygon.normal.z, 0)

wrap = bpy.data.objects["sample-belt-001"]
wrap_points = [wrap.matrix_world @ vertex.co for vertex in wrap.data.vertices]
close(min(point.x for point in wrap_points), -0.16)
close(max(point.x for point in wrap_points), 5.16)
assert any(abs(point.x - 0.05) < 3e-6 for point in wrap_points)
assert any(abs(point.x - 4.95) < 3e-6 for point in wrap_points)
close(volume(wrap.name), (5.22 * 4.22 - 4.9 * 3.9) * 0.2 + (5.32 * 4.32 - 4.9 * 3.9) * 0.1)

local = bpy.data.objects["sample-belt-002"]
local_points = [local.matrix_world @ vertex.co for vertex in local.data.vertices]
close(min(point.y for point in local_points), -0.13)
close(max(point.y for point in local_points), 0.05)
close(volume(local.name), 2.02 * 0.18 * 0.2)
print("PASS: balcony winding, rail volumes, infill overlap, stepped and local belt offsets and volumes")
