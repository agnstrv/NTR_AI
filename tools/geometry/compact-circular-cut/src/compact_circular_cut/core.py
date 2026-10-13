"""Blender 5.x: circular opening with short, paired radial spokes.

Geometry backend for the Compact Circular Cut addon. In Object Mode select the cylinder, then Shift-select
the target mesh LAST (active), then F3 -> Compact Circular Cut.
The cutter determines the profile, orientation, dimensions and segment count.
The local subtraction is rebuilt as short paired spokes, not Boolean topology.
Supports thin surfaces, through holes and blind holes in closed meshes.
Existing openings/edge notches and arbitrary non-cylindrical cutters are rejected.

Radius and transition width are WORLD units. Circle vertices are protected:
only the outer transition is reduced, two spokes to one outer vertex.
Source edges constrain the transition; collinear cutter-edge intersections
are added where needed to preserve the original piecewise planar surface.
New surface vertices are projected by barycentric coordinates in the cut plane.
Existing outer boundary vertices are reused without moving them.
"""
import math
import bpy
import bmesh
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from mathutils.geometry import delaunay_2d_cdt, tessellate_polygon
from bpy.props import FloatProperty, BoolProperty, StringProperty

TAU = math.tau
GEOMETRY_REVISION = 'surface_edges_1.1.1'


def _components(faces):
    remaining = set(faces)
    result = []
    while remaining:
        seed = remaining.pop()
        part, todo = {seed}, [seed]
        while todo:
            face = todo.pop()
            for edge in face.edges:
                for other in edge.link_faces:
                    if other in remaining:
                        remaining.remove(other)
                        part.add(other)
                        todo.append(other)
        result.append(part)
    return result


def _boundary(part):
    edges = [e for f in part for e in f.edges
             if sum(g in part for g in e.link_faces) == 1]
    edges = list(set(edges))
    vertices = {v for e in edges for v in e.verts}
    if any(sum(v in e.verts for e in edges) != 2 for v in vertices):
        raise ValueError('Selected patch must have one closed boundary.')
    return edges, vertices


def _projector(part, matrix, normal, center, ray_length, uv_layer):
    vertices = list({v for f in part for v in f.verts})
    indices = {v: i for i, v in enumerate(vertices)}
    world = [matrix @ v.co for v in vertices]
    # Triangulate a temporary copy for ray hits and UV interpolation only.
    temp = bmesh.new()
    copied = {v: temp.verts.new(v.co) for v in vertices}
    source_normals={copied[v]:v.normal.copy() for v in vertices}
    source_uv = {}
    for face in part:
        new = temp.faces.new([copied[v] for v in face.verts])
        for loop in face.loops:
            source_uv[(new, copied[loop.vert])] = (
                loop[uv_layer].uv.copy() if uv_layer else Vector((0, 0)))
    temp_uv = temp.loops.layers.uv.new('projection')
    for face in temp.faces:
        for loop in face.loops:
            loop[temp_uv].uv = source_uv[(face, loop.vert)]
    original_edges = {frozenset(e.verts) for e in temp.edges}
    bmesh.ops.triangulate(temp, faces=list(temp.faces))
    temp.normal_update()
    temp.verts.index_update()
    temp.faces.index_update()
    tri_points = [[matrix @ v.co for v in f.verts] for f in temp.faces]
    tri_uv = [[loop[temp_uv].uv.copy() for loop in f.loops] for f in temp.faces]
    tri_normals=[[source_normals[v] for v in f.verts] for f in temp.faces]
    # Keep the source's structural edges, plus non-planar triangulation folds.
    # Projection of vertices alone does not preserve the surface between them.
    support_edges = []
    for edge in temp.edges:
        keep = frozenset(edge.verts) in original_edges
        if len(edge.link_faces) == 2:
            a, b = edge.link_faces
            keep |= a.normal.dot(b.normal) < 1 - 1e-7
        if keep:
            support_edges.append(tuple(matrix @ vert.co for vert in edge.verts))
    temp.free()

    def project(point):
        # Solve in the cut's projection plane. Ray casting exactly on an old
        # strip edge can miss or return an inaccurate hit on long thin faces.
        candidates = []
        for index, (a,b,c) in enumerate(tri_points):
            ab, ac, ap = b-a, c-a, point-a
            ab -= normal*ab.dot(normal)
            ac -= normal*ac.dot(normal)
            ap -= normal*ap.dot(normal)
            aa, bb, cc = ab.dot(ab), ab.dot(ac), ac.dot(ac)
            den = aa*cc-bb*bb
            if abs(den)<1e-18:
                continue
            s = (cc*ap.dot(ab)-bb*ap.dot(ac))/den
            t = (aa*ap.dot(ac)-bb*ap.dot(ab))/den
            violation = max(-s, -t, s+t-1, 0)
            if violation <= 2e-6:
                hit = a+(b-a)*s+(c-a)*t
                candidates.append((violation, -hit.dot(normal), index, s,t,hit))
        if not candidates:
            raise ValueError('Circle/transition leaves the selected patch; select a larger patch.')
        _,_,index,s,t,hit = min(candidates, key=lambda item:(round(item[0],7),item[1]))
        ua, ub, uc = tri_uv[index]
        na,nb,nc=tri_normals[index]
        return hit, ua + (ub - ua) * s + (uc - ua) * t, (na+(nb-na)*s+(nc-na)*t).normalized()

    project.support_edges = support_edges
    return project


def _clip_outside_convex(a, b, polygon, epsilon):
    """Return the parts of a source edge outside the compact transition ring."""
    delta = b - a
    low, high = 0.0, 1.0
    for p, q in zip(polygon, polygon[1:] + polygon[:1]):
        edge = q - p
        offset = edge.x * (a.y - p.y) - edge.y * (a.x - p.x)
        slope = edge.x * delta.y - edge.y * delta.x
        if abs(slope) < epsilon:
            if offset < -epsilon:
                return [(a, b)]
            continue
        t = -offset / slope
        if slope > 0:
            low = max(low, t)
        else:
            high = min(high, t)
    if low >= high or high < 0 or low > 1:
        return [(a, b)]
    pieces = []
    if low > epsilon:
        pieces.append((a, a + delta * min(low, 1)))
    if high < 1 - epsilon:
        pieces.append((a + delta * max(high, 0), b))
    return pieces


def compact_circular_cut(obj, face_indices, center_world, radius,
                         segments=32, transition_width=None, bridge_shell=True,
                         *, cutter_profile=None, cutter_axis=None,
                         cutter_limits=None, blind_cap=None, coordinate_origin=None):
    """Atomic mesh edit; on validation failure the original mesh is untouched.

    Returns contour indices and statistics. One selected surface creates an
    open hole. Two disconnected selected surfaces create a through opening;
    bridge_shell controls whether their circular borders are connected.
    """
    if obj.type != 'MESH' or obj.mode != 'OBJECT':
        raise ValueError('Function requires a mesh in Object Mode.')
    if radius <= 0 or segments < 8 or (segments % 2 and cutter_profile is None):
        raise ValueError('Radius > 0; at least 8 contour vertices required.')
    width = radius * 0.16 if transition_width is None else transition_width
    if not 0 < width < radius:
        raise ValueError('Transition width must be between 0 and radius.')
    if obj.data.shape_keys:
        raise ValueError('Mesh with shape keys needs a separate topology workflow.')
    bpy.context.view_layer.update()
    matrix = obj.matrix_world.copy()
    if coordinate_origin is not None:matrix.translation-=Vector(coordinate_origin)
    inverse=matrix.inverted()
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.faces.ensure_lookup_table()
    bm.normal_update()
    original_normals=[item.vector.copy() for item in obj.data.corner_normals]
    loop_normals={loop:original_normals[li] for face in bm.faces
                  for loop,li in zip(face.loops,obj.data.polygons[face.index].loop_indices)}
    old_v, old_f = len(bm.verts), len(bm.faces)
    try:
        selected = {bm.faces[i] for i in face_indices}
        if not selected:
            raise ValueError('Select surface faces surrounding the hole.')
        parts = _components(selected)
        if len(parts) not in (1, 2):
            raise ValueError('Select one patch, or two disconnected front/back patches.')
        normal_matrix = matrix.to_3x3().inverted().transposed()
        n = sum((normal_matrix @ f.normal * f.calc_area()
                 for f in parts[0]), Vector()).normalized()
        if cutter_axis is not None:n = Vector(cutter_axis).normalized()
        if n.length < 0.9:
            raise ValueError('Patch has inconsistent normals.')
        helper = Vector((0, 0, 1)) if abs(n.z) < .9 else Vector((0, 1, 0))
        u, v = helper.cross(n).normalized(), None
        v = n.cross(u).normalized()
        center = Vector(center_world)
        if cutter_profile is None:
            profile = [(u*math.cos(TAU*i/segments)+v*math.sin(TAU*i/segments))*radius for i in range(segments)]
        else:
            profile = sorted([Vector(p) for p in cutter_profile],
                             key=lambda p: math.atan2(p.dot(v),p.dot(u)) % TAU)
            segments = len(profile)
        groups = [list(range(i,min(i+2,segments))) for i in range(0,segments,2)]
        reduced_profile = []
        for group in groups:
            midpoint = sum((profile[i] for i in group),Vector())/len(group)
            if len(group)==2:
                tangent = profile[group[1]]-profile[group[0]]
                outward = tangent.cross(n).normalized()
            else:outward = midpoint.normalized()
            reduced_profile.append(midpoint+outward*width)
        ring_angles = [math.atan2(p.dot(v),p.dot(u)) % TAU for p in reduced_profile]
        span = max((matrix @ vert.co - center).length for f in selected for vert in f.verts)
        ray_length = max(span * 3, radius * 8, 1)
        uv_layer = bm.loops.layers.uv.active
        plans = []
        for part in parts:
            edges, boundary = _boundary(part)
            pn = sum((normal_matrix @ f.normal * f.calc_area()
                      for f in part), Vector()).normalized()
            if abs(pn.dot(n)) < (.15 if cutter_axis is not None else .8):
                raise ValueError('Front/back patches must face along the same cut axis.')
            # World projection fixes the opening radius, including scaled objects.
            angles = {}
            for vert in boundary:
                q = matrix @ vert.co - center
                angles[vert] = math.atan2(q.dot(v), q.dot(u)) % TAU
                if math.hypot(q.dot(u), q.dot(v)) <= radius + width * 1.02:
                    raise ValueError('Patch boundary is too close to the circle.')
            outer = sorted(boundary, key=angles.get)
            keys = {frozenset(e.verts) for e in edges}
            if any(frozenset((a, b)) not in keys
                   for a, b in zip(outer, outer[1:] + outer[:1])):
                raise ValueError('Patch needs a single star-shaped outer boundary.')
            if max((angles[outer[(i+1) % len(outer)]] - angles[outer[i]]) % TAU
                   for i in range(len(outer))) >= math.pi:
                raise ValueError('Hole center must be inside the selected patch.')
            ray_normal = n if pn.dot(n)>0 else -n
            project = _projector(part, matrix, ray_normal, center, ray_length, uv_layer)
            inner_points, reduced_points = [], []
            for p in profile:
                pair=project(center+p)
                if cutter_limits and not cutter_limits[0]-1e-5 <= (pair[0]-center).dot(n) <= cutter_limits[1]+1e-5:
                    raise ValueError('Cylinder end intersects the rim; extend the cutter past the surface.')
                inner_points.append(pair)
            for p in reduced_profile:reduced_points.append(project(center+p))
            plans.append((part, pn.dot(n) > 0, outer, angles,
                          inner_points, reduced_points, next(iter(part)).material_index, project))
        cutter_segments = segments
        # Preserve source folds through the transition as well. Intersections
        # on a cutter edge are collinear subdivisions, never a changed profile.
        # Use the union for both sides so through-hole walls share the same rim.
        knots = [{0.0} for _ in profile]
        def xy(point):
            return Vector((point.dot(u), point.dot(v)))
        def cross2(a, b):
            return a.x*b.y - a.y*b.x
        for plan in plans:
            for start, end in plan[-1].support_edges:
                a, b = xy(start-center), xy(end-center)
                for i, (p, q) in enumerate(zip(profile, profile[1:]+profile[:1])):
                    c, d = xy(p), xy(q)
                    edge, source_edge = d-c, b-a
                    denominator = cross2(edge, source_edge)
                    if abs(denominator) < radius*radius*1e-10:
                        continue
                    t = cross2(a-c, source_edge)/denominator
                    s = cross2(a-c, edge)/denominator
                    if 1e-5 < t < 1-1e-5 and -1e-5 <= s <= 1+1e-5:
                        if all(abs(t-other)>1e-5 for other in knots[i]):
                            knots[i].add(t)
        if any(len(values)>1 for values in knots):
            profile = [p+(q-p)*t for p,q,values in zip(profile,profile[1:]+profile[:1],knots)
                       for t in sorted(values)]
            segments = len(profile)
            groups = [list(range(i,min(i+2,segments))) for i in range(0,segments,2)]
            reduced_profile = []
            for group in groups:
                midpoint = sum((profile[i] for i in group),Vector())/len(group)
                outward = ((profile[group[-1]]-profile[group[0]]).cross(n).normalized()
                           if len(group)==2 else midpoint.normalized())
                reduced_profile.append(midpoint+outward*width)
            plans = [(part,forward,outer,angles,
                      [project(center+p) for p in profile],
                      [project(center+p) for p in reduced_profile],material,project)
                     for part,forward,outer,angles,_,_,material,project in plans]
        new_faces, contours = [], []
        for part, forward, outer, angles, inner_pts, reduced_pts, material, project in plans:
            uv_by_vert = {}
            normal_by_vert={vert:vert.normal.copy() for vert in outer}
            def make_vertex(pair):
                point, tex, smooth_normal = pair
                vert = bm.verts.new(inverse @ point)
                uv_by_vert[vert] = tex
                normal_by_vert[vert]=smooth_normal
                return vert
            inner = [make_vertex(pair) for pair in inner_pts]
            reduced = [make_vertex(pair) for pair in reduced_pts]
            contours.append(inner)
            # Boundary UVs are taken from the selected side, not its neighbors.
            for face in part:
                for loop in face.loops:
                    if loop.vert in outer:
                        uv_by_vert.setdefault(loop.vert, loop[uv_layer].uv.copy() if uv_layer else Vector((0, 0)))
            def face(vertices):
                f = bm.faces.new(vertices if forward else list(reversed(vertices)))
                f.material_index = material
                f.smooth = True
                f.select = True
                if uv_layer:
                    for loop in f.loops:loop[uv_layer].uv = uv_by_vert[loop.vert]
                for loop in f.loops:loop_normals[loop]=normal_by_vert[loop.vert]
                new_faces.append(f)
                return f
            # Constrain the replacement with the source mesh OUTSIDE the short
            # transition. A long zipper chord across a curved strip changes its
            # shape even when both endpoints lie on the original surface.
            coords, refs, constraints = [], [], []
            epsilon = max(radius * 1e-6, 1e-7)
            def flat(point):
                delta = point - center
                return Vector((delta.dot(u), delta.dot(v)))
            def add(point, ref=None):
                for index, existing in enumerate(coords):
                    if (point-existing).length <= epsilon:
                        if refs[index] is None and ref is not None:
                            refs[index] = ref
                        return index
                coords.append(point)
                refs.append(ref)
                return len(coords) - 1
            def loop_edges(indices):
                constraints.extend(zip(indices, indices[1:] + indices[:1]))
            inner_ids = [add(xy(p), vert) for p,vert in zip(profile,inner)]
            reduced_ids = [add(xy(p), vert) for p,vert in zip(reduced_profile,reduced)]
            outer_ids = [add(flat(matrix @ vert.co), vert) for vert in outer]
            loop_edges(inner_ids)
            loop_edges(reduced_ids)
            loop_edges(outer_ids)
            for j, group in enumerate(groups):
                k = (j + 1) % len(groups)
                for i in group:
                    constraints.append((inner_ids[i], reduced_ids[j]))
                constraints.append((inner_ids[groups[k][0]], reduced_ids[j]))
            reduced_2d = [coords[i] for i in reduced_ids]
            inner_2d = [coords[i] for i in inner_ids]
            def inside(point, polygon, tolerance=0):
                return all((b.x-a.x)*(point.y-a.y) - (b.y-a.y)*(point.x-a.x) >= -tolerance
                           for a, b in zip(polygon, polygon[1:] + polygon[:1]))
            if not all(inside(p, reduced_2d, epsilon) for p in inner_2d):
                raise ValueError('Transition too narrow for this cylinder segment count; increase its width.')
            for vert in {vert for f in part for vert in f.verts} - set(outer):
                point = flat(matrix @ vert.co)
                if not inside(point, inner_2d, epsilon):
                    add(point, vert)
                    uv_by_vert[vert] = project(matrix @ vert.co)[1]
                    normal_by_vert[vert] = vert.normal.copy()
            for a, b in project.support_edges:
                for p, q in _clip_outside_convex(flat(a), flat(b), inner_2d, epsilon):
                    if (p-q).length > epsilon:
                        constraints.append((add(p), add(q)))
            points, _, triangles, origins, _, _ = delaunay_2d_cdt(
                coords, constraints, [outer_ids], 4, epsilon, True)
            mapped, remap = [], {}
            for point, origin_ids in zip(points, origins):
                existing = [refs[i] for i in origin_ids if refs[i] is not None]
                if existing:
                    # Never move an original boundary or cutter-contour vertex.
                    vert = existing[0]
                else:
                    vert = make_vertex(project(center + u*point.x + v*point.y))
                mapped.append(vert)
                for input_id in origin_ids:
                    remap[input_id] = vert
            contours[-1] = [remap[i] for i in inner_ids]
            # The BMesh is an isolated copy: deleting here is still atomic.
            # Keep source vertices/edges until constrained faces have been built.
            bmesh.ops.delete(bm, geom=list(part), context='FACES_ONLY')
            for tri in triangles:
                samples = tessellate_polygon([[Vector((points[i].x,points[i].y,0)) for i in tri]])
                if not samples:
                    continue
                # Vertex average can lie inside the HOLE for a concave outside
                # polygon. A tessellated face triangle supplies an interior point.
                midpoint = sum((points[tri[i]] for i in samples[0]),Vector((0,0)))/3
                if inside(midpoint, inner_2d, epsilon):
                    continue
                vertices = [mapped[i] for i in tri]
                if len(set(vertices)) == len(vertices):
                    face(vertices)
        # Remove discarded wire edges crossing the cut, without welding its rim.
        wires = [edge for edge in bm.edges if not edge.link_faces]
        if wires:
            bmesh.ops.delete(bm, geom=wires, context='EDGES')
        if blind_cap is not None:
            cap=[bm.verts.new(inverse@(Vector(blind_cap)+p)) for p in profile]
            bottom=bm.faces.new(cap if plans[0][1] else list(reversed(cap)))
            bottom.material_index=plans[0][-2];bottom.smooth=False
            if uv_layer:
                for loop,p in zip(bottom.loops,profile if plans[0][1] else list(reversed(profile))):
                    loop[uv_layer].uv=(.5+p.dot(u)/(radius*2),.5+p.dot(v)/(radius*2))
            contours.append(cap)
        if len(contours) == 2 and bridge_shell:
            a, b = contours
            for i in range(segments):
                j = (i+1) % segments
                indices=[a[i],a[j],b[j],b[i]]
                wall = bm.faces.new(indices if plans[0][1] else list(reversed(indices)))
                wall.smooth = True
                wall.material_index = plans[0][-2]
                new_faces.append(wall)
                if uv_layer:
                    coords = [(i/segments, 0), ((i+1)/segments, 0),
                              ((i+1)/segments, 1), (i/segments, 1)]
                    for loop, tex in zip(wall.loops, coords):loop[uv_layer].uv = tex
        # Remove loose vertices left by the discarded patch, without welding
        # any circle vertices or touching the rest of the mesh.
        loose = [vert for vert in bm.verts if not vert.link_edges]
        if loose:bmesh.ops.delete(bm, geom=loose, context='VERTS')
        bm.normal_update()
        bm.verts.index_update()
        bm.faces.index_update()
        hole_indices = [[vert.index for vert in ring] for ring in contours]
        report = {'geometry_revision': GEOMETRY_REVISION,
                  'segments': cutter_segments, 'contour_vertices_per_side': segments,
                  'source_intersections_per_side': segments-cutter_segments,
                  'transition_vertices_per_side': len(groups),
                  'sides': len(contours), 'radius_world': radius,
                  'transition_width_world': width, 'vertices_before': old_v,
                  'vertices_after': len(bm.verts), 'faces_before': old_f,
                  'faces_after': len(bm.faces), 'contours': hole_indices,
                  'blind': blind_cap is not None}
        if obj.data.users>1:obj.data=obj.data.copy()
        custom_normals=[loop_normals.get(loop,Vector((0,0,0))) for f in bm.faces for loop in f.loops]
        bm.to_mesh(obj.data)
        obj.data.update()
        obj.data.normals_split_custom_set(custom_normals)
        return report
    finally:
        bm.free()


def _cylinder_profile(cutter,origin=None):
    """Find opposite planar caps, even after rotation/scale were applied."""
    bpy.context.view_layer.update()
    evaluated=cutter.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh=evaluated.to_mesh()
    matrix=cutter.matrix_world.copy()
    if origin is None:origin=matrix.translation.copy()
    matrix.translation-=Vector(origin)
    try:
        bm=bmesh.new();bm.from_mesh(mesh)
        try:
            clusters=[]
            for face in bm.faces:
                for normal,faces in clusters:
                    if normal.dot(face.normal)>.99999:
                        faces.add(face);break
                else:clusters.append((face.normal.copy(),{face}))
            caps=[]
            for normal,faces in clusters:
                parts=_components(faces)
                for part in parts:
                    edges,verts=_boundary(part)
                    if len(verts)>=8:
                        points=[matrix@v.co for v in verts]
                        center=sum(points,Vector())/len(points)
                        caps.append((normal,points,center,part))
            pairs=[(a,b) for i,a in enumerate(caps) for b in caps[i+1:]
                   if a[0].dot(b[0])<-.9999 and len(a[1])==len(b[1])]
            if len(pairs)!=1:raise ValueError('Cutter must be a straight closed cylinder with two planar caps (8+ sides).')
            a,b=pairs[0];axis=(b[2]-a[2]).normalized();length=(b[2]-a[2]).length
            if length<1e-6:raise ValueError('Cylinder has zero length.')
            center=(a[2]+b[2])/2
            profile=[p-a[2]-axis*(p-a[2]).dot(axis) for p in a[1]]
            opposite=[p-b[2]-axis*(p-b[2]).dot(axis) for p in b[1]]
            radius=max(p.length for p in profile);minimum=min(p.length for p in profile)
            tolerance=max(radius*1e-4,1e-6)
            if any(min((p-q).length for q in opposite)>tolerance for p in profile):
                raise ValueError('Cutter caps must have matching profiles; cones/tapered cutters are unsupported.')
            if any(abs((p-a[2]).dot(axis))>tolerance for p in a[1]) or any(abs((p-b[2]).dot(axis))>tolerance for p in b[1]):
                raise ValueError('Cylinder caps must be perpendicular to its extrusion axis.')
            helper=Vector((0,0,1)) if abs(axis.z)<.9 else Vector((0,1,0))
            u=helper.cross(axis).normalized();v=axis.cross(u)
            profile.sort(key=lambda p:math.atan2(p.dot(v),p.dot(u))%TAU)
            points=[Vector((p.dot(u),p.dot(v))) for p in profile]
            if any((points[(i+1)%len(points)]-points[i]).cross(points[(i+2)%len(points)]-points[(i+1)%len(points)])<=0 for i in range(len(points))):
                raise ValueError('Cylinder profile must be convex and consistently ordered.')
            side_verts={vert for face in bm.faces if face not in a[3] and face not in b[3] for vert in face.verts}
            for vert in side_verts:
                q=matrix@vert.co-center;q=Vector((q.dot(u),q.dot(v)))
                distances=[]
                for p1,p2 in zip(points,points[1:]+points[:1]):
                    edge=p2-p1;t=max(0,min(1,(q-p1).dot(edge)/edge.length_squared))
                    distances.append((q-(p1+edge*t)).length)
                if min(distances)>tolerance*2:
                    raise ValueError('Use a straight cylinder without bevels, taper or changing side profile.')
            return center,axis,profile,length,radius,minimum,u,v
        finally:bm.free()
    finally:evaluated.to_mesh_clear()


def _overlaps_disk(triangle,radius):
    # Conservative projected selection: vertices, edge distances or disk center.
    r2=radius*radius
    if any(p.length_squared<=r2 for p in triangle):return True
    signs=[]
    for a,b in zip(triangle,triangle[1:]+triangle[:1]):
        edge=b-a;den=edge.length_squared
        if den>1e-16:
            t=max(0,min(1,-a.dot(edge)/den))
            if (a+edge*t).length_squared<=r2:return True
        signs.append(edge.cross(-a))
    return all(x>=0 for x in signs) or all(x<=0 for x in signs)


def _inside_mesh(bvh,point,scale):
    direction=Vector((.371,.529,.763)).normalized();count=0
    origin=point.copy();epsilon=max(scale*1e-6,1e-7)
    for _ in range(10000):
        hit,_,_,_=bvh.ray_cast(origin,direction)
        if hit is None:return count%2==1
        count+=1;origin=hit+direction*epsilon
    raise ValueError('Could not classify cutter endpoints in this mesh.')


def compact_cylinder_difference(target,cutter,transition_ratio=.16):
    """Two-object subtraction; target is edited only after validation succeeds."""
    if target==cutter or target.type!='MESH' or cutter.type!='MESH':
        raise ValueError('Select two different mesh objects.')
    if target.mode!='OBJECT':raise ValueError('Use Object Mode.')
    bpy.context.view_layer.update()
    origin=cutter.matrix_world.translation.copy()
    center,axis,profile,length,radius,minimum,u,v=_cylinder_profile(cutter,origin)
    width=minimum*transition_ratio
    mesh=target.data;mesh.calc_loop_triangles();matrix=target.matrix_world.copy();matrix.translation-=origin
    world=[matrix@v.co for v in mesh.vertices]
    normal_matrix=matrix.to_3x3().inverted().transposed()
    allowed={p.index for p in mesh.polygons if abs((normal_matrix@p.normal).normalized().dot(axis))>.35}
    selected=set();reach=radius+width*2.5
    for tri in mesh.loop_triangles:
        if tri.polygon_index not in allowed:continue
        pts=[world[i]-center for i in tri.vertices];depths=[p.dot(axis) for p in pts]
        if min(depths)>length/2 or max(depths)<-length/2:continue
        projected=[Vector((p.dot(u),p.dot(v))) for p in pts]
        if _overlaps_disk(projected,reach):selected.add(tri.polygon_index)
    if not selected:raise ValueError('Cylinder does not intersect a suitable target surface.')
    # Grow one face row to keep the compact ring inside a closed outer boundary.
    edges={}
    for p in mesh.polygons:
        for key in p.edge_keys:edges.setdefault(tuple(sorted(key)),[]).append(p.index)
    grown=set(selected)
    for i in selected:
        for key in mesh.polygons[i].edge_keys:
            for j in edges[tuple(sorted(key))]:
                if j in allowed and (normal_matrix@mesh.polygons[i].normal).normalized().dot((normal_matrix@mesh.polygons[j].normal).normalized())>.85:
                    depths=[(world[k]-center).dot(axis) for k in mesh.polygons[j].vertices]
                    if min(depths)<=length/2 and max(depths)>=-length/2:grown.add(j)
    selected=grown
    bm=bmesh.new();bm.from_mesh(mesh);bm.faces.ensure_lookup_table()
    try:
        parts=_components({bm.faces[i] for i in selected});closed=all(len(e.link_faces)==2 for e in bm.edges)
    finally:bm.free()
    if len(parts)>2:raise ValueError('Cutter crosses multiple separate layers; cut them individually.')
    blind=None
    if len(parts)==1 and closed:
        bvh=BVHTree.FromPolygons(world,[list(t.vertices) for t in mesh.loop_triangles],all_triangles=True)
        ends=[center-axis*length/2,center+axis*length/2]
        inside=[_inside_mesh(bvh,p,max(radius,length)) for p in ends]
        if sum(inside)!=1:raise ValueError('For a blind cut one cylinder end must be inside the closed target.')
        blind=ends[inside.index(True)]
    report=compact_circular_cut(target,sorted(selected),center,radius,len(profile),width,True,
                                cutter_profile=profile,cutter_axis=axis,
                                cutter_limits=(-length/2,length/2),blind_cap=blind,
                                coordinate_origin=origin)
    report['cutter']=cutter.name;report['target']=target.name
    report['profile_from_cutter']=True
    return report


class MESH_OT_compact_circular_cut(bpy.types.Operator):
    bl_idname = 'mesh.compact_circular_cut'
    bl_label = 'Compact Circular Cut'
    bl_description = 'Subtract selected cylinder from active mesh and rebuild compact radial topology'
    bl_options = {'REGISTER', 'UNDO'}

    transition_ratio: FloatProperty(name='Short spoke width / radius', default=.16, min=.02, max=.8)
    hide_cutter: BoolProperty(name='Hide cutter after cut',default=True)
    target_name: StringProperty(options={'HIDDEN'})
    cutter_name: StringProperty(options={'HIDDEN'})

    @classmethod
    def poll(cls, context):
        return context.active_object is not None and context.active_object.type == 'MESH' and context.mode == 'OBJECT'

    def execute(self, context):
        if not self.target_name or not self.cutter_name:
            selected=[o for o in context.selected_objects if o.type=='MESH']
            if len(selected)!=2:
                self.report({'ERROR'},'Select cylinder first, then target mesh last (active).')
                return {'CANCELLED'}
            obj=context.active_object;cutter=next(o for o in selected if o!=obj)
            self.target_name=obj.name;self.cutter_name=cutter.name
        else:
            obj=bpy.data.objects.get(self.target_name);cutter=bpy.data.objects.get(self.cutter_name)
        try:
            if obj is None or cutter is None:raise ValueError('Target or cutter no longer exists.')
            report=compact_cylinder_difference(obj,cutter,self.transition_ratio)
            if self.hide_cutter:cutter.hide_set(True)
            self.report({'INFO'},f"Cutter: {report['segments']}; rim: {report['contour_vertices_per_side']}; paired transition: {report['transition_vertices_per_side']}")
        except Exception as error:
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}
        return {'FINISHED'}


