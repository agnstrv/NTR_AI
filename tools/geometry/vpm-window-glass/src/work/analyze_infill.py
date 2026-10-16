import bpy,numpy as np,json,collections
from pathlib import Path
base=Path(__file__).resolve().parents[1]
bpy.ops.wm.open_mainfile(filepath=str(base/'outputs/Windows_Infill_Before.blend'))
o=bpy.data.objects['Plane'];m=o.data
p=np.array([v.co[:] for v in m.vertices],float);fs=[list(f.vertices) for f in m.polygons]
exec((base/'outputs/window_quad_retopology.py').read_text(encoding='utf-8').split('def profile')[0].split("TARGET='Окно_Plane_001'")[1])
cs=components(p,fs)
print('components',len(cs),'sizes',collections.Counter(len(v) for v,f in cs))
report=[]
for ci,(vs,ff) in enumerate(cs):
 q=p[vs];ns=np.array([m.polygons[i].normal[:] for i in ff]);ar=np.array([m.polygons[i].area for i in ff]);cov=np.linalg.eigvalsh(np.cov(q[:,:2].T))
 report.append(dict(i=ci,v=len(vs),f=len(ff),bounds=np.ptp(q,axis=0).tolist(),eig=cov.tolist()))
json.dump(dict(points=p.tolist(),faces=fs,components=cs,matrix=[list(r) for r in o.matrix_world],report=report),open(base/'work/infill_geometry.json','w'))
print(json.dumps(report[:10]))
for ci in [0,1,10]:
 vs,ff=cs[ci];q=p[vs];print('COMP',ci,'firstpoints',q[:20].tolist());print('normals',collections.Counter(tuple(round(x,3) for x in m.polygons[i].normal) for i in ff).most_common(15))
