import bpy,bmesh,json,time,numpy as np
from pathlib import Path
from mathutils import Vector
R=Path(__file__).resolve().parents[1];bpy.ops.wm.open_mainfile(filepath=str(R/'outputs/Impost_Before.blend'))
o=bpy.data.objects['WindowFrameSource'];original_matrix=o.matrix_world.copy();o.data=o.data.copy()
b=bmesh.new();b.from_mesh(o.data);scale=bpy.context.scene.unit_settings.scale_length;M=o.matrix_world.to_3x3()*scale;inv=M.inverted()
for v in b.verts:v.co=M@v.co
filled=bmesh.ops.holes_fill(b,edges=[e for e in b.edges if e.is_boundary],sides=0)['faces'];bmesh.ops.recalc_face_normals(b,faces=list(b.faces));b.normal_update();b.verts.ensure_lookup_table();b.verts.index_update()
seen=set();cs=[]
def hull(q):
 q=sorted(set(q))
 def cross(o,a,c):return (a[0]-o[0])*(c[1]-o[1])-(a[1]-o[1])*(c[0]-o[0])
 lo=[];hi=[]
 for p in q:
  while len(lo)>1 and cross(lo[-2],lo[-1],p)<=1e-10:lo.pop()
  lo.append(p)
 for p in reversed(q):
  while len(hi)>1 and cross(hi[-2],hi[-1],p)<=1e-10:hi.pop()
  hi.append(p)
 return np.array(lo[:-1]+hi[:-1])
def overlap(a,c):
 if len(a)<3 or len(c)<3:return False
 for poly in (a,c):
  for j,p in enumerate(poly):
   d=poly[(j+1)%len(poly)]-p;n=np.array([-d[1],d[0]]);aa=a@n;cc=c@n
   if min(aa.max(),cc.max())-max(aa.min(),cc.min())<1e-7:return False
 return True
for v in b.verts:
 if v in seen:continue
 todo=[v];seen.add(v);vs=[]
 while todo:
  w=todo.pop();vs.append(w)
  for e in w.link_edges:
   t=e.other_vert(w)
   if t not in seen:seen.add(t);todo.append(t)
 fs=set(f for w in vs for f in w.link_faces);groups={}
 for f in fs:
  n=f.normal.copy();d=n.dot(f.verts[0].co);key=(tuple(round(x,4) for x in n),round(d,4));groups.setdefault(key,[]).append(f)
 patches=[]
 for fs in groups.values():
  n=fs[0].normal.copy();pvs=set(v for f in fs for v in f.verts);d=n.dot(fs[0].verts[0].co);axis=min(range(3),key=lambda i:abs(n[i]));u=n.cross(Vector(tuple(1 if i==axis else 0 for i in range(3)))).normalized();w=n.cross(u)
  pts=np.array([tuple(v.co) for v in pvs]);patches.append({'n':np.array(n),'d':d,'vs':pvs,'u':np.array(u),'w':np.array(w),'pts':pts,'move':0.0})
 pts=np.array([tuple(v.co) for v in vs]);cs.append({'min':pts.min(0),'max':pts.max(0),'patches':patches})
mins=np.array([c['min'] for c in cs]);maxs=np.array([c['max'] for c in cs]);pairs=0;connections=[]
for i,c in enumerate(cs):
 candidates=np.where(np.all(maxs>=c['min']-.050002,axis=1)&np.all(mins<=c['max']+.050002,axis=1))[0]
 for j in candidates:
  if j<=i:continue
  for a in c['patches']:
   for z in cs[j]['patches']:
    if a['n']@z['n']>-.99999:continue
    gap=float(z['pts'][0]@a['n']-a['d'])
    if not -1e-6<gap<=.050003:continue
    aa=hull([tuple(x) for x in np.column_stack((a['pts']@a['u'],a['pts']@a['w']))]);zz=hull([tuple(x) for x in np.column_stack((z['pts']@a['u'],z['pts']@a['w']))])
    if overlap(aa,zz):
     move=gap/2+5e-4;a['move']=max(a['move'],move);z['move']=max(z['move'],move);connections.append((int(i),int(j),gap));pairs+=1
 if i%1000==0:print('PROXIMITY',i,pairs,flush=True)
deltas={}
for c in cs:
 for p in c['patches']:
  if p['move']:
   d=Vector(p['n'])*p['move']
   for v in p['vs']:deltas[v]=deltas.get(v,Vector())+d
for v,d in deltas.items():v.co+=d
uv=b.loops.layers.uv.active
filled_set=set(filled)
if uv:
 for f in filled:
  for l in f.loops:
   refs=[q[uv].uv.copy() for g in l.vert.link_faces if g not in filled_set for q in g.loops if q.vert==l.vert]
   if refs:l[uv].uv=sum(refs,Vector((0,0)))/len(refs)
bmesh.ops.recalc_face_normals(b,faces=list(b.faces));b.to_mesh(o.data);b.free()
prepared=o.copy();prepared.data=o.data.copy();prepared.name='_UVReference';prepared.matrix_world.identity();bpy.data.libraries.write(str(R/'work/UVReference.blend'),{prepared},fake_user=True)
bpy.data.objects.remove(prepared)
bpy.ops.object.select_all(action='DESELECT');o.select_set(True);bpy.context.view_layer.objects.active=o
print('BEFORE_UNION',len(cs),pairs,len(deltas),flush=True);bpy.ops.object.mode_set(mode='EDIT');bpy.ops.mesh.select_all(action='SELECT');o.matrix_world.identity();bpy.ops.mesh.separate(type='LOOSE');bpy.ops.object.mode_set(mode='OBJECT')
parts=list(bpy.context.selected_objects);col=bpy.data.collections.new('_BooleanParts');bpy.context.scene.collection.children.link(col)
for part in parts:
 for c in list(part.users_collection):c.objects.unlink(part)
 col.objects.link(part)
root=bpy.data.objects.new('_UnionRoot',bpy.data.meshes.new('_Empty'));bpy.context.scene.collection.objects.link(root);mod=root.modifiers.new('Union','BOOLEAN');mod.operation='UNION';mod.operand_type='COLLECTION';mod.collection=col;mod.solver='MANIFOLD'
print('MANIFOLD_START',len(parts),flush=True);bpy.context.view_layer.update();result=bpy.data.meshes.new_from_object(root.evaluated_get(bpy.context.evaluated_depsgraph_get()));print('MANIFOLD_RESULT',len(result.vertices),len(result.polygons),flush=True)
assert len(result.polygons)>0
for c in list(o.users_collection):c.objects.unlink(o)
bpy.context.scene.collection.objects.link(o);o.data=result
for part in parts:
 if part!=o:bpy.data.objects.remove(part,do_unlink=True)
bpy.data.objects.remove(root,do_unlink=True);bpy.data.collections.remove(col);bpy.context.view_layer.objects.active=o;o.select_set(True)
b=bmesh.new();b.from_mesh(o.data);bmesh.ops.recalc_face_normals(b,faces=list(b.faces));b.normal_update()
seen=set();sizes=[]
for v in b.verts:
 if v in seen:continue
 todo=[v];seen.add(v);count=0
 while todo:
  w=todo.pop();count+=1
  for e in w.link_edges:
   t=e.other_vert(w)
   if t not in seen:seen.add(t);todo.append(t)
 sizes.append(count)
r={'components_before':len(cs),'components_after':len(sizes),'faces_before':61444,'faces_after':len(b.faces),'vertices_after':len(b.verts),'filled_caps':len(filled),'proximity_face_pairs':pairs,'maximum_gap_m':max((x[2] for x in connections),default=0),'boundary_edges':sum(e.is_boundary for e in b.edges),'nonmanifold_edges':sum(not e.is_manifold for e in b.edges),'component_sizes':sizes}
for v in b.verts:v.co=inv@v.co
b.to_mesh(o.data);b.free();o.matrix_world=original_matrix;o.data.update();o.data.materials.clear();r['uv_layers']=[u.name for u in o.data.uv_layers]
(R/'work/result.json').write_text(json.dumps(r,indent=2));print('RESULT',json.dumps(r),flush=True)
bpy.ops.wm.save_as_mainfile(filepath=str(R/'outputs/Impost_Unified.blend'))




