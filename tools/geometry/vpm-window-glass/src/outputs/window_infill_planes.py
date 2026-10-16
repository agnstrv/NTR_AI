"""Create quad window infills from the paired skins of applied Solidify frames.

Prepared geometry is read from work/infill_geometry.json. The original frames
are never modified. Units are meters. Each connected window frame receives
one mesh containing infills for its clear openings. Edges overlap frames 2 cm.
"""
import json,numpy as np,collections
from pathlib import Path
BASE=Path(__file__).resolve().parents[1]
OVERLAP=.02

def area(q):return float(np.sum(q[:,0]*np.roll(q[:,1],-1)-q[:,1]*np.roll(q[:,0],-1))/2)
def simplify(q):
 q=np.array(q,float)
 for _ in range(10):
  keep=[]
  for i,b in enumerate(q):
   a=q[i-1];c=q[(i+1)%len(q)];ab=b-a;bc=c-b
   if np.linalg.norm(ab)<1e-5:continue
   cross=abs(float(ab[0]*bc[1]-ab[1]*bc[0]));length=np.linalg.norm(c-a)
   if len(q)>3 and length>1e-8 and cross/length<.00003 and ab@bc>=0:continue
   keep.append(i)
  if len(keep)==len(q) or len(keep)<3:break
  q=q[keep]
 return q
def expand(q):
 if area(q)<0:q=q[::-1]
 out=[]
 for i,b in enumerate(q):
  a=q[i-1];c=q[(i+1)%len(q)];u=b-a;u/=np.linalg.norm(u);v=c-b;v/=np.linalg.norm(v)
  nu=np.array([u[1],-u[0]]);nv=np.array([v[1],-v[0]])
  mat=np.array([nu,nv]);delta=np.linalg.lstsq(mat,np.array([OVERLAP,OVERLAP]),rcond=None)[0]
  out.append(b+delta)
 return np.array(out)
def clip(q,x,greater):
 out=[]
 for a,b in zip(q,np.roll(q,-1,axis=0)):
  ia=a[0]>=x-1e-9 if greater else a[0]<=x+1e-9;ib=b[0]>=x-1e-9 if greater else b[0]<=x+1e-9
  if ia:out.append(a)
  if ia!=ib:out.append(a+(b-a)*((x-a[0])/(b[0]-a[0])))
 return simplify(out) if len(out)>2 else np.array([])
def build():
 import bpy
 from mathutils import Matrix,Vector
 from mathutils.geometry import tessellate_polygon
 d=json.load(open(BASE/'work/infill_geometry.json'));p=np.array(d['points']);n=len(p)//2;middle=(p[:n]+p[n:])/2
 profiles=json.load(open(BASE/'work/infill_profiles.json'));loops=json.load(open(BASE/'work/infill_loops.json'))['loops']
 groups=collections.defaultdict(list)
 for x in profiles:groups[x['component']].append(x)
 source=bpy.data.objects['Plane'];assert len(source.data.vertices)==len(p)
 assert max(np.linalg.norm(np.array([v.co[:] for v in source.data.vertices])-p,axis=1))<1e-7
 coll=bpy.data.collections.new('Заполнение окон — середина толщины');bpy.context.scene.collection.children.link(coll)
 reports=[];total_openings=0
 for ci,items in groups.items():
  outer={x['i'] for x in items if not x['inner']}
  outer.add(max(items,key=lambda x:x['area'])['i'])
  # Closed horizontal boundaries belong to the roof/rail framing, not glazing.
  outer.update(x['i'] for x in items if np.ptp(np.array(x['uv'])[:,1])<.0001)
  # A reversed skin reverses every loop in that frame, including its apertures.
  if all(not x['inner'] for x in items):outer={max(items,key=lambda x:x['area'])['i']}
  verts=[];faces=[];lookup={};opened=[];curved=0;max_error=0.
  def vertex(co):
   key=tuple(round(float(c),7) for c in co)
   if key not in lookup:lookup[key]=len(verts);verts.append(list(map(float,co)))
   return lookup[key]
  for item in items:
   if item['i'] in outer:continue
   uv=simplify(item['uv']);line=np.array(item['line']);total=np.array(item['total']);segments=np.diff(line,axis=0);length=np.linalg.norm(segments,axis=1)
   if len(uv)<3 or abs(area(uv))<.00001:continue
   assert item['error']<.002,(ci,item['i'],item['error'])
   uv=expand(uv);directions=segments/length[:,None]
   bends=[total[k] for k in range(1,len(total)-1) if np.linalg.norm(directions[k]-directions[k-1])>.0005]
   stops=[float(uv[:,0].min())]+[float(s) for s in bends if uv[:,0].min()+1e-5<s<uv[:,0].max()-1e-5]+[float(uv[:,0].max())]
   def mapco(q):
    s,z=q;k=int(np.clip(np.searchsorted(total,s,side='right')-1,0,len(length)-1));xy=line[k]+(s-total[k])/length[k]*segments[k]
    return np.array([xy[0],xy[1],z])
   ids=loops[item['i']]['ids'];orig=middle[ids];orig-=orig.mean(0);normal=np.cross(orig,np.roll(orig,-1,axis=0)).sum(0)
   # Hole loops run opposite to the exterior surface normal.
   target=-normal if item['inner'] else normal
   def emit(poly):
    if len(poly)<3:return
    xyz=np.array([mapco(q) for q in poly]);normal=np.cross(xyz-xyz.mean(0),np.roll(xyz-xyz.mean(0),-1,axis=0)).sum(0)
    if normal@target<0:poly=poly[::-1]
    if len(poly)==4:faces.append([vertex(mapco(q)) for q in poly]);return
    center=poly.mean(0)
    for i,b in enumerate(poly):
     a=poly[i-1];c=poly[(i+1)%len(poly)];quad=[b,(b+c)/2,center,(a+b)/2]
     faces.append([vertex(mapco(q)) for q in quad])
   parts=[]
   for a,b in zip(stops,stops[1:]):
    part=clip(clip(uv,a,True),b,False)
    if len(part)>2 and abs(area(part))>1e-9:parts.append(part)
   if any(len(part)!=4 for part in parts):
    # Split every strip in this aperture equally so boundary midpoints join.
    for part in parts:
     center=part.mean(0)
     for k,b in enumerate(part):
      a=part[k-1];c=part[(k+1)%len(part)];emit(np.array([b,(b+c)/2,center,(a+b)/2]))
   else:
    for part in parts:emit(part)
   opened.append(item['i']);curved+=int(len(stops)>2);max_error=max(max_error,item['error'])
  if not faces:continue
  # Conform rare coincident strip boundaries before adding edge midpoints.
  pts=np.array(verts);edge_hits={}
  for f in faces:
   for a,b in zip(f,f[1:]+f[:1]):
    key=tuple(sorted((a,b)))
    if key in edge_hits:continue
    a,b=key;vec=pts[b]-pts[a];length=np.linalg.norm(vec)
    if length<1e-8:continue
    t=(pts-pts[a])@vec/(length*length);dist=np.linalg.norm(pts-pts[a]-t[:,None]*vec,axis=1)
    hits=np.where((t*length>1e-5)&((1-t)*length>1e-5)&(dist<1e-5))[0]
    if len(hits):edge_hits[key]=[int(i) for i in sorted(hits,key=lambda i:t[i])]
  if edge_hits:
   conformed=[]
   for f in faces:
    outline=[]
    for a,b in zip(f,f[1:]+f[:1]):
     outline.append(a);key=tuple(sorted((a,b)));hits=edge_hits.get(key,[]);outline.extend(hits if a<b else hits[::-1])
    poly=pts[outline];center=poly.mean(0)
    for k,b in enumerate(poly):
     a=poly[k-1];c=poly[(k+1)%len(poly)];conformed.append([vertex(q) for q in [b,(b+c)/2,center,(a+b)/2]])
   faces=conformed
  used=sorted({v for f in faces for v in f});remap={v:i for i,v in enumerate(used)};verts=[verts[i] for i in used];faces=[[remap[v] for v in f] for f in faces]
  mesh=bpy.data.meshes.new(f'Окно_Заполнение_{ci+1:03d}');mesh.from_pydata(verts,[],faces);mesh.update()
  obj=bpy.data.objects.new(mesh.name,mesh);coll.objects.link(obj);obj.matrix_world=Matrix(d['matrix'])
  obj['window_infill']=True;obj['frame_source']='Plane';obj['frame_component']=ci;obj['overlap_m']=OVERLAP;obj['depth_fraction']=.5;obj['aperture_count']=len(opened)
  reports.append(dict(object=obj.name,component=ci,apertures=len(opened),vertices=len(verts),quads=len(faces),curved_apertures=curved,profile_error_m=max_error));total_openings+=len(opened)
 for o in bpy.context.selected_objects:o.select_set(False)
 for o in coll.objects:o.select_set(True)
 bpy.context.view_layer.objects.active=next(iter(coll.objects))
 result=dict(objects=len(reports),apertures=total_openings,quads=sum(r['quads'] for r in reports),curved_apertures=sum(r['curved_apertures'] for r in reports),overlap_m=OVERLAP,depth_fraction=.5,details=reports)
 json.dump(result,open(BASE/'work/infill_result.json','w'),ensure_ascii=False,indent=2)
 print('WINDOW INFILLS', {k:v for k,v in result.items() if k!='details'})
 return result
if __name__=='__main__':build()
