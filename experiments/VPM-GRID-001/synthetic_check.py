"""Blender 5.0 regression on synthetic geometry and generated solid UDIMs only.
Run with --background --factory-startup --python-exit-code 1 --python this_file.
The check resets the scene; never run it in a production session.
"""
import bpy,bmesh,runpy,json,zlib,struct
from pathlib import Path
from mathutils import Vector
ROOT=Path(__file__).resolve().parent
CODE=ROOT/'scripts'
WORK=ROOT/'.synthetic-work'
WORK.mkdir(exist_ok=True)
bpy.ops.wm.read_factory_settings(use_empty=True)
for tile in (1001,1004):
 def chunk(kind,data):return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
 png=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',16,16,8,2,0,0,0))+chunk(b'IDAT',zlib.compress((b'\0'+bytes((80,80,80))*16)*16))+chunk(b'IEND',b'')
 (WORK/f'pattern.{tile}.png').write_bytes(png)
image=bpy.data.images.load(str(WORK/'pattern.1001.png'));image.source='TILED';image.filepath=str(WORK/'pattern.<UDIM>.png');image.tiles.new(1004);image.reload()
mat=bpy.data.materials.new('Synthetic UDIM');mat.use_nodes=True
node=mat.node_tree.nodes.new('ShaderNodeTexImage');node.image=image
mat.node_tree.links.new(node.outputs['Color'],mat.node_tree.nodes.get('Principled BSDF').inputs['Base Color'])
helper=runpy.run_path(str(CODE/'vpm_cut_weld_main009.py'))
def plane(name,x0,x1):
 mesh=bpy.data.meshes.new(name);mesh.from_pydata([(x0,0,0),(x1,0,0),(x1,0,4),(x0,0,4)],[],[(0,1,2,3)])
 o=bpy.data.objects.new(name,mesh);bpy.context.collection.objects.link(o)
 mesh.uv_layers.new(name='UVMap');mesh.materials.append(mat)
 return o
results=[]
for suffix in ('006','010'):
 for o in list(bpy.context.scene.objects):bpy.data.objects.remove(o,do_unlink=True)
 main=plane('Main',0,4);part=plane('VPM.'+suffix,4,8)
 main['vpm_density']=1000.;main['vpm_resolution']=2048
 bm=bmesh.new();bm.from_mesh(main.data);uv=bm.loops.layers.uv['UVMap']
 for axis in (0,2):
  for x in helper['grid'](0,4,2.048):
   p=Vector((0,0,0));p[axis]=x;n=Vector((0,0,0));n[axis]=1
   bmesh.ops.bisect_plane(bm,geom=list(bm.verts)+list(bm.edges)+list(bm.faces),dist=1e-7,plane_co=p,plane_no=n)
 for f in bm.faces:
  for l in f.loops:l[uv].uv=(l.vert.co.x/2.048,l.vert.co.z/2.048)
 bm.to_mesh(main.data);bm.free()
 bpy.context.view_layer.objects.active=part;part.select_set(True)
 s=runpy.run_path(str(CODE/f'vpm_cut_main{suffix}_1004.py'));s['ROOT']=CODE
 # Imported functions keep their own module globals; redirect only report output.
 fn=s['run'];fn.__globals__['ROOT']=CODE
 r=fn(None)
 assert r['faces_after']>1 and r['Main_UV_error']==0 and r['matching_interface_vertices']>=3
 assert r['cell_subdivision']==1 and r['step_XYZ_m']==[2.048]*3
 assert r['UV_bounds'][0][0]>=3 and r['UV_bounds'][0][1]<=4
 results.append({'test':'cut_'+suffix,'faces_after':r['faces_after'],'matches':r['matching_interface_vertices'],'pass':True})
for o in list(bpy.context.scene.objects):bpy.data.objects.remove(o,do_unlink=True)
o=plane('SyntheticMirror',0,1);uv=o.data.uv_layers.active
for i,q in enumerate(((3.1,.1),(3.1,.9),(3.9,.9),(3.9,.1))):uv.data[i].uv=q
bpy.context.view_layer.objects.active=o;o.select_set(True)
s=runpy.run_path(str(CODE/'fix_mirrored_uv.py'));fn=s['run'];fn.__globals__['ROOT']=WORK
r=fn(False);assert r[0]['mirrored_faces_corrected']==1 and r[0]['negative_UV_faces_after']==0
assert r[0]['details'][0]['udim']==1004
results.append({'test':'negative_uv_same_udim','pass':True})
for suffix in ('006','010'):
 (CODE/f'Main{suffix}_1004_report.json').unlink(missing_ok=True)
data={'Blender':bpy.app.version_string,'fixture':'synthetic planes and solid generated UDIM','checks':results,'pass':True}
(ROOT/'reports'/'synthetic_check.json').write_text(json.dumps(data,indent=2))
print('SYNTHETIC_CHECK_OK',json.dumps(data),flush=True)
