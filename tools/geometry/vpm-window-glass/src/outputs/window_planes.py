"""Создание плейнов окон по геометрии рам в Blender 5.0.

В Blender откройте этот файл в Text Editor и нажмите Run Script.
main() создаёт плейны и, если рядом есть window_plane_adjust.py,
смещает их к наружному краю и расширяет на 0,10 м.
Нормали всех полигонов направляются в сторону наружного смещения.
Для обработки только существующих плейнов: main(existing_only=True).
Исходный меш, его UV и материалы не изменяются. Файл сцены не сохраняется.
Алгоритм рассчитан на вертикальные окна указанного исходного проекта.
Повторный запуск обрабатывает существующие плейны. Для новой генерации:
main(recreate=True) создаёт новую коллекцию, сохраняя прежние плейны.
"""
import bpy
import bmesh
import numpy as np
import collections
import importlib.util
from pathlib import Path
from mathutils import Vector
from mathutils.bvhtree import BVHTree

SOURCE_NAME = 'WindowFrameSource'
COLLECTION_NAME = 'Плейны окон'

def _group_components(source):
    o=source
    M=o.matrix_world.to_3x3()
    b=bmesh.new()
    b.from_mesh(o.data)
    for v in b.verts:v.co=M@v.co
    seen=set();cs=[]
    for v in b.verts:
     if v in seen:continue
     todo=[v];seen.add(v);vs=[]
     while todo:
      w=todo.pop();vs.append(w)
      for e in w.link_edges:
       z=e.other_vert(w)
       if z not in seen:seen.add(z);todo.append(z)
     ps=np.array([tuple(w.co) for w in vs]);ind={w:i for i,w in enumerate(vs)};fs=list(set(f for w in vs for f in w.link_faces));faces=[[ind[w] for w in f.verts] for f in fs];cs.append({'points':ps,'faces':faces,'min':ps.min(0),'max':ps.max(0),'tree':BVHTree.FromPolygons([Vector(p) for p in ps],faces)})
    mins=np.array([c['min'] for c in cs]);maxs=np.array([c['max'] for c in cs]);parent=list(range(len(cs)))
    def find(i):
     while parent[i]!=i:parent[i]=parent[parent[i]];i=parent[i]
     return i
    pairs=0
    for i,c in enumerate(cs):
     candidates=np.where(np.all(maxs>=c['min']-.05001,axis=1)&np.all(mins<=c['max']+.05001,axis=1))[0]
     for j in candidates:
      if j<=i or find(i)==find(j):continue
      z=cs[j];hit=bool(c['tree'].overlap(z['tree']))
      if not hit:
       small,large=(c,z) if len(c['points'])<len(z['points']) else (z,c)
       hit=any(large['tree'].find_nearest(Vector(p),.05001)[0] is not None for p in small['points'])
      if hit:parent[find(i)]=find(j);pairs+=1
     pass  # Keep grouping silent in the interactive editor.
    groups={}
    for i,c in enumerate(cs):groups.setdefault(find(i),[]).append(i)
    r=[]
    for group in groups.values():
     ps=np.vstack([cs[i]['points'] for i in group]);lo=ps.min(0);hi=ps.max(0);vals=np.linalg.eigvalsh(np.cov(ps[:,:2].T));vertical=sum(cs[i]['max'][2]-cs[i]['min'][2]>.3 and np.linalg.norm((cs[i]['max']-cs[i]['min'])[:2])<.4 for i in group);horizontal=sum(cs[i]['max'][2]-cs[i]['min'][2]<.08 for i in group)
     r.append({'parts':group,'bounds':[lo.tolist(),hi.tolist()],'vertical':int(vertical),'horizontal':int(horizontal),'planarity_ratio':float(vals[0]/max(vals[1],1e-9))})

    data={'groups':r,'components':[{'points':c['points'].tolist(),'faces':c['faces']} for c in cs],'translation':list(o.matrix_world.translation)}
    b.free()
    return data

def _find_paths(D):
    reports=[]
    for gi,g in enumerate(D['groups']):
     vertical=[];rails=[]
     for ci in g['parts']:
      p=np.array(D['components'][ci]['points']);span=np.ptp(p,axis=0);center=p.mean(0);cov=(p-center).T@(p-center);vals,V=np.linalg.eigh(cov);direction=V[:,-1]
      if abs(direction[2])>.95 and span[2]>.1:
       vertical.append({'xy':center[:2],'lo':float(p[:,2].min()),'hi':float(p[:,2].max()),'source':ci})
      else:rails.append(p)
     parent=list(range(len(vertical)))
     def find(i):
      while parent[i]!=i:parent[i]=parent[parent[i]];i=parent[i]
      return i
     for i,a in enumerate(vertical):
      for j,z in enumerate(vertical[i+1:],i+1):
       if np.linalg.norm(a['xy']-z['xy'])<=.08001:parent[find(i)]=find(j)
     groups={}
     for i,c in enumerate(vertical):groups.setdefault(find(i),[]).append(c)
     cols=[{'xy':np.mean([x['xy'] for x in c],axis=0).tolist(),'lo':min(x['lo'] for x in c),'hi':max(x['hi'] for x in c)} for c in groups.values()];ps=np.array([c['xy'] for c in cols]);edges=set()
     for p in rails:
      xy=p[:,:2];mean=xy.mean(0);_,V=np.linalg.eigh((xy-mean).T@(xy-mean));ax=V[:,-1];ay=np.array([-ax[1],ax[0]]);width=(xy-mean)@ax;depth=(xy-mean)@ay
      if len(cols)<2:continue
      s=(ps-mean)@ax;t=(ps-mean)@ay;near_vertex=np.min(np.linalg.norm(ps[:,None,:]-xy[None,:,:],axis=2),axis=1)<.18; candidates=np.where(((s>=width.min()-.12)&(s<=width.max()+.12)&(np.abs(t)<max(.12,(depth.max()-depth.min())/2+.05)))|near_vertex)[0]
      order=sorted(candidates,key=lambda i:s[i])
      for i,j in zip(order,order[1:]):
       if np.linalg.norm(ps[i]-ps[j])>.1:edges.add(tuple(sorted((int(i),int(j)))))
     # Only repair a missing link at a profile junction, using the actual rail geometry as evidence.
     degrees=collections.Counter(k for e in edges for k in e);connected=set(degrees)
     reports.append({'group':gi,'columns':cols,'edges':sorted(edges),'degrees':list(degrees.values()),'parts':len(g['parts']),'unconnected':len(cols)-len(connected)})

    return reports

def _refine_paths(D, P):
    for gi,a in enumerate(P):
     cols=a['columns'];edges=set(tuple(e) for e in a['edges'])
     for ci in D['groups'][gi]['parts']:
      p=np.array(D['components'][ci]['points']);mean=p.mean(0);_,V=np.linalg.eigh((p-mean).T@(p-mean))
      if abs(V[2,-1])>.95:continue
      unique=[]
      for q in p[:,:2]:
       if not any(np.linalg.norm(q-z)<1e-5 for z in unique):unique.append(q)
      if len(unique)!=4:continue
      pairs=sorted((float(np.linalg.norm(x-y)),i,j) for i,x in enumerate(unique) for j,y in enumerate(unique[i+1:],i+1));used=set();ends=[]
      for dist,i,j in pairs:
       if i in used or j in used or dist>.4:continue
       used.update((i,j));xy=(unique[i]+unique[j])/2;ids=np.where((np.linalg.norm(p[:,:2]-unique[i],axis=1)<1e-5)|(np.linalg.norm(p[:,:2]-unique[j],axis=1)<1e-5))[0];lo=float(p[ids,2].min());hi=float(p[ids,2].max());ds=[np.linalg.norm(xy-c['xy']) for c in cols];k=int(np.argmin(ds))
       if ds[k]>.18:k=len(cols);cols.append({'xy':xy.tolist(),'lo':lo,'hi':hi,'inferred':True})
       elif cols[k].get('inferred'):cols[k]['lo']=min(cols[k]['lo'],lo);cols[k]['hi']=max(cols[k]['hi'],hi)
       ends.append(k)
      if len(ends)==2 and ends[0]!=ends[1]:edges.add(tuple(sorted(ends)))
     # Split a long inferred edge at every existing point on the same surface.
     fixed=set();xy=np.array([c['xy'] for c in cols])
     for i,j in edges:
      v=xy[j]-xy[i];length=np.linalg.norm(v);ts=(xy-xy[i])@v/max(length**2,1e-12);dist=np.linalg.norm(xy-(xy[i]+ts[:,None]*v),axis=1);ids=[k for k in range(len(cols)) if 0<ts[k]<1 and dist[k]<.055];order=[i]+sorted(ids,key=lambda k:ts[k])+[j]
      fixed.update(tuple(sorted((u,v))) for u,v in zip(order,order[1:]) if u!=v)
     a['edges']=sorted(fixed);degrees=collections.Counter(k for e in fixed for k in e);a['degrees']=list(degrees.values());a['unconnected']=len(cols)-len(degrees)
     # A rail end sometimes has no separate vertical post. Its height is fixed by the adjacent full-height posts.
     for k,c in enumerate(cols):
      if c['hi']-c['lo']<.3:
       adj=[cols[j if i==k else i] for i,j in fixed if k in (i,j)];full=[z for z in adj if z['hi']-z['lo']>.3]
       if full:c['lo']=min(z['lo'] for z in full);c['hi']=max(z['hi'] for z in full)

    return P

def _build_planes(source, col, G, P):
    made=[]
    counts=[]
    translation=Vector(G['translation'])
    # Match the outward direction to the nearby facade.
    main=bpy.data.objects.get('Main');facade=None
    if main:
     mesh=main.data;facade=BVHTree.FromPolygons([main.matrix_world@v.co for v in mesh.vertices],[list(f.vertices) for f in mesh.polygons])
    for gi,a in enumerate(P):
     columns=a['columns'];xy=np.array([c['xy'] for c in columns]);mean=xy.mean(0);_,basis=np.linalg.eigh((xy-mean).T@(xy-mean))
     if np.max(np.abs((xy-mean)@basis[:,0]))<1e-4:xy=mean+(((xy-mean)@basis[:,1])[:,None]*basis[:,1])
     edges=set(tuple(e) for e in a['edges']);raw=[]
     for ci in G['groups'][gi]['parts']:
      p=np.array(G['components'][ci]['points']);mean=p.mean(0);_,V=np.linalg.eigh((p-mean).T@(p-mean))
      if abs(V[2,-1])>.95 and np.ptp(p[:,2])>.1:raw.append((mean[:2],float(p[:,2].min()),float(p[:,2].max())))
     spans=[]
     for i,c in enumerate(columns):
      distances=[np.linalg.norm(q-xy[i]) for q,lo,hi in raw];best=min(distances,default=100)
      intervals=sorted((lo,hi) for dist,(q,lo,hi) in zip(distances,raw) if dist<=min(.18,best+.012))
      merged=[]
      for lo,hi in intervals:
       if merged and lo<=merged[-1][1]+.012:merged[-1]=(merged[-1][0],max(merged[-1][1],hi))
       else:merged.append((lo,hi))
      spans.append(merged)
     for repeat in range(3):
      for i,s in enumerate(spans):
       if s:continue
       adj=[j if i==k else k for k,j in edges if i in (k,j)];near=[spans[j] for j in adj if spans[j]]
       if near:
        allspans=sorted(q for z in near for q in z);merged=[]
        for lo,hi in allspans:
         if merged and lo<=merged[-1][1]+.012:merged[-1]=(merged[-1][0],max(merged[-1][1],hi))
         else:merged.append((lo,hi))
        spans[i]=merged
     # Remove a diagonal shortcut across the two posts of a mitred corner.
     changed=True
     while changed:
      changed=False
      for i,j in list(edges):
       for k in range(len(columns)):
        if k in (i,j) or tuple(sorted((i,k))) not in edges or tuple(sorted((j,k))) not in edges:continue
        tri=[tuple(sorted(e)) for e in ((i,j),(i,k),(j,k))];lengths=[np.linalg.norm(xy[u]-xy[v]) for u,v in tri]
        if min(lengths)<.3 and max(lengths)<2:
         edges.remove(tri[int(np.argmax(lengths))]);changed=True;break
       if changed:break
     verts=[];faces=[];vlookup={};segments=[]
     def vert(x,y,z):
      key=(round(float(x),5),round(float(y),5),round(float(z),4))
      if key not in vlookup:vlookup[key]=len(verts);verts.append((float(x),float(y),float(z)))
      return vlookup[key]
     for i,j in edges:
      for lo,hi in spans[i]:
       for low,high in spans[j]:
        if min(hi,high)-max(lo,low)<.12:continue
        l0,h0,l1,h1=lo,hi,low,high
        # A shared tall post may border two distinct storey windows.
        if (hi-lo)-(high-low)>.8 and lo<=low+.02 and hi>=high-.02:l0,h0=low,high
        if (high-low)-(hi-lo)>.8 and low<=lo+.02 and high>=hi-.02:l1,h1=lo,hi
        vs=[vert(*xy[i],l0),vert(*xy[j],l1),vert(*xy[j],h1),vert(*xy[i],h0)]
        if len(set(vs))<4:continue
        pts=[Vector(verts[k])+translation for k in vs];normal=(pts[1]-pts[0]).cross(pts[3]-pts[0]);center=sum(pts,Vector())/4
        if facade:
         q=facade.find_nearest(center)
         if q[0] is not None and normal.dot(q[1])<0:vs.reverse()
        faces.append(vs);segments.append((i,j,l0,h0,l1,h1))
     assert faces,('No faces',gi)
     # Make a separate object for each connected window surface.
     mesh=bpy.data.meshes.new('_WindowTemp');mesh.from_pydata(verts,[],faces);b=bmesh.new();b.from_mesh(mesh);b.faces.ensure_lookup_table();seen=set();pieces=[]
     for f in b.faces:
      if f in seen:continue
      todo=[f];seen.add(f);fs=[]
      while todo:
       w=todo.pop();fs.append(w)
       for e in w.edges:
        for z in e.link_faces:
         if z not in seen:seen.add(z);todo.append(z)
      pieces.append(fs)
     for fs in pieces:
      vset=list(set(v for f in fs for v in f.verts));index={v:k for k,v in enumerate(vset)};me=bpy.data.meshes.new(f'WindowPlane_{len(made)+1:03d}');me.from_pydata([v.co for v in vset],[],[[index[v] for v in f.verts] for f in fs]);bm=bmesh.new();bm.from_mesh(me);bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces));bm.normal_update();before=len(bm.faces)
      # Remove coplanar divisions, keeping all bends in the surface.
      bmesh.ops.dissolve_limit(bm,angle_limit=.0002,use_dissolve_boundaries=False,verts=list(bm.verts),edges=list(bm.edges),delimit={'NORMAL'});bm.to_mesh(me);bm.free();me.update();obj=bpy.data.objects.new(f'Окно_Plane_{len(made)+1:03d}',me);col.objects.link(obj);obj.location=translation;obj['source_object']=source.name;obj['source_window_group']=gi+1;obj['window_plane']=True;made.append(obj)
     counts.append((gi,len(pieces),len(faces)));b.free();bpy.data.meshes.remove(mesh)

    return made

def create_window_planes(source_name=SOURCE_NAME, collection_name=COLLECTION_NAME):
    """Создать отдельный меш для каждого окна; вернуть список объектов.

    Изгибы сохраняются рёбрами, копланарные деления удаляются.
    Расстояния в алгоритме заданы в метрах; требуется Unit Scale = 1.
    """
    source = bpy.data.objects.get(source_name)
    if source is None or source.type != 'MESH':
        raise ValueError('Не найден исходный меш: ' + source_name)
    unit_scale = bpy.context.scene.unit_settings.scale_length or 1.0
    if abs(unit_scale - 1.0) > 1e-8:
        raise ValueError('Этот алгоритм требует Unit Scale = 1 (одна единица = метр).')
    G = _group_components(source)
    P = _refine_paths(G, _find_paths(G))
    col = bpy.data.collections.get(collection_name)
    if col is None:
        col = bpy.data.collections.new(collection_name)
        bpy.context.scene.collection.children.link(col)
    made = _build_planes(source, col, G, P)
    print('Создано плейнов окон:', len(made))
    return made


def main(existing_only=False, source_name=SOURCE_NAME,
         collection_name=COLLECTION_NAME, adjust=True, recreate=False):
    """Создать и обработать плейны либо обработать уже существующие."""
    col = bpy.data.collections.get(collection_name)
    existing = [o for o in col.objects if o.type == 'MESH' and o.get('window_plane')] if col else []
    if existing_only or (existing and not recreate):
        if col is None:
            raise ValueError('Не найдена коллекция: ' + collection_name)
        made = existing
        if not made:
            raise ValueError('В коллекции нет плейнов окон.')
    else:
        if recreate:
            fresh = bpy.data.collections.new(collection_name)
            bpy.context.scene.collection.children.link(fresh)
            collection_name = fresh.name
        made = create_window_planes(source_name, collection_name)
    if adjust and not all(o.get('window_plane_cutouts') for o in made):
        bpy.context.view_layer.update()
        filename = globals().get('__file__')
        if not filename:
            text = bpy.context.space_data.text if bpy.context.area and bpy.context.area.type == 'TEXT_EDITOR' else None
            filename = bpy.path.abspath(text.filepath) if text and text.filepath else None
        companion = Path(filename).resolve().with_name('window_plane_adjust.py') if filename else None
        if companion is None or not companion.is_file():
            raise FileNotFoundError('Сохраните этот скрипт и window_plane_adjust.py в одной папке либо вызовите main(adjust=False).')
        spec = importlib.util.spec_from_file_location('window_plane_adjust', companion)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.adjust_window_planes(made, source_name=source_name, expansion=0.10)
    return made


if __name__ == '__main__':
    main()
