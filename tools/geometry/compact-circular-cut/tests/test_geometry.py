import bpy,bmesh,sys,math,json
from pathlib import Path
from mathutils import Vector
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'src'))
r=root.parent/'compact_cut_test_output'
(r/'outputs').mkdir(parents=True,exist_ok=True)
from compact_circular_cut.core import compact_cylinder_difference,_cylinder_profile
from compact_circular_cut import register
for o in list(bpy.data.objects):bpy.data.objects.remove(o,do_unlink=True)
def cutter(n=32,location=(0,0,0),depth=8,scale=(1,1,1),rotation=(0,0,0)):
 bpy.ops.mesh.primitive_cylinder_add(vertices=n,radius=.8,depth=depth,location=location,rotation=rotation)
 o=bpy.context.object;o.scale=scale;o.name=f'Cutter_{n}';return o
def cube():
 bpy.ops.mesh.primitive_cube_add(size=6);o=bpy.context.object;o.name='Target';o.data.uv_layers.new();return o
def validate(o,report,cut,closed):
 assert report['segments']==len(_cylinder_profile(cut)[2])
 bm=bmesh.new();bm.from_mesh(o.data);bm.verts.ensure_lookup_table()
 assert all(len(e.link_faces)<=2 for e in bm.edges)
 assert all(e.is_contiguous for e in bm.edges if len(e.link_faces)==2),'Inconsistent face winding'
 if closed:assert all(len(e.link_faces)==2 for e in bm.edges),('Expected closed result',report['segments'],[(tuple(e.verts[0].co),tuple(e.verts[1].co),len(e.link_faces)) for e in bm.edges if len(e.link_faces)!=2])
 origin=cut.matrix_world.translation.copy();matrix=o.matrix_world.copy();matrix.translation-=origin
 center,axis,profile,length,radius,minimum,u,v=_cylinder_profile(cut,origin)
 projected=[Vector((p.dot(u),p.dot(v))) for p in profile]
 rings=report['contours'];all_circle={bm.verts[i] for ring in rings for i in ring}
 for ri,ring in enumerate(rings):
  for i in ring:
   vert=bm.verts[i];q=matrix@vert.co-center;p=Vector((q.dot(u),q.dot(v)))
   def edge_distance(a,b):
    edge=b-a;t=max(0,min(1,(p-a).dot(edge)/edge.length_squared))
    return (p-a-edge*t).length
   assert min(edge_distance(a,b) for a,b in zip(projected,projected[1:]+projected[:1]))<2e-5,'Rim must stay on the cutter profile'
   if not (report['blind'] and ri==1):
    ns=[e.other_vert(vert) for e in vert.link_edges if e.other_vert(vert) not in all_circle]
    assert ns,'Every rim vertex needs an outer spoke'
    assert min((o.matrix_world.to_3x3()@(w.co-vert.co)).length for w in ns)<radius*.55
 # Every original cutter vertex must still be present, even where source-edge
 # intersections require extra collinear vertices along the cutter edges.
 for ring in rings:
  points=[matrix@bm.verts[i].co-center for i in ring]
  flat=[Vector((q.dot(u),q.dot(v))) for q in points]
  assert all(min((p-q).length for q in flat)<2e-5 for p in projected)
 bm.free()
reports=[];examples=[]
for n in (16,17,32):
 target=cube();cut=cutter(n);rep=compact_cylinder_difference(target,cut);validate(target,rep,cut,True);reports.append(rep);examples.append((target,cut))
# Tilt and nonuniform scale are taken from the cutter, without applying transforms.
target=cube();cut=cutter(24,scale=(1.2,.75,1),rotation=(0,.3,.2));rep=compact_cylinder_difference(target,cut);validate(target,rep,cut,True);reports.append(rep);examples.append((target,cut))
# Applied rotations/scales must not change the cap detection or vertex count.
target=cube();cut=cutter(20,rotation=(.1,.2,.3));bpy.context.view_layer.objects.active=cut;bpy.ops.object.transform_apply(location=False,rotation=True,scale=True)
rep=compact_cylinder_difference(target,cut);validate(target,rep,cut,True);reports.append(rep);examples.append((target,cut))
# Blind recess: a cutter end lies inside the closed mesh.
target=cube();cut=cutter(16,location=(0,0,3),depth=2);rep=compact_cylinder_difference(target,cut);validate(target,rep,cut,True);assert rep['blind'];reports.append(rep);examples.append((target,cut))
# Building-sized world coordinates and shared mesh data.
target=cube();target.location=(5043,15165,176);other=bpy.data.objects.new('Shared_original',target.data);bpy.context.collection.objects.link(other);original_count=len(other.data.vertices)
cut=cutter(24,location=(5043,15165,176),rotation=(.13,.21,.3));rep=compact_cylinder_difference(target,cut);validate(target,rep,cut,True);assert len(other.data.vertices)==original_count and other.data!=target.data;reports.append(rep)
target.hide_set(True);target.hide_render=True;other.hide_set(True);other.hide_render=True;cut.hide_set(True);cut.hide_render=True
# Convex sheet, no face selection required.
vertices=[];faces=[];n=20
for j in range(n+1):
 for i in range(n+1):
  x=-3+i*6/n;y=-3+j*6/n;vertices.append((x,y,.1*x*x+.04*y*y))
for j in range(n):
 for i in range(n):
  a=j*(n+1)+i;faces.append((a,a+1,a+n+2,a+n+1))
mesh=bpy.data.meshes.new('Convex_sheet');mesh.from_pydata(vertices,[],faces);mesh.update();target=bpy.data.objects.new('Convex_sheet',mesh);bpy.context.collection.objects.link(target)
for p in mesh.polygons:p.use_smooth=True
cut=cutter(31,depth=5,scale=(1.2,.8,1));rep=compact_cylinder_difference(target,cut);validate(target,rep,cut,False);reports.append(rep);examples.append((target,cut))
# An unsupported boundary notch must fail without modifying the target.
target=cube();cut=cutter(16,location=(2.8,0,0));original=([v.co[:] for v in target.data.vertices],[p.vertices[:] for p in target.data.polygons])
try:compact_cylinder_difference(target,cut)
except ValueError:pass
else:raise AssertionError('Edge crossing should reject atomically')
assert original==([v.co[:] for v in target.data.vertices],[p.vertices[:] for p in target.data.polygons])
target.hide_set(True);target.hide_render=True;cut.hide_set(True);cut.hide_render=True
# Real operator with the two-object selection workflow.
register();target=cube();cut=cutter(12)
bpy.ops.object.select_all(action='DESELECT');cut.select_set(True);target.select_set(True);bpy.context.view_layer.objects.active=target
assert bpy.ops.mesh.compact_circular_cut(hide_cutter=True)=={'FINISHED'};assert cut.hide_get();examples.append((target,cut))
for i,(target,cut) in enumerate(examples):
 target.location.x=i*8;cut.location.x+=i*8;cut.hide_set(True);cut.hide_render=True
for screen in bpy.data.screens:
 for area in screen.areas:
  if area.type=='VIEW_3D':area.spaces.active.region_3d.view_location=Vector((24,0,0));area.spaces.active.region_3d.view_distance=60
bpy.data.texts.load(str(root/'standalone/circular_cut_compact.py'))
(r/'outputs/cylinder_cut_test_report.json').write_text(json.dumps({'passed':True,'cases':reports,'operator_test':True,'edge_failure_atomic':True},indent=2))
bpy.ops.wm.save_as_mainfile(filepath=str(r/'outputs/cylinder_cut_examples.blend'))
print('CYLINDER_CUT_TESTS_PASSED',[(p['segments'],p['sides'],p['blind']) for p in reports])
