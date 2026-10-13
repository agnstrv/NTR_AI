"""Assign cut VPM faces to grey/beige/white UDIMs by sampling colocated NPM diffuse.
Run inside Blender; UV islands are translated only. Geometry is not modified.
"""
import bpy,json,math,numpy as np
from pathlib import Path
from collections import Counter
from mathutils import Vector
from mathutils.bvhtree import BVHTree
ROOT=Path(__file__).resolve().parent

def run(save_path=None):
 ctx=bpy.context
 if ctx.mode!='OBJECT':bpy.ops.object.mode_set(mode='OBJECT')
 high=ctx.active_object
 assert high and high.type=='MESH' and high.get('vpm_rows_z')==8,'Select the cut VPM facade'
 low=bpy.data.objects.get('VPM')
 assert low and any(c.name=='low' for c in low.users_collection),'NPM in low not found'
 mesh=high.data
 original=[v.co.copy() for v in mesh.vertices]
 source_uv=mesh.uv_layers.active
 assert source_uv
 olduv=np.array([list(d.uv) for d in source_uv.data],dtype=np.float64)
 # Each polygon must fit one tile; use face-center integer offsets, not per-vertex modulo.
 local=olduv.copy()
 for f in mesh.polygons:
  ids=list(f.loop_indices)
  offset=np.floor(olduv[ids].mean(axis=0)+1e-8)
  local[ids]-=offset
 assert local.min()>=-1e-5 and local.max()<=1.00001,('Input UV crosses tile',local.min(),local.max())
 anchor=high.matrix_world.translation.copy()
 low.data.calc_loop_triangles()
 verts=[low.matrix_world@v.co-anchor for v in low.data.vertices]
 triangles=list(low.data.loop_triangles)
 bvh=BVHTree.FromPolygons(verts,[list(t.vertices) for t in triangles],all_triangles=True)
 luv=low.data.uv_layers.active
 material=low.data.materials[0]
 bsdf=next(n for n in material.node_tree.nodes if n.type=='BSDF_PRINCIPLED')
 link=bsdf.inputs['Base Color'].links[0]
 im=link.from_node.image
 assert im and im.source=='FILE'
 w,h=im.size
 pixels=np.empty(w*h*4,dtype=np.float32);im.pixels.foreach_get(pixels);pixels=pixels.reshape(h,w,4)
 def pixel(uv):
  x=min(w-1,int((uv.x%1)*w)); y=min(h-1,int((uv.y%1)*h))
  return pixels[y,x,:3]
 def getcolor(hit,idx):
  t=triangles[idx];a,b,c=[verts[i] for i in t.vertices]
  e0=b-a;e1=c-a;e2=hit-a
  d00=e0.dot(e0);d01=e0.dot(e1);d11=e1.dot(e1);d20=e2.dot(e0);d21=e2.dot(e1)
  den=d00*d11-d01*d01
  if abs(den)<1e-20:return None
  v=(d11*d20-d01*d21)/den;z=(d00*d21-d01*d20)/den
  uv=luv.data[t.loops[0]].uv*(1-v-z)+luv.data[t.loops[1]].uv*v+luv.data[t.loops[2]].uv*z
  return pixel(uv)
 def classify(rgb):
  r,g,b=map(float,rgb)
  if r-b>0.10 and r>g+0.04:return 1002
  if (r+g+b)/3>0.74:return 1003
  return 1001
 distances=[];fallbacks=0
 def sample(p,n):
  nonlocal fallbacks
  nearest=bvh.find_nearest(p)
  assert nearest[2] is not None
  hit,hn,idx,d=nearest
  if hn.dot(n)<0.75:
   candidates=bvh.find_nearest_range(p,max(0.03,d+0.025))
   aligned=[q for q in candidates if q[1].dot(n)>0.75]
   if aligned:hit,hn,idx,d=min(aligned,key=lambda q:q[3])
   else:fallbacks+=1
  distances.append(d)
  rgb=getcolor(hit,idx)
  return classify(rgb) if rgb is not None else 1001,rgb,d
 labels=[];mixed=[];samples_hist=Counter();source_colors=[]
 normalmat=high.matrix_world.to_3x3().inverted().transposed()
 for f in mesh.polygons:
  positions=[high.matrix_world@mesh.vertices[mesh.loops[i].vertex_index].co-anchor for i in f.loop_indices]
  center=sum(positions,Vector())/len(positions)
  normal=(normalmat@f.normal).normalized()
  points=[center]+[center*.7+v*.3 for v in positions]
  votes=[sample(p,normal) for p in points]
  counts=Counter(v[0] for v in votes)
  choice=counts.most_common(1)[0][0]
  labels.append(choice);samples_hist.update(v[0] for v in votes)
  source_colors.append([float(a) for a in votes[0][1]])
  if len(counts)>1:mixed.append({'face':f.index,'votes':dict(counts),'selected':choice})
 print('CLASSIFIED',dict(Counter(labels)), 'mixed',len(mixed),'max_distance',max(distances),flush=True)
 # Keep a reversible UV snapshot, then write the translated islands to a dedicated layer.
 backup=mesh.uv_layers.get('VPM_UV_Before_UDIM') or mesh.uv_layers.new(name='VPM_UV_Before_UDIM')
 backup.data.foreach_set('uv',olduv.astype(np.float32).ravel())
 out=mesh.uv_layers.get('VPM_UDIM_Color') or mesh.uv_layers.new(name='VPM_UDIM_Color')
 values=local.copy()
 for f,label in zip(mesh.polygons,labels):
  ids=list(f.loop_indices);values[ids,0]+=(label-1001)%10; values[ids,1]+=(label-1001)//10
 out.data.foreach_set('uv',values.astype(np.float32).ravel())
 mesh.uv_layers.active=out;out.active_render=True
 # Explicit UV binding, on copies so no other object's materials change.
 target_image=None
 for i,m in enumerate(mesh.materials):
  if not m:continue
  copy=m.copy();mesh.materials[i]=copy
  tree=copy.node_tree
  uvnode=tree.nodes.new('ShaderNodeUVMap');uvnode.uv_map=out.name;uvnode.label='UDIM colour from NPM'
  for n in list(tree.nodes):
   if n.type=='TEX_IMAGE' and n.image and n.image.source=='TILED':
    tree.links.new(uvnode.outputs['UV'],n.inputs['Vector']);target_image=n.image
 assert target_image and {1001,1002,1003}.issubset({t.number for t in target_image.tiles})
 target_image.pack()
 attr=mesh.attributes.get('VPM_UDIM') or mesh.attributes.new('VPM_UDIM','INT','FACE')
 attr.data.foreach_set('value',labels)
 assert len(original)==len(mesh.vertices) and all((a-v.co).length==0 for a,v in zip(original,mesh.vertices))
 error=0
 for f in mesh.polygons:
  ids=list(f.loop_indices)
  error=max(error,float(np.abs((values[ids]-values[ids[0]])-(olduv[ids]-olduv[ids[0]])).max()))
 assert error<1e-6,('UV scale changed',error)
 report={'VPM':high.name,'NPM':low.name,'UDIM_colors':{'1001':'grey','1002':'beige','1003':'white'},'faces_by_UDIM':dict(Counter(labels)),'faces':len(labels),'sample_votes':dict(samples_hist),'mixed_faces':len(mixed),'mixed_face_details':mixed,'distance_max_m':max(distances),'distance_p99_m':float(np.percentile(distances,99)),'normal_fallback_samples':fallbacks,'UV_translation_error':error,'geometry_unchanged':True,'rows_Z':8}
 (ROOT/'UDIM_Color_report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
 # Hide NPM only for viewport comparison; all reference geometry stays in the scene.
 for obj in bpy.data.collections['low'].all_objects:obj.hide_set(True)
 high.hide_set(False);high.select_set(True);ctx.view_layer.objects.active=high
 for screen in bpy.data.screens:
  for area in screen.areas:
   if area.type=='IMAGE_EDITOR':area.spaces.active.image=target_image
 if ctx.area and ctx.area.type=='CONSOLE':ctx.area.type='VIEW_3D'
 if save_path:bpy.ops.wm.save_as_mainfile(filepath=str(save_path))
 print('UDIM_COLOR_OK',dict(Counter(labels)),flush=True)
 return report

if __name__=='__main__':run(ROOT/'Facade_8Rows_UDIM_Color.blend')
