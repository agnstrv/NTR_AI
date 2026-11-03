import importlib.util,json,time
from pathlib import Path
import numpy as np
root=Path(__file__).resolve().parents[2]/'src'/'window-atlas';s=importlib.util.spec_from_file_location('tolerant',root/'tolerant_groups.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
group=m.group_tiles
start=time.perf_counter()
def boundary(x,h=12,w=16):
 a=np.ones((h,w),np.uint8);a[:,x:]=2;return a
def same(a,b):return len(group([a,b]))==1
assert same(boundary(8),boundary(9))
assert not same(boundary(8),boundary(10))
a=boundary(8);b=a.copy();b[:,4]=3
assert not same(a,b) # A new separator cannot be swallowed.
c=b.copy();c[:,4]=1
assert not same(b,c) # Lost separator is also forbidden.
a=np.tile(np.array([1,1,3,3,2,2,4,4],np.uint8),(8,1));b=np.tile(np.array([1,1,4,4,2,2,3,3],np.uint8),(8,1))
assert not same(a,b) # Changed colour order.
a=boundary(8);large=np.repeat(np.repeat(a,2,axis=0),2,axis=1)
g=group([a,large]);assert len(g)==1 and g[0]['representative']==1
assert len(group([boundary(8),boundary(10)],tolerance=2))==1
assert len(group([boundary(8),boundary(11)],tolerance=2))==2
assert len(group([boundary(8),boundary(11)],tolerance=3))==1
assert len(group([boundary(8),boundary(12)],tolerance=3))==2
# Repeated same-colour separators cannot match a neighbouring separator.
counter_a=np.full((4,19),2,np.uint8);counter_a[:,[1,3,5,7,9,13,17]]=3
counter_b=np.full((4,19),2,np.uint8);counter_b[:,[1,5,9,11,13,15,17]]=3
assert len(group([counter_a,counter_b],tolerance=2))==2
assert len(group([counter_a.T.copy(),counter_b.T.copy()],tolerance=2))==2
assert len(group([counter_a,counter_b],tolerance=3))==2
counter_c=np.full((4,19),2,np.uint8);counter_c[:,[2,4,6,8,10,14,18]]=3
# Keep a trailing white pixel so the edge topology is unchanged.
wide_a=np.pad(counter_a,((0,0),(0,2)),constant_values=2)
wide_c=np.pad(counter_c,((0,0),(0,2)),constant_values=2)
assert len(group([wide_a,wide_c],tolerance=1))==1
assert len(group([boundary(8),boundary(9)],tolerance=0))==2
# No transitive chaining: 8~9 and 9~10 does not permit 8~10.
g=group([boundary(8),boundary(9),boundary(10)]);assert len(g)==2
# Confirm connectivity counts using direct flood fill, randomized tiny tiles.
rng=np.random.default_rng(55)
def flood(a):
 seen=np.zeros(a.shape,bool);counts={};h,w=a.shape
 for y in range(h):
  for x in range(w):
   if seen[y,x]:continue
   color=int(a[y,x]);counts[color]=counts.get(color,0)+1;stack=[(y,x)];seen[y,x]=True
   while stack:
    yy,xx=stack.pop()
    for dy,dx in [(0,1),(0,-1),(1,0),(-1,0)]:
     ny,nx=yy+dy,xx+dx
     if 0<=ny<h and 0<=nx<w and not seen[ny,nx] and a[ny,nx]==color:seen[ny,nx]=True;stack.append((ny,nx))
 return tuple(sorted(counts.items()))
for _ in range(100):
 a=rng.integers(1,5,size=(12,16),dtype=np.uint8);assert m._component_counts(a)==flood(a)
a=boundary(8);saved=a.copy();assert same(a,a);assert np.array_equal(a,saved)
assert group([])==[]
for bad in [[np.zeros((2,2),float)],[np.zeros((0,2),np.uint8)]]:
 try:group(bad)
 except ValueError:pass
 else:raise AssertionError('invalid tile accepted')
report={'result':'passed','checks':['1px boundary shift grouped','2px boundary shift rejected at tolerance1','tolerance2 and3 exact limits','repeated-separator substitution counterexample rejected in both orientations','all ordered separators shifted1 grouped','lost/new separator rejected','changed colour order rejected','largest representative','native-grid resize both directions','zero tolerance','no transitive chains','100 randomized component counts versus independent flood fill','no mutation','empty and invalid inputs'],'seconds':time.perf_counter()-start}
print(json.dumps(report,indent=2))
