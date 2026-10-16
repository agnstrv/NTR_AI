"""Четырёхугольная сетка окон, включая перекрёстные и Т-образные узлы.

Blender Text Editor: Run Script. Обрабатывается только Окно_Plane_001.
Рамы разворачиваются по своей вертикальной поверхности, делятся на сетку
по границам стоек и перекладин и возвращаются на исходные изгибы.
Для нерегулярных участков применяется согласованное разбиение на квады.
"""
import bpy,bmesh,numpy as np,collections
from mathutils import Vector
from mathutils.kdtree import KDTree
from mathutils.geometry import delaunay_2d_cdt
from mathutils.bvhtree import BVHTree
TARGET='Окно_Plane_001'

def components(points,faces):
    parent=list(range(len(points)))
    def root(i):
        while parent[i]!=i:parent[i]=parent[parent[i]];i=parent[i]
        return i
    for f in faces:
        for i in f[1:]:parent[root(i)]=root(f[0])
    groups=collections.defaultdict(list)
    for i,f in enumerate(faces):groups[root(f[0])].append(i)
    return [(sorted(set(v for i in fs for v in faces[i])),fs) for fs in groups.values()]

def profile(points,faces,ids,face_ids):
    q=points[ids,:2];parent=list(range(len(q)))
    def root(i):
        while parent[i]!=i:parent[i]=parent[parent[i]];i=parent[i]
        return i
    for i in range(len(q)):
        for j in np.where(np.linalg.norm(q-q[i],axis=1)<.00015)[0]:parent[root(int(j))]=root(i)
    groups=collections.defaultdict(list)
    for i in range(len(q)):groups[root(i)].append(i)
    nodes=np.array([np.median(q[v],axis=0) for v in groups.values()]);mapping={ids[i]:k for k,v in enumerate(groups.values()) for i in v};edges=set()
    for fi in face_ids:
        f=faces[fi]
        for i,j in zip(f,f[1:]+f[:1]):
            u,v=mapping[i],mapping[j]
            if u==v:continue
            d=nodes[v]-nodes[u];length=float(np.linalg.norm(d));t=(nodes-nodes[u])@d/(length*length);distance=np.linalg.norm(nodes-nodes[u]-t[:,None]*d,axis=1)
            stops=[u]+sorted(np.where((t>1e-5)&(t<1-1e-5)&(distance<.00015))[0],key=lambda k:t[k])+[v]
            for x,y in zip(stops,stops[1:]):edges.add(tuple(sorted((int(x),int(y)))))
    parent=list(range(len(nodes)));tree=collections.defaultdict(list)
    for x,y in sorted(edges,key=lambda e:np.linalg.norm(nodes[e[0]]-nodes[e[1]])):
        rx,ry=root(x),root(y)
        if rx==ry:continue
        parent[rx]=ry;length=float(np.linalg.norm(nodes[x]-nodes[y]));tree[x].append((y,length));tree[y].append((x,length))
    def far(start):
        distance={start:0.};previous={start:None};todo=[start]
        while todo:
            i=todo.pop()
            for j,length in tree[i]:
                if j in distance:continue
                distance[j]=distance[i]+length;previous[j]=i;todo.append(j)
        last=max(distance,key=distance.get);return last,distance,previous
    start,dist,pre=far(0);end,dist,pre=far(start);path=[end]
    while path[-1]!=start:path.append(pre[path[-1]])
    line=nodes[path[::-1]];d=np.diff(line,axis=0);length=np.linalg.norm(d,axis=1);total=np.concatenate(([0.],np.cumsum(length)))
    t=np.clip(np.sum((q[:,None,:]-line[:-1])*d,axis=2)/(length*length),0,1);projection=line[:-1]+t[:,:,None]*d;distance=np.linalg.norm(projection-q[:,None,:],axis=2);best=distance.argmin(1)
    s=total[best]+t[np.arange(len(q)),best]*length[best]
    return line,total,s,float(distance[np.arange(len(q)),best].max()),len(dist)==len(nodes),nodes,tree

def levels(values,tolerance=.0002):
    groups=[]
    for v in sorted(values):
        if groups and v-groups[-1][0]<=tolerance:groups[-1].append(float(v))
        else:groups.append([float(v)])
    return np.array([float(np.median(g)) for g in groups])

def inside(points,polygon):
    answer=np.zeros(len(points),dtype=bool)
    for a,b in zip(polygon,np.roll(polygon,-1,axis=0)):
        if abs(b[1]-a[1])<1e-12:continue
        crossing=(a[1]>points[:,1])!=(b[1]>points[:,1])
        answer^=crossing&(points[:,0]<(b[0]-a[0])*(points[:,1]-a[1])/(b[1]-a[1])+a[0])
    return answer

def repair_edges(bm,tolerance=1e-5):
    for repeat in range(4):
        vertices=list(bm.verts);tree=KDTree(len(vertices))
        for i,v in enumerate(vertices):tree.insert(v.co,i)
        tree.balance();weld={}
        for e in list(bm.edges):
            a,b=e.verts;d=b.co-a.co;length=d.length
            if length<2*tolerance:continue
            hits=[]
            for co,i,dist in tree.find_range((a.co+b.co)/2,length/2+tolerance):
                v=vertices[i]
                if v in (a,b) or any(v in f.verts for f in e.link_faces):continue
                t=(v.co-a.co).dot(d)/d.length_squared
                if t*length<=tolerance or (1-t)*length<=tolerance:continue
                if (v.co-a.co-t*d).length<=tolerance:hits.append((t,v))
            previous=0.;remaining=e;start=a
            for t,target in sorted(hits,key=lambda q:q[0]):
                if t-previous<1e-9:continue
                new_edge,new_v=bmesh.utils.edge_split(remaining,start,(t-previous)/(1-previous));new_v.co=target.co;weld[new_v]=target
                remaining=next(edge for edge in new_v.link_edges if b in edge.verts);start=new_v;previous=t
        if not weld:break
        bmesh.ops.weld_verts(bm,targetmap=weld)

def union_cdt(polygons):
    vertices=[];constraints=[]
    for polygon in polygons:
        area=float(np.sum(polygon[:,0]*np.roll(polygon[:,1],-1)-polygon[:,1]*np.roll(polygon[:,0],-1)))
        if abs(area)<1e-10:continue
        if area<0:polygon=polygon[::-1]
        start=len(vertices);vertices.extend(Vector(p) for p in polygon);constraints.append(list(range(start,len(vertices))))
    if not constraints:return []
    cv,ce,cf,ov,oe,of=delaunay_2d_cdt(vertices,[],constraints,1,1e-6,False)
    centers=np.array([np.array([tuple(cv[i]) for i in f]).mean(0) for f in cf]);covered=np.zeros(len(cf),dtype=bool)
    for polygon in polygons:covered|=inside(centers,polygon)
    return [np.array([tuple(cv[i]) for i in f]) for f,keep in zip(cf,covered) if keep]

def union_triangles_3d(triangles):
    # Union the actual triangulated surface in each planar patch. This removes
    # duplicate coverage and supplies one conforming triangulation at crossings.
    triangles=np.array(triangles);cross=np.cross(triangles[:,1]-triangles[:,0],triangles[:,2]-triangles[:,0]);area=np.linalg.norm(cross,axis=1)
    pending=set(np.where(area>1e-9)[0]);result=[]
    while pending:
        first=max(pending,key=lambda i:area[i]);origin=triangles[first,0];n=cross[first]/area[first];d=triangles-origin
        distance=np.max(np.abs(d@n),axis=1);dot=np.abs(cross@n)/np.maximum(area,1e-20)
        chosen=[i for i in pending if distance[i]<2e-5 and dot[i]>.99999]
        if not chosen:chosen=[first]
        pending.difference_update(chosen);u=triangles[first,1]-origin;u/=np.linalg.norm(u);v=np.cross(n,u);basis=np.array([u,v])
        projected=[(triangles[i]-origin)@basis.T for i in chosen]
        for polygon in union_cdt(projected):result.append(polygon@basis+origin)
    return result

def build_window_quads_legacy(obj):
    mesh=obj.data
    if mesh.uv_layers:raise ValueError('У меша есть UV: требуется интерполяция UV при перестроении сетки.')
    points=np.array([tuple(v.co) for v in mesh.vertices]);faces=[list(f.vertices) for f in mesh.polygons]
    mesh.calc_loop_triangles();triangles=list(mesh.loop_triangles);output=[];quads=[];materials=[];smooth=[];lookup={};reports=[]
    def vertex(co):
        co=np.array(co,dtype=np.float32);key=tuple(float(x) for x in co)
        if key not in lookup:lookup[key]=len(output);output.append(key)
        return lookup[key]
    def add_quad(coords,material,shading):
        ids=[vertex(p) for p in coords]
        if len(set(ids))!=len(ids):return
        q=np.array([output[i] for i in ids]);q-=q.mean(0)
        if np.linalg.norm(np.sum(np.cross(q,np.roll(q,-1,axis=0)),axis=0))<1e-10:return
        quads.append(ids);materials.append(material);smooth.append(shading)
    for gi,(ids,face_ids) in enumerate(components(points,faces)):
        line,total,s,error,complete,*extra=profile(points,faces,ids,face_ids)
        uv=np.column_stack((s,points[ids,2]));index={v:i for i,v in enumerate(ids)}
        edges=collections.Counter(tuple(sorted((a,b))) for fi in face_ids for a,b in zip(faces[fi],faces[fi][1:]+faces[fi][:1]))
        diagonal=False
        for (a,b),count in edges.items():
            difference=np.abs(uv[index[a]]-uv[index[b]])
            if count==1 and difference[0]>.0005 and difference[1]>.0005:diagonal=True
        first=len(quads)
        if complete and error<.001 and not diagonal:
            sl=levels(list(s)+list(total));zl=levels(uv[:,1]);centers=np.array([[(sl[i]+sl[i+1])/2,(zl[j]+zl[j+1])/2] for i in range(len(sl)-1) for j in range(len(zl)-1)])
            owner=np.full(len(centers),-1,dtype=int);signed={}
            chosen=set(face_ids)
            for triangle in triangles:
                fi=triangle.polygon_index
                if fi not in chosen:continue
                polygon=uv[[index[v] for v in triangle.vertices]];covered=inside(centers,polygon);owner[(owner<0)&covered]=fi
                signed.setdefault(fi,float(np.sum(polygon[:,0]*np.roll(polygon[:,1],-1)-polygon[:,1]*np.roll(polygon[:,0],-1))))
            def world(x,z):
                k=int(np.clip(np.searchsorted(total,x,side='right')-1,0,len(line)-2));t=(x-total[k])/(total[k+1]-total[k]);xy=line[k]+t*(line[k+1]-line[k]);return (xy[0],xy[1],z)
            for i in range(len(sl)-1):
                for j in range(len(zl)-1):
                    fi=int(owner[i*(len(zl)-1)+j])
                    if fi<0:continue
                    coords=[world(sl[i],zl[j]),world(sl[i+1],zl[j]),world(sl[i+1],zl[j+1]),world(sl[i],zl[j+1])]
                    if signed[fi]<0:coords.reverse()
                    add_quad(coords,mesh.polygons[fi].material_index,mesh.polygons[fi].use_smooth)
            method='structured'
        else:
            chosen=set(face_ids);local={v:i for i,v in enumerate(ids)};ts=[t for t in triangles if t.polygon_index in chosen]
            if complete and error<.001:
                polys=[uv[[index[v] for v in t.vertices]] for t in ts]
                # Creases are included as vertical constraints by partitioning
                # the parameter domain into consecutive profile strips.
                irregular=[]
                for lo,hi in zip(total,total[1:]):
                    if hi-lo<1e-5:continue
                    clipped=[]
                    for polygon in polys:
                        shape=list(polygon)
                        for sign,bound in ((1,hi),(-1,-lo)):
                            new=[]
                            for a,b in zip(shape,shape[1:]+shape[:1]):
                                da=sign*a[0]-bound;db=sign*b[0]-bound
                                if da<=0:new.append(a)
                                if (da<0<db) or (db<0<da):new.append(a+(b-a)*da/(da-db))
                            shape=new
                            if len(shape)<3:break
                        if len(shape)>=3:clipped.append(np.array(shape))
                    for polygon in union_cdt(clipped):
                        world_polygon=[]
                        k=int(np.clip(np.searchsorted(total,(lo+hi)/2)-1,0,len(line)-2))
                        for x,z in polygon:
                            t=(x-total[k])/(total[k+1]-total[k]);xy=line[k]+t*(line[k+1]-line[k]);world_polygon.append((xy[0],xy[1],z))
                        irregular.append(np.array(world_polygon))
                original_uv=uv[[index[v] for v in faces[face_ids[0]]]];sense=np.sum(original_uv[:,0]*np.roll(original_uv[:,1],-1)-original_uv[:,1]*np.roll(original_uv[:,0],-1))
                if sense<0:irregular=[f[::-1] for f in irregular]
            else:irregular=union_triangles_3d([points[list(t.vertices)] for t in ts])
            for polygon in irregular:add_quad(polygon,mesh.polygons[face_ids[0]].material_index,mesh.polygons[face_ids[0]].use_smooth)
            method='irregular'
        if len(quads)==first:raise ValueError('Не удалось построить окно: '+str(gi))
        reports.append({'component':gi,'method':method,'quads':len(quads)-first,'profile_error':error})
    # Make the coarse mesh conforming before all-quad subdivision. Only mixed
    # components are refined; regular intersections keep their central quad.
    coarse=bpy.data.meshes.new('_QuadCoarse');coarse.from_pydata(output,[],quads);coarse.update();bm=bmesh.new();bm.from_mesh(coarse);bpy.data.meshes.remove(coarse)
    bmesh.ops.remove_doubles(bm,verts=list(bm.verts),dist=5e-6);repair_edges(bm,2e-5)
    for f,material,shading in zip(bm.faces,materials,smooth):f.material_index=material;f.smooth=shading
    seen=set();refine=set()
    for first in bm.faces:
        if first in seen:continue
        todo=[first];seen.add(first);part=[]
        while todo:
            f=todo.pop();part.append(f)
            for vert in f.verts:
                for neighbor in vert.link_faces:
                    if neighbor not in seen:seen.add(neighbor);todo.append(neighbor)
        if any(len(f.verts)!=4 for f in part):refine.update(part)
    refine_layer=bm.faces.layers.int.new('quad_refinement')
    for f in bm.faces:f[refine_layer]=int(f in refine)
    if refine:bmesh.ops.triangulate(bm,faces=[f for f in bm.faces if f[refine_layer] and len(f.verts)>3],quad_method='FIXED',ngon_method='EAR_CLIP')
    output=[];quads=[];materials=[];smooth=[];lookup={}
    for f in bm.faces:
        co=np.array([tuple(v.co) for v in f.verts]);center=co.mean(0)
        if f in refine:
            for k in range(len(co)):add_quad([co[k],(co[k]+co[(k+1)%len(co)])/2,center,(co[k]+co[(k-1)%len(co)])/2],f.material_index,f.smooth)
        else:add_quad(co,f.material_index,f.smooth)
    bm.free()
    result=bpy.data.meshes.new(mesh.name+'_Quads');result.from_pydata(output,[],quads);result.update()
    for mat in mesh.materials:result.materials.append(mat)
    for f,material,shading in zip(result.polygons,materials,smooth):f.material_index=material;f.use_smooth=shading
    assert all(len(f.vertices)==4 for f in result.polygons)
    return result,reports

def build_window_quads(obj):
    """Восстановить решётку по исходным рамам и существующему контуру."""
    source=bpy.data.objects['WindowFrameSource']
    original=obj.data
    if original.uv_layers:raise ValueError('У меша есть UV; необходима её интерполяция.')
    points=np.array([tuple(v.co) for v in original.vertices]);faces=[list(f.vertices) for f in original.polygons]
    original.calc_loop_triangles();original_triangles=list(original.loop_triangles)
    original_surface=BVHTree.FromPolygons([v.co for v in original.vertices],faces)
    inverse=np.linalg.inv(np.array(obj.matrix_world,dtype=float));M=inverse@np.array(source.matrix_world,dtype=float)
    sp=np.array([tuple(v.co) for v in source.data.vertices])@M[:3,:3].T+M[:3,3]
    beams=[sp[ids] for ids,fs in components(sp,[list(f.vertices) for f in source.data.polygons])]
    bmin=np.array([q.min(0) for q in beams]);bmax=np.array([q.max(0) for q in beams])
    output=[];quads=[];lookup={};used=set();reports=[];exact_patches=[]
    def vertex(co):
        # One canonical coordinate at each junction, despite CAD rounding.
        key=tuple(np.rint(np.array(co)/.00005).astype(np.int64))
        if key not in lookup:lookup[key]=len(output);output.append(tuple(float(x) for x in np.array(co,dtype=np.float32)))
        return lookup[key]
    for gi,(ids,face_ids) in enumerate(components(points,faces)):
        line,total,s,error,complete,nodes,tree=profile(points,faces,ids,face_ids)
        if error>=.001:
            selected=set(face_ids);triangles_3d=[]
            for t in original_triangles:
                if t.polygon_index not in selected:continue
                triangle=points[list(t.vertices)];edge_length=max(np.linalg.norm(triangle[(i+1)%3]-triangle[i]) for i in range(3));area=np.linalg.norm(np.cross(triangle[1]-triangle[0],triangle[2]-triangle[0]))
                if area/max(edge_length,1e-9)>1e-4:triangles_3d.append(triangle)
            exact_patches.extend(union_triangles_3d(triangles_3d));reports.append({'component':gi,'method':'exact_quads','quads':0,'profile_error':error,'chains':0});continue
        q=points[ids];lo=q.min(0);hi=q.max(0);zlo=float(lo[2]);zhi=float(hi[2]);candidates=np.where(np.all(bmax>=lo-.35,axis=1)&np.all(bmin<=hi+.35,axis=1))[0]
        if error<.001 and complete:chains=[(line,True,True)]
        else:
            chains=[];seen=set()
            for node,neighbors in tree.items():
                if len(neighbors)==2:continue
                for next_node,length in neighbors:
                    if tuple(sorted((node,next_node))) in seen:continue
                    path=[node,next_node];seen.add(tuple(sorted((node,next_node))))
                    while len(tree[path[-1]])==2:
                        options=[j for j,length in tree[path[-1]] if j!=path[-2]];n=options[0];seen.add(tuple(sorted((path[-1],n))));path.append(n)
                    xy=nodes[path]
                    if np.linalg.norm(np.diff(xy,axis=0),axis=1).sum()>.0002:chains.append((xy,len(tree[path[0]])==1,len(tree[path[-1]])==1))
        component_z=levels([zlo,zhi,zlo+.10,zhi-.10,*bmin[candidates,2],*bmax[candidates,2]])
        first=len(quads)
        for line,left_outer,right_outer in chains:
            d=np.diff(line,axis=0);length=np.linalg.norm(d,axis=1);total=np.concatenate(([0.],np.cumsum(length)));width=total[-1]
            def projection(xy):
                t=np.clip(np.sum((xy[:,None,:]-line[:-1])*d,axis=2)/(length*length),0,1);projected=line[:-1]+t[:,:,None]*d;dist=np.linalg.norm(projected-xy[:,None,:],axis=2);best=dist.argmin(1)
                along=total[best]+t[np.arange(len(xy)),best]*length[best];return along,dist[np.arange(len(xy)),best]
            rectangles=[];previous_surface=[];chosen_faces=set(face_ids)
            for triangle in original_triangles:
                if triangle.polygon_index not in chosen_faces:continue
                co=points[list(triangle.vertices)];along,distance=projection(co[:,:2])
                if distance.max()<.001:
                    polygon=np.column_stack((along,co[:,2]));area=np.sum(polygon[:,0]*np.roll(polygon[:,1],-1)-polygon[:,1]*np.roll(polygon[:,0],-1))
                    if abs(area)>1e-10:previous_surface.append(polygon)
            for ci in candidates:
                beam=beams[ci];along,distance=projection(beam[:,:2])
                if distance.min()>.30 or float(np.median(distance))>.30:continue
                a=float(along.min());b=float(along.max());bottom=max(zlo,float(beam[:,2].min()));top=min(zhi,float(beam[:,2].max()))
                if b-a>.0001 and top-bottom>.0001:rectangles.append((a,b,bottom,top))
            if left_outer:rectangles.append((0,min(.10,width),zlo,zhi))
            if right_outer:rectangles.append((max(0,width-.10),width,zlo,zhi))
            rectangles.extend([(0,width,zlo,min(zlo+.10,zhi)),(0,width,max(zhi-.10,zlo),zhi)])
            # Include coordinates from neighbouring pieces, so contacting parts
            # have identical subdivisions along their common border.
            allxy=points[:,:2];valid=np.all(allxy>=line.min(0)-.001,axis=1)&np.all(allxy<=line.max(0)+.001,axis=1);along,dist=projection(allxy[valid]);additional=along[dist<.00015]
            sl=levels([0.,width,*total,*additional,*[x for r in rectangles for x in r[:2]],*[float(x) for p in previous_surface for x in p[:,0]]])
            sl=sl[(sl>=-1e-6)&(sl<=width+1e-6)];zl=component_z[(component_z>=zlo-.0002)&(component_z<=zhi+.0002)];zl=levels([zlo,zhi,*zl,*[z for r in rectangles for z in r[2:]],*[float(z) for p in previous_surface for z in p[:,1]]])
            def world(x,z):
                k=int(np.clip(np.searchsorted(total,x,side='right')-1,0,len(line)-2));t=(x-total[k])/(total[k+1]-total[k]);xy=line[k]+t*d[k];return (xy[0],xy[1],z)
            def occupancy(centers):
                previous=np.zeros(len(centers),dtype=bool);cad=np.zeros(len(centers),dtype=bool)
                for polygon in previous_surface:previous|=inside(centers,polygon)
                for a,b,bottom,top in rectangles:cad|=(centers[:,0]>=a)&(centers[:,0]<=b)&(centers[:,1]>=bottom)&(centers[:,1]<=top)
                for i in np.where(cad&~previous)[0]:
                    nearest=original_surface.find_nearest(Vector(world(*centers[i])))
                    if nearest[0] is not None and nearest[3]<.002:previous[i]=True
                return previous
            centers=np.array([[(sl[i]+sl[i+1])/2,(zl[j]+zl[j+1])/2] for i in range(len(sl)-1) for j in range(len(zl)-1)]);filled=occupancy(centers)
            # Keep silhouette boundaries and real folds, not hidden profile
            # divisions or collinear vertices left by previous operations.
            mask=filled.reshape(len(sl)-1,len(zl)-1)
            bends=[]
            for k in range(1,len(line)-1):
                if float(d[k-1]@d[k]/(length[k-1]*length[k]))<.999999875:bends.append(total[k])
            keep_s=[0]+[k for k in range(1,len(sl)-1) if np.any(mask[k-1]!=mask[k]) or any(abs(sl[k]-b)<.0003 for b in bends)]+[len(sl)-1]
            keep_z=[0]+[k for k in range(1,len(zl)-1) if np.any(mask[:,k-1]!=mask[:,k])]+[len(zl)-1]
            sl=sl[keep_s];zl=zl[keep_z];centers=np.array([[(sl[i]+sl[i+1])/2,(zl[j]+zl[j+1])/2] for i in range(len(sl)-1) for j in range(len(zl)-1)]);filled=occupancy(centers)
            normal_vote=np.zeros(3)
            for fi in face_ids:
                co=points[faces[fi]];co-=co.mean(0);normal_vote+=np.sum(np.cross(co,np.roll(co,-1,axis=0)),axis=0)
            for i in range(len(sl)-1):
                for j in range(len(zl)-1):
                    if not filled[i*(len(zl)-1)+j]:continue
                    co=np.array([world(sl[i],zl[j]),world(sl[i+1],zl[j]),world(sl[i+1],zl[j+1]),world(sl[i],zl[j+1])]);n=np.cross(co[1]-co[0],co[3]-co[0])
                    if np.linalg.norm(n)<1e-9:continue
                    if n@normal_vote<0:co=co[::-1]
                    f=[vertex(c) for c in co]
                    if len(set(f))!=4:continue
                    key=tuple(sorted(f))
                    if key in used:continue
                    used.add(key);quads.append(f)
        if len(quads)==first:raise ValueError('Не построена решётка: '+str(gi))
        reports.append({'component':gi,'method':'frame_grid','quads':len(quads)-first,'profile_error':error,'chains':len(chains)})
    result=bpy.data.meshes.new(original.name+'_QuadGrid');result.from_pydata(output,[],quads);result.update()
    for mat in original.materials:result.materials.append(mat)
    for f in result.polygons:f.use_smooth=True
    conformed=conform_quad_grid(result);bpy.data.meshes.remove(result)
    if exact_patches:
        final=combine_exact_quads(conformed,exact_patches);bpy.data.meshes.remove(conformed);conformed=final
    return conformed,reports

def combine_exact_quads(grid,triangles):
    points=[tuple(v.co) for v in grid.vertices];faces=[list(f.vertices) for f in grid.polygons]
    for triangle in triangles:
        longest=max(np.linalg.norm(triangle[(i+1)%len(triangle)]-triangle[i]) for i in range(len(triangle)));area=np.linalg.norm(np.cross(triangle[1]-triangle[0],triangle[2]-triangle[0]))
        if area/max(longest,1e-9)<1e-4:continue
        start=len(points);points.extend(tuple(p) for p in triangle);faces.append(list(range(start,len(points))))
    temp=bpy.data.meshes.new('_MixedQuadPatches');temp.from_pydata(points,[],faces);bm=bmesh.new();bm.from_mesh(temp);bpy.data.meshes.remove(temp)
    bmesh.ops.remove_doubles(bm,verts=list(bm.verts),dist=5e-6);repair_edges(bm,2e-5)
    bad=[f for f in bm.faces if f.calc_area()<1e-9]
    if bad:bmesh.ops.delete(bm,geom=bad,context='FACES_ONLY')
    seen=set();refine=set()
    for first in bm.faces:
        if first in seen:continue
        part=[];todo=[first];seen.add(first)
        while todo:
            f=todo.pop();part.append(f)
            for v in f.verts:
                for g in v.link_faces:
                    if g not in seen:seen.add(g);todo.append(g)
        if any(len(f.verts)!=4 for f in part):refine.update(part)
    output=[];quads=[];lookup={};used=set()
    def add(coords):
        coords=np.array(coords,dtype=np.float32);co=coords.astype(float);co-=co.mean(0)
        if np.linalg.norm(np.sum(np.cross(co,np.roll(co,-1,axis=0)),axis=0))<1e-10:return
        ids=[]
        for p in coords:
            key=tuple(float(v) for v in p)
            if key not in lookup:lookup[key]=len(output);output.append(key)
            ids.append(lookup[key])
        if len(set(ids))!=4:return
        key=tuple(sorted(ids))
        if key not in used:used.add(key);quads.append(ids)
    for f in bm.faces:
        co=np.array([tuple(v.co) for v in f.verts])
        if f not in refine:add(co);continue
        center=co.mean(0)
        for i in range(len(co)):add([co[i],(co[i]+co[(i+1)%len(co)])/2,center,(co[i]+co[(i-1)%len(co)])/2])
    bm.free();result=bpy.data.meshes.new(grid.name+'_Exact');result.from_pydata(output,[],quads);result.update()
    for mat in grid.materials:result.materials.append(mat)
    for f in result.polygons:f.use_smooth=True
    return result

def conform_quad_grid(mesh):
    """Продолжить разрезы через квады, сохраняя четыре вершины в каждой грани."""
    columns={};coordinates=[];levels_by_column=[];vertex_column=[]
    for vertex in mesh.vertices:
        xy=np.array(vertex.co[:2]);key=tuple(np.rint(xy/.00005).astype(np.int64))
        if key not in columns:columns[key]=len(coordinates);coordinates.append(xy);levels_by_column.append(set())
        index=columns[key];vertex_column.append(index);levels_by_column[index].add(int(round(float(vertex.co.z)/1e-5)))
    tree=KDTree(len(coordinates))
    for i,xy in enumerate(coordinates):tree.insert(Vector((xy[0],xy[1],0)),i)
    tree.balance();records=[];adj=collections.defaultdict(set)
    for face in mesh.polygons:
        ids=list(face.vertices);nodes=list(dict.fromkeys(vertex_column[i] for i in ids))
        if len(nodes)!=2:raise ValueError('Квад не является вертикальной полосой')
        a,b=nodes;xy_a=coordinates[a];xy_b=coordinates[b];d=xy_b-xy_a;length=np.linalg.norm(d);stops=[(0.,a),(1.,b)]
        if length<1e-8:continue
        midpoint=(xy_a+xy_b)/2
        for co,i,dist in tree.find_range(Vector((midpoint[0],midpoint[1],0)),length/2+.00005):
            if i in nodes:continue
            t=float((coordinates[i]-xy_a)@d)/(length*length)
            if 1e-6<t<1-1e-6 and np.linalg.norm(coordinates[i]-xy_a-t*d)<.00005:stops.append((t,i))
        stops=[i for t,i in sorted(stops)];z=[int(round(float(mesh.vertices[i].co.z)/1e-5)) for i in ids];lo=min(z);hi=max(z)
        n=np.array(face.normal,dtype=float);records.append((stops,lo,hi,n,face.material_index,face.use_smooth))
        for node in stops:adj[node].add(len(records)-1)
    queue=collections.deque(range(len(records)));queued=set(queue)
    while queue:
        index=queue.popleft();queued.discard(index);nodes,lo,hi,n,mat,shading=records[index]
        shared={lo,hi}
        for node in nodes:shared.update(z for z in levels_by_column[node] if lo<z<hi)
        for node in nodes:
            new=shared-levels_by_column[node]
            if new:
                levels_by_column[node].update(new)
                for neighbor in adj[node]:
                    if neighbor not in queued:queue.append(neighbor);queued.add(neighbor)
    output=[];quads=[];materials=[];smooth=[];lookup={};used=set()
    def vertex(node,z):
        key=(node,z)
        if key not in lookup:lookup[key]=len(output);output.append((float(coordinates[node][0]),float(coordinates[node][1]),z*1e-5))
        return lookup[key]
    for nodes,lo,hi,normal,mat,shading in records:
        zl=sorted({lo,hi}|{z for node in nodes for z in levels_by_column[node] if lo<z<hi})
        for a,b in zip(nodes,nodes[1:]):
            if np.linalg.norm(coordinates[b]-coordinates[a])<1e-6:continue
            for bottom,top in zip(zl,zl[1:]):
                f=[vertex(a,bottom),vertex(b,bottom),vertex(b,top),vertex(a,top)];co=np.array([output[i] for i in f]);n=np.cross(co[1]-co[0],co[3]-co[0])
                if n@normal<0:f.reverse()
                key=tuple(sorted(f))
                if key in used:continue
                used.add(key);quads.append(f);materials.append(mat);smooth.append(shading)
    result=bpy.data.meshes.new(mesh.name+'_Conforming');result.from_pydata(output,[],quads);result.update()
    for mat in mesh.materials:result.materials.append(mat)
    for f,mat,shading in zip(result.polygons,materials,smooth):f.material_index=mat;f.use_smooth=shading
    return result

def orient_to_facade(obj,mesh):
    main=bpy.data.objects.get('Main')
    if main is None:return 0
    inverse=np.linalg.inv(np.array(obj.matrix_world,dtype=float));M=inverse@np.array(main.matrix_world,dtype=float)
    positions=np.array([tuple(v.co) for v in main.data.vertices])@M[:3,:3].T+M[:3,3]
    tree=BVHTree.FromPolygons([Vector(p) for p in positions],[list(f.vertices) for f in main.data.polygons]);reversed_faces=0
    for f in mesh.polygons:
        p=np.array([tuple(mesh.vertices[i].co) for i in f.vertices]);center=Vector(p.mean(0));q=p-p.mean(0);n=np.sum(np.cross(q,np.roll(q,-1,axis=0)),axis=0);length=np.linalg.norm(n)
        if length<1e-12:continue
        n/=length;nearest=tree.find_nearest(center)
        if nearest[0] is None:continue
        if abs(float(n@nearest[1]))>.65:wanted=nearest
        else:
            aligned=[q for q in tree.find_nearest_range(center,nearest[3]+.5) if abs(float(n@q[1]))>.65]
            if not aligned:continue
            wanted=min(aligned,key=lambda q:q[3])
        if float(n@wanted[1])<0:f.flip();reversed_faces+=1
    mesh.update();return reversed_faces

def main():
    obj=bpy.data.objects[TARGET]
    if obj.mode!='OBJECT':bpy.ops.object.mode_set(mode='OBJECT')
    mesh,reports=build_window_quads(obj);orient_to_facade(obj,mesh);obj.data=mesh;obj['window_quad_topology']=True
    print('WINDOW_QUADS',len(mesh.vertices),len(mesh.polygons),len(reports))

if __name__=='__main__':main()
