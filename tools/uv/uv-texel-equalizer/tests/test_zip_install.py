"""Synthetic 1.1 ZIP import/registration smoke check; no user project."""
import sys
from pathlib import Path
import bpy

base = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(base / 'dist/uv_texel_equalizer_v1_1_0.zip'))
import uv_texel_equalizer as addon

assert addon.bl_info['version'] == (1, 1, 0)
addon.register()
assert bpy.context.scene.texel_equalizer.up_axis == 'Z'
assert bpy.context.scene.texel_equalizer.fallback_axis == 'Y'
assert bpy.ops.uv.texel_equalizer_orientation_fix.get_rna_type().identifier == 'UV_OT_texel_equalizer_orientation_fix'
addon.register()
addon.unregister()
assert not hasattr(bpy.types.Scene, 'texel_equalizer')
print('ZIP 1.1 PASS: direct import, registration, defaults, operator, rerun, unregister')
