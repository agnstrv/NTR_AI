"""Close NPM-matched window/door holes in the VPM facade with 1 m recesses.
New faces share existing perimeter vertices. New UV islands are packed into UDIM 1004.
"""
import bpy,bmesh,numpy as np,json,math
from pathlib import Path
from collections import Counter
from mathutils import Vector
from mathutils.bvhtree import BVHTree
ROOT=Path(__file__).resolve().parent

def boundary_cycles(bm):
 boundary={e for e in bm.edges if e.is_boundary};cycles=[];failed=[]
 while boundary:
  start=min(boundary,key=lambda e:e.index).link_loops[0];l=start;path=[];seen=set()
  while l.edge not in seen:
   if not l.edge.is_boundary:break
   seen.add(l.edge);path.append(l);boundary.discard(l.edge)
   k=l.link_loop_next;guard=0
   while not k.edge.is_boundary and guard<100:
    if not k.edge.is_manifold:break
    k=k.link_loop_radial_next.link_loop_next;guard+=1
   l=k
  if l==start:cycles.append(path)
  else:failed.append(path)
 return cycles,failed

def pack_charts(charts):
 # Uniform scale, with non-overlapping shelves and a 3-pixel gutter at 2048.
 ordered=sorted(range(len(charts)),key=lambda i:max(charts[i]['size']),reverse=True)
 gap=3/2048
 def fit(scale):
  x=gap;y=gap;row=0;placements={}
  for i in ordered:
   w,h=charts[i]['size'];w*=scale;h*=scale
   if x+w+gap>1:x=gap;y+=row+gap;row=0
   if y+h+gap>1:return None
   placements[i]=(3+x,y,scale);x+=w+gap;row=max(row,h)
  return placements
 lo=0.;hi=1.
 while fit(hi):hi*=2
 for _ in range(45):
  mid=(lo+hi)/2
  if fit(mid):lo=mid
  else:hi=mid
 positions=fit(lo*.999)
 assert positions
 return positions

def run(save_path=None):
 ctx=bpy.context
 if ctx.mode!='OBJECT':bpy.ops.object.mode_set(mode='OBJECT')
 high=ctx.active_object
 assert high and high.type=='MESH' and high.get('vpm_rows_z')==8
 assert not high.get('vpm_recesses_done'),'Recesses already created'
 low=bpy.data.objects['VPM']
 original_mesh=high.data
 work=original_mesh.copy()
 bm=bmesh.new();bm.from_mesh(work);bm.normal_update();bm.verts.ensure_lookup_table();bm.edges.ensure_lookup_table();bm.faces.ensure_lookup_table()
 before_boundary=sum(e.is_boundary for e in bm.edges)
 before_nonmanifold=sum(len(e.link_faces)>2 for e in bm.edges)
 marker=bm.faces.layers.int.get('VPM_Recess') or bm.faces.layers.int.new('VPM_Recess')
 old_vertices=[v.co.copy() for v in bm.verts];old_faces=list(bm.faces)
 uvl=bm.loops.layers.uv.get('VPM_UDIM_Color') or bm.loops.layers.uv.active
 assert uvl
 old_uv={f.index:[l[uvl].uv.copy() for l in f.loops] for f in old_faces}
 cycles,failed=boundary_cycles(bm)
 # A window perimeter can be a simple open chain where the source already has
 # overlapping/nonmanifold wall edges. Complete its missing rim without deleting wall faces.
 from types import SimpleNamespace
 boundary={e for e in bm.edges if e.is_boundary};synthetic=set()
 while boundary:
  todo=[next(iter(boundary))];group=set()
  while todo:
   e=todo.pop()
   if e not in boundary:continue
   boundary.remove(e);group.add(e)
   for v in e.verts:todo.extend(k for k in v.link_edges if k in boundary)
  verts={v for e in group for v in e.verts}
  ends=[v for v in verts if sum(e in group for e in v.link_edges)==1]
  if len(ends)!=2 or any(sum(e in group for e in v.link_edges)>2 for v in verts) or len(group)<4:continue
  # Only short planar chains with a vertical missing segment qualify.
  if (ends[0].co-ends[1].co).xy.length>.01:continue
  points=np.array([tuple(v.co) for v in verts]);delta=np.ptp(points,axis=0)
  if not (.4<delta[2]<6 and max(delta[:2])<20):continue
  current=ends[0];path=[];used=set()
  while len(used)<len(group):
   edge=next(e for e in current.link_edges if e in group and e not in used)
   used.add(edge);path.append(SimpleNamespace(vert=current,edge=edge,face=edge.link_faces[0]))
   current=edge.other_vert(current)
  if path[0].edge.link_loops[0].vert!=path[0].vert:
   current=ends[1];path=[];used=set()
   while len(used)<len(group):
    edge=next(e for e in current.link_edges if e in group and e not in used)
    used.add(edge);path.append(SimpleNamespace(vert=current,edge=edge,face=edge.link_faces[0]));current=edge.other_vert(current)
  edge=bm.edges.new((current,path[0].vert));synthetic.add(edge)
  path.append(SimpleNamespace(vert=current,edge=edge,face=path[0].face));cycles.append(path)
 anchor=high.matrix_world.translation.copy();world=high.matrix_world;inv=world.inverted();normalmat=world.to_3x3().inverted().transposed()
 low.data.calc_loop_triangles();ts=list(low.data.loop_triangles)
 lverts=[low.matrix_world@v.co-anchor for v in low.data.vertices]
 bvh=BVHTree.FromPolygons(lverts,[t.vertices for t in ts],all_triangles=True)
 luv=low.data.uv_layers.active
 def lookup(point,normal):
  p=world@point-anchor
  hit,hn,idx,d=bvh.find_nearest(p)
  if idx is None:return None
  # Sample the same-facing surface, allowing frames near the glass plane.
  choices=bvh.find_nearest_range(p,max(.12,d+.05))
  good=[q for q in choices if q[1].dot(normal)>.7]
  if good:hit,hn,idx,d=min(good,key=lambda q:q[3])
  t=ts[idx];a,b,c=[lverts[i] for i in t.vertices]
  e=b-a;f=c-a;q=hit-a;den=e.dot(e)*f.dot(f)-e.dot(f)**2
  if abs(den)<1e-20:return None
  v=(f.dot(f)*q.dot(e)-e.dot(f)*q.dot(f))/den
  z=(e.dot(e)*q.dot(f)-e.dot(f)*q.dot(e))/den
  uv=luv.data[t.loops[0]].uv*(1-v-z)+luv.data[t.loops[1]].uv*v+luv.data[t.loops[2]].uv*z
  return {'uv':list(uv),'distance':d,'alignment':hn.dot(normal)}
 def window_region(uv):
  u,v=uv
  # NPM atlas: top row is flat wall/roof swatches. Top-right includes door sprites.
  if v>.79:return .005<u<.995
  # Perforated grilles and stone patches aren't windows or doors.
  if u>.61 and .615<v<.78:return False
  if u>.84 and .32<v<.615:return False
  if u>.59 and v<.12:return False
  return .005<u<.995 and .005<v<.99
 accepted=[];rejected=[]
 for ci,path in enumerate(cycles):
  outer=[l.vert for l in path]
  if len(set(outer))!=len(outer):rejected.append({'cycle':ci,'reason':'self-touching boundary'});continue
  center=sum((v.co for v in outer),Vector())/len(outer)
  ar=np.array([tuple(v.co-center) for v in outer]);_,s,vh=np.linalg.svd(ar,full_matrices=False)
  n=Vector(vh[-1]);avg=sum((l.face.normal*l.edge.calc_length() for l in path),Vector())
  if n.dot(avg)<0:n=-n
  nw=(normalmat@n).normalized()
  dims=np.ptp(ar,axis=0);flat=float(np.abs(ar@np.array(n)).max())
  if abs(nw.z)>.35 or dims[2]<.4 or dims[2]>12 or flat>2:
   rejected.append({'cycle':ci,'reason':'exterior/roof boundary','dims':dims.tolist()});continue
  checks=[lookup(center,nw)]+[lookup(center*.5+v.co*.5,nw) for v in outer[::max(1,len(outer)//8)]]
  valid=[q for q in checks if q and q['distance']<2 and q['alignment']>.7 and window_region(q['uv'])]
  if len(valid)<len(checks)*.55:
   rejected.append({'cycle':ci,'reason':'NPM not window/door','checks':checks});continue
  accepted.append({'cycle':ci,'outer':outer,'path':path,'normal':n,'flat':flat,'checks':checks})
 assert accepted,'No matched openings'
 charts=[];new_faces=[];depths=[];caps=0
 # Entire result is built on an unlinked mesh until verification succeeds.
 try:
  for oi,g in enumerate(accepted,1):
   outer=g['outer'];n=g['normal'];inner=[]
   for v in outer:
    if g['flat']<.002:vn=n
    else:
     adjacent=[l.face for l in g['path'] if v in l.edge.verts]
     vn=sum((f.normal*f.calc_area() for f in adjacent),Vector()).normalized()
     if vn.dot(n)<.1:vn=n
     # On curved vertical walls, ignore minor vertical normal noise.
     if abs(vn.z)<.3:vn.z=0;vn.normalize()
    wn=(normalmat@vn).normalized()
    displacement=inv.to_3x3()@(-wn)
    iv=bm.verts.new(v.co+displacement);inner.append(iv)
    depths.append((world.to_3x3()@(iv.co-v.co)).length)
   # Reverse the existing boundary winding to face outward.
   cap=bm.faces.new(list(reversed(inner)));cap[marker]=oi;new_faces.append(cap);caps+=1
   # Project the recessed cap into a plane; keep its aspect ratio.
   axis=Vector((0,0,1)).cross((normalmat@n).normalized()).normalized()
   vertical=Vector((0,0,1))
   raw={v:Vector(((world@v.co).dot(axis),(world@v.co).dot(vertical))) for v in inner}
   lo=Vector((min(q.x for q in raw.values()),min(q.y for q in raw.values())))
   size=(max(q.x for q in raw.values())-lo.x,max(q.y for q in raw.values())-lo.y)
   charts.append({'size':size,'loops':[(l,raw[l.vert]-lo) for l in cap.loops]})
   # One continuous unfolded strip for each opening's reveals.
   chartloops=[];distance=0.
   for i,(a,ia) in enumerate(zip(outer,inner)):
    j=(i+1)%len(outer);b=outer[j];ib=inner[j]
    face=bm.faces.new([b,a,ia,ib]);face[marker]=oi;new_faces.append(face)
    width=(world.to_3x3()@(b.co-a.co)).length
    uvs={b:Vector((distance+width,0)),a:Vector((distance,0)),ia:Vector((distance,1)),ib:Vector((distance+width,1))}
    chartloops.extend((l,uvs[l.vert]) for l in face.loops);distance+=width
    # Seams separate the cap from its reveals, and one strip end.
    e=bm.edges.get((ia,ib));e.seam=True
    bm.edges.get((a,b)).seam=True
    if i==0:bm.edges.get((a,ia)).seam=True
   charts.append({'size':(distance,1.),'loops':chartloops})
  for e in list(synthetic):
   if len(e.link_faces)==0:bm.edges.remove(e);synthetic.remove(e)
  placements=pack_charts(charts)
  for i,c in enumerate(charts):
   x,y,scale=placements[i]
   for l,uv in c['loops']:l[uvl].uv=(x+uv.x*scale,y+uv.y*scale)
  bm.normal_update()
  # Verify original geometry and UVs, exact 1 m movement, manifold recess joins.
  assert all((old_vertices[i]-v.co).length==0 for i,v in enumerate(list(bm.verts)[:len(old_vertices)]))
  for f in old_faces:assert all((l[uvl].uv-u).length==0 for l,u in zip(f.loops,old_uv[f.index]))
  assert max(abs(d-1) for d in depths)<1e-5
  assert all(3<l[uvl].uv.x<4 and 0<l[uvl].uv.y<1 for f in new_faces for l in f.loops)
  assert all(len(e.link_faces)==(1 if e in synthetic else 2) for g in accepted for l in g['path'] for e in [l.edge])
  after_nonmanifold=sum(len(e.link_faces)>2 for e in bm.edges)
  assert after_nonmanifold==before_nonmanifold
  bm.to_mesh(work);work.update()
  # Existing 1001-1003 image stays intact. Add an explicit dark blank tile for recesses.
  image=next(n.image for m in work.materials if m and m.use_nodes for n in m.node_tree.nodes if n.type=='TEX_IMAGE' and n.image and n.image.source=='TILED')
  import shutil
  # Save a portable four-tile set in outputs; the fourth is a plain dark placeholder.
  pattern=bpy.path.abspath(image.filepath)
  for number in (1001,1002,1003):
   src=Path(pattern.replace('<UDIM>',str(number)))
   dst=ROOT/('Facade_With_Openings.%d.png'%number)
   shutil.copyfile(src,dst)
  blank=bpy.data.images.new('Recess tile 1004',width=2048,height=2048,alpha=True)
  blank.generated_color=(.035,.045,.055,1)
  blank.filepath_raw=str(ROOT/'Facade_With_Openings.1004.png');blank.file_format='PNG';blank.save()
  bpy.data.images.remove(blank)
  newimage=image.copy()
  if newimage.packed_file:newimage.unpack(method='REMOVE')
  newimage.filepath=str(ROOT/'Facade_With_Openings.<UDIM>.png')
  if not newimage.tiles.get(1004):newimage.tiles.new(1004,label='Windows and doors recesses')
  newimage.reload();newimage.pack()
  for i,m in enumerate(list(work.materials)):
   if not m or not m.use_nodes:continue
   copied=m.copy();work.materials[i]=copied
   for node in copied.node_tree.nodes:
    if node.type=='TEX_IMAGE' and node.image==image:node.image=newimage
  for screen in bpy.data.screens:
   for area in screen.areas:
    if area.type=='IMAGE_EDITOR':area.spaces.active.image=newimage
  high.data=work
  if original_mesh.users==0:bpy.data.meshes.remove(original_mesh)
  high['vpm_recesses_done']=True;high['vpm_recess_depth_m']=1.;high['vpm_recess_openings']=len(accepted)
  report={'object':high.name,'openings':len(accepted),'recess_depth_m':1,'new_caps':caps,'new_reveal_faces':len(new_faces)-caps,'new_faces':len(new_faces),'new_vertices':len(depths),'depth_error_max_m':max(abs(d-1) for d in depths),'original_geometry_and_UV_unchanged':True,'new_faces_UDIM':1004,'nonmanifold_edges_before':before_nonmanifold,'nonmanifold_edges_after':after_nonmanifold,'boundary_edges_before':before_boundary,'boundary_edges_after':sum(e.is_boundary for e in bm.edges),'rejected_boundaries':rejected,'unclosed_boundary_chains':len(failed),'unclosed_chains_details':[{'edges':len(path),'dims':[max(l.vert.co[a] for l in path)-min(l.vert.co[a] for l in path) for a in range(3)]} for path in failed if path],'matched_openings':[{'cycle':g['cycle'],'vertices':len(g['outer']),'curvature_m':g['flat']} for g in accepted]}
  (ROOT/'Openings_1004_report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
  for obj in bpy.data.collections['low'].all_objects:obj.hide_set(True)
  high.hide_set(False)
  for obj in list(ctx.selected_objects):obj.select_set(False)
  high.select_set(True);ctx.view_layer.objects.active=high
  if ctx.area and ctx.area.type=='CONSOLE':ctx.area.type='VIEW_3D'
  if save_path:bpy.ops.wm.save_as_mainfile(filepath=str(save_path))
  print('OPENINGS_OK',len(accepted),'newfaces',len(new_faces),'deptherror',report['depth_error_max_m'],flush=True)
  return report
 except:
  if high.data!=work and work.users==0:bpy.data.meshes.remove(work)
  raise
 finally:bm.free()

if __name__=='__main__':run(ROOT/'Facade_Openings_1m_UDIM1004.blend')





