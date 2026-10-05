"""Mirror only negative UV patches; match the existing image within the same UDIM."""
import bpy,bmesh,numpy as np,json,math
from pathlib import Path
ROOT=Path(__file__).resolve().parent
def area(f,uv):
 q=[l[uv].uv for l in f.loops]
 return sum(a.x*b.y-b.x*a.y for a,b in zip(q,q[1:]+q[:1]))/2
def run(save=True):
 if bpy.context.mode!='OBJECT':bpy.ops.object.mode_set(mode='OBJECT')
 report=[];loaded=[];pixels={}
 def image_for(o,tile):
  if tile in pixels:return pixels[tile]
  image=next(n.image for m in o.data.materials if m and m.use_nodes for n in m.node_tree.nodes if n.type=='TEX_IMAGE' and n.image and n.image.source=='TILED')
  path=bpy.path.abspath(image.filepath).replace('<UDIM>',str(tile))
  im=bpy.data.images.load(path,check_existing=False);loaded.append(im)
  w,h=im.size;arr=np.empty(w*h*4,dtype=np.float32);im.pixels.foreach_get(arr)
  pixels[tile]=arr.reshape(h,w,4)[:,:,:3]
  return pixels[tile]
 for o in bpy.context.scene.objects:
  if o.type!='MESH' or not o.visible_get() or not o.data.uv_layers.active:continue
  mesh=o.data;bm=bmesh.new();bm.from_mesh(mesh);bm.faces.ensure_lookup_table();bm.faces.index_update()
  uv=bm.loops.layers.uv[mesh.uv_layers.active.name]
  bad={f for f in bm.faces if area(f,uv)<-1e-10}
  if not bad:bm.free();continue
  coords=[v.co.copy() for v in mesh.vertices];original={l:l[uv].uv.copy() for f in bm.faces for l in f.loops}
  remaining=set(bad);groups=[]
  while remaining:
   seed=remaining.pop();fs={seed};queue=[seed]
   for f in queue:
    for l in f.loops:
     e=l.edge
     if len(e.link_loops)!=2:continue
     b=e.link_loops[0] if e.link_loops[1]==l else e.link_loops[1]
     if b.face not in remaining:continue
     aa={l.vert:l[uv].uv,l.link_loop_next.vert:l.link_loop_next[uv].uv};bb={b.vert:b[uv].uv,b.link_loop_next.vert:b.link_loop_next[uv].uv}
     if all((aa[v]-bb[v]).length<1e-6 for v in e.verts):remaining.remove(b.face);fs.add(b.face);queue.append(b.face)
   groups.append(fs)
  entries=[]
  for fs in groups:
   loops=[l for f in fs for l in f.loops];q=np.array([list(l[uv].uv) for l in loops]);center=q.mean(0)
   base=np.floor(center).astype(int);tile=1001+int(base[0])+10*int(base[1]);local=q-base
   assert local.min()>=-1e-6 and local.max()<=1+1e-6,'Patch crosses UDIM boundary'
   arr=image_for(o,tile);h,w,_=arr.shape
   def sample(qs):
    xy=np.clip(qs,0,1);x=xy[...,0]*(w-1);y=xy[...,1]*(h-1)
    x0=x.astype(int);y0=y.astype(int);x1=np.minimum(x0+1,w-1);y1=np.minimum(y0+1,h-1);a=(x-x0)[...,None];b=(y-y0)[...,None]
    return (arr[y0,x0]*(1-a)+arr[y0,x1]*a)*(1-b)+(arr[y1,x0]*(1-a)+arr[y1,x1]*a)*b
   samples=[];boundary=[]
   for f in fs:
    fq=np.array([list(l[uv].uv) for l in f.loops])-base
    c=fq.mean(0)
    for a,b in zip(fq,np.roll(fq,-1,axis=0)):
     for t in np.linspace(0,1,9):
      edge=a*(1-t)+b*t
      for depth in (.05,.3,.6,1):samples.append(c*(1-depth)+edge*depth)
    for l in f.loops:
     if any(n not in fs for n in l.edge.link_faces):
      a=np.array(l[uv].uv)-base;b=np.array(l.link_loop_next[uv].uv)-base
      boundary.extend(a*(1-t)+b*t for t in np.linspace(0,1,13))
   samples=np.array(samples);old=sample(samples);best=None
   for axis in (0,1):
    lo=max(float(local[:,axis].max()),0);hi=min(1+float(local[:,axis].min()),2)
    sums=np.unique(np.r_[np.linspace(lo,hi,513),local[:,axis].min()+local[:,axis].max(),np.clip(1,lo,hi)])
    new=np.broadcast_to(samples,(len(sums),*samples.shape)).copy();new[:,:,axis]=sums[:,None]-samples[None,:,axis]
    errors=np.mean((sample(new)-old[None,:,:])**2,axis=(1,2))
    displacement=np.mean((new[:,:,axis]-samples[:,axis])**2,axis=1)
    score=errors+1e-5*displacement
    if boundary:
     bd=np.array(boundary);changed=np.broadcast_to(bd,(len(sums),*bd.shape)).copy();changed[:,:,axis]=sums[:,None]-bd[None,:,axis]
     score+=3*np.mean((sample(changed)-sample(bd)[None,:,:])**2,axis=(1,2))
    idx=int(np.argmin(score));candidate=(float(score[idx]),axis,float(sums[idx]),float(errors[idx]))
    if best is None or candidate[0]<best[0]:best=candidate
   _,axis,total,error=best
   for l in loops:l[uv].uv[axis]=float(2*base[axis]+total-l[uv].uv[axis])
   assert all(area(f,uv)>0 for f in fs)
   entries.append({'faces':sorted(f.index for f in fs),'udim':tile,'axis':'UV'[axis],'pivot':float(base[axis]+total/2),'image_sample_RMSE':math.sqrt(error)})
  assert not any(area(f,uv)<-1e-10 for f in bm.faces)
  assert all((l[uv].uv-original[l]).length==0 for f in bm.faces if f not in bad for l in f.loops)
  for f in bm.faces:f.select=f in bad
  bm.to_mesh(mesh);bm.free();mesh.update()
  assert len(mesh.vertices)==len(coords) and all((v.co-co).length==0 for v,co in zip(mesh.vertices,coords))
  report.append({'object':o.name,'mirrored_faces_corrected':len(bad),'patches':len(groups),'geometry_unchanged':True,'other_faces_UV_unchanged':True,'negative_UV_faces_after':0,'details':entries})
 for im in loaded:bpy.data.images.remove(im)
 (ROOT/'UV_Mirror_report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
 if bpy.context.area and bpy.context.area.type=='CONSOLE':bpy.context.area.type='VIEW_3D'
 if save:bpy.ops.wm.save_as_mainfile(filepath=str(ROOT/'UV_Mirror_Corrected.blend'))
 print('UV_MIRROR_OK',[(r['object'],r['mirrored_faces_corrected']) for r in report],flush=True)
 return report
if __name__=='__main__':run()
