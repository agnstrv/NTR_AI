"""Synthetic audit and stitch assertions for Blender background mode."""
from collections import Counter
from pathlib import Path
import runpy

import bpy

ROOT = Path(__file__).parent
TOOL = runpy.run_path(str(ROOT.parent / "src" / "t-junctions.py"))
TEST_VERTICES = [(0, 0, 0), (2, 0, 0), (0, 1, 0), (.5, 0, 0), (1, -1, 0), (.8, 0, .0001)]
TEST_FACES = [(0, 1, 2), (1, 3, 4), (3, 0, 4)]
PLAN = {"splits": [{"edge": [1, 0], "vertices": [3]}]}


def fixture(name, vertices=TEST_VERTICES, faces=TEST_FACES):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def check_uv(actual, expected):
    assert max(abs(a - b) for a, b in zip(actual, expected)) < 1e-6


def prepare_uv(mesh):
    mesh.materials.append(bpy.data.materials.new("Surface"))
    mesh.materials.append(bpy.data.materials.new("Other"))
    mesh.polygons[0].material_index = 1
    mesh.polygons[0].use_smooth = True
    for layer_name in ("Detail", "UVMap"):
        layer = mesh.uv_layers.new(name=layer_name, do_init=False)
        for face in mesh.polygons:
            for k, loop_id in enumerate(face.loop_indices):
                layer.uv[loop_id].vector = (.1 + .8 * k, .2 + .1 * face.index)
    mesh.uv_layers["Detail"].active_render = True
    mesh.uv_layers.active = mesh.uv_layers["UVMap"]
    next(e for e in mesh.edges if set(e.vertices) == {0, 1}).use_seam = True


def snapshot(mesh):
    return ([tuple(v.co) for v in mesh.vertices],
            [tuple(f.vertices) for f in mesh.polygons],
            [tuple(p.vector) for uv in mesh.uv_layers for p in uv.uv])


def reject(obj, plan, reason):
    first = snapshot(obj.data)
    try:
        TOOL["split"](obj, plan, .0003, .0001)
    except ValueError as error:
        assert reason in str(error), error
    else:
        raise AssertionError("Unsafe split was accepted")
    assert snapshot(obj.data) == first


sample = fixture("Stitch")
mesh = sample.data
prepare_uv(mesh)
bpy.context.view_layer.update()
original = snapshot(mesh)
audit = list(TOOL["scan"](sample, .0003, .0001))
row = next(r for r in audit if r["edge"] == [0, 1])
assert [v["vertex"] for v in row["vertices"]] == [3, 5]
assert row["vertices"][0]["endpoint_subedge_faces"] == [1, 1]
assert row["vertices"][1]["endpoint_subedge_faces"] == [0, 0]
assert snapshot(mesh) == original
reject(sample, {"splits": [{"edge": [0, 1], "vertices": [5]}]}, "Missing unique opposite")
assert TOOL["split"](sample, PLAN, .0003, .0001) == (1, 1)
assert [tuple(v.co) for v in mesh.vertices] == original[0]
assert len(mesh.polygons) == 3
repaired = next(f for f in mesh.polygons if len(f.vertices) == 4)
assert list(repaired.vertices) == [0, 3, 1, 2]
assert repaired.material_index == 1 and repaired.use_smooth
assert mesh.uv_layers.active.name == "UVMap"
assert mesh.uv_layers["Detail"].active_render
for layer in mesh.uv_layers:
    for j, expected in zip(repaired.loop_indices, ((.1, .2), (.3, .2), (.9, .2), (1.7, .2))):
        check_uv(layer.uv[j].vector, expected)
    for verts in TEST_FACES[1:]:
        untreated = next(f for f in mesh.polygons if tuple(f.vertices) == verts)
        for k, loop_id in enumerate(untreated.loop_indices):
            face_index = TEST_FACES.index(verts)
            check_uv(layer.uv[loop_id].vector, (.1 + .8 * k, .2 + .1 * face_index))
edges = {TOOL["edge_key"](*e.vertices): e for e in mesh.edges}
assert (0, 1) not in edges
assert edges[0, 3].use_seam and edges[1, 3].use_seam
uses = TOOL["incidence"]({f.index: list(f.vertices) for f in mesh.polygons})
assert all(Counter(forward for _, forward in uses[edge]) == {True: 1, False: 1}
           for edge in ((0, 3), (1, 3)))
assert not any(r["edge"] == [0, 1] for r in TOOL["scan"](sample, .0003, .0001))

fold = fixture("Reversed", faces=[TEST_FACES[0], TEST_FACES[1][::-1], TEST_FACES[2]])
bpy.context.view_layer.update()
reject(fold, PLAN, "Missing unique opposite")
overlap = fixture("FoldedOverlap", vertices=[(0, 0, 0), (2, 0, 0), (0, 1, 0), (.5, 0, 0), (1, .2, 0)],
                  faces=TEST_FACES)
bpy.context.view_layer.update()
reject(overlap, PLAN, "Possible folded overlap")
bent = fixture("RightAngle", vertices=[(0, 0, 0), (2, 0, 0), (0, 1, 0), (.5, 0, 0), (1, 0, 1)],
               faces=TEST_FACES)
bpy.context.view_layer.update()
assert TOOL["split"](bent, PLAN, .0003, .0001) == (1, 1)
data = fixture("ExtraData")
data.data.attributes.new("External", type="FLOAT", domain="POINT")
reject(data, PLAN, "Unsupported attributes")

# A plan with several vertices on the same edge preserves their real order.
multi = fixture("TwoKnots", vertices=[(0, 0, 0), (3, 0, 0), (0, 1, 0), (.5, 0, 0),
                                     (1, 0, 0), (1, -1, 0)],
                faces=[(0, 1, 2), (1, 4, 5), (4, 3, 5), (3, 0, 5)])
bpy.context.view_layer.update()
assert TOOL["split"](multi, {"splits": [{"edge": [0, 1], "vertices": [4, 3]}]}, .0003, .0001) == (1, 1)
assert list(next(f for f in multi.data.polygons if len(f.vertices) == 5).vertices) == [0, 3, 4, 1, 2]
print("PASS: read-only scan, ordered split, UV and material, opposed seam, conservative refusal")

# Repeat from a saved fixture with the actual command line and reopen its output.
import json
import subprocess
from uuid import uuid4

prefix = f"junction-test-{uuid4().hex}"
src = ROOT / (prefix + "-fixture.blend")
dst = ROOT / (prefix + "-stitched.blend")
report = ROOT / (prefix + "-scan.json")
plan_file = ROOT / (prefix + "-split.json")
try:
    plan_file.write_text(json.dumps(PLAN), encoding="utf-8")
    cli = fixture("CommandLineFixture")
    prepare_uv(cli.data)
    bpy.context.preferences.filepaths.save_version = 0
    bpy.ops.wm.save_as_mainfile(filepath=str(src))
    baseline = src.read_bytes()
    base = [bpy.app.binary_path, "--factory-startup", "-b", str(src), "-t", "2", "--python-exit-code", "1",
            "--python", str(ROOT.parent / "src" / "t-junctions.py"), "--"]
    common = ["--object", cli.name, "--distance", ".0003"]
    subprocess.run(base + ["scan", *common, "--report", str(report)], check=True)
    audit = json.loads(report.read_text(encoding="utf-8"))
    assert [0, 1] in [r["edge"] for r in audit["candidates"]]
    subprocess.run(base + ["split", *common, "--plan", str(plan_file), "--output", str(dst)], check=True)
    assert src.read_bytes() == baseline
    bpy.ops.wm.open_mainfile(filepath=str(dst))
    result = bpy.data.objects["CommandLineFixture"].data
    assert len(result.vertices) == len(TEST_VERTICES) and len(result.polygons) == len(TEST_FACES)
    corrected = next(f for f in result.polygons if len(f.vertices) == 4)
    assert list(corrected.vertices) == [0, 3, 1, 2] and corrected.material_index == 1
    check_uv(result.uv_layers["UVMap"].uv[corrected.loop_start + 1].vector, (.3, .2))
finally:
    for path in (src, dst, report, plan_file):
        path.unlink(missing_ok=True)
print('PASS: background commands, original file unchanged, saved repair reopened')
