import json,numpy as np,collections
from pathlib import Path
base=Path(__file__).resolve().parent.parent
data=json.load(open(base/'work/continuous_groups.json'))
def projection(q,line):
 delta=np.diff(line,axis=0);length=np.linalg.norm(delta,axis=1);total=np.r_[0,np.cumsum(length)]
 t=np.clip(np.sum((q[:,None]-line[:-1])*delta,axis=2)/(length*length),0,1);pr=line[:-1]+t[:,:,None]*delta;ds=np.linalg.norm(pr-q[:,None],axis=2);k=ds.argmin(1)
 return total[k]+t[np.arange(len(q)),k]*length[k],ds[np.arange(len(q)),k],total
for g in data['groups']:
 p=np.concatenate([np.array(f['points']) for f in g['faces']]);q=p[:,:2];clusters=[]
 for v in q:
  hit=next((i for i,x in enumerate(clusters) if np.linalg.norm(v-x[0])<.001),None)
  if hit is None:clusters.append([v])
  else:clusters[hit].append(v)
 nodes=np.array([np.median(c,axis=0) for c in clusters]);N=len(nodes);dist=np.linalg.norm(nodes[:,None]-nodes[None,:],axis=2);used={0};near=dist[0].copy();prev=np.zeros(N,int);tree=collections.defaultdict(list)
 while len(used)<N:
  near[list(used)]=np.inf;j=int(near.argmin());i=int(prev[j]);tree[i].append((j,dist[i,j]));tree[j].append((i,dist[i,j]));used.add(j);better=dist[j]<near;near[better]=dist[j,better];prev[better]=j
 def far(i):
  dd={i:0};previous={i:None};todo=[i]
  while todo:
   a=todo.pop()
   for b,l in tree[a]:
    if b in dd:continue
    dd[b]=dd[a]+l;previous[b]=a;todo.append(b)
  last=max(dd,key=dd.get);return last,previous
 start,_=far(0);end,prev=far(start);path=[end]
 while path[-1]!=start:path.append(prev[path[-1]])
 line=nodes[path];s,err,total=projection(q,line);closed=False
 if max(err)>.003 and np.linalg.norm(line[0]-line[-1])<total[-1]/5:
  trial=np.vstack((line,line[0]));ss,ee,tt=projection(q,trial)
  if max(ee)<max(err)/2:line=trial;s,err,total=ss,ee,tt;closed=True
 if not closed and np.linalg.norm(line[0]-line[-1])<total[-1]/5:
  crosses=False
  for face in g['faces']:
   ss,ee,tt=projection(np.array(face['points'])[:,:2],line)
   if np.ptp(ss)>total[-1]*.75:crosses=True
  if crosses:
   line=np.vstack((line,line[0]));s,err,total=projection(q,line);closed=True
 # Store every actual bend; collinear sampling points are removed later.
 g['line']=line.tolist();g['closed']=closed;g['profile_max_error']=float(max(err));g['profile_rms_error']=float(np.sqrt(np.mean(err**2)))
json.dump(data,open(base/'work/continuous_profiled.json','w'),ensure_ascii=False)
print('profile errors',[(g['component'],round(g['profile_max_error'],5),g['closed']) for g in data['groups'] if g['profile_max_error']>.0015]);print('closed',[(g['component']) for g in data['groups'] if g['closed']])
