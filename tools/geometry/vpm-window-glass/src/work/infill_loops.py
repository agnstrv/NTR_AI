import json,numpy as np,collections
from pathlib import Path
base=Path(__file__).resolve().parent.parent
d=json.load(open(base/'work/infill_geometry.json'));p=np.array(d['points']);n=len(p)//2;mid=(p[:n]+p[n:])/2
mp={v:i for i,(vs,fs) in enumerate(d['components']) for v in vs};parent=list(range(len(d['components'])))
def root(i):
 while parent[i]!=i:parent[i]=parent[parent[i]];i=parent[i]
 return i
buckets=collections.defaultdict(list);weld={};tol=.00002
import itertools
for i,q in enumerate(mid):
 cell=np.floor(q/tol).astype(int);hits=[]
 for step in itertools.product([-1,0,1],repeat=3):
  for j in buckets[tuple(cell+step)]:
   if {mp[i],mp[j]} in ({163,164},{179,194}) and np.linalg.norm(q-mid[j])<tol:hits.append(j)
 if hits:
  j=min(hits);weld[i]=j;parent[root(mp[i])]=root(mp[j])
 else:weld[i]=i;buckets[tuple(cell)].append(i)
faces=[[weld[v] for v in f] for f in d['faces'] if max(f)<n]
faces=[f for f in faces if len(set(f))==len(f)]
edges=collections.defaultdict(list)
for fi,f in enumerate(faces):
 for a,b in zip(f,f[1:]+f[:1]):edges[tuple(sorted((a,b)))].append((a,b,fi))
boundary=[v[0] for v in edges.values() if len(v)==1];todo={(a,b):(fi) for a,b,fi in boundary};loops=[];bad=[]
while todo:
 a,b=next(iter(todo));loop=[a];fs=[]
 for k in range(len(boundary)+1):
  fs.append(todo.pop((a,b)) if (a,b) in todo else todo.pop((b,a)));loop.append(b)
  if b==loop[0]:break
  nxt=[e if e[0]==b else e[::-1] for e in todo if b in e]
  if len(nxt)!=1:bad.append((len(loop),len(nxt)));break
  a,b=nxt[0]
 else:bad.append('endless')
 if loop[-1]!=loop[0]:continue
 loop=loop[:-1];q=mid[loop];q=q-q.mean(0);ln=np.cross(q,np.roll(q,-1,axis=0)).sum(0)
 sn=np.zeros(3)
 for fi in fs:
  r=mid[faces[fi]];r-=r.mean(0);sn+=np.cross(r,np.roll(r,-1,axis=0)).sum(0)
 dot=float(ln@sn);loops.append(dict(ids=loop,inner=dot<0,area=float(np.linalg.norm(ln)/2),bounds=np.ptp(mid[loop],axis=0).tolist()))
json.dump(dict(loops=loops,bad=bad,component_map={i:root(i) for i in range(len(parent))}),open(base/'work/infill_loops.json','w'))
print('LOOPS',len(loops),'inner',sum(l['inner'] for l in loops),'bad',bad,'areas',np.quantile([l['area'] for l in loops if l['inner']],[0,.1,.5,.9,1]));print('outer',[(i,l['area'],l['bounds']) for i,l in enumerate(loops) if not l['inner']][:8])
