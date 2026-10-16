import bpy,bmesh,math,importlib.util,json
from pathlib import Path
BASE=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('texel_orientation',BASE/'src/uv_texel_equalizer.py');mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
tests=[]
def run(name,fn):fn();tests.append(name);print('PASS',name)
def object_mesh(verts,faces,uvs):
 if bpy.context.object and bpy.context.object.mode!='OBJECT':bpy.ops.object.mode_set(mode='OBJECT')
 m=bpy.data.meshes.new('orientation_test');m.from_pydata(verts,[],faces);m.update();layer=m.uv_layers.new(name='MyUV')
 for f,coords in zip(m.polygons,uvs):
  for li,uv in zip(f.loop_indices,coords):layer.data[li].uv=uv
 o=bpy.data.objects.new('orientation_test',m);bpy.context.collection.objects.link(o);bpy.ops.object.select_all(action='DESELECT');o.select_set(True);bpy.context.view_layer.objects.active=o;return o
def plane():return object_mesh([(0,0,0),(1,0,0),(1,0,1),(0,0,1)],[(0,1,2,3)],[[(0,0),(.2,0),(.2,.2),(0,.2)]])
def coords(o):return [tuple(l.uv) for l in o.data.uv_layers.active.data]
def transform(o,angle=0,reflect=False,width=2048,height=2048):
 uv=coords(o);p=[(u*width,v*height) for u,v in uv];cx=(min(q[0] for q in p)+max(q[0] for q in p))/2;cy=(min(q[1] for q in p)+max(q[1] for q in p))/2;c,s=math.cos(math.radians(angle)),math.sin(math.radians(angle))
 for loop,(x,y) in zip(o.data.uv_layers.active.data,p):
  x-=cx;y-=cy
  if reflect:x=-x
  loop.uv=((cx+c*x-s*y)/width,(cy+s*x+c*y)/height)
def correct(o,**kw):
 before=mod.equalize(o,width=kw.get('width',2048),height=kw.get('height',2048),strict=False)
 r=mod.orient(o,apply=True,**kw);after=mod.orient(o,**kw)
 assert not after['mirrored_islands'] and not after['rotated_islands'] and not after['ambiguous_islands'],after
 density=mod.equalize(o,width=kw.get('width',2048),height=kw.get('height',2048),strict=False)
 assert abs(density['target_px_m']/before['target_px_m']-1)<1e-5
 return r
def already():
 o=plane();before=coords(o);r=mod.orient(o);assert r['details'][0]['upright'] and not r['mirrored_islands'];assert mod.orient(o,apply=True)['already_correct'];assert coords(o)==before
run('upright vertical window is unchanged',already)
for angle in [90,180,-90,37]:
 def rotated(angle=angle):
  o=plane();transform(o,angle);assert not mod.orient(o)['details'][0]['upright'];correct(o)
 run('rotation '+str(angle)+' degrees corrected with density preserved',rotated)
def mirror():
 o=plane();transform(o,reflect=True);assert mod.orient(o)['mirrored_islands']==[1];r=correct(o);assert r['changed_islands']==[1]
run('mirrored island corrected as a whole',mirror)
def both():
 o=plane();transform(o,143,True);r=mod.orient(o);assert r['mirrored_islands']==[1];correct(o)
run('reflection plus arbitrary rotation',both)
def horizontal():
 o=object_mesh([(0,0,0),(1,0,0),(1,1,0),(0,1,0)],[(0,1,2,3)],[[(0,0),(.2,0),(.2,.2),(0,.2)]]);transform(o,180);r=mod.orient(o);assert r['details'][0]['fallback_used'] and r['details'][0]['world_axis_used']=='Y';correct(o)
run('horizontal island uses world Y fallback',horizontal)
def world():
 o=plane();o.rotation_euler[1]=math.pi/2;bpy.context.view_layer.update();r=mod.orient(o);assert not r['details'][0]['upright'];correct(o)
run('world-space rotation of the object is respected',world)
def negative():
 o=plane();o.scale.x=-1;bpy.context.view_layer.update();assert mod.orient(o)['mirrored_islands']==[1];correct(o)
run('negative object scale handedness',negative)
def curved():
 o=object_mesh([(0,0,0),(1,0,0),(1,0,1),(0,0,1),(1,1,0),(1,1,1)],[(0,1,2,3),(1,4,5,2)],
               [[(0,0),(.2,0),(.2,.2),(0,.2)],[(.2,0),(.4,0),(.4,.2),(.2,.2)]])
 transform(o,90);assert mod.orient(o)['islands']==1;correct(o)
 assert mod.orient(o)['islands']==1
run('curved vertical island remains connected',curved)
def contradictory():
 o=object_mesh([(0,0,0),(1,0,0),(1,0,1),(0,0,1),(1,1,0),(0,1,0)],[(0,1,2,3),(3,2,4,5)],
               [[(0,0),(.2,0),(.2,.2),(0,.2)],[(0,.2),(.2,.2),(.2,.4),(0,.4)]])
 r=mod.orient(o);assert r['ambiguous_islands']==[1];before=coords(o)
 try:mod.orient(o,apply=True)
 except mod.TexelError:pass
 else:raise AssertionError('must refuse conflicting directions')
 assert coords(o)==before
run('conflicting up directions abort atomically',contradictory)
def rectimage():
 o=plane()
 for loop in o.data.uv_layers.active.data:loop.uv.x*=.5
 transform(o,37,width=4096,height=2048);correct(o,width=4096,height=2048)
run('pixel-space rotation preserves shape on rectangular images',rectimage)
def pinned():
 o=plane();transform(o,180);o.data.uv_layers.active.data[0].pin_uv=True;before=coords(o)
 try:mod.orient(o,apply=True)
 except mod.TexelError:pass
 else:raise AssertionError('pin must block')
 assert coords(o)==before
run('orientation pin protection',pinned)
def edit():
 o=plane();transform(o,90);bpy.ops.object.mode_set(mode='EDIT');bm=bmesh.from_edit_mesh(o.data);bm.faces.ensure_lookup_table();bm.faces[0].hide_set(True)
 r=mod.orient(o,apply=True);assert r['applied'] and o.mode=='EDIT' and bm.faces[0].hide
 bpy.ops.object.mode_set(mode='OBJECT');assert mod.orient(o)['details'][0]['upright']
run('Edit Mode preserves hiding and mode',edit)
def shared():
 o=plane();transform(o,90);other=bpy.data.objects.new('orientation_linked',o.data);bpy.context.collection.objects.link(other);before=coords(other);correct(o);assert o.data!=other.data and coords(other)==before
run('shared data is separated for orientation',shared)
def overlap():
 uv=[[(0,0),(.4,0),(.4,.1),(0,.1)],[(.32,.02),(.42,.02),(.42,.12),(.32,.12)]]
 o=object_mesh([(0,0,0),(4,0,0),(4,0,1),(0,0,1),(5,0,0),(6,0,0),(6,0,1),(5,0,1)],[(0,1,2,3),(4,5,6,7)],uv)
 c,s=0,1
 for li in o.data.polygons[0].loop_indices:
  loop=o.data.uv_layers.active.data[li];x,y=loop.uv.x-.2,loop.uv.y-.05;loop.uv=(.2-y,.05+x)
 before=coords(o)
 try:mod.orient(o,apply=True)
 except mod.TexelError as error:assert 'пересечение' in str(error),str(error)
 else:raise AssertionError('overlap must abort')
 assert coords(o)==before
run('rotation cannot introduce new island intersections',overlap)
def operators():
 o=plane();transform(o,180);mod.register();assert bpy.ops.uv.texel_equalizer_orientation_audit()=={'FINISHED'};assert bpy.ops.uv.texel_equalizer_orientation_fix()=={'FINISHED'};mod.unregister()
run('new UI operators register and execute',operators)
(BASE/'reports/current/texel-orientation-tests.json').write_text(json.dumps(dict(passed=len(tests),tests=tests),indent=2),encoding='utf-8')
print('ALL ORIENTATION TESTS PASSED',len(tests))
