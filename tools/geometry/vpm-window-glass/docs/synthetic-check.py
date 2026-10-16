"""Synthetic-only Blender check. Never opens or saves a .blend file."""
from pathlib import Path
import importlib.util, json, ast
import bpy, bmesh, numpy as np

ROOT=Path(__file__).resolve().parents[1]
modules={}
for path in sorted((ROOT/'src/outputs').glob('*.py')):
    ast.parse(path.read_text(encoding='utf-8'))
    spec=importlib.util.spec_from_file_location(path.stem,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    modules[path.stem]=module
checks=['seven output modules compile and import without main execution']
assert len(modules)==7

infill=modules['window_infill_planes']
square=np.array([[0.,0.],[1.,0.],[1.,1.],[0.,1.]])
expanded=infill.expand(square)
assert np.allclose(expanded.min(0),[-.02,-.02])
assert np.allclose(expanded.max(0),[1.02,1.02])
assert abs(infill.area(expanded)-1.04**2)<1e-10
clipped=infill.clip(square,.5,True)
assert abs(infill.area(clipped)-.5)<1e-10
checks+=['infill square expands by 2 cm and preserves expected area','infill clipping retains half of unit square']

continuous=modules['window_continuous_infill']
s,total=continuous.project(np.array([[.5,.2],[1.5,-.3]]),np.array([[0.,0.],[2.,0.]]))
assert np.allclose(s,[.5,1.5]) and np.allclose(total,[0.,2.])
checks+=['continuous profile projection on straight synthetic segment']

cleanup=modules['window_plane_cleanup']
mesh=bpy.data.meshes.new('synthetic-junction')
mesh.from_pydata([(0,0,0),(2,0,0),(2,1,0),(0,1,0),(1,0,0),(1,-1,0),(0,-1,0)],[],[(0,1,2,3),(0,4,5,6)])
bm=bmesh.new();bm.from_mesh(mesh)
before=cleanup.junctions(bm,1e-5)
assert before
cleanup.connect_junctions(bm,1e-5)
assert not cleanup.junctions(bm,1e-5)
bm.free();bpy.data.meshes.remove(mesh)
checks+=['synthetic T-junction found and connected']

bpy.context.scene.unit_settings.scale_length=.01
try:
    modules['window_planes'].create_window_planes(source_name='missing-synthetic-source')
except ValueError:
    checks+=['missing source rejected before scene mutation']
else:
    raise AssertionError('missing source accepted')

result={'blender':bpy.app.version_string,'checks':checks,'passed':len(checks),
        'scope':'synthetic helpers and import only; no client scene, no end-to-end window reconstruction'}
(ROOT/'cases').mkdir(exist_ok=True)
(ROOT/'cases/synthetic-check.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(result,ensure_ascii=False))
