"""Headless Blender integration tests; no user project is opened or written."""
import bpy,bmesh,importlib.util,math,json
from pathlib import Path
BASE=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('uv_texel_equalizer',BASE/'src/uv_texel_equalizer.py')
mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
tests=[]
def run(name,fn):
 fn();tests.append(name);print('PASS',name)
def activate(o):
 if bpy.context.object and bpy.context.object.mode!='OBJECT':bpy.ops.object.mode_set(mode='OBJECT')
 bpy.ops.object.select_all(action='DESELECT');o.select_set(True);bpy.context.view_layer.objects.active=o
def squares(scales=(.1,.2),uv_offsets=((0,0),(2,0)),size=(1,1)):
 verts=[];faces=[]
 for i in range(len(scales)):
  start=len(verts);x=i*3;w,h=size
  verts.extend([(x,0,0),(x+w,0,0),(x+w,h,0),(x,h,0)]);faces.append(list(range(start,start+4)))
 mesh=bpy.data.meshes.new('texel_test');mesh.from_pydata(verts,[],faces);mesh.update();layer=mesh.uv_layers.new(name='CustomUV')
 for f,s,off in zip(mesh.polygons,scales,uv_offsets):
  for li,xy in zip(f.loop_indices,[(0,0),(s*size[0],0),(s*size[0],s*size[1]),(0,s*size[1])]):layer.data[li].uv=(xy[0]+off[0],xy[1]+off[1])
 o=bpy.data.objects.new('texel_test',mesh);bpy.context.collection.objects.link(o);activate(o);return o
def coords(o):return [tuple(x.uv) for x in o.data.uv_layers.active.data]
def assert_close(a,b,t=1e-5):assert abs(a-b)<=t*max(1,abs(b)),(a,b)
def basic():
 o=squares();before=coords(o);geometry=[tuple(v.co) for v in o.data.vertices];r=mod.equalize(o)
 assert r['islands']==2 and not r['blocked'];assert coords(o)==before
 assert_close(r['target_px_m'],2048*math.sqrt(.025))
 r=mod.equalize(o,apply=True);assert r['applied'] and r['max_relative_error_after']<1e-5
 assert geometry==[tuple(v.co) for v in o.data.vertices]
 again=mod.equalize(o,apply=True);assert not again['applied'] and again['already_equal']
 assert_close(sum(s['pixel_area'] for s in mod.equalize(o)['details']),sum(s['pixel_area'] for s in r['details']))
run('RMS mean, equalization, geometry unchanged, idempotence',basic)
def arithmetic():
 o=squares();r=mod.equalize(o,apply=True,average='ARITHMETIC');assert_close(r['target_px_m'],307.2)
run('arithmetic mean',arithmetic)
def seams():
 m=bpy.data.meshes.new('adjacent');m.from_pydata([(0,0,0),(1,0,0),(2,0,0),(0,1,0),(1,1,0),(2,1,0)],[],[(0,1,4,3),(1,2,5,4)]);m.uv_layers.new(name='UV')
 o=bpy.data.objects.new('adjacent',m);bpy.context.collection.objects.link(o);activate(o)
 for f in m.polygons:
  for li in f.loop_indices:
   v=m.vertices[m.loops[li].vertex_index];m.uv_layers.active.data[li].uv=(v.co.x*.1,v.co.y*.1)
 assert mod.equalize(o)['islands']==1
 for li in m.polygons[1].loop_indices:m.uv_layers.active.data[li].uv.x+=1
 assert mod.equalize(o)['islands']==2
run('UV continuity joins faces; actual seam separates',seams)
def rectangle():
 o=squares(scales=(.1,),uv_offsets=((0,0),));layer=o.data.uv_layers.active
 for l in layer.data:l.uv.x*=2
 r=mod.equalize(o);assert r['blocked'];assert r['details'][0]['max_anisotropy']>1.99
 assert r['details'][0]['max_angle_error_deg']>10 # triangle check catches rectangle stretch
 before=coords(o)
 try:mod.equalize(o,apply=True)
 except mod.TexelError:pass
 else:raise AssertionError('should refuse pre-existing stretch')
 assert coords(o)==before
run('rectangular stretch missed by polygon corner angles is detected',rectangle)
def world_scale():
 o=squares();o.scale=(2,3,1);bpy.context.view_layer.update()
 r=mod.equalize(o);assert r['blocked']
 assert_close(r['details'][0]['world_area_m2'],6)
 o.scale=(2,2,2);o.location=(1e6,1e6,1e6);bpy.context.view_layer.update()
 r=mod.equalize(o,apply=True);assert r['applied'];assert_close(r['details'][0]['world_area_m2'],4)
run('nonuniform object scale, world metric, large translations',world_scale)
def rectangular_image():
 o=squares()
 for l in o.data.uv_layers.active.data:l.uv.x*=.5
 r=mod.equalize(o,apply=True,width=4096,height=2048);assert not r['blocked']
run('rectangular texture pixel aspect',rectangular_image)
def pinned():
 o=squares();o.data.uv_layers.active.data[0].pin_uv=True;before=coords(o)
 try:mod.equalize(o,apply=True)
 except mod.TexelError:pass
 else:raise AssertionError('pin protection')
 assert coords(o)==before
run('pinned UV aborts atomically',pinned)
def collapsed():
 o=squares()
 for li in o.data.polygons[0].loop_indices:o.data.uv_layers.active.data[li].uv=(0,0)
 try:mod.equalize(o,apply=True)
 except mod.TexelError:pass
 else:raise AssertionError('collapsed UV')
run('collapsed UV rejected',collapsed)
def linked():
 o=squares();other=bpy.data.objects.new('other',o.data);bpy.context.collection.objects.link(other);before=coords(other)
 mod.equalize(o,apply=True);assert o.data!=other.data and coords(other)==before
run('shared Mesh Data copied without changing other object',linked)
def edit():
 o=squares();bpy.ops.object.mode_set(mode='EDIT');bm=bmesh.from_edit_mesh(o.data);bm.faces.ensure_lookup_table();bm.faces[1].hide_set(True);bm.faces[0].select_set(True)
 r=mod.equalize(o,apply=True);assert r['islands']==2 and r['applied'];assert o.mode=='EDIT';assert bm.faces[1].hide
 bpy.ops.object.mode_set(mode='OBJECT');assert mod.equalize(o)['max_relative_error_before']<1e-5
run('Edit Mode includes hidden faces and preserves mode/hiding',edit)
def overlap():
 # Small island grows into nearby large island; island continuity is unrelated.
 o=squares(scales=(.1,.4),uv_offsets=((0,0),(.12,0)));before=coords(o)
 try:mod.equalize(o,apply=True)
 except mod.TexelError as error:assert 'пересечение' in str(error)
 else:raise AssertionError('new overlap should be blocked')
 assert coords(o)==before
run('new island overlap rejected without UV writes',overlap)
def mirrored():
 o=squares()
 for li in o.data.polygons[1].loop_indices:o.data.uv_layers.active.data[li].uv.x*=-1
 r=mod.equalize(o,apply=True);assert r['applied'] and not r['blocked']
run('uniformly mirrored island remains mirrored',mirrored)
def units():
 o=squares();old=bpy.context.scene.unit_settings.scale_length;bpy.context.scene.unit_settings.scale_length=.01
 r=mod.equalize(o);assert_close(r['details'][0]['density_px_m'],20480)
 bpy.context.scene.unit_settings.scale_length=old
run('scene units in px per meter',units)
def precision():
 o=squares(scales=(.001,.2),uv_offsets=((1000,1000),(2,0)));before=coords(o)
 try:mod.equalize(o,apply=True,strict=False)
 except mod.TexelError:assert coords(o)==before
 else:assert mod.equalize(o)['max_relative_error_before']<1e-5
run('large UV float32 precision checked before committing',precision)
def register():
 mod.register();mod.register();assert hasattr(bpy.types.Scene,'texel_equalizer');mod.unregister()
run('UI registers, reruns and unregisters',register)
(BASE/'reports/current/texel-equalizer-tests.json').write_text(json.dumps(dict(passed=len(tests),tests=tests),ensure_ascii=False,indent=2),encoding='utf-8')
print('ALL PASSED',len(tests))
