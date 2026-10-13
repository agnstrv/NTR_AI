"""Cut Main.009 on Main's VPM grid and weld their shared boundary.
Keeps Main geometry/UVs and the added part's material. Result remains named Main.
"""
import bpy,bmesh,math,json
from pathlib import Path
from collections import defaultdict,Counter
from mathutils import Vector
from mathutils.kdtree import KDTree
ROOT=Path(__file__).resolve().parent
PART='VPM.009'

def grid(lo,hi,step,eps=1e-6):
 return [i*step for i in range(math.floor((lo+eps)/step)+1,math.ceil((hi-eps)/step))]

def edge_index(edges,cell=2.5):
 index=defaultdict(list)
 for e in edges:
  a,b=[v.co for v in e.verts]
  lo=[math.floor((min(a[i],b[i])-.002)/cell) for i in range(3)]
  hi=[math.floor((max(a[i],b[i])+.002)/cell) for i in range(3)]
  for x in range(lo[0],hi[0]+1):
   for y in range(lo[1],hi[1]+1):
    for z in range(lo[2],hi[2]+1):index[(x,y,z)].append(e)
 return index

def conform(bm,edges,points,tolerance=.001):
 index=edge_index(edges);splits=defaultdict(list)
 for v in points:
  key=tuple(math.floor(c/2.5) for c in v.co)
  for e in index.get(key,[]):
   a,b=[k.co for k in e.verts];direction=b-a;length2=direction.length_squared
   if length2<1e-14:continue
   t=(v.co-a).dot(direction)/length2
   if t<=0 or t>=1:continue
   q=a+direction*t
   if (q-v.co).length>tolerance or min((q-a).length,(q-b).length)<=tolerance:continue
   splits[e].append(t)
 count=0
 for edge,values in splits.items():
  a,b=edge.verts;length=(b.co-a.co).length
  values=sorted(values);unique=[]
  for t in values:
   if not unique or (t-unique[-1])*length>tolerance:unique.append(t)
  current=edge;start=a;prev=0.
  for t in unique:
   newedge,newv=bmesh.utils.edge_split(current,start,(t-prev)/(1-prev))
   current=current if b in current.verts else newedge
   start=newv;prev=t;count+=1
 return count

def run(save_path=None, write_report=True):
 ctx=bpy.context
 if ctx.mode!='OBJECT':bpy.ops.object.mode_set(mode='OBJECT')
 main=bpy.data.objects['Main'];part=bpy.data.objects[PART]
 assert main.type=='MESH' and part.type=='MESH'
 assert not main.get('vpm_main009_merged'),'Already merged'
 assert not part.data.shape_keys and not main.data.shape_keys
 scale=ctx.scene.unit_settings.scale_length
 density=float(main.get('vpm_density',848.9121184461806));resolution=int(main.get('vpm_resolution',2048))
 step=resolution/density/scale
 # Main's baked grid has zero local origin; its world translation is the shared anchor.
 transform=main.matrix_world.inverted()@part.matrix_world
 pm=part.data.copy();pm.transform(transform)
 uv=pm.uv_layers.active
 if uv:uv.name='VPM_UDIM_Color'
 else:uv=pm.uv_layers.new(name='VPM_UDIM_Color')
 pm.attributes.new('VPM_Main009','INT','FACE').data.foreach_set('value',[1]*len(pm.polygons))
 pm.attributes.new('VPM_Main009_Vertex','INT','POINT').data.foreach_set('value',[1]*len(pm.vertices))
 cut=bmesh.new();cut.from_mesh(pm);cut.normal_update()
 before_part_area=sum(f.calc_area() for f in cut.faces)
 planes=[]
 for axis in range(3):
  axisstep=step
  planes.extend((axis,x) for x in grid(min(v.co[axis] for v in cut.verts),max(v.co[axis] for v in cut.verts),axisstep))
 for axis,x in planes:
  p=Vector((0,0,0));p[axis]=x;n=Vector((0,0,0));n[axis]=1
  result=bmesh.ops.bisect_plane(cut,geom=list(cut.verts)+list(cut.edges)+list(cut.faces),dist=step*1e-7,plane_co=p,plane_no=n,clear_inner=False,clear_outer=False)
  for elem in result.get('geom_cut',[]):
   if isinstance(elem,bmesh.types.BMEdge):elem.seam=True
 cut.normal_update()
 uvl=cut.loops.layers.uv['VPM_UDIM_Color']
 for f in cut.faces:
  axis=max(range(3),key=lambda a:abs(f.normal[a]));axes=((1,2),(0,2),(0,1))[axis]
  sign=1 if f.normal[axis]*(1,-1,1)[axis]>=0 else -1
  values=[Vector((sign*l.vert.co[axes[0]]/step,l.vert.co[axes[1]]/step)) for l in f.loops]
  offset=Vector([math.floor(sum(v[a] for v in values)/len(values)) for a in (0,1)])
  for l,v in zip(f.loops,values):
   local=v-offset
   assert all(-1e-5<=a<=1.00001 for a in local)
   l[uvl].uv=[max(0,min(1,a)) for a in local]
 part_cut_faces=len(cut.faces);cut.to_mesh(pm);cut.free()
 staged=main.data.copy()
 if not staged.attributes.get('VPM_Main009'):staged.attributes.new('VPM_Main009','INT','FACE')
 if not staged.attributes.get('VPM_Main009_Vertex'):staged.attributes.new('VPM_Main009_Vertex','INT','POINT')
 bm=bmesh.new();bm.from_mesh(staged);bm.from_mesh(pm);bm.normal_update()
 origin=bm.faces.layers.int['VPM_Main009'];vertex_origin=bm.verts.layers.int['VPM_Main009_Vertex'];uvl=bm.loops.layers.uv['VPM_UDIM_Color']
 # Remap the part's materials to appended slots without modifying any shared material.
 material_start=len(staged.materials)
 for m in part.data.materials:
  if m:
   copied=m.copy()
   if copied.use_nodes:
    tree=copied.node_tree;node=tree.nodes.new('ShaderNodeUVMap');node.uv_map='VPM_UDIM_Color'
    for tex in list(tree.nodes):
     if tex.type=='TEX_IMAGE' and tex.image:tree.links.new(node.outputs['UV'],tex.inputs['Vector'])
   staged.materials.append(copied)
 for f in bm.faces:
  if f[origin]:f.material_index+=material_start
 old_main_faces=[f for f in bm.faces if not f[origin]]
 old_positions={v:v.co.copy() for v in bm.verts if not v[vertex_origin]}
 old_uv={f:{l.vert:l[uvl].uv.copy() for l in f.loops} for f in old_main_faces}
 main_area_before=sum(f.calc_area() for f in old_main_faces)
 nonmanifold_before=sum(len(e.link_faces)>2 for e in bm.edges)
 main_edges=[e for e in bm.edges if e.is_boundary and not e.link_faces[0][origin]]
 part_edges=[e for e in bm.edges if e.is_boundary and e.link_faces[0][origin]]
 main_points={v for e in main_edges for v in e.verts};part_points={v for e in part_edges for v in e.verts}
 main_splits=conform(bm,main_edges,part_points)
 part_splits=conform(bm,part_edges,main_points)
 main_points={v for e in bm.edges if e.is_boundary and not e.link_faces[0][origin] for v in e.verts}
 part_points={v for e in bm.edges if e.is_boundary and e.link_faces[0][origin] for v in e.verts}
 kdt=KDTree(len(main_points));main_list=list(main_points)
 for i,v in enumerate(main_list):kdt.insert(v.co,i)
 kdt.balance();mapping={};moves=[]
 for v in part_points:
  co,index,distance=kdt.find(v.co)
  if distance<=.001:mapping[v]=main_list[index];moves.append(distance)
 assert len(mapping)>0,'No shared vertices found'
 bmesh.ops.weld_verts(bm,targetmap=mapping)
 bm.normal_update()
 shared=[e for e in bm.edges if len(e.link_faces)==2 and {f[origin] for f in e.link_faces}=={0,1}]
 assert shared,'Meshes were not connected by shared edges'
 assert all((v.co-co).length==0 for v,co in old_positions.items())
 uv_error=0.
 for f,snapshot in old_uv.items():
  for l in f.loops:
   if l.vert in snapshot:uv_error=max(uv_error,(l[uvl].uv-snapshot[l.vert]).length)
 assert uv_error<1e-6
 main_area_after=sum(f.calc_area() for f in bm.faces if not f[origin]);part_area_after=sum(f.calc_area() for f in bm.faces if f[origin])
 assert abs(main_area_after-main_area_before)/main_area_before<1e-5
 assert abs(part_area_after-before_part_area)/before_part_area<1e-4
 nonmanifold_after=sum(len(e.link_faces)>2 for e in bm.edges)
 assert nonmanifold_after<=nonmanifold_before
 report={'object':'Main','merged_source':PART,'texture_resolution_px':resolution,'density_px_m':density,'grid_step_m':step*scale,'grid_planes':len(planes),'cell_subdivision':1,'grid_step_XYZ_m':[step*scale]*3,'part_faces_before':len(part.data.polygons),'part_faces_after_cut':part_cut_faces,'Main_edge_splits':main_splits,'part_edge_splits':part_splits,'welded_vertices':len(mapping),'shared_edges':len(shared),'weld_distance_max_m':max(moves)*scale,'Main_original_vertices_unchanged':True,'Main_UV_error':uv_error,'Main_area_before_m2':main_area_before*scale**2,'Main_area_after_m2':main_area_after*scale**2,'part_area_before_m2':before_part_area*scale**2,'part_area_after_m2':part_area_after*scale**2,'nonmanifold_edges_before':nonmanifold_before,'nonmanifold_edges_after':nonmanifold_after,'vertices_final':len(bm.verts),'faces_final':len(bm.faces)}
 bm.to_mesh(staged);bm.free();staged.update()
 oldmesh=main.data;main.data=staged
 if oldmesh.users==0:bpy.data.meshes.remove(oldmesh)
 partmesh=part.data;bpy.data.objects.remove(part,do_unlink=True)
 if partmesh.users==0:bpy.data.meshes.remove(partmesh)
 bpy.data.meshes.remove(pm)
 main['vpm_main009_merged']=True
 for o in list(ctx.selected_objects):o.select_set(False)
 main.hide_set(False);main.select_set(True);ctx.view_layer.objects.active=main
 for m in main.data.materials:
  if m and m.use_nodes:
   for n in m.node_tree.nodes:
    if n.type=='TEX_IMAGE' and n.image:n.image.pack()
 if write_report:
  (ROOT/'Main009_FullCells_report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
 if ctx.area and ctx.area.type=='CONSOLE':ctx.area.type='VIEW_3D'
 if save_path:bpy.ops.wm.save_as_mainfile(filepath=str(save_path))
 print('MAIN009_MERGE_OK',json.dumps(report),flush=True)
 return report

if __name__=='__main__':run(ROOT/'Main_With_009_FullCells_Welded.blend')

