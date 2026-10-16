"""Вырезать внутреннюю пустоту за плейнами по исходному мешу рам.

Blender Text Editor: Run Script. По внешним границам сохраняется полоса
шириной 10 см. Положение рам и плейнов не меняется.
Алгоритм использует проекцию реальных полигонов рам, сохраняет изгибы.
"""
import bpy,bmesh,numpy as np,collections
from mathutils import Vector
from mathutils.geometry import delaunay_2d_cdt
SOURCE_NAME='WindowFrameSource'

def normal(p):
    q=p-p.mean(axis=0);n=np.sum(np.cross(q,np.roll(q,-1,axis=0)),axis=0)
    return n/np.linalg.norm(n)

def slab_clip(poly,n,lo,hi):
    for sign,bound in ((1,hi),(-1,-lo)):
        result=[]
        for a,b in zip(poly,poly[1:]+poly[:1]):
            da=sign*float(a@n)-bound;db=sign*float(b@n)-bound
            if da<=0:result.append(a)
            if (da<0 and db>0) or (da>0 and db<0):result.append(a+(b-a)*da/(da-db))
        poly=result
        if len(poly)<3:return []
    return poly

def convex_hull(points):
    p=sorted(set((round(float(q[0]),7),round(float(q[1]),7)) for q in points))
    def cross(a,b,c):return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
    lower=[];upper=[]
    for q in p:
        while len(lower)>1 and cross(lower[-2],lower[-1],q)<=1e-10:lower.pop()
        lower.append(q)
    for q in reversed(p):
        while len(upper)>1 and cross(upper[-2],upper[-1],q)<=1e-10:upper.pop()
        upper.append(q)
    return np.array(lower[:-1]+upper[:-1])

def cut_window_planes(planes=None,source_name=SOURCE_NAME):
    source=bpy.data.objects[source_name]
    anchor=np.array(source.matrix_world.translation,dtype=float)
    scale=bpy.context.scene.unit_settings.scale_length or 1.
    sm=np.array(source.matrix_world,dtype=float)
    sp=np.array([tuple(v.co) for v in source.data.vertices])@sm[:3,:3].T+(sm[:3,3]-anchor)
    source.data.calc_loop_triangles()
    tri=np.array([list(t.vertices) for t in source.data.loop_triangles])
    tp=sp[tri];mins=tp.min(axis=1);maxs=tp.max(axis=1)
    parent=list(range(len(sp)))
    def root(i):
        while parent[i]!=i:parent[i]=parent[parent[i]];i=parent[i]
        return i
    for e in source.data.edges:
        a,b=e.vertices;parent[root(a)]=root(b)
    vertex_groups=np.array([root(i) for i in range(len(sp))]);group_vertices=collections.defaultdict(list)
    for i,g in enumerate(vertex_groups):group_vertices[int(g)].append(i)
    triangle_groups=vertex_groups[tri[:,0]];convex={g:True for g in group_vertices}
    for t,g in zip(tp,triangle_groups):
        n=np.cross(t[1]-t[0],t[2]-t[0]);length=np.linalg.norm(n)
        if length<1e-12:continue
        d=(sp[group_vertices[int(g)]]-t[0])@(n/length)
        if d.min()<-2e-5 and d.max()>2e-5:convex[int(g)]=False
    planes=list(planes) if planes is not None else [o for o in bpy.context.scene.objects if o.type=='MESH' and o.get('window_plane')]
    reports=[]
    for oi,obj in enumerate(planes):
        if obj.get('window_plane_cutouts'):
            reports.append({'object':obj.name,'already_processed':True});continue
        mesh=obj.data;matrix=np.array(obj.matrix_world,dtype=float);linear=matrix[:3,:3];offset=matrix[:3,3]-anchor
        old=np.array([tuple(v.co) for v in mesh.vertices]);points=old@linear.T+offset
        original_edges=collections.Counter(tuple(sorted((int(a),int(b)))) for f in mesh.polygons for a,b in zip(list(f.vertices),list(f.vertices)[1:]+list(f.vertices)[:1]))
        outer=[(points[a],points[b]) for (a,b),count in original_edges.items() if count==1]
        vertices=[];faces=[];covered=[];lookup={};directions=[]
        def vertex(p,n):
            key=tuple(np.rint(p/2e-5).astype(np.int64))
            if key not in lookup:lookup[key]=len(vertices);vertices.append(p);directions.append(n)
            else:directions[lookup[key]]=directions[lookup[key]]+n
            return lookup[key]
        for polygon in mesh.polygons:
            ids=list(polygon.vertices);p=points[ids];origin=p.mean(axis=0);n=normal(p)
            u=np.cross([0.,0.,1.],n)
            if np.linalg.norm(u)<.1:u=p[1]-p[0]
            u/=np.linalg.norm(u);v=np.cross(n,u);basis=np.array([u,v])
            plane=(p-origin)@basis.T
            lower=p.min(0)-.4/scale;upper=p.max(0)+.4/scale
            candidates=np.where(np.all(maxs>=lower,axis=1)&np.all(mins<=upper,axis=1))[0]
            verts2=[Vector(q) for q in plane];input_faces=[list(range(len(plane)))];bounds_lo=plane.min(0)-1e-5;bounds_hi=plane.max(0)+1e-5
            # Protect the existing 10 cm perimeter even where imported frame
            # members have tiny gaps at their joints.
            for ia,ib in zip(range(len(ids)),list(range(1,len(ids)))+[0]):
                if original_edges[tuple(sorted((ids[ia],ids[ib])))]!=1:continue
                a=plane[ia];b=plane[ib];d=b-a;length=np.linalg.norm(d)
                if length<1e-8:continue
                inward=np.array([-d[1],d[0]])/length
                band=np.array([a,b,b+inward*.10/scale,a+inward*.10/scale])
                start=len(verts2);verts2.extend(Vector(q) for q in band);input_faces.append(list(range(start,len(verts2))))
            projected_groups=collections.defaultdict(list)
            projected_polygons=[]
            for ti in candidates:
                q=tp[ti]-origin;depth=q@n
                if depth.min()>.03/scale or depth.max()<-.35/scale:continue
                clipped=slab_clip(list(q),n,-.35/scale,.03/scale)
                if len(clipped)<3:continue
                projected=np.array(clipped)@basis.T
                if np.any(projected.max(0)<bounds_lo) or np.any(projected.min(0)>bounds_hi):continue
                group=int(triangle_groups[ti])
                if convex[group]:projected_groups[group].extend(projected);continue
                projected_polygons.append(projected)
            projected_polygons.extend(convex_hull(q) for q in projected_groups.values())
            for projected in projected_polygons:
                if len(projected)<3:continue
                area=np.sum(projected[:,0]*np.roll(projected[:,1],-1)-projected[:,1]*np.roll(projected[:,0],-1))
                if abs(area)<1e-9:continue
                if area<0:projected=projected[::-1]
                start=len(verts2);verts2.extend(Vector(q) for q in projected);input_faces.append(list(range(start,len(verts2))))
            result=delaunay_2d_cdt(verts2,[],input_faces,1,1e-5,True)
            cv,ce,cf,ov,oe,of=result
            centers=np.array([np.array([tuple(cv[k]) for k in f]).mean(0) for f in cf])
            inside=np.zeros(len(cf),dtype=bool)
            for a,b in zip(plane,np.roll(plane,-1,axis=0)):
                crossing=(a[1]>centers[:,1])!=(b[1]>centers[:,1])
                if abs(b[1]-a[1])>1e-12:inside^=crossing&(centers[:,0]<(b[0]-a[0])*(centers[:,1]-a[1])/(b[1]-a[1])+a[0])
            support=np.zeros(len(cf),dtype=bool)
            # Coincident imported triangles can make CDT provenance ambiguous;
            # classify against the actual projected polygons instead.
            raw=np.array([tuple(q) for q in verts2])
            for source_face in input_faces[1:]:
                hull=raw[source_face];valid=np.ones(len(cf),dtype=bool)
                for a,b in zip(hull,np.roll(hull,-1,axis=0)):
                    d=b-a;q=centers-a;valid&=(d[0]*q[:,1]-d[1]*q[:,0])>=-1e-9
                support|=valid
            for cfi,f in enumerate(cf):
                if not inside[cfi]:continue
                q=np.array([tuple(cv[k]) for k in f]);world=q@basis+origin
                if np.linalg.norm(np.cross(world[1]-world[0],world[2]-world[0]))<1e-10:continue
                out=[vertex(w,n) for w in world]
                if len(set(out))<3:continue
                if float(normal(world)@n)<0:out.reverse()
                faces.append(out);covered.append(bool(support[cfi]))
        if not faces:raise ValueError('Нет результата проекции: '+obj.name)
        edge_faces=collections.defaultdict(list)
        for fi,f in enumerate(faces):
            for a,b in zip(f,f[1:]+f[:1]):edge_faces[tuple(sorted((a,b)))].append(fi)
        empty=set(i for i,c in enumerate(covered) if not c);seen=set();remove=set();holes=0
        vertices=np.array(vertices)
        def on_outer(a,b):
            midpoint=(vertices[a]+vertices[b])/2
            for start,end in outer:
                d=end-start;t=float((midpoint-start)@d)/float(d@d)
                if -.0001<=t<=1.0001 and np.linalg.norm(midpoint-start-np.clip(t,0,1)*d)<5e-5:return True
            return False
        adj=collections.defaultdict(set);outer_void=set()
        for (a,b),use in edge_faces.items():
            void=[i for i in use if i in empty]
            if len(use)==1 and void and on_outer(a,b):outer_void.update(void)
            for i in void:adj[i].update(j for j in void if j!=i)
        for first in empty:
            if first in seen:continue
            todo=[first];seen.add(first);region=[];touches=False
            while todo:
                i=todo.pop();region.append(i);touches|=i in outer_void
                for j in adj[i]:
                    if j not in seen:seen.add(j);todo.append(j)
            if not touches:remove.update(region);holes+=1
        if remove:
            old_area=sum(f.area for f in mesh.polygons)
            inverse=np.linalg.inv(linear);local=(vertices-offset)@inverse.T
            me=bpy.data.meshes.new(mesh.name+'_Cutouts');me.from_pydata(local,[],[f for i,f in enumerate(faces) if i not in remove]);me.update()
            for mat in mesh.materials:me.materials.append(mat)
            # The generated planes have no UV layers; stop if the user added any.
            if mesh.uv_layers:raise ValueError('Для сохранения добавленной UV требуется отдельная обработка: '+obj.name)
            bm=bmesh.new();bm.from_mesh(me)
            bmesh.ops.remove_doubles(bm,verts=list(bm.verts),dist=2e-5/scale)
            bmesh.ops.dissolve_degenerate(bm,dist=1e-5/scale,edges=list(bm.edges))
            loose=[v for v in bm.verts if not v.link_faces]
            if loose:bmesh.ops.delete(bm,geom=loose,context='VERTS')
            bmesh.ops.dissolve_limit(bm,angle_limit=.0002,use_dissolve_boundaries=False,verts=list(bm.verts),edges=list(bm.edges),delimit={'NORMAL'})
            degenerate=[]
            for f in bm.faces:
                q=np.array([tuple(v.co) for v in f.verts]);q-=q.mean(0)
                if np.linalg.norm(np.sum(np.cross(q,np.roll(q,-1,axis=0)),axis=0))<1e-10:degenerate.append(f)
            if degenerate:bmesh.ops.delete(bm,geom=degenerate,context='FACES_ONLY')
            bm.to_mesh(me);bm.free();me.update();obj.data=me
            # New vertices receive the same outward reference, so later normal
            # checks remain valid without moving or expanding the cut surfaces.
            reference=[];incident=collections.defaultdict(list)
            actual=np.array([tuple(v.co) for v in me.vertices])@linear.T+offset
            for f in me.polygons:
                ids=list(f.vertices);n=normal(actual[ids])
                for index in ids:incident[index].append(n)
            depth=float(obj.get('window_plane_outward_offset_min_m',.075))/scale
            for index,world in enumerate(actual):
                A=np.array(incident[index]);delta=np.linalg.lstsq(A,np.full(len(A),depth),rcond=1e-3)[0] if len(A) else np.zeros(3)
                reference.append((world-delta-offset)@inverse.T)
            obj['window_plane_base_coordinates']=np.array(reference).ravel().tolist()
            removed_area=old_area-sum(f.area for f in me.polygons)
        else:removed_area=0.
        obj['window_plane_cutouts']=True
        reports.append({'object':obj.name,'holes':holes,'removed_triangles':len(remove),'removed_area_local':removed_area,'faces':len(obj.data.polygons)})
        if oi%25==0:print('CUTOUT_PROGRESS',oi+1,len(planes),flush=True)
    return reports

if __name__=='__main__':
    result=cut_window_planes();print('CUTOUTS_COMPLETE',sum(r.get('holes',0) for r in result))
