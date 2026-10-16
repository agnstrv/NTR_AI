import numpy as np,json,collections
from pathlib import Path
base=Path(__file__).resolve().parent.parent
src=(base/'outputs/window_quad_retopology.py').read_text(encoding='utf-8');exec(src[src.index('def profile('):src.index('def levels(')])
d=json.load(open(base/'work/infill_geometry.json'));p=np.array(d['points']);n=len(p)//2;mid=(p[:n]+p[n:])/2;loopdata=json.load(open(base/'work/infill_loops.json'));ls=loopdata['loops'];cmap=loopdata['component_map']
mp={v:i for i,(vs,fs) in enumerate(d['components']) for v in vs};profiles=[]
for i,l in enumerate(ls):
 ids=l['ids'];line,total,s,error,complete,nodes,tree=profile(mid,[ids],ids,[0]);uv=np.column_stack((s,mid[ids,2]));profiles.append(dict(i=i,component=cmap[str(mp[ids[0]])],line=line.tolist(),total=total.tolist(),uv=uv.tolist(),error=error,inner=l['inner'],area=l['area']))
json.dump(profiles,open(base/'work/infill_profiles.json','w'))
print('profile failures',[(x['i'],x['component'],round(x['error'],5),round(x['area'],3),x['inner']) for x in profiles if x['error']>.002]);print('largest',[(x['i'],x['component'],round(x['area'],2),x['inner']) for x in profiles if x['area']>20])
