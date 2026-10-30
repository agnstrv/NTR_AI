"""Restore Roma's generic plant card inside Blender; importing creates no objects."""

import json
import math
from pathlib import Path


def create_plant_card(name="plant-card-template", size_m=(3.0, 3.0, 4.0), collection=None):
    """Create an upright card in metres, with its planting base at the origin.

    size_m is world X width, world Y depth, world Z height. Existing objects
    and the current selection are preserved. The returned object is at (0, 0, 0).
    """
    import bpy

    size = tuple(float(value) for value in size_m)
    if len(size) != 3 or any(not math.isfinite(value) or value <= 0 for value in size):
        raise ValueError("size_m must contain three positive finite dimensions in metres")
    unit_scale = float(bpy.context.scene.unit_settings.scale_length)
    if not math.isfinite(unit_scale) or unit_scale <= 0:
        raise ValueError("The scene must have a positive finite unit scale")

    path = Path(__file__).resolve().parent.parent / "assets" / "plant-card.json"
    asset = json.loads(path.read_text(encoding="utf-8"))
    if asset["schema_version"] != 1 or asset["units"] != "metres":
        raise ValueError("Unsupported plant card template schema or units")

    # Asset vertices are metres; Blender vertices use scene units.
    factors = [size[i] / asset["base_size_m"][i] / unit_scale for i in range(3)]
    vertices = [[point[i] * factors[i] for i in range(3)] for point in asset["vertices"]]
    target = collection if collection is not None else bpy.context.collection
    mesh = bpy.data.meshes.new(name + "-mesh")
    obj = None
    try:
        mesh.from_pydata(vertices, [], asset["faces"])
        mesh.update()
        uv = mesh.uv_layers.new(name=asset["uv_layer_name"])
        for polygon, coordinates in zip(mesh.polygons, asset["uv_faces"], strict=True):
            for loop_index, coordinate in zip(polygon.loop_indices, coordinates, strict=True):
                uv.data[loop_index].uv = coordinate
        obj = bpy.data.objects.new(name, mesh)
        obj["plant_card_template"] = "album-plant-placement/assets/plant-card.json"
        obj["template_schema_version"] = asset["schema_version"]
        obj["requested_size_m"] = list(size)
        target.objects.link(obj)
        return obj
    except Exception:
        if obj is not None:
            bpy.data.objects.remove(obj, do_unlink=True)
        if mesh.users == 0:
            bpy.data.meshes.remove(mesh)
        raise
