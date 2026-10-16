import bpy,json,numpy as np,collections
from pathlib import Path
from mathutils import Vector
from mathutils.kdtree import KDTree
base=Path(__file__).resolve().parents[1]
bpy.ops.wm.open_mainfile(filepath=str(base/'work/Windows_Infill_Review.blend'))
old=[];labels=[]
anchor=np.array(bpy.data.objects['Окно_Заполнение_001'].matrix_world,float)
for o in bpy.data.objects:
 if o.type!='MESH' or not o.get('window_infill'):continue
 mat=np.linalg.inv(anchor)@np.array(o.matrix_world,float)
 for v in o.data.vertices:old.append((mat@np.array([*v.co,1]))[:3]);labels.append(int(o['frame_component']))
tree=KDTree(len(old))
for i,p in enumerate(old):tree.insert(Vector(p),i)
tree.balance()
bpy.ops.wm.open_mainfile(filepath=str(base/'outputs/Windows_Continuous_Before.blend'))
objects=[o for o in bpy.data.objects if o.type=='MESH' and o.get('window_infill')];print('CURRENT',[(o.name,len(o.data.vertices),len(o.data.polygons),[l.name for l in o.data.uv_layers],[m.name if m else '' for m in o.data.materials]) for o in objects])
groups=collections.defaultdict(list);distances=[]
for o in objects:
 mat=np.linalg.inv(anchor)@np.array(o.matrix_world,float);p=np.array([(mat@np.array([*v.co,1]))[:3] for v in o.data.vertices]);lab=[]
 for pt in p:
  co,i,dist=tree.find(Vector(pt));lab.append(labels[i]);distances.append(dist)
 for f in o.data.polygons:
  ci=collections.Counter(lab[i] for i in f.vertices).most_common(1)[0][0]
  groups[ci].append(dict(object=o.name,face=f.index,points=p[list(f.vertices)].tolist()))
profiles=json.load(open(base/'work/infill_profiles.json'));out=[]
for ci,faces in groups.items():
 profile=max((x for x in profiles if x['component']==ci),key=lambda x:x['area']);line=np.array(profile['line']);s=np.array(profile['total']);d=np.diff(line,axis=0);length=np.linalg.norm(d,axis=1);p=np.concatenate([np.array(f['points']) for f in faces]);q=p[:,:2];t=np.clip(np.sum((q[:,None,:]-line[:-1])*d,axis=2)/(length*length),0,1);pr=line[:-1]+t[:,:,None]*d;ds=np.linalg.norm(pr-q[:,None,:],axis=2);best=ds.argmin(1);error=ds[np.arange(len(q)),best]
 out.append(dict(component=ci,faces=faces,profile=profile,max_error=float(max(error))))
json.dump(dict(anchor=anchor.tolist(),groups=out),open(base/'work/continuous_groups.json','w'),ensure_ascii=False)
print('GROUPS',len(groups),'old matching error',np.quantile(distances,[0,.5,.99,1]),'profile errors',[(x['component'],round(x['max_error'],6)) for x in out if x['max_error']>.0002])
