"""Non-destructive, topology-preserving vertical section preparation for Blender.

prepare_sections(obj, cut_detector) does not mutate obj. cut_detector receives
(all world-space component points, common normal), and returns cut coordinates
in the frame's horizontal u axis. Original vertex indices are retained.
"""
from collections import defaultdict
from mathutils import Vector

PLANAR_TOL = 2e-5
EDGE_TOL = 2e-6


def _normal(points):
    base = points[0]
    value = Vector((0, 0, 0))
    for a, b in zip(points, points[1:] + points[:1]):
        value += (a - base).cross(b - base)
    if value.length < 1e-12:
        raise ValueError('Cannot section a zero-area polygon')
    return value.normalized()


def _frame(points, normal, vertical):
    if vertical:
        u = Vector((-normal.y, normal.x, 0)).normalized()
        # Exactly orthonormal, also handles small planar facade slopes.
        v = normal.cross(u).normalized()
    else:
        edges = [b-a for a,b in zip(points,points[1:]+points[:1])]
        u = max(edges,key=lambda e:e.length_squared).normalized()
        v = normal.cross(u).normalized()
        u = v.cross(normal).normalized()
    a,b = min(p.dot(u) for p in points),max(p.dot(u) for p in points)
    c,d = min(p.dot(v) for p in points),max(p.dot(v) for p in points)
    anchor = points[0]-u*points[0].dot(u)-v*points[0].dot(v)
    return (u,v,a,b,c,d,anchor)


def prepare_sections(obj, cut_detector):
    """Return vertices, faces, sections and stats; all geometry is world-space.

    faces: dicts with indices, poly, parent, section, frame, n, nonplanar.
    sections: dict keyed by (component_index, interval_index); each value has
      frame, n, parents, members (output face indices), polygons (world points).
    Nonplanar source polygons are kept intact, except collinear edge vertices
    inserted to match cuts made in their neighboring planar polygons.
    """
    mesh = obj.data
    vertices = [obj.matrix_world @ v.co for v in mesh.vertices]
    original_count = len(vertices)
    raw = [list(p.vertices) for p in mesh.polygons]
    edge_faces = defaultdict(list)
    face_edges = []
    normals = []
    planar = []
    vertical = []
    for fi,ids in enumerate(raw):
        points = [vertices[i] for i in ids]
        n = _normal(points)
        normals.append(n)
        planar.append(max(abs((p-points[0]).dot(n)) for p in points) <= PLANAR_TOL)
        vertical.append(abs(n.z) < .1)
        edges = [tuple(sorted((a,b))) for a,b in zip(ids,ids[1:]+ids[:1])]
        face_edges.append(edges)
        for edge in edges:
            edge_faces[edge].append(fi)
    graph = defaultdict(set)
    for edge,adj in edge_faces.items():
        if len(adj) != 2:
            continue
        a,b = adj
        if not (planar[a] and planar[b] and vertical[a] and vertical[b]):
            continue
        if normals[a].dot(normals[b]) > 1-1e-7:
            graph[a].add(b)
            graph[b].add(a)
    components=[]
    seen=set()
    for seed in range(len(raw)):
        if seed in seen:
            continue
        seen.add(seed)
        members=[]
        stack=[seed]
        n=normals[seed]
        origin=vertices[raw[seed][0]]
        while stack:
            fi=stack.pop()
            members.append(fi)
            for other in graph[fi]:
                if other in seen:
                    continue
                if normals[other].dot(n)<=1-1e-7:
                    continue
                if max(abs((vertices[i]-origin).dot(n)) for i in raw[other]) > PLANAR_TOL:
                    continue
                seen.add(other)
                stack.append(other)
        components.append(members)

    # Edge registry includes only points created by cuts. Every intersection is
    # computed once from canonical original endpoints, never from rounded coords.
    edge_points=defaultdict(list)
    vertex_support={i:set() for i in range(original_count)}
    for edge in edge_faces:
        for i in edge:
            vertex_support[i].add(edge)

    def intersection(a,b,u,value):
        common=vertex_support[a] & vertex_support[b]
        if not common:
            raise ValueError('Parallel cuts unexpectedly crossed an internal cut edge')
        edge=min(common)
        i,j=edge
        start,end=vertices[i],vertices[j]
        denom=(end-start).dot(u)
        if abs(denom)<1e-12:
            raise ValueError('Intersection requested on an edge parallel to cut plane')
        t=(value-start.dot(u))/denom
        t=max(0.,min(1.,t))
        length=(end-start).length
        if t*length <= EDGE_TOL:
            return i
        if (1-t)*length <= EDGE_TOL:
            return j
        for old_t,idx in edge_points[edge]:
            if abs(t-old_t)*length <= EDGE_TOL:
                return idx
        idx=len(vertices)
        vertices.append(start+(end-start)*t)
        vertex_support[idx]={edge}
        edge_points[edge].append((t,idx))
        return idx

    def clip(ids,u,value,less):
        result=[]
        for a,b in zip(ids,ids[1:]+ids[:1]):
            da=vertices[a].dot(u)-value
            db=vertices[b].dot(u)-value
            # Snap the classification near an original/cached point consistently.
            if abs(da)<EDGE_TOL:da=0.
            if abs(db)<EDGE_TOL:db=0.
            ina=da<=0 if less else da>=0
            inb=db<=0 if less else db>=0
            if ina:result.append(a)
            if ina != inb:
                result.append(intersection(a,b,u,value))
        clean=[]
        for idx in result:
            if not clean or idx!=clean[-1]:clean.append(idx)
        if len(clean)>1 and clean[0]==clean[-1]:clean.pop()
        return clean

    prepared=[]
    sections={}
    cuts_total=0
    for ci,members in enumerate(components):
        seed=members[0]
        point_ids=sorted({i for fi in members for i in raw[fi]})
        points=[vertices[i] for i in point_ids]
        n=normals[seed]
        fr=_frame(points,n,vertical[seed])
        u,v,a,b,c,d,anchor=fr
        requested=[]
        if planar[seed] and vertical[seed]:
            requested=sorted(float(t) for t in cut_detector(points,n))
        cuts=[]
        for cut in requested:
            if a+EDGE_TOL<cut<b-EDGE_TOL and (not cuts or cut-cuts[-1]>EDGE_TOL):
                cuts.append(cut)
        cuts_total+=len(cuts)
        bounds=[a]+cuts+[b]
        for fi in members:
            remaining=raw[fi][:]
            for interval in range(len(bounds)-1):
                if not remaining:break
                if interval<len(cuts):
                    left=clip(remaining,u,cuts[interval],True)
                    remaining=clip(remaining,u,cuts[interval],False)
                else:
                    left=remaining
                    remaining=[]
                if len(set(left))<3:continue
                pts=[vertices[i] for i in left]
                area_vector=Vector((0,0,0))
                for p,q in zip(pts,pts[1:]+pts[:1]):
                    area_vector+=(p-pts[0]).cross(q-pts[0])
                if area_vector.length<1e-10:continue
                section=(ci,interval)
                section_frame=(u,v,bounds[interval],bounds[interval+1],c,d,anchor)
                if section not in sections:
                    sections[section]={'frame':section_frame,'n':n,'parents':[], 'members':[], 'polygons':[], 'nonplanar':not planar[seed]}
                entry={'indices':left,'parent':fi,'section':section,'frame':section_frame,'n':n,'nonplanar':not planar[fi]}
                prepared.append(entry)
                if fi not in sections[section]['parents']:sections[section]['parents'].append(fi)

    # Insert every split point along original shared edges, including neighboring
    # horizontal/unmodified polygons. This preserves original mesh connectivity.
    inserted_neighbors=0
    for face in prepared:
        ids=face['indices']
        result=[]
        for a,b in zip(ids,ids[1:]+ids[:1]):
            result.append(a)
            common=vertex_support[a]&vertex_support[b]
            if not common:continue
            edge=min(common)
            if edge not in edge_points:continue
            i,j=edge
            start=vertices[i];direction=vertices[j]-start
            length2=direction.length_squared
            ta=(vertices[a]-start).dot(direction)/length2
            tb=(vertices[b]-start).dot(direction)/length2
            between=[(t,idx) for t,idx in edge_points[edge] if idx not in (a,b) and min(ta,tb)+1e-9<t<max(ta,tb)-1e-9]
            between.sort(reverse=tb<ta)
            result.extend(idx for t,idx in between)
            inserted_neighbors+=len(between)
        face['indices']=result
        face['poly']=[vertices[i] for i in result]
    for fi,face in enumerate(prepared):
        section=sections[face['section']]
        section['members'].append(fi)
        section['polygons'].append(face['poly'])
    return {'vertices':vertices,'faces':prepared,'sections':sections,'stats':{
        'original_vertices':original_count,'original_faces':len(raw),
        'output_vertices':len(vertices),'output_faces':len(prepared),
        'components':len(components),'sections':len(sections),
        'component_cuts':cuts_total,'neighbor_edge_insertions':inserted_neighbors,
        'nonplanar_original_faces':[i for i,p in enumerate(planar) if not p],
    }}
