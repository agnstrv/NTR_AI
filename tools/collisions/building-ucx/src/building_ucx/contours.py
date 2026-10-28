"""Experimental 2D decomposition extracted from the October production trial."""
import numpy as np,shapely
from shapely.geometry import Polygon,MultiPolygon
from shapely.ops import unary_union

def polys(g):
 if g.is_empty:return []
 if g.geom_type=='Polygon':return [g]
 if not hasattr(g,'geoms'):return []
 return [p for q in g.geoms for p in polys(q)]

def convex_parts(poly):
 poly=shapely.set_precision(poly,.001)
 if poly.geom_type!='Polygon':return [piece for component in polys(poly) for piece in convex_parts(component)]
 if poly.area<.0001:return []
 if not poly.interiors and poly.convex_hull.area-poly.area<1e-10:return [poly.convex_hull]
 triangles=list(shapely.constrained_delaunay_triangles(poly).geoms)
 parts={i:p for i,p in enumerate(triangles) if p.area>1e-7}
 while True:
  edges={};candidates=[]
  for i,p in parts.items():
   xy=list(p.exterior.coords)
   for a,b in zip(xy,xy[1:]):
    key=tuple(sorted((tuple(np.round(a,3)),tuple(np.round(b,3)))))
    if key in edges:
     j=edges[key];h=unary_union([p,parts[j]])
     if h.geom_type=='Polygon' and not h.interiors and h.convex_hull.area-h.area<1e-10:
      # Prefer long joins and compact, large resulting convex volumes.
      score=(np.linalg.norm(np.array(a)-b),h.area)
      candidates.append((score,i,j,h.convex_hull))
    else:edges[key]=i
  if not candidates:break
  candidates.sort(key=lambda c:c[0],reverse=True);used=set()
  for _,i,j,h in candidates:
   if i in used or j in used:continue
   parts[i]=h;del parts[j];used.update((i,j))
 return list(parts.values())

def prism(p,lo,hi,kind):
 xy=np.array(shapely.orient_polygons(p).exterior.coords[:-1]);n=len(xy)
 return {'kind':kind,'vertices':np.vstack([np.c_[xy,np.full(n,lo)],np.c_[xy,np.full(n,hi)]]).tolist(),
 'faces':[list(range(n-1,-1,-1)),list(range(n,2*n))]+[[i,(i+1)%n,(i+1)%n+n,i+n] for i in range(n)],'lo':lo,'hi':hi,'wkt':p.wkt}
