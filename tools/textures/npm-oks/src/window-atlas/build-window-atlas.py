"""Source-classified section atlas. Run with Blender factory startup on a copy.
Configuration and all client data stay outside version control.
"""
import bpy,json,math,hashlib,struct,zlib,importlib.util,sys
import numpy as np
from pathlib import Path
from collections import Counter
from mathutils import Vector
from mathutils.bvhtree import BVHTree
ROOT=Path(__file__).parent
config_path=Path(sys.argv[sys.argv.index('--config')+1]) if '--config' in sys.argv else ROOT/'case-config.json'
CONFIG=json.loads(config_path.read_text(encoding='utf-8-sig'))
OUT=Path(CONFIG['output']);OUT.mkdir(exist_ok=True,parents=True)
TARGETS=CONFIG['targets'];PAD=3
IMAGE_NAME=CONFIG.get('image_name','window-atlas-d.png')
BLEND_NAME=CONFIG.get('blend_name','window-atlas.blend')
if (OUT/BLEND_NAME).resolve()==Path(bpy.data.filepath).resolve():raise ValueError('Output must not overwrite the source blend')
worker=None
if '--raster-worker' in sys.argv:
 pos=sys.argv.index('--raster-worker');worker=(int(sys.argv[pos+1]),int(sys.argv[pos+2]))
COLORS=np.array([[255,0,0],[160,160,160],[255,255,255],[32,32,32],[255,0,0],[0,0,0]],np.uint8)
def module(name):
 s=importlib.util.spec_from_file_location(name,ROOT/(name+'.py'));m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
geom=module('geometry_sections');packing=module('atlas_packing');grouping=module('tolerant_groups')
def write_png(path,rgb):
 h,w,_=rgb.shape
 def chunk(tag,data):return struct.pack('>I',len(data))+tag+data+struct.pack('>I',zlib.crc32(tag+data)&0xffffffff)
 raw=b''.join(b'\x00'+row.tobytes() for row in rgb[::-1])
 path.write_bytes(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',w,h,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(raw,6))+chunk(b'IEND',b''))
def category(name):
 for key,value in CONFIG['source_ids'].items():
  if '['+key+']' in name:return value
 return 4
vertices=[];polygons=[];cats=[];names=[]
for o in bpy.data.collections[CONFIG['source_collection']].all_objects:
 if o.type!='MESH':continue
 off=len(vertices);vertices.extend(o.matrix_world@v.co for v in o.data.vertices)
 polygons.extend(tuple(off+i for i in p.vertices) for p in o.data.polygons)
 cats.extend([category(o.name)]*len(o.data.polygons));names.extend([o.name]*len(o.data.polygons))
TREE=BVHTree.FromPolygons(vertices,polygons)
HITS=Counter();MISSES=0;DEPTH=Counter();GRAZING=0
# Bidirectional, nearest to the actual target surface. No distant back wall projection.
def sample(p,n,record=False):
 global MISSES,GRAZING
 found=[]
 for sign in [-1,1]:
  loc,no,i,d=TREE.ray_cast(p-n*(sign*1e-5),n*sign,.40001)
  if i is not None:found.append(((loc-p).length,i,no))
 if not found:
  if record:MISSES+=1
  return 0
 dist,i,no=min(found,key=lambda t:t[0])
 if record:
  HITS[names[i]]+=1;DEPTH[round(dist,3)]+=1
  if abs(no.dot(n))<.2:GRAZING+=1
 return cats[i]
def cuts(points,n):
 u=Vector((-n.y,n.x,0)).normalized();v=n.cross(u).normalized()
 a=min(p.dot(u) for p in points);b=max(p.dot(u) for p in points)
 c=min(p.dot(v) for p in points);d=max(p.dot(v) for p in points)
 anchor=points[0]-u*points[0].dot(u)-v*points[0].dot(v)
 if b-a<.45:return []
 width=max(32,math.ceil((b-a)*120));dark=np.zeros(width,bool)
 for x in range(width):
  xx=a+(x+.5)/width*(b-a)
  dark[x]=sum(sample(anchor+u*xx+v*(c+t*(d-c)),n)==3 for t in [.13,.27,.41,.57,.71,.83,.93])>=5
 result=[];start=None
 for i,val in enumerate(np.r_[dark,False]):
  if val and start is None:start=i
  if not val and start is not None:
   xx=a+(start+i)/2/width*(b-a)
   if xx>a+.08 and xx<b-.08:result.append(xx)
   start=None
 return result
prepared={};sections=[];before={};smooth={}
for name in TARGETS:
 o=bpy.data.objects[name];before[name]={'vertices':len(o.data.vertices),'faces':len(o.data.polygons),'area':sum(p.area for p in o.data.polygons)}
 smooth[name]=[p.use_smooth for p in o.data.polygons]
 result=geom.prepare_sections(o,cuts);prepared[name]=result
 for sid,section in result['sections'].items():
  section['name']=name;section['id']=sid;section['global_id']=len(sections);sections.append(section)
 print('GEOMETRY',name,result['stats'],flush=True)
if worker is None:(OUT/'section-geometry.json').write_text(json.dumps({name:{'vertices':[list(v) for v in r['vertices']],'faces':[f['indices'] for f in r['faces']]} for name,r in prepared.items()}),encoding='utf-8')
# Rasterize once at high density, retain source samples and polygon mask for auditing.
HIGH=64

cache_inputs={'source_sha256':hashlib.sha256(Path(bpy.data.filepath).read_bytes()).hexdigest(),'targets':TARGETS,'source_collection':CONFIG['source_collection'],'source_ids':CONFIG['source_ids'],'high_density':HIGH,'sampling_version':3,'geometry_sha256':hashlib.sha256((ROOT/'geometry_sections.py').read_bytes()).hexdigest()}
cache_fingerprint=hashlib.sha256(json.dumps(cache_inputs,sort_keys=True).encode()).hexdigest()[:16]
CACHE=Path(CONFIG.get('cache_root',str(OUT)))/('raster-cache-'+cache_fingerprint);CACHE.mkdir(exist_ok=True)
if worker is None:(OUT/'cache-manifest.json').write_text(json.dumps(cache_inputs,indent=2),encoding='utf-8')
all_hits=Counter();all_depth=Counter();all_misses=0;all_grazing=0
for k,s in enumerate(sections):
 if worker is not None and k%worker[1]!=worker[0]:continue
 cache_path=CACHE/('%04d.npz'%k)
 if cache_path.exists():
  cached=np.load(cache_path);s['high']=cached['grid'];s['mask']=cached['mask'];stats=json.loads(str(cached['stats']))
  all_hits.update(stats['hits']);all_depth.update({float(a):b for a,b in stats['depth'].items()});all_misses+=stats['misses'];all_grazing+=stats['grazing']
  continue
 HITS.clear();DEPTH.clear();MISSES=0;GRAZING=0
 u,v,a,b,c,d,anchor=s['frame'];n=s['n'];w=max(2,math.ceil((b-a)*HIGH));h=max(2,math.ceil((d-c)*HIGH))
 xs=a+(np.arange(w)+.5)/w*(b-a);ys=c+(np.arange(h)+.5)/h*(d-c)
 xx,yy=np.meshgrid(xs,ys);mask=np.zeros((h,w),bool)
 for poly in s['polygons']:
  pv=[(p.dot(u),p.dot(v)) for p in poly];inside=np.zeros((h,w),bool)
  for (x1,y1),(x2,y2) in zip(pv,pv[1:]+pv[:1]):
   if abs(y2-y1)>1e-12:inside^=((y1>yy)!=(y2>yy))&(xx<(x2-x1)*(yy-y1)/(y2-y1)+x1)
  mask|=inside
 grid=np.full((h,w),4,np.uint8)
 for y in range(h):
  base=anchor+v*float(ys[y])
  for x in range(w):
   if mask[y,x]:grid[y,x]=sample(base+u*float(xs[x]),n,True)
 s['high']=grid;s['mask']=mask
 stats={'hits':dict(HITS),'depth':dict(DEPTH),'misses':MISSES,'grazing':GRAZING}
 with cache_path.with_suffix('.tmp').open('wb') as cache_file:np.savez_compressed(cache_file,grid=grid,mask=mask,stats=json.dumps(stats))
 cache_path.with_suffix('.tmp').replace(cache_path)
 all_hits.update(HITS);all_depth.update(DEPTH);all_misses+=MISSES;all_grazing+=GRAZING
 if k%300==0:print('HIGH_RASTER',k,len(sections),flush=True)
if worker is not None:
 print('WORKER_COMPLETE',worker,flush=True)
 sys.exit(0)
HITS=all_hits;DEPTH=all_depth;MISSES=all_misses;GRAZING=all_grazing
# Extend valid border colours eight pixels outside each polygon before downsampling.
# Real no-hit pixels inside the mask remain red and stay separately counted.
for s in sections:
 grid=s['high'].copy();filled=s['mask'].copy()
 for iteration in range(8):
  if filled.all():break
  new=filled.copy()
  for dy,dx in [(0,1),(0,-1),(1,0),(-1,0)]:
   src=np.roll(grid,(dy,dx),(0,1));valid=np.roll(filled,(dy,dx),(0,1))
   if dy==1:valid[0,:]=False
   if dy==-1:valid[-1,:]=False
   if dx==1:valid[:,0]=False
   if dx==-1:valid[:,-1]=False
   take=valid&~new;grid[take]=src[take];new|=take
  filled=new
 s['high']=grid
# Shrink with nearest colour, conserving every sampled dark mullion through max pooling.
def shrink(s,density):
 u,v,a,b,c,d,anchor=s['frame'];w=max(2,math.ceil((b-a)*density));h=max(2,math.ceil((d-c)*density));src=s['high'];sh,sw=src.shape
 yi=np.minimum(sh-1,((np.arange(h)+.5)/h*sh).astype(int));xi=np.minimum(sw-1,((np.arange(w)+.5)/w*sw).astype(int))
 grid=src[np.ix_(yi,xi)].copy();grid[grid==0]=4
 # A subpixel dark separator must not disappear because the sample centre misses it.
 if np.any(src==3):
  sy,sx=np.nonzero(src==3)
  ty=np.minimum(h-1,((sy+.5)/sh*h).astype(int));tx=np.minimum(w-1,((sx+.5)/sw*w).astype(int))
  grid[ty,tx]=3
 return grid
(OUT/'section-manifest.json').write_text(json.dumps([{'id':s['global_id'],'object':s['name'],'parents':s['parents'],'width':s['frame'][3]-s['frame'][2],'height':s['frame'][5]-s['frame'][4],'nonplanar':s['nonplanar']} for s in sections]),encoding='utf-8')
def preserves_visible_classes(section,grid):
 high=section['high'];mask=section['mask'];sh,sw=high.shape;h,w=grid.shape
 yy=np.minimum(h-1,((np.arange(sh)+.5)/sh*h).astype(int));xx=np.minimum(w-1,((np.arange(sw)+.5)/sw*w).astype(int))
 actual=grid[np.ix_(yy,xx)][mask];expected=np.where(high[mask]==0,4,high[mask])
 return set(np.unique(expected)).issubset(set(np.unique(actual)))
if CONFIG.get('template_plan'):
 plan=json.loads(Path(CONFIG['template_plan']).read_text(encoding='utf-8'))
 def load_tile(path):
  data=Path(path).read_bytes();pos=8;packed=b''
  while pos<len(data):
   length=struct.unpack('>I',data[pos:pos+4])[0];tag=data[pos+4:pos+8];payload=data[pos+8:pos+8+length]
   if tag==b'IHDR':pw,ph,depth,kind,_,_,interlace=struct.unpack('>IIBBBBB',payload);assert (depth,kind,interlace)==(8,2,0)
   if tag==b'IDAT':packed+=payload
   pos+=length+12
  raw=np.frombuffer(zlib.decompress(packed),np.uint8).reshape(ph,1+pw*3);assert not raw[:,0].any()
  rgb=raw[:,1:].reshape(ph,pw,3)[::-1];grid=np.full((ph,pw),4,np.uint8)
  for category_id in [1,2,3,4]:grid[np.all(rgb==COLORS[category_id],axis=2)]=category_id
  return grid
 groups=[]
 assert 1<=len(plan['templates'])<=20
 assert [t['id'] for t in plan['templates']]==list(range(len(plan['templates'])))
 assert sorted(a['section'] for a in plan['assignments'])==list(range(len(sections)))
 assert all(0<=a['template']<len(plan['templates']) for a in plan['assignments'])
 for template in plan['templates']:
  tid=template['id'];grid=load_tile(template['png'])
  # Preserve every native texel. No downsampling of thin source features.
  if CONFIG.get('black_edge_traces'):
   red=grid==4;h,w=grid.shape;black=np.zeros_like(red)
   for vertical in [True,False]:
    view=red if vertical else red.T;target=black if vertical else black.T
    limit=max(2,math.ceil(view.shape[0]*.06))
    for column in range(view.shape[1]):
     line=view[:,column];start=None
     for index,value in enumerate(np.r_[line,False]):
      if value and start is None:start=index
      if not value and start is not None:
       length=index-start
       if length<=limit and (start<limit or index>len(line)-limit):target[start:index,column]=True
       start=None
   grid=grid.copy();grid[black]=5
  groups.append({'grid':grid,'members':template['members'],'representative':template['representative_section']})
 origins=packing.pack_rectangles([(g['grid'].shape[1],g['grid'].shape[0]) for g in groups],padding=PAD)
 if origins is None:raise RuntimeError('Native templates cannot fit reserved half; do not downsample silently')
 for g,xy in zip(groups,origins):g['xy']=xy
 for assignment in plan['assignments']:
  sections[assignment['section']]['group']=assignment['template'];sections[assignment['section']]['effective_density']=0
 density=0;TOLERANCE=None
 area=sum((g['grid'].shape[0]+2*PAD)*(g['grid'].shape[1]+2*PAD) for g in groups)
else:
 TOLERANCE=CONFIG.get('group_tolerance',2)
 for density in [48,40,32,28,24,20]:
  tiles=[]
  for s in sections:
   effective_density=density;grid=shrink(s,effective_density)
   while not preserves_visible_classes(s,grid) and effective_density<HIGH:
    effective_density=min(HIGH,effective_density*1.5);grid=shrink(s,effective_density)
   s['effective_density']=effective_density
   valid=s['high'][s['mask']];valid=np.where(valid==0,4,valid)
   if len(valid) and np.all(valid==valid[0]):grid=np.full((2,2),valid[0],np.uint8)
   tiles.append(grid)
  matches=grouping.group_tiles(tiles,tolerance=TOLERANCE)
  safe_matches=[]
  for match in matches:
   rep=match['representative'];safe=[]
   for sid in match['members']:
    if preserves_visible_classes(sections[sid],tiles[rep]):safe.append(sid)
    else:safe_matches.append({'representative':sid,'members':[sid]})
   if safe:safe_matches.append({'representative':rep,'members':safe})
  matches=safe_matches
  groups=[]
  for gid,match in enumerate(matches):
   groups.append({'grid':tiles[match['representative']],'members':match['members'],'representative':match['representative']})
   for sid in match['members']:sections[sid]['group']=gid
  sizes=[(g['grid'].shape[1],g['grid'].shape[0]) for g in groups]
  area=sum((w+2*PAD)*(h+2*PAD) for w,h in sizes)
  print('PACK_TRY',density,len(groups),area,flush=True)
  if area>1024*2048:continue
  origins=packing.pack_rectangles(sizes,padding=PAD)
  if origins is not None:
   for g,origin in zip(groups,origins):g['xy']=origin
   break
 else:raise RuntimeError('No acceptable atlas fit; no scene saved')
atlas=np.zeros((2048,2048,3),np.uint8)
for g in groups:
 x,y=g['xy'];h,w=g['grid'].shape;atlas[y-PAD:y+h+PAD,x-PAD:x+w+PAD]=COLORS[np.pad(g['grid'],PAD,mode='edge')]
write_png(OUT/IMAGE_NAME,atlas)
image=bpy.data.images.load(str(OUT/IMAGE_NAME),check_existing=False);image.colorspace_settings.name='sRGB'
mat=bpy.data.materials.new('M_Savinskaja_Windows');mat.use_nodes=True
tex=mat.node_tree.nodes.new('ShaderNodeTexImage');tex.image=image;tex.interpolation='Closest';tex.extension='EXTEND'
bsdf=mat.node_tree.nodes.get('Principled BSDF');mat.node_tree.links.new(tex.outputs['Color'],bsdf.inputs['Base Color']);bsdf.inputs['Roughness'].default_value=.5
report={'blender':bpy.app.version_string,'template_plan':CONFIG.get('template_plan'),'template_mode':bool(CONFIG.get('template_plan')),'black_edge_traces':bool(CONFIG.get('black_edge_traces')),'density_px_per_unit':density,'high_density':HIGH,'group_tolerance_pixels':TOLERANCE,'cuts':{n:r['stats'] for n,r in prepared.items()},'pieces':sum(len(r['faces']) for r in prepared.values()),'groups':len(groups),'repeated_groups':sum(len(g['members'])>1 for g in groups),'source_hits':dict(HITS),'no_hit_samples':MISSES,'depth_histogram':dict(DEPTH),'grazing_samples':GRAZING,'palette':COLORS.tolist(),'objects':{},'atlas':[2048,2048],'reserved_half':'x>=1024','padding':PAD,'group_manifest':[],'section_manifest':[]}
for name,r in prepared.items():
 o=bpy.data.objects[name];inv=o.matrix_world.inverted();mesh=bpy.data.meshes.new(name+'-window-sections');mesh.from_pydata([inv@v for v in r['vertices']],[],[f['indices'] for f in r['faces']]);mesh.update();uv=mesh.uv_layers.new(name='UVMap')
 for face,desc in zip(mesh.polygons,r['faces']):
  s=r['sections'][desc['section']];g=groups[s['group']];gx,gy=g['xy'];h,w=g['grid'].shape;u,v,a,b,c,d,anchor=s['frame']
  for li,q in zip(face.loop_indices,desc['poly']):uv.data[li].uv=((gx+(q.dot(u)-a)/(b-a)*w)/2048,(gy+(q.dot(v)-c)/(d-c)*h)/2048)
  face.use_smooth=smooth[name][desc['parent']]
 mesh.materials.append(mat);o.data=mesh
 after={'vertices':len(mesh.vertices),'faces':len(mesh.polygons),'area':sum(p.area for p in mesh.polygons)}
 report['objects'][name]={'before':before[name],'after':after,'area_relative_error':abs(after['area']-before[name]['area'])/before[name]['area']}
 assert report['objects'][name]['area_relative_error']<1e-5
 assert all(-1e-6<=p.uv.x<=.500001 and -1e-6<=p.uv.y<=1.000001 for p in uv.data)
for i,g in enumerate(groups):report['group_manifest'].append({'id':i,'xy':g['xy'],'size':[g['grid'].shape[1],g['grid'].shape[0]],'members':g['members'],'representative':g['representative']})
for s in sections:
 u,v,a,b,c,d,anchor=s['frame'];report['section_manifest'].append({'id':s['global_id'],'object':s['name'],'parents':s['parents'],'group':s['group'],'width':b-a,'height':d-c,'nonplanar':s['nonplanar'],'effective_density':s['effective_density']})
report['occupied_pixels_including_padding']=area;report['occupied_fraction']=area/2048**2
assert report['occupied_fraction']<=.5 and not atlas[:,1024:].any()
(OUT/'production-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
# Dump actual float32 output to independent geometry validator.
(OUT/'output-geometry.json').write_text(json.dumps({n:{'vertices':[list(bpy.data.objects[n].matrix_world@v.co) for v in bpy.data.objects[n].data.vertices],'faces':[list(p.vertices) for p in bpy.data.objects[n].data.polygons]} for n in TARGETS}),encoding='utf-8')
bpy.context.preferences.filepaths.save_version=0
bpy.ops.wm.save_as_mainfile(filepath=str(OUT/BLEND_NAME))
image.filepath='//'+IMAGE_NAME
bpy.ops.wm.save_as_mainfile(filepath=str(OUT/BLEND_NAME),relative_remap=False)
print('COMPLETE',density,len(groups),report['occupied_fraction'],flush=True)
