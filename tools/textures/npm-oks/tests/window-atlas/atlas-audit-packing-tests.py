"""Behavior checks for atlas-packing.py; standalone, no Blender."""
import importlib.util, json, random, time
from pathlib import Path
root=Path(__file__).resolve().parents[2]/'src'/'window-atlas'
spec=importlib.util.spec_from_file_location('atlas_packing',root/'atlas-packing.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
pack=m.pack_rectangles

def verify(sizes,result,width,height,padding):
    assert result is not None
    assert len(sizes)==len(result)
    rects=[]
    for (w,h),(x,y) in zip(sizes,result):
        r=(x-padding,y-padding,x+w+padding,y+h+padding)
        assert 0<=r[0]<r[2]<=width and 0<=r[1]<r[3]<=height
        for a,b,c,d in rects:
            assert r[2]<=a or r[0]>=c or r[3]<=b or r[1]>=d, (r,(a,b,c,d))
        rects.append(r)

start=time.perf_counter()
assert pack([])==[]
assert pack([(8,2)],2,8,0) is None # No rotation.
assert pack([(11,1)],10,10,0) is None
assert pack([(6,6)]*3,10,10,0) is None # Area lower bound.
assert pack([(6,6)],10,10,3) is None # Padding must also fit.
verify([(4,4)],pack([(4,4)],10,10,3),10,10,3)
# Perfect packing of differently sized rectangles in gaps.
for sizes in [[(6,6),(4,4),(4,6),(6,4)],[(10,4),(6,6),(4,3),(4,3)],[(1,10)]*10]:
    verify(sizes,pack(sizes,10,10,0),10,10,0)
# A shelf cannot fill a shorter row's gaps with later shorter rectangles.
sizes=[(60,100),(40,60),(40,40)]
verify(sizes,pack(sizes,100,100,0),100,100,0)
rng=random.Random(8520)
count=0
for trial in range(40):
    sizes=[(rng.randint(2,40),rng.randint(2,150)) for _ in range(120)]
    result=pack(sizes,512,1024,3)
    verify(sizes,result,512,1024,3)
    assert result==pack(sizes,512,1024,3), 'non-deterministic'
    count+=len(sizes)
# Actual scale, many thin strips and tall sections, <= half-atlas bounds.
sizes=[(rng.randint(2,35),rng.randint(40,220)) for _ in range(600)]
verify(sizes,pack(sizes),1024,2048,3)
for bad in [[(0,2)],[(1.5,2)],[(True,4)]]:
    try:pack(bad)
    except ValueError:pass
    else:raise AssertionError('invalid input accepted')
report={'result':'passed','random_rectangles_checked':count,'atlas_scale_rectangles_checked':600,'checks':['bounds including padding','pairwise non-overlap including padding','index order','no rotation','deterministic','exact and impossible fits','empty and invalid inputs'],'seconds':time.perf_counter()-start}

print(json.dumps(report,indent=2))
