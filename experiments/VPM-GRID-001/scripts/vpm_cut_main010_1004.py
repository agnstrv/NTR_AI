"""Cut Main.010 on Main's full XYZ grid; conform interfaces and stack its UV in 1004.
Keeps Main.010 as a separate object. Main's UV and existing vertices are preserved.
"""
import bpy,bmesh,importlib.util,math,json
from pathlib import Path
from mathutils import Vector
ROOT=Path(__file__).resolve().parent
NAME='VPM.010'

def run(save_path=None):
 ctx=bpy.context
 if ctx.mode!='OBJECT':bpy.ops.object.mode_set(mode='OBJECT')
 part=bpy.data.objects[NAME];main=bpy.data.objects['Main']
 assert not part.get('vpm_010_cut'),'Part already cut'
 assert not part.data.shape_keys
 spec=importlib.util.spec_from_file_location('vpm_interface',ROOT/'vpm_cut_weld_main009.py')
 helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
 scale=ctx.scene.unit_settings.scale_length;resolution=int(main.get('vpm_resolution',2048));density=float(main.get('vpm_density',848.9121184461806))
 step=resolution/density/scale
 assert all(abs(main.matrix_world[i][j]-(1 if i==j else 0))<1e-7 for i in range(3) for j in range(3)),'Main grid transform changed'
 transform=main.matrix_world.inverted()@part.matrix_world
 pm=part.data.copy();pm.transform(transform)
 mb=main.data.copy()
 # Keep the imported UVMap as a backup; the generated UV drives the material.
 pm.uv_layers.new(name='VPM_GRID')
 pm.uv_layers.new(name='VPM_UDIM_Color')
 pb=bmesh.new();pb.from_mesh(pm);pb.normal_update()
 area_before=sum(f.calc_area() for f in pb.faces)
 old_vertices=[v.co.copy() for v in pb.verts]
 planes=[(axis,x) for axis in range(3) for x in helper.grid(min(v.co[axis] for v in pb.verts),max(v.co[axis] for v in pb.verts),step)]
 for axis,x in planes:
  point=Vector((0,0,0));point[axis]=x;normal=Vector((0,0,0));normal[axis]=1
  cut=bmesh.ops.bisect_plane(pb,geom=list(pb.verts)+list(pb.edges)+list(pb.faces),dist=step*1e-7,plane_co=point,plane_no=normal,clear_inner=False,clear_outer=False)
  for e in cut.get('geom_cut',[]):
   if isinstance(e,bmesh.types.BMEdge):e.seam=True
 pb.normal_update()
 grid=pb.loops.layers.uv['VPM_GRID'];udim=pb.loops.layers.uv['VPM_UDIM_Color']
 for f in pb.faces:
  axis=max(range(3),key=lambda a:abs(f.normal[a]));axes=((1,2),(0,2),(0,1))[axis]
  sign=1 if f.normal[axis]*(1,-1,1)[axis]>=0 else -1
  coords=[Vector((sign*l.vert.co[axes[0]]/step,l.vert.co[axes[1]]/step)) for l in f.loops]
  offset=Vector([math.floor(sum(q[a] for q in coords)/len(coords)) for a in (0,1)])
  for l,q in zip(f.loops,coords):
   l[grid].uv=q;uv=q-offset
   assert all(-1e-5<=a<=1.00001 for a in uv)
   l[udim].uv=(3+max(0,min(1,uv.x)),max(0,min(1,uv.y)))
 # Insert existing neighbour vertices in the new boundary; reciprocally subdivide
 # Main boundary edges where a new cut meets them. No Main vertex is moved.
 bm=bmesh.new();bm.from_mesh(mb);bm.normal_update()
 main_uv_name=main.data.uv_layers.active.name
 mainuv=bm.loops.layers.uv[main_uv_name]
 original_main={v:v.co.copy() for v in bm.verts}
 original_uv={f:{l.vert:l[mainuv].uv.copy() for l in f.loops} for f in bm.faces}
 main_area_before=sum(f.calc_area() for f in bm.faces)
 main_edges=[e for e in bm.edges if e.is_boundary];part_edges=[e for e in pb.edges if e.is_boundary]
 main_points={v for e in main_edges for v in e.verts};part_points={v for e in part_edges for v in e.verts}
 part_splits=helper.conform(pb,part_edges,main_points)
 part_points={v for e in pb.edges if e.is_boundary for v in e.verts}
 main_splits=helper.conform(bm,main_edges,part_points)
 # Snap only coincident interface vertices (at most 1 mm) to the unchanged Main.
 from mathutils.kdtree import KDTree
 mains={v for e in bm.edges if e.is_boundary for v in e.verts};mainlist=list(mains);kd=KDTree(len(mainlist))
 for i,v in enumerate(mainlist):kd.insert(v.co,i)
 kd.balance();matched=0;maxsnap=0
 for v in {v for e in pb.edges if e.is_boundary for v in e.verts}:
  co,i,d=kd.find(v.co)
  if d<=.001:
   v.co=co;matched+=1;maxsnap=max(maxsnap,d)
 pb.normal_update();bm.normal_update()
 assert all((v.co-co).length==0 for v,co in original_main.items())
 uv_error=max(((l[mainuv].uv-snap[l.vert]).length for f,snap in original_uv.items() for l in f.loops if l.vert in snap),default=0)
 assert uv_error<1e-6
 assert all(3-1e-6<=l[udim].uv.x<=4+1e-6 and -1e-6<=l[udim].uv.y<=1+1e-6 for f in pb.faces for l in f.loops)
 area_after=sum(f.calc_area() for f in pb.faces)
 assert abs(area_after-area_before)/area_before<1e-4
 assert abs(sum(f.calc_area() for f in bm.faces)-main_area_before)/main_area_before<1e-5
 report={'object':NAME,'neighbour':'Main','step_XYZ_m':[step*scale]*3,'grid_anchor_world':list(main.matrix_world.translation),'cell_subdivision':1,'grid_planes':len(planes),'faces_before':len(part.data.polygons),'faces_after':len(pb.faces),'vertices_after':len(pb.verts),'UDIM':1004,'UV_bounds':[[min(l[udim].uv[a] for f in pb.faces for l in f.loops),max(l[udim].uv[a] for f in pb.faces for l in f.loops)] for a in range(2)],'Main_boundary_edge_splits':main_splits,'part_boundary_edge_splits':part_splits,'matching_interface_vertices':matched,'interface_snap_max_m':maxsnap*scale,'Main_original_vertices_unchanged':True,'Main_UV_error':uv_error,'area_before_m2':area_before*scale**2,'area_after_m2':area_after*scale**2}
 pb.to_mesh(pm);pb.free();bm.to_mesh(mb);bm.free();pm.update();mb.update()
 pm.uv_layers.active=pm.uv_layers['VPM_UDIM_Color'];pm.uv_layers.active.active_render=True
 # Use Main's existing UDIM material, with an explicit reference to the new UV.
 mat=next(m for m in main.data.materials if m and m.use_nodes and any(n.type=='TEX_IMAGE' and n.image and n.image.source=='TILED' and n.image.tiles.get(1004) for n in m.node_tree.nodes))
 mat=mat.copy();mat.name='Main010_UDIM1004'
 tree=mat.node_tree;uvnode=tree.nodes.new('ShaderNodeUVMap');uvnode.uv_map='VPM_UDIM_Color'
 for node in list(tree.nodes):
  if node.type=='TEX_IMAGE' and node.image:
   tree.links.new(uvnode.outputs['UV'],node.inputs['Vector']);node.image.pack()
 pm.materials.clear();pm.materials.append(mat)
 for f in pm.polygons:f.material_index=0
 oldpart=part.data;oldmain=main.data
 part.data=pm;part.matrix_world=main.matrix_world.copy();main.data=mb
 if oldpart.users==0:bpy.data.meshes.remove(oldpart)
 if oldmain.users==0:bpy.data.meshes.remove(oldmain)
 part['vpm_010_cut']=True;part['vpm_density']=density;part['vpm_resolution']=resolution;part['vpm_udim']=1004;part['vpm_grid_anchor_world']=list(main.matrix_world.translation)
 for o in list(ctx.selected_objects):o.select_set(False)
 part.hide_set(False);part.select_set(True);ctx.view_layer.objects.active=part
 (ROOT/'Main010_1004_report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
 if ctx.area and ctx.area.type=='CONSOLE':ctx.area.type='VIEW_3D'
 if save_path:bpy.ops.wm.save_as_mainfile(filepath=str(save_path))
 print('MAIN010_1004_OK',json.dumps(report),flush=True)
 return report

if __name__=='__main__':run(ROOT/'Main010_Cut_UDIM1004.blend')
