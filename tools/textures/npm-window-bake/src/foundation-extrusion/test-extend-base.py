import bpy
import importlib.util
from mathutils import Vector
from pathlib import Path

path = Path(__file__).with_name("extend-base.py")
spec = importlib.util.spec_from_file_location("extend_base", path)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
mesh = bpy.data.meshes.new("Walls")
mesh.from_pydata(
    [(0,0,0),(2,0,0),(2,1,0),(0,1,0),(0,0,3),(2,0,3),(2,1,3),(0,1,3)],
    [],
    [(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7)]
)
obj = bpy.data.objects.new("Walls", mesh)
bpy.context.scene.collection.objects.link(obj)
obj.rotation_euler = (0.21,0.32,0.43)
obj.scale = (1.2,2.2,0.9)
bpy.context.view_layer.update()
for name in ("UVMap","Secondary"):
    uv = mesh.uv_layers.new(name=name)
    for i, corner in enumerate(uv.uv):
        corner.vector = (0.05*i, 0.02*i)
mesh.materials.append(bpy.data.materials.new("A"))
mesh.materials.append(bpy.data.materials.new("B"))
for face in mesh.polygons:
    face.material_index = face.index % 2
before_uv = {uv.name: [tuple(c.vector) for c in uv.uv] for uv in mesh.uv_layers}
before_faces = [tuple(p.vertices) for p in mesh.polygons]
before = [obj.matrix_world @ v.co for v in mesh.vertices]
edge_plan = []
for edge in mesh.edges:
    if max(edge.vertices) < 4:
        edge_plan.append({"edge": edge.index, "uv": {"UVMap": [0.05,0.10,0.15,0.30], "Secondary": [0.20,0.25,0.50,0.55]}})
expect = {"added_vertices": 4,"added_faces": 4}
bpy.context.scene.unit_settings.system = 'METRIC'
bpy.context.scene.unit_settings.scale_length = 0.5
assert mod.extend_base(obj, edge_plan, 2) == expect
assert len(mesh.vertices) == 12 and len(mesh.polygons) == 8
assert [tuple(p.vertices) for p in mesh.polygons[:4]] == before_faces
for uv in mesh.uv_layers:
    assert [tuple(c.vector) for c in list(uv.uv)[:16]] == before_uv[uv.name]
for v in mesh.vertices[8:]:
    point = obj.matrix_world @ v.co
    assert min((point - original + Vector((0,0,4))).length for original in before[:4]) < 1e-5
for face in mesh.polygons[4:]:
    b,a,da,db = face.vertices
    adjacent = [p for p in mesh.polygons[:4] if {a,b}.issubset(p.vertices)]
    assert len(adjacent) == 1 and face.material_index == adjacent[0].material_index
    vertices = list(adjacent[0].vertices)
    assert vertices[(vertices.index(a)+1) % len(vertices)] == b
    for uv, (u0,v0,u1,v1) in zip(mesh.uv_layers, ((.05,.10,.15,.30),(.20,.25,.50,.55))):
        got = [tuple(round(c, 5) for c in uv.uv[i].vector) for i in face.loop_indices]
        assert got == [(u1,v1),(u0,v1),(u0,v0),(u1,v0)], got
    assert len(set((da,db))) == 2
try:
    mod.extend_base(obj, edge_plan, 2)
except ValueError as e:
    assert "exactly one" in str(e)
else:
    raise AssertionError("Internal edges accepted")
assert len(mesh.polygons) == 8
print("PASS: base extrusion world units, winding, material, unchanged UV, two new UV strips, rejection")
