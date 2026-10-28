import numpy as np

def clean(poly):
 coords=[];mapping={};faces=[]
 for face in poly['polygons']:
  ids=[]
  for p in face:
   key=tuple(np.round(p,9))
   if key not in mapping:mapping[key]=len(coords);coords.append(p)
   i=mapping[key]
   if not ids or i!=ids[-1]:ids.append(i)
  if len(ids)>1 and ids[0]==ids[-1]:ids.pop()
  if len(set(ids))>=3:faces.append(ids)
 return {'vertices':np.array(coords,dtype=float).reshape(-1,3),'faces':faces}

def planes(poly):
 v=poly['vertices'];center=v.mean(0);out=[];seen=set()
 for face in poly['faces']:
  p=v[face];n=None
  for j in range(1,len(p)-1):
   q=np.cross(p[j]-p[0],p[j+1]-p[0]);length=np.linalg.norm(q)
   if length>1e-10:n=q/length;break
  if n is None:continue
  d=float(n@p[0])
  if n@center>d:n=-n;d=-d
  key=tuple(np.round(np.r_[n,d],7))
  if key in seen:continue
  seen.add(key);out.append((n,d))
 return out

def clip(poly,n,d):
 v=poly['vertices'];dist=v@n-d
 if not len(v) or dist.min()>1e-8:return None
 if dist.max()<=1e-9:return poly
 faces=[];caps=list(v[abs(dist)<1e-8])
 for face in poly['faces']:
  ps=v[face];ds=ps@n-d;out=[]
  for a,b,da,db in zip(ps,np.roll(ps,-1,axis=0),ds,np.roll(ds,-1)):
   if da<=1e-9:out.append(a)
   if (da<0 and db>0) or (da>0 and db<0):
    p=a+(b-a)*(da/(da-db));out.append(p);caps.append(p)
  if len(out)>=3:faces.append(out)
 if len(caps)>=3:
  cap=np.unique(np.round(caps,9),axis=0);center=cap.mean(0);helper=np.eye(3)[np.argmin(abs(n))];u=np.cross(n,helper);u/=np.linalg.norm(u);w=np.cross(n,u);q=cap-center;order=np.argsort(np.arctan2(q@w,q@u));faces.append(cap[order])
 if not faces:return None
 result=clean({'polygons':faces})
 return result if len(result['vertices'])>=4 else None

def volume(poly):
 v=poly['vertices'];c=v.mean(0);value=0.
 for face in poly['faces']:
  p=v[face]-c
  for i in range(1,len(p)-1):value+=abs(np.dot(p[0],np.cross(p[i],p[i+1])))/6
 return value

def subtract(a,b,eps=1e-8):
 bp=planes(b);av=a['vertices']
 if any(np.min(av@n-d)>=-eps for n,d in bp):return [a]
 intersection=a
 for n,d in bp:
  intersection=clip(intersection,n,d)
  if intersection is None:return [a]
 if volume(intersection)<eps:return [a]
 if np.all(np.max(av@np.array([n for n,d in bp]).T-np.array([d for n,d in bp]),axis=1)<eps):return []
 pieces=[];current=a
 for n,d in bp:
  outer=clip(current,-n,-d)
  if outer is not None and volume(outer)>eps:pieces.append(outer)
  current=clip(current,n,d)
  if current is None:break
 return pieces

def inset(poly,amount=.001):
 for n,d in planes(poly):
  poly=clip(poly,n,d-amount)
  if poly is None:return None
 return poly
