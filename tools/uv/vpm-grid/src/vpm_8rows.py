"""Cut the active facade into eight texture rows, shared world XYZ grid.
Texture layout: two columns, one row. Preserves image aspect and stacks UV in 1001.
"""
import bpy,bmesh,importlib.util,json,math
from pathlib import Path
from mathutils import Vector
ROOT=Path(__file__).resolve().parent

def run(rows=8,save_path=None):
 spec=importlib.util.spec_from_file_location('vpm_grid',ROOT/'vpm_auto_uv.py')
 vpm=importlib.util.module_from_spec(spec); spec.loader.exec_module(vpm)
 ctx=bpy.context
 if ctx.mode!='OBJECT': bpy.ops.object.mode_set(mode='OBJECT')
 source=ctx.active_object
 assert source and source.type=='MESH','Select a mesh'
 others={o.name for o in bpy.data.objects if o!=source}
 original_name=source.name
 # Evaluate first; keep the original until all checks have succeeded.
 prepared=vpm.new_work_copy(ctx,source)
 coords=[v.co.copy() for v in prepared.data.vertices]
 anchor=Vector([min(c[a] for c in coords) for a in range(3)])
 height=max(c.z for c in coords)-anchor.z
 assert height>0
 scale=ctx.scene.unit_settings.scale_length
 step=height/rows
 density=2048/(step*scale)
 for vert in prepared.data.vertices: vert.co-=anchor
 prepared.data.update()
 stats=vpm.write_uv(prepared.data,scale,density,2048,(0,0,0))
 vpm.add_report(prepared,stats,density,2048,scale,(0,0,0))
 result,report=vpm.cut_object(ctx,prepared)
 # The PNG has TWO columns. Cut the central vertical grout line too.
 bm=bmesh.new(); bm.from_mesh(result.data)
 try:
  for axis in (0,1):
   for value in vpm.grid_values(0,max(v.co[axis] for v in bm.verts),step/2,epsilon=step*1e-6):
    if abs(value/step-round(value/step))<1e-6: continue
    point=Vector((0,0,0)); point[axis]=value
    normal=Vector((0,0,0)); normal[axis]=1
    cut=bmesh.ops.bisect_plane(bm,geom=list(bm.verts)+list(bm.edges)+list(bm.faces),dist=step*1e-6,plane_co=point,plane_no=normal,clear_inner=False,clear_outer=False)
    for e in cut.get('geom_cut',[]):
     if isinstance(e,bmesh.types.BMEdge): e.seam=True
  bm.normal_update(); bm.to_mesh(result.data)
 finally: bm.free()
 vpm.write_uv(result.data,scale,density,2048,(0,0,0))
 tiled=vpm.stack_tiles(result)
 # Verify the continuous pre-stack UV represents Z as eight repeats.
 grid=result.data.uv_layers['VPM_GRID']
 vertical=[]
 max_error=0
 for f in result.data.polygons:
  if vpm.dominant_axis(f.normal)==2: continue
  for li in f.loop_indices:
   z=result.data.vertices[result.data.loops[li].vertex_index].co.z
   uv=grid.data[li].uv.y
   max_error=max(max_error,abs(uv-z/step)); vertical.append(uv)
 assert max_error<1e-5,('Z UV verification',max_error)
 assert all(-1e-6<=a<=1+1e-6 for d in tiled.data for a in d.uv),'UV outside 1001'
 after_area=sum(f.area for f in result.data.polygons)*scale*scale
 assert abs(after_area-report['area_before_m2'])/report['area_before_m2']<1e-4
 result.matrix_world.translation=anchor
 # Make materials unique before binding their image nodes explicitly to this UV.
 for i,m in enumerate(result.data.materials):
  if not m: continue
  copied=m.copy(); result.data.materials[i]=copied
  if copied.use_nodes:
   tree=copied.node_tree
   uvnode=tree.nodes.new('ShaderNodeUVMap'); uvnode.uv_map=tiled.name
   uvnode.label='8 rows along world Z'
   for n in list(tree.nodes):
    if n.type=='TEX_IMAGE' and n.image:
     tree.links.new(uvnode.outputs['UV'],n.inputs['Vector']); n.extension='REPEAT'
     n.image.pack()
 result.name=original_name+'_VPM_8Rows'
 vpm.discard_object(source); vpm.activate(ctx,result)
 assert others.issubset({o.name for o in bpy.data.objects})
 report.update(object=result.name,rows_Z=rows,texture_columns=2,texture_rows=1,height_m=height*scale,tile_height_m=step*scale,tile_width_m=step*scale/2,density_setting_px_per_m=density,faces=len(result.data.polygons),vertices=len(result.data.vertices),UV_range_Z=[min(vertical),max(vertical)],UV_Z_max_error=max_error,area_after_m2=after_area,UV_layer=tiled.name)
 result['vpm_rows_z']=rows
 if hasattr(ctx.scene,'vpm_density'): ctx.scene.vpm_density=density
 if hasattr(ctx.scene,'vpm_resolution'): ctx.scene.vpm_resolution=2048
 (ROOT/'Facade_8Rows_report.json').write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
 for screen in bpy.data.screens:
  for area in screen.areas:
   if area.type=='IMAGE_EDITOR':
    area.spaces.active.image=next((n.image for m in result.data.materials if m and m.use_nodes for n in m.node_tree.nodes if n.type=='TEX_IMAGE' and n.image),None)
 if ctx.area and ctx.area.type=='CONSOLE': ctx.area.type='VIEW_3D'
 if save_path: bpy.ops.wm.save_as_mainfile(filepath=str(save_path))
 print('VPM_8ROWS_OK',json.dumps(report))
 return result

if __name__=='__main__': run(8,ROOT/'Facade_8Rows_2048.blend')
