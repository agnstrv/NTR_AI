"""Continuous window sheets. Preserve frame depth, outer glazing contour,
materials and sampled boundary UVs; remove coplanar internal subdivisions.
Uses the current scene snapshot and the prepared per-window profile map.
"""
import bpy,numpy as np,json,collections
from pathlib import Path
from mathutils import Vector
from mathutils.geometry import closest_point_on_tri,barycentric_transform
BASE=Path(__file__).resolve().parents[1]
def project(q,line):
 d=np.diff(line,axis=0);length=np.linalg.norm(d,axis=1);total=np.r_[0,np.cumsum(length)];t=np.clip(np.sum((q[:,None]-line[:-1])*d,axis=2)/(length*length),0,1);pr=line[:-1]+t[:,:,None]*d;dist=np.linalg.norm(pr-q[:,None],axis=2);k=dist.argmin(1)
 return total[k]+t[np.arange(len(q)),k]*length[k],total
def levels(values,tol=.0015):
 groups=[]
 for x in sorted(values):
  if groups and x-groups[-1][0]<tol:groups[-1].append(float(x))
  else:groups.append([float(x)])
 return np.array([np.mean(g) for g in groups])
def build():
 data=json.load(open(BASE/'work/continuous_profiled.json'));anchor=np.array(data['anchor']);source=bpy.data.objects['Окно_Заполнение_001'];old=source.data
 old.calc_loop_triangles();layers=[l.name for l in old.uv_layers];triangles=collections.defaultdict(list);selected={}
 for g in data['groups']:
  for f in g['faces']:selected[f['face']]=g['component']
 mat=np.linalg.inv(anchor)@np.array(source.matrix_world,float);inv=np.linalg.inv(mat)
 points=np.array([(mat@np.array([*v.co,1]))[:3] for v in old.vertices])
 for tri in old.loop_triangles:
  fi=tri.polygon_index
  if fi not in selected:continue
  xyz=[Vector(points[i]) for i in tri.vertices];uv={l:[Vector((*old.uv_layers[l].data[i].uv,0)) for i in tri.loops] for l in layers}
  triangles[selected[fi]].append((xyz,uv,old.polygons[fi].material_index))
 verts=[];faces=[];face_uv=[];face_material=[];reports=[]
 for g in data['groups']:
  ci=g['component'];line=np.array(g['line']);closed=g['closed'];delta=np.diff(line,axis=0);length=np.linalg.norm(delta,axis=1);total=np.r_[0,np.cumsum(length)]
  polygons=[];all_s=[]
  for f in g['faces']:
   p=np.array(f['points']);ss,_=project(p[:,:2],line)
   if closed and np.ptp(ss)>total[-1]/2:ss[ss<total[-1]/2]+=total[-1]
   uv=np.column_stack((ss,p[:,2]));polygons.append(uv);all_s.extend(ss)
   if closed:
    for shift in [-total[-1],total[-1]]:
     q=uv.copy();q[:,0]+=shift;polygons.append(q)
  lo=0 if closed else min(all_s);hi=total[-1] if closed else max(all_s)
  samples=levels([lo,hi]+[s for s in all_s if lo<s<hi]+[s for s in total if lo<s<hi]);bottom=[];top=[]
  for s in samples:
   zs=[]
   for poly in polygons:
    if s<poly[:,0].min()-.002 or s>poly[:,0].max()+.002:continue
    scan=float(np.clip(s,poly[:,0].min(),poly[:,0].max()))
    for a,b in zip(poly,np.roll(poly,-1,axis=0)):
     if abs(b[0]-a[0])<1e-10:
      if abs(scan-a[0])<1e-7:zs.extend([a[1],b[1]])
     elif min(a[0],b[0])-1e-7<=scan<=max(a[0],b[0])+1e-7:zs.append(a[1]+(b[1]-a[1])*(scan-a[0])/(b[0]-a[0]))
   bottom.append(min(zs) if zs else np.nan);top.append(max(zs) if zs else np.nan)
  bottom=np.array(bottom);top=np.array(top)
  for arr in [bottom,top]:
   good=np.isfinite(arr);arr[~good]=np.interp(samples[~good],samples[good],arr[good])
  # Join the outer corners across mullion gaps. Individual pane ends can be
  # staggered under a frame; they must not notch the whole window outline.
  if ci!=253:
   cloud=np.concatenate(polygons)
   cloud=cloud[(cloud[:,0]>=lo-.002)&(cloud[:,0]<=hi+.002)]
   unique=sorted(set(tuple(q) for q in cloud));lower=[];upper=[]
   def cross(a,b,c):return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
   for point in unique:
    while len(lower)>1 and cross(lower[-2],lower[-1],point)<=1e-10:lower.pop()
    lower.append(point)
   for point in reversed(unique):
    while len(upper)>1 and cross(upper[-2],upper[-1],point)<=1e-10:upper.pop()
    upper.append(point)
   hull=np.array(lower[:-1]+upper[:-1]);newbottom=[];newtop=[]
   for s in samples:
    zs=[]
    for a,b in zip(hull,np.roll(hull,-1,axis=0)):
     if abs(a[0]-b[0])<1e-10:
      if abs(s-a[0])<.002:zs.extend([a[1],b[1]])
     elif min(a[0],b[0])-.002<=s<=max(a[0],b[0])+.002:
      t=np.clip((s-a[0])/(b[0]-a[0]),0,1);zs.append(a[1]+t*(b[1]-a[1]))
    newbottom.append(min(zs) if zs else np.nan);newtop.append(max(zs) if zs else np.nan)
   bottom=np.array(newbottom);top=np.array(newtop)
   width=hi-lo
   for arr,level in [(top,float(cloud[:,1].max())),(bottom,float(cloud[:,1].min()))]:
    extent=cloud[abs(cloud[:,1]-level)<.002,0]
    if len(extent)>1 and np.ptp(extent)>width*.75:arr[:]=level
  narrow=top-bottom<.0001
  if np.any(narrow):
   middle=(top[narrow]+bottom[narrow])/2;bottom[narrow]=middle-.00005;top[narrow]=middle+.00005
  if closed:
   bottom[0]=bottom[-1]=min(bottom[0],bottom[-1]);top[0]=top[-1]=max(top[0],top[-1])
  def xy(s):
   k=int(np.clip(np.searchsorted(total,s,side='right')-1,0,len(length)-1));return line[k]+delta[k]*(s-total[k])/length[k]
  coords=np.array([[*xy(s),z] for s,b,t in zip(samples,bottom,top) for z in [b,t]]).reshape(-1,2,3)
  # Remove every station whose top and bottom both follow the same straight
  # surface. This yields a single quad on a planar rectangular window.
  keep=list(range(len(samples)))
  changed=True
  while changed:
   changed=False
   for k in range(1,len(keep)-1):
    a,b,c=keep[k-1:k+2];u=(samples[b]-samples[a])/(samples[c]-samples[a]);expected=coords[a]*(1-u)+coords[c]*u
    if np.max(np.linalg.norm(coords[b]-expected,axis=1))<.00035:
     keep.pop(k);changed=True;break
  coords=coords[keep];samples=samples[keep]
  # Preserve orientation of the visible original sheet.
  oldnormal=np.zeros(3)
  for xyz,uv,mi in triangles[ci]:oldnormal+=np.cross(np.array(xyz[1])-xyz[0],np.array(xyz[2])-xyz[0])
  start=len(verts);ids=[]
  for k,pair in enumerate(coords):
   if closed and k==len(coords)-1:ids.append(ids[0]);continue
   pair_ids=[]
   for co in pair:pair_ids.append(len(verts));verts.append((inv@np.r_[co,1])[:3].tolist())
   ids.append(pair_ids)
  flip=None
  for k in range(len(coords)-1):
   idx=[ids[k][0],ids[k+1][0],ids[k+1][1],ids[k][1]];xyz=[coords[k,0],coords[k+1,0],coords[k+1,1],coords[k,1]]
   normal=np.cross(xyz[1]-xyz[0],xyz[3]-xyz[0])
   center=Vector(np.mean(xyz,axis=0));near_tri=min(triangles[ci],key=lambda item:(center-closest_point_on_tri(center,*item[0])).length_squared)[0]
   reference=np.cross(np.array(near_tri[1])-near_tri[0],np.array(near_tri[2])-near_tri[0])
   if flip is None:flip=normal@reference<0
   if flip:idx=idx[::-1];xyz=xyz[::-1]
   out_uv={l:[] for l in layers};mi=[]
   for co in xyz:
    point=Vector(co);best=None
    for tri,uv,material in triangles[ci]:
     nearest=closest_point_on_tri(point,*tri);dist=(point-nearest).length_squared
     if best is None or dist<best[0]:best=(dist,nearest,tri,uv,material)
    _,nearest,tri,uv,material=best;mi.append(material)
    for l in layers:out_uv[l].append(list(barycentric_transform(nearest,*tri,*uv[l]))[:2])
   faces.append(idx);face_uv.append(out_uv);face_material.append(collections.Counter(mi).most_common(1)[0][0])
  reports.append(dict(component=ci,faces=len(coords)-1,closed=closed,old_faces=len(g['faces']),stations=len(coords)))
 mesh=bpy.data.meshes.new(old.name+'_Слитное');mesh.from_pydata(verts,[],faces);mesh.update()
 for material in old.materials:mesh.materials.append(material)
 for i,f in enumerate(mesh.polygons):f.material_index=face_material[i]
 for l in layers:
  layer=mesh.uv_layers.new(name=l)
  for i,f in enumerate(mesh.polygons):
   for loop,uv in zip(f.loop_indices,face_uv[i][l]):layer.data[loop].uv=uv
 source.data=mesh;source['continuous_windows']=len(reports);source['continuous_infill']=True
 text=bpy.data.texts.get('window_continuous_infill.py') or bpy.data.texts.new('window_continuous_infill.py');text.clear();text.write(Path(__file__).read_text(encoding='utf-8'))
 result=dict(windows=len(reports),vertices=len(verts),quads=len(faces),single_quad_windows=sum(x['faces']==1 for x in reports),details=reports)
 json.dump(result,open(BASE/'work/continuous_result.json','w'),ensure_ascii=False,indent=2);print({k:v for k,v in result.items() if k!='details'})
 return result
if __name__=='__main__':build()
