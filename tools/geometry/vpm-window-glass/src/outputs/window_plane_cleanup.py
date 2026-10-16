"""Blender: соединить Т-стыки плейнов и растворить лишние рёбра.

Запуск: Text Editor → Run Script. Обрабатываются только window_plane=True.
Контуры проёмов, внешние границы, материалы и изгибы сохраняются.
Допуск соединения 0,05 мм; рёбра изгибов не растворяются.
"""
import bpy,bmesh,numpy as np,collections
from mathutils import Vector
from mathutils.kdtree import KDTree
from mathutils.bvhtree import BVHTree

def accurate_normal(co):
    q=np.array(co,dtype=float);q-=q.mean(0);n=np.sum(np.cross(q,np.roll(q,-1,axis=0)),axis=0)
    length=np.linalg.norm(n);return n/length if length>1e-12 else np.zeros(3)

def junctions(bm,tolerance):
    bm.verts.ensure_lookup_table();vertices=list(bm.verts);tree=KDTree(len(vertices))
    for i,v in enumerate(vertices):tree.insert(v.co,i)
    tree.balance();result=[]
    for edge in list(bm.edges):
        a,b=edge.verts;d=b.co-a.co;length=d.length
        if length<2*tolerance:continue
        hits=[]
        for co,i,dist in tree.find_range((a.co+b.co)/2,length/2+tolerance):
            v=vertices[i]
            if v in (a,b):continue
            if any(v in face.verts for face in edge.link_faces):continue
            t=(v.co-a.co).dot(d)/(length*length)
            if t*length<=tolerance or (1-t)*length<=tolerance:continue
            distance=(v.co-a.co-t*d).length
            if distance<=tolerance:
                if distance>1e-6:
                    if not any(f.normal.dot(g.normal)>.9999995 for f in edge.link_faces for g in v.link_faces):continue
                hits.append((t,v,distance))
        if hits:result.append((edge,a,b,sorted(hits,key=lambda q:q[0])))
    return result

def connect_junctions(bm,tolerance):
    count=0;maximum=0.
    for repeat in range(5):
        found=junctions(bm,tolerance)
        if not found:break
        targetmap={}
        for edge,a,b,hits in found:
            if not edge.is_valid:continue
            remaining=edge;start=a;previous=0.
            for t,target,distance in hits:
                if not target.is_valid or t-previous<1e-9:continue
                new_edge,new_vertex=bmesh.utils.edge_split(remaining,start,(t-previous)/(1-previous))
                new_vertex.co=target.co;targetmap[new_vertex]=target
                # edge_split returns the start-side edge; continue towards b.
                remaining=next(e for e in new_vertex.link_edges if b in e.verts)
                start=new_vertex;previous=t;count+=1;maximum=max(maximum,distance)
        if targetmap:bmesh.ops.weld_verts(bm,targetmap=targetmap)
        else:break
    left=junctions(bm,tolerance)
    if left:raise ValueError('Остались Т-стыки: '+str(len(left)))
    return count,maximum

def dissolve_safe(bm,tolerance):
    queue=collections.deque(bm.edges);removed=0
    while queue:
        edge=queue.popleft()
        if not edge.is_valid or len(edge.link_faces)!=2:continue
        f,g=edge.link_faces
        if f.material_index!=g.material_index:continue
        fv=list(f.verts);gv=list(g.verts);ends=set(edge.verts)
        # Retain the bridges required to represent holes as ordinary mesh faces.
        if len(set(fv))!=len(fv) or len(set(gv))!=len(gv):continue
        if set(fv)&set(gv)!=ends:continue
        f.normal_update();g.normal_update()
        if f.normal.dot(g.normal)<.9999995:continue
        large=f if f.calc_area()>=g.calc_area() else g
        if any(abs((v.co-large.verts[0].co).dot(large.normal))>tolerance/2 for v in set(fv+gv)):continue
        a,b=edge.verts
        def path(vertices,start,end):
            i=vertices.index(start);p=vertices[i:]+vertices[:i]
            return p if p[-1]==end else None
        p=path(fv,a,b);q=path(gv,b,a)
        if p is None or q is None:p=path(fv,b,a);q=path(gv,a,b)
        if p is None or q is None:continue
        combined=p+q[1:-1]
        co=np.array([tuple(v.co) for v in combined]);co-=co.mean(0)
        vector=np.sum(np.cross(co,np.roll(co,-1,axis=0)),axis=0)
        area=np.linalg.norm(vector)/2;old_area=f.calc_area()+g.calc_area()
        if abs(area-old_area)>max(1e-9,old_area*.0001):continue
        result=bmesh.ops.dissolve_edges(bm,edges=[edge],use_verts=False,use_face_split=False)
        removed+=1
        for face in result.get('region',[]):
            if isinstance(face,bmesh.types.BMFace) and face.is_valid:
                face.normal_update();queue.extend(face.edges)
    return removed

def remove_collinear(bm,tolerance):
    for repeat in range(4):
        changed=0
        for v in list(bm.verts):
            if not v.is_valid or len(v.link_edges)!=2:continue
            a,b=[e.other_vert(v) for e in v.link_edges];d=b.co-a.co
            if d.length<2*tolerance:continue
            t=(v.co-a.co).dot(d)/d.length_squared
            if not 0<t<1 or (v.co-a.co-t*d).length>tolerance/2:continue
            if any(len(f.verts)<=3 for f in v.link_faces):continue
            bmesh.ops.dissolve_verts(bm,verts=[v],use_face_split=False,use_boundary_tear=False);changed+=1
        if not changed:break

def cleanup_window_planes(planes=None,tolerance_m=.00005):
    if bpy.context.mode!='OBJECT':bpy.ops.object.mode_set(mode='OBJECT')
    planes=list(planes) if planes is not None else [o for o in bpy.context.scene.objects if o.type=='MESH' and o.get('window_plane')]
    unit=bpy.context.scene.unit_settings.scale_length or 1.;reports=[]
    for oi,obj in enumerate(planes):
        mesh=obj.data
        if mesh.users>1:mesh=obj.data=mesh.copy()
        # All generated window objects have uniform scale; convert metres.
        sizes=[obj.matrix_world.to_3x3().col[i].length for i in range(3)]
        if max(sizes)-min(sizes)>1e-6:raise ValueError('Неравномерный масштаб: '+obj.name)
        tol=tolerance_m/(unit*sizes[0]);bm=bmesh.new()
        original_tree=BVHTree.FromPolygons([v.co for v in mesh.vertices],[list(f.vertices) for f in mesh.polygons])
        original_normals=[accurate_normal([tuple(mesh.vertices[i].co) for i in f.vertices]) for f in mesh.polygons]
        mesh.calc_loop_triangles()
        temporary=bpy.data.meshes.new('_CleanupTriangles')
        temporary.from_pydata([tuple(v.co) for v in mesh.vertices],[],[list(t.vertices) for t in mesh.loop_triangles])
        for f,t in zip(temporary.polygons,mesh.loop_triangles):f.material_index=mesh.polygons[t.polygon_index].material_index
        bm.from_mesh(temporary);bpy.data.meshes.remove(temporary)
        bm.faces.ensure_lookup_table();bm.normal_update()
        for f,t in zip(bm.faces,mesh.loop_triangles):
            n=accurate_normal([tuple(v.co) for v in f.verts])
            if float(n@original_normals[t.polygon_index])<0:f.normal_flip()
        before=(len(mesh.vertices),len(mesh.edges),len(mesh.polygons));area_before=sum(f.calc_area() for f in bm.faces)
        bmesh.ops.remove_doubles(bm,verts=list(bm.verts),dist=1e-6/(unit*sizes[0]))
        joined,deviation=connect_junctions(bm,tol)
        bad=[f for f in bm.faces if f.calc_area()<1e-10]
        if bad:bmesh.ops.delete(bm,geom=bad,context='FACES_ONLY')
        bm.normal_update()
        # Only coplanar divisions: preserve the folds and all hole boundaries.
        if mesh.uv_layers:raise ValueError('Для сохранения добавленной UV требуется отдельная обработка: '+obj.name)
        dissolve_safe(bm,tol)
        remove_collinear(bm,tol)
        bm.normal_update()
        # Repair again after dissolving, so no vertex ends inside a surviving edge.
        extra,error=connect_junctions(bm,tol);joined+=extra;deviation=max(deviation,error)
        bad=[]
        for f in bm.faces:
            q=np.array([tuple(v.co) for v in f.verts]);q-=q.mean(0)
            if np.linalg.norm(np.sum(np.cross(q,np.roll(q,-1,axis=0)),axis=0))<1e-10:bad.append(f)
        if bad:bmesh.ops.delete(bm,geom=bad,context='FACES_ONLY')
        loose=[v for v in bm.verts if not v.link_faces]
        if loose:bmesh.ops.delete(bm,geom=loose,context='VERTS')
        bm.normal_update();area_after=sum(f.calc_area() for f in bm.faces)
        relative=abs(area_after-area_before)/max(area_before,1e-9)
        if relative>.001:print('AREA_REVIEW',obj.name,relative,flush=True)
        nonmanifold=sum(len(e.link_faces)>2 for e in bm.edges)
        after=(len(bm.verts),len(bm.edges),len(bm.faces));bm.to_mesh(mesh);bm.free();mesh.update()
        for repeat in range(3):
            check=bmesh.new();check.from_mesh(mesh);bad=[]
            for f in check.faces:
                q=np.array([tuple(v.co) for v in f.verts]);q-=q.mean(0)
                if np.linalg.norm(np.sum(np.cross(q,np.roll(q,-1,axis=0)),axis=0))<1e-10:bad.append(f)
            if not bad:check.free();break
            bmesh.ops.delete(check,geom=bad,context='FACES_ONLY');check.to_mesh(mesh);check.free();mesh.update()
        after=(len(mesh.vertices),len(mesh.edges),len(mesh.polygons))
        orient=bmesh.new();orient.from_mesh(mesh)
        for f in orient.faces:
            co=np.array([tuple(v.co) for v in f.verts]);n=accurate_normal(co);center=Vector(co.mean(0));nearest=original_tree.find_nearest(center)
            candidates=original_tree.find_nearest_range(center,nearest[3]+.02) if nearest[0] is not None else []
            if candidates:
                wanted=max(candidates,key=lambda q:abs(float(n@original_normals[q[2]])))
                if float(n@original_normals[wanted[2]])<0:f.normal_flip()
        orient.to_mesh(mesh);orient.free();mesh.update()
        # Preserve an outward reference for subsequent normal checks.
        M=np.array(obj.matrix_world.to_3x3(),dtype=float);inv=np.linalg.inv(M)
        p=np.array([tuple(v.co) for v in mesh.vertices])@M.T;incident=[[] for v in mesh.vertices]
        for f in mesh.polygons:
            ids=list(f.vertices);q=p[ids]-p[ids].mean(0);n=np.sum(np.cross(q,np.roll(q,-1,axis=0)),axis=0);length=np.linalg.norm(n)
            if length<1e-12:raise ValueError('Вырожденный полигон: '+obj.name+str((f.index,len(ids),length)))
            for i in ids:incident[i].append(n/length)
        depth=float(obj.get('window_plane_outward_offset_min_m',.075))/unit;reference=[]
        for i,point in enumerate(p):
            A=np.array(incident[i]);direction=A.sum(0) if len(A) else np.zeros(3);length=np.linalg.norm(direction)
            if length>1e-8:
                direction/=length;minimum=float(np.min(A@direction))
                if minimum<=1e-5:raise ValueError('Противоположные грани на одном стыке: '+obj.name)
                delta=direction*depth/minimum
            else:delta=np.zeros(3)
            reference.append((point-delta)@inv.T)
        obj['window_plane_base_coordinates']=np.array(reference).ravel().tolist();obj['window_plane_cleaned']=True
        reports.append({'object':obj.name,'before':before,'after':after,'joined':joined,'remaining_junctions':0,'maximum_join_deviation_m':deviation*unit*sizes[0],'relative_area_difference':relative,'nonmanifold_edges':nonmanifold})
        if oi%25==0:print('CLEANUP_PROGRESS',oi+1,len(planes),flush=True)
    return reports

def repair_window_junctions(planes=None,tolerance_m=.00005):
    planes=list(planes) if planes is not None else [o for o in bpy.context.scene.objects if o.type=='MESH' and o.get('window_plane')]
    reports=[];unit=bpy.context.scene.unit_settings.scale_length or 1.
    for obj in planes:
        mesh=obj.data;positions=[v.co.copy() for v in mesh.vertices];stored=np.array(obj['window_plane_base_coordinates']).reshape(-1,3)
        tree=KDTree(len(positions))
        for i,p in enumerate(positions):tree.insert(p,i)
        tree.balance();tol=tolerance_m/(unit*obj.matrix_world.to_3x3().col[0].length)
        bm=bmesh.new();bm.from_mesh(mesh);bm.normal_update();joined,error=connect_junctions(bm,tol)
        if joined:
            bm.to_mesh(mesh);mesh.update()
            obj['window_plane_base_coordinates']=np.array([stored[tree.find(v.co)[1]] for v in mesh.vertices]).ravel().tolist()
        bm.free()
        check=bmesh.new();check.from_mesh(mesh);check.normal_update();remaining=len(junctions(check,tol));check.free()
        if remaining:raise ValueError('Остались стыки после записи меша: '+obj.name)
        reports.append({'object':obj.name,'joined':joined,'remaining':remaining})
    return reports

if __name__=='__main__':
    reports=cleanup_window_planes();repairs=repair_window_junctions()
    print('CLEANUP_COMPLETE',len(reports),sum(r['joined'] for r in reports)+sum(r['joined'] for r in repairs))
