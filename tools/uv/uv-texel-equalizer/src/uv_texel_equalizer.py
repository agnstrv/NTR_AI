"""Blender 4.3+/5.x: equalize island density and correct UV orientation.

Run in Blender's Text Editor, then use UV Editor > N > Texel.
No UVs are changed merely by running/registering this file.

The corner-angle comparison is adapted from the user-supplied ATRIUM AGR 2.0,
angle_distortion_checker.py / select_faces_with_angle_distortion (the
Find Stretched Faces button). Its UI operator is deliberately not invoked:
it changes selection/mode, assumes UVMap and ignores n-gons/world transforms.
Additional triangle Jacobian and intra-island density checks close those gaps.
Whole-island winding analysis extends ATRIUM's mirrored_uv_checker.py;
world-up alignment uses projected triangle tangent maps, not polygon bounds.
"""
bl_info = {"name": "UV Texel Equalizer", "author": "Codex", "version": (1, 1, 0),
           "blender": (4, 3, 0), "location": "UV Editor > Sidebar > Texel",
           "description": "Equal texel density; fix mirrored/upside-down UV islands without stretching",
           "category": "UV"}

import bpy
import bmesh
import math
import json
import struct
from collections import defaultdict
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, PointerProperty, StringProperty


class TexelError(RuntimeError):
    pass


def _vsub(a, b):
    return tuple(x-y for x, y in zip(a, b))


def _dot(a, b):
    return sum(x*y for x, y in zip(a, b))


def _cross(a, b):
    return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])


def _length(a):
    return math.sqrt(_dot(a, a))


def _angle(a, b):
    """ATRIUM's normalized dot/acos comparison, in double precision."""
    den = _length(a)*_length(b)
    if den <= 1e-30:
        raise TexelError("Вырожденное ребро: угол определить нельзя.")
    return math.degrees(math.acos(max(-1., min(1., _dot(a, b)/den))))


def _f32(value):
    try:
        result = struct.unpack('f', struct.pack('f', value))[0]
    except (OverflowError, struct.error):
        raise TexelError("Новые UV выходят за диапазон точности Blender.")
    if not math.isfinite(result):
        raise TexelError("Неконечная координата UV.")
    return result


def _snapshot(obj):
    if obj.mode == 'EDIT':
        bm = bmesh.from_edit_mesh(obj.data)
        bm.faces.ensure_lookup_table()
        bm.faces.index_update()
        bm.verts.index_update()
        temporary = bpy.data.meshes.new('_Texel_Audit_Temporary')
        copy = bm.copy()
        try:
            copy.to_mesh(temporary)
        finally:
            copy.free()
        return temporary, True
    if obj.mode != 'OBJECT':
        raise TexelError("Используйте Object Mode или Edit Mode.")
    return obj.data, False


def _islands(mesh, uv, epsilon):
    parent = list(range(len(mesh.polygons)))
    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    edges = defaultdict(list)
    for face in mesh.polygons:
        loops = list(face.loop_indices)
        for a, b in zip(loops, loops[1:]+loops[:1]):
            va, vb = mesh.loops[a].vertex_index, mesh.loops[b].vertex_index
            if va > vb:
                va, vb, a, b = vb, va, b, a
            edges[(va, vb)].append((face.index, a, b))
    def same(a, b):
        return max(abs(a[0]-b[0]), abs(a[1]-b[1])) <= epsilon
    for links in edges.values():
        for i, (fa, a, b) in enumerate(links):
            for fb, c, d in links[i+1:]:
                if same(uv[a], uv[c]) and same(uv[b], uv[d]):
                    parent[root(fa)] = root(fb)
    groups = defaultdict(list)
    for face in mesh.polygons:
        groups[root(face.index)].append(face.index)
    return sorted(groups.values(), key=lambda g: g[0])


def _triangle(points, coords):
    e1, e2 = _vsub(points[1], points[0]), _vsub(points[2], points[0])
    twice_area = _length(_cross(e1, e2))
    x1 = _length(e1)
    if twice_area <= 1e-30 or x1 <= 1e-30:
        raise TexelError("Вырожденный 3D-треугольник.")
    u, v = _vsub(coords[1], coords[0]), _vsub(coords[2], coords[0])
    determinant = u[0]*v[1]-u[1]*v[0]
    if abs(determinant) <= 1e-30:
        raise TexelError("UV-треугольник схлопнут в точку или линию.")
    x2, y2 = _dot(e1, e2)/x1, twice_area/x1
    col1 = (u[0]/x1, u[1]/x1)
    col2 = ((v[0]-u[0]*x2/x1)/y2, (v[1]-u[1]*x2/x1)/y2)
    a, b, c = _dot(col1, col1), _dot(col1, col2), _dot(col2, col2)
    largest = (a+c+math.hypot(a-c, 2*b))/2
    det_j = determinant/(x1*y2)
    smallest = det_j*det_j/largest if largest > 0 else 0
    if smallest <= 0:
        raise TexelError("UV-преобразование численно вырождено.")
    ratio = math.sqrt(largest/smallest)
    angle_error = max(abs(_angle(_vsub(points[(i-1)%3], points[i]),
                                       _vsub(points[(i+1)%3], points[i])) -
                          _angle(_vsub(coords[(i-1)%3], coords[i]),
                                 _vsub(coords[(i+1)%3], coords[i]))) for i in range(3))
    return dict(area=twice_area/2, pixel_area=abs(determinant)/2,
                ratio=ratio, angle=angle_error,
                density=math.sqrt(abs(determinant)/twice_area), sign=1 if determinant > 0 else -1)


def _measure(mesh, obj, uv, width, height, unit):
    # Transform edge coordinates in Python doubles. Object translation is
    # intentionally omitted, avoiding cancellation on georeferenced models.
    m = [[float(obj.matrix_world[i][j])*unit for j in range(3)] for i in range(3)]
    local = [tuple(v.co) for v in mesh.vertices]
    mesh.calc_loop_triangles()
    result = []
    for tri in mesh.loop_triangles:
        origin = local[tri.vertices[0]]
        points = []
        for index in tri.vertices:
            edge = _vsub(local[index], origin)
            points.append(tuple(_dot(row, edge) for row in m))
        coords = [(uv[i][0]*width, uv[i][1]*height) for i in tri.loops]
        try:
            value = _triangle(points, coords)
        except TexelError as error:
            raise TexelError(f"Грань {tri.polygon_index+1}: {error}")
        value.update(face=tri.polygon_index, loops=tuple(tri.loops))
        result.append(value)
    return result


def _corner_errors(mesh, obj, uv, width, height, unit):
    """Find Stretched Faces logic, extended to every polygon, active UV and pixels."""
    m = [[float(obj.matrix_world[i][j])*unit for j in range(3)] for i in range(3)]
    errors = {}
    for face in mesh.polygons:
        indices = list(face.loop_indices)
        maximum = 0.
        for i, center in enumerate(indices):
            previous, following = indices[i-1], indices[(i+1)%len(indices)]
            co = mesh.vertices[mesh.loops[center].vertex_index].co
            a = _vsub(mesh.vertices[mesh.loops[previous].vertex_index].co, co)
            b = _vsub(mesh.vertices[mesh.loops[following].vertex_index].co, co)
            a, b = tuple(_dot(row, a) for row in m), tuple(_dot(row, b) for row in m)
            ua = ((uv[previous][0]-uv[center][0])*width, (uv[previous][1]-uv[center][1])*height)
            ub = ((uv[following][0]-uv[center][0])*width, (uv[following][1]-uv[center][1])*height)
            maximum = max(maximum, abs(_angle(a, b)-_angle(ua, ub)))
        errors[face.index] = maximum
    return errors


def _triangles_overlap(a, b):
    # Strict interior overlap, not a shared edge or a shared corner.
    for tri in (a,b):
        for p,q in zip(tri,tri[1:]+tri[:1]):
            dx,dy=q[0]-p[0],q[1]-p[1]
            length=math.hypot(dx,dy)
            if length <= 1e-30:
                return False
            normal=(-dy/length,dx/length)
            aa=[_dot(_vsub(v,p),normal) for v in a]
            bb=[_dot(_vsub(v,p),normal) for v in b]
            tolerance=max(max(aa)-min(aa),max(bb)-min(bb),1e-10)*1e-10
            if min(max(aa),max(bb))-max(min(aa),min(bb)) <= tolerance:
                return False
    return True


def _new_overlap(mesh, before, after, owner):
    entries=[]
    for tri in mesh.loop_triangles:
        points=[after[i] for i in tri.loops]
        xs,ys=[p[0] for p in points],[p[1] for p in points]
        entries.append((min(xs),max(xs),min(ys),max(ys),tri.polygon_index,tuple(tri.loops),points))
    active=[]
    for item in sorted(entries,key=lambda e:e[0]):
        xmin,xmax,ymin,ymax,face,loops,points=item
        active=[previous for previous in active if previous[1]>xmin]
        for previous in active:
            if owner[face]==owner[previous[4]] or previous[3]<=ymin or ymax<=previous[2]:
                continue
            if _triangles_overlap(points,previous[6]) and not _triangles_overlap(
                    [before[i] for i in loops],[before[i] for i in previous[5]]):
                return owner[face]+1,owner[previous[4]]+1
        active.append(item)
    return None


def _commit_uv(obj,mesh,uv_name,before,after,temporary,single_user):
    """Only called after validation. Restore original UVs if a write fails."""
    if temporary:
        if obj.data.users>1 and single_user:
            raise TexelError("Для общего Mesh Data сначала выйдите в Object Mode: "
                             "скрипт создаст отдельную копию данных.")
        bm=bmesh.from_edit_mesh(obj.data);bm.faces.ensure_lookup_table()
        uv_layer=bm.loops.layers.uv.get(uv_name)
        saved=[(loop,tuple(loop[uv_layer].uv)) for face in bm.faces for loop in face.loops]
        try:
            for face in bm.faces:
                for loop,li in zip(face.loops,mesh.polygons[face.index].loop_indices):
                    loop[uv_layer].uv=after[li]
            bmesh.update_edit_mesh(obj.data,loop_triangles=False,destructive=False)
        except Exception:
            for loop,value in saved:loop[uv_layer].uv=value
            bmesh.update_edit_mesh(obj.data,loop_triangles=False,destructive=False)
            raise
    else:
        original=obj.data
        destination=original.copy() if original.users>1 and single_user else original
        try:
            destination.uv_layers[uv_name].data.foreach_set('uv',[c for xy in after for c in xy])
            destination.update()
            if destination!=original:obj.data=destination
        except Exception:
            if destination==original:
                destination.uv_layers[uv_name].data.foreach_set('uv',[c for xy in before for c in xy])
                destination.update()
            elif destination.users==0:bpy.data.meshes.remove(destination)
            raise


def equalize(obj=None, *, apply=False, uv_name='', width=2048, height=2048,
             average='AREA_RMS', strict=True, angle_limit=1., anisotropy_limit=1.01,
             local_density_limit=.01, tolerance=1e-5, epsilon=0., respect_pins=True,
             single_user=True, protect_overlaps=True, scene=None):
    """Analyze/apply to ALL faces of one mesh, including unselected/hidden faces.

    D_i = sqrt(UV pixel area / world surface area in square meters).
    AREA_RMS = sqrt(sum(pixel areas)/sum(world areas)), preserving total UV area.
    ARITHMETIC = sum(D_i)/N. AREA_MEAN = sum(A_i*D_i)/sum(A_i).
    UVs are transformed by one positive scalar per island about its bbox center.
    Blender float32 UVs are simulated and validated before any write occurs.
    No unwrap, pack, move, rotate, material edits or geometry edits are performed.
    """
    scene = scene or bpy.context.scene
    obj = obj or bpy.context.active_object
    if not obj or obj.type != 'MESH':
        raise TexelError("Выберите один активный меш.")
    if obj.data.library or obj.library:
        raise TexelError("Связанные библиотечные данные доступны только для чтения.")
    if width < 1 or height < 1 or tolerance <= 0:
        raise TexelError("Некорректное разрешение или допуск.")
    if average not in {'AREA_RMS', 'ARITHMETIC', 'AREA_MEAN'}:
        raise TexelError("Неизвестный метод среднего.")
    unit = float(scene.unit_settings.scale_length)
    if not math.isfinite(unit) or unit <= 0:
        raise TexelError("Некорректный масштаб единиц сцены.")
    mesh, temporary = _snapshot(obj)
    try:
        layer = mesh.uv_layers.get(uv_name) if uv_name else mesh.uv_layers.active
        if layer is None:
            raise TexelError("Нужный UV-слой не найден.")
        uv_name = layer.name
        uv = [tuple(loop.uv) for loop in layer.data]
        if not mesh.polygons:
            raise TexelError("В меше нет полигонов.")
        if not all(math.isfinite(c) for xy in uv for c in xy):
            raise TexelError("UV содержат NaN/Infinity.")
        islands = _islands(mesh, uv, epsilon)
        values = _measure(mesh, obj, uv, width, height, unit)
        corner_errors = _corner_errors(mesh, obj, uv, width, height, unit)
        owner = {fi:ii for ii, island in enumerate(islands) for fi in island}
        metrics = [[] for _ in islands]
        for value in values:
            metrics[owner[value['face']]].append(value)
        stats, bad_faces, bad_islands = [], set(), []
        for ii, group in enumerate(metrics):
            area = math.fsum(t['area'] for t in group)
            pixels = math.fsum(t['pixel_area'] for t in group)
            if area <= 0 or pixels <= 0:
                raise TexelError(f"Остров {ii+1} имеет нулевую площадь.")
            density = math.sqrt(pixels/area)
            minimum, maximum = min(t['density'] for t in group), max(t['density'] for t in group)
            spread = maximum/minimum-1
            signs = {t['sign'] for t in group}
            bad = {t['face'] for t in group if t['ratio'] > anisotropy_limit or t['angle'] > angle_limit}
            bad.update(fi for fi in islands[ii] if corner_errors[fi] > angle_limit)
            if spread > local_density_limit or len(signs) > 1:
                bad.update(islands[ii])
            if bad:
                bad_islands.append(ii+1)
                bad_faces.update(bad)
            stats.append(dict(island=ii+1,faces=[fi+1 for fi in islands[ii]],
                              world_area_m2=area,pixel_area=pixels,density_px_m=density,
                              local_density_spread=spread,max_anisotropy=max(t['ratio'] for t in group),
                              max_angle_error_deg=max(max(t['angle'] for t in group),
                                                      max(corner_errors[fi] for fi in islands[ii])),
                              mixed_uv_orientation=len(signs)>1))
        if average == 'AREA_RMS':
            target = math.sqrt(math.fsum(s['pixel_area'] for s in stats)/math.fsum(s['world_area_m2'] for s in stats))
        elif average == 'AREA_MEAN':
            target = math.fsum(s['world_area_m2']*s['density_px_m'] for s in stats)/math.fsum(s['world_area_m2'] for s in stats)
        else:
            target = math.fsum(s['density_px_m'] for s in stats)/len(stats)
        deviation = max(abs(s['density_px_m']/target-1) for s in stats)
        report = dict(object=obj.name,uv_layer=uv_name,islands=len(islands),average=average,
                      resolution=[width,height],unit_scale_m=unit,target_px_m=target,
                      max_relative_error_before=deviation,tolerance=tolerance,
                      stretched_faces=[fi+1 for fi in sorted(bad_faces)],
                      stretched_islands=bad_islands,blocked=bool(strict and bad_faces),
                      details=stats,applied=False)
        if not apply:
            return report
        if strict and bad_faces:
            raise TexelError(f"Обнаружены исходные искажения: {len(bad_faces)} граней. "
                             "Сначала выполните проверку; UV не изменены.")
        if deviation <= tolerance:
            report['max_relative_error_after'] = deviation
            report['already_equal'] = True
            return report
        candidate = list(uv)
        for ii, island in enumerate(islands):
            loops = [li for fi in island for li in mesh.polygons[fi].loop_indices]
            xs, ys = [uv[i][0] for i in loops], [uv[i][1] for i in loops]
            center = ((min(xs)+max(xs))/2, (min(ys)+max(ys))/2)
            scale = target/stats[ii]['density_px_m']
            stats[ii]['scale'] = scale
            for li in loops:
                value = tuple(_f32(center[j]+(uv[li][j]-center[j])*scale) for j in (0,1))
                if respect_pins and layer.data[li].pin_uv and value != uv[li]:
                    raise TexelError("Масштабирование переместит закреплённый UV. "
                                     "Снимите Pin или отключите защиту закреплений. Ничего не изменено.")
                candidate[li] = value
        after = _measure(mesh, obj, candidate, width, height, unit)
        after_metrics = [[] for _ in islands]
        for before, later in zip(values, after):
            if before['sign'] != later['sign']:
                raise TexelError("Потеря ориентации UV из-за точности. Ничего не изменено.")
            if abs(later['ratio']/before['ratio']-1) > max(1e-5,tolerance*5) or abs(later['angle']-before['angle']) > .001:
                raise TexelError("Точности UV недостаточно для сохранения формы. "
                                 "Проверьте очень маленькие острова и большие координаты UDIM.")
            after_metrics[owner[later['face']]].append(later)
        errors = []
        for group in after_metrics:
            density = math.sqrt(math.fsum(t['pixel_area'] for t in group)/math.fsum(t['area'] for t in group))
            errors.append(abs(density/target-1))
        if max(errors) > tolerance:
            raise TexelError(f"Не достигнут допуск плотности: {max(errors):.3g}. UV не изменены.")
        # Do not merge previously separate UV islands at an accidental new contact.
        if _islands(mesh, candidate, epsilon) != islands:
            raise TexelError("Новый масштаб соединяет или разрывает UV-острова. Ничего не изменено.")
        if protect_overlaps:
            collision=_new_overlap(mesh,uv,candidate,owner)
            if collision:
                raise TexelError(f"Появится новое пересечение островов {collision[0]} и {collision[1]}. "
                                 "Увеличьте свободное место между островами. UV не изменены.")
        _commit_uv(obj,mesh,uv_name,uv,candidate,temporary,single_user)
        report.update(applied=True,max_relative_error_after=max(errors),
                      outside_0_1=any(c < 0 or c > 1 for xy in candidate for c in xy))
        return report
    finally:
        if temporary:
            bpy.data.meshes.remove(mesh)


def _orientation_data(mesh,obj,uv,width,height,axis,fallback_axis,epsilon,angle_tolerance):
    islands=_islands(mesh,uv,epsilon)
    owner={fi:ii for ii,island in enumerate(islands) for fi in island}
    matrix=[[float(obj.matrix_world[i][j]) for j in range(3)] for i in range(3)]
    determinant=_dot(matrix[0],_cross(matrix[1],matrix[2]))
    if abs(determinant)<=1e-30:raise TexelError("Нулевой масштаб объекта: ориентация неопределима.")
    handedness=1 if determinant>0 else -1
    axes={'X':(1.,0.,0.),'Y':(0.,1.,0.),'Z':(0.,0.,1.)}
    if axis not in axes or fallback_axis not in axes or axis==fallback_axis:
        raise TexelError("Основная и запасная мировые оси должны быть разными.")
    vectors=[[] for _ in islands];signs=[set() for _ in islands]
    mesh.calc_loop_triangles()
    for tri in mesh.loop_triangles:
        ii=owner[tri.polygon_index];p=[tuple(mesh.vertices[v].co) for v in tri.vertices]
        e1=tuple(_dot(row,_vsub(p[1],p[0])) for row in matrix)
        e2=tuple(_dot(row,_vsub(p[2],p[0])) for row in matrix)
        pixel=[(uv[i][0]*width,uv[i][1]*height) for i in tri.loops]
        u,v=_vsub(pixel[1],pixel[0]),_vsub(pixel[2],pixel[0])
        twice_area=_length(_cross(e1,e2))
        det=u[0]*v[1]-u[1]*v[0]
        if twice_area<=1e-30 or abs(det)<=1e-30:
            raise TexelError(f"Грань {tri.polygon_index+1}: вырожденная геометрия/UV.")
        signs[ii].add((1 if det>0 else -1)*handedness)
        n=tuple(c/twice_area for c in _cross(e1,e2))
        a,b,c=_dot(e1,e1),_dot(e1,e2),_dot(e2,e2)
        gram=twice_area*twice_area
        choices={}
        for key in (axis,fallback_axis):
            direction=axes[key];projected=tuple(direction[j]-n[j]*_dot(direction,n) for j in range(3))
            magnitude=_length(projected)
            if magnitude<.05:continue
            d1,d2=_dot(projected,e1),_dot(projected,e2)
            beta,gamma=(d1*c-d2*b)/gram,(d2*a-d1*b)/gram
            pushed=(beta*u[0]+gamma*v[0],beta*u[1]+gamma*v[1]);norm=_length(pushed)
            if norm<=1e-30:continue
            choices[key]=((pushed[0]/norm,pushed[1]/norm),twice_area/2*magnitude*magnitude)
        vectors[ii].append((tri.polygon_index,twice_area/2,choices))
    details=[]
    for ii,island in enumerate(islands):
        entries=vectors[ii];area=math.fsum(e[1] for e in entries)
        primary=math.fsum(e[1] for e in entries if axis in e[2])
        used_axis=axis if primary>=area*.5 else fallback_axis
        relevant=[(fi,choice[used_axis][0],choice[used_axis][1]) for fi,ar,choice in entries if used_axis in choice]
        mirrored=signs[ii]=={-1};mixed=len(signs[ii])!=1
        # Calculate required rotation AFTER the optional U reflection.
        def summary(reflect):
            weighted=[(((-d[0] if reflect else d[0]),d[1]),weight) for fi,d,weight in relevant]
            x=math.fsum(d[0]*w for d,w in weighted);y=math.fsum(d[1]*w for d,w in weighted)
            total=math.fsum(w for d,w in weighted);norm=math.hypot(x,y)
            if total<=0 or norm<total*1e-8:return None
            direction=(x/norm,y/norm)
            maximum=max(_angle(d,direction) for d,w in weighted)
            return dict(rotation_deg=math.degrees(math.atan2(direction[0],direction[1])),
                        coherence=norm/total,max_direction_spread_deg=maximum)
        original=summary(False);corrected=summary(mirrored)
        ambiguous=(mixed or not original or not corrected or
                   corrected['max_direction_spread_deg']>max(5.,angle_tolerance*2))
        details.append(dict(island=ii+1,faces=[i+1 for i in island],mirrored=mirrored,
                            mixed_orientation=mixed,world_axis_used=used_axis,
                            fallback_used=used_axis!=axis,ambiguous=bool(ambiguous),
                            rotation_deg=original['rotation_deg'] if original else None,
                            rotation_after_mirror_deg=corrected['rotation_deg'] if corrected else None,
                            max_direction_spread_deg=corrected['max_direction_spread_deg'] if corrected else None,
                            coherence=corrected['coherence'] if corrected else 0.,
                            upside_down=bool(original and math.cos(math.radians(original['rotation_deg']))<0),
                            upright=bool(original and abs(original['rotation_deg'])<=angle_tolerance)))
    return islands,owner,details


def orient(obj=None,*,apply=False,uv_name='',width=2048,height=2048,axis='Z',
           fallback_axis='Y',angle_tolerance=1.,fix_mirror=True,fix_upright=True,
           epsilon=0.,tolerance=1e-5,respect_pins=True,single_user=True,protect_overlaps=True):
    """Reflect/rotate whole islands in pixel space; preserve every local density.

    World-up is projected onto triangles and mapped into UV tangent space.
    A consistently negative UV winding (including object handedness) is mirrored.
    Mixed winding or conflicting per-face up directions requires manual review.
    No automatic face-normal correction, unwrap, packing or density change.
    """
    obj=obj or bpy.context.active_object
    if not obj or obj.type!='MESH':raise TexelError("Выберите один активный меш.")
    if obj.library or obj.data.library:raise TexelError("Библиотечный меш доступен только для чтения.")
    if min(width,height)<1 or tolerance<=0:raise TexelError("Некорректное разрешение или допуск.")
    mesh,temporary=_snapshot(obj)
    try:
        layer=mesh.uv_layers.get(uv_name) if uv_name else mesh.uv_layers.active
        if layer is None:raise TexelError("UV-слой не найден.")
        if not mesh.polygons:raise TexelError("В меше нет полигонов.")
        uv_name=layer.name;uv=[tuple(l.uv) for l in layer.data]
        if not all(math.isfinite(c) for xy in uv for c in xy):raise TexelError("Неконечные UV.")
        islands,owner,details=_orientation_data(mesh,obj,uv,width,height,axis,fallback_axis,epsilon,angle_tolerance)
        report=dict(task='ORIENTATION',object=obj.name,uv_layer=uv_name,islands=len(islands),
                    world_up_axis=axis,fallback_axis=fallback_axis,angle_tolerance_deg=angle_tolerance,
                    mirrored_islands=[d['island'] for d in details if d['mirrored']],
                    rotated_islands=[d['island'] for d in details if not d['upright']],
                    ambiguous_islands=[d['island'] for d in details if d['ambiguous']],
                    details=details,applied=False)
        if not apply:return report
        if not fix_mirror and not fix_upright:return report
        if any(d['mixed_orientation'] for d in details):
            raise TexelError("Внутри острова смешана ориентация граней. Проверьте UV и нормали; ничего не изменено.")
        if fix_upright and report['ambiguous_islands']:
            raise TexelError("Направления верха внутри острова противоречат друг другу: "
                             +', '.join(map(str,report['ambiguous_islands'][:12]))+". Ничего не изменено.")
        candidate=list(uv);changed=[];flipped=set()
        for ii,island in enumerate(islands):
            detail=details[ii];reflect=bool(fix_mirror and detail['mirrored'])
            degrees=(detail['rotation_after_mirror_deg'] if reflect else detail['rotation_deg']) if fix_upright else 0.
            if degrees is None:degrees=0.
            if abs(degrees)<=angle_tolerance:degrees=0.
            if not reflect and degrees==0.:continue
            loops=[li for fi in island for li in mesh.polygons[fi].loop_indices]
            pixel=[(uv[i][0]*width,uv[i][1]*height) for i in loops]
            center=((min(p[0] for p in pixel)+max(p[0] for p in pixel))/2,
                    (min(p[1] for p in pixel)+max(p[1] for p in pixel))/2)
            theta=math.radians(degrees);co,si=math.cos(theta),math.sin(theta)
            for li in loops:
                x,y=uv[li][0]*width-center[0],uv[li][1]*height-center[1]
                if reflect:x=-x
                value=(_f32((center[0]+co*x-si*y)/width),_f32((center[1]+si*x+co*y)/height))
                if respect_pins and layer.data[li].pin_uv and value!=uv[li]:
                    raise TexelError("Исправление переместит закреплённые UV. Ничего не изменено.")
                candidate[li]=value
            changed.append(ii+1)
            if reflect:flipped.add(ii)
            detail.update(applied_reflection=reflect,applied_rotation_deg=degrees)
        if not changed:
            report['already_correct']=True;return report
        unit=float(bpy.context.scene.unit_settings.scale_length)
        before=_measure(mesh,obj,uv,width,height,unit);after=_measure(mesh,obj,candidate,width,height,unit)
        for a,b in zip(before,after):
            expected_sign=-a['sign'] if owner[a['face']] in flipped else a['sign']
            if b['sign']!=expected_sign or abs(a['density']/b['density']-1)>tolerance or \
               abs(a['ratio']/b['ratio']-1)>max(1e-5,tolerance*5) or abs(a['angle']-b['angle'])>.001:
                raise TexelError("Точности UV недостаточно для поворота без изменения формы/текселя. Ничего не изменено.")
        if _islands(mesh,candidate,epsilon)!=islands:
            raise TexelError("Преобразование изменит состав UV-островов. Ничего не изменено.")
        if protect_overlaps:
            collision=_new_overlap(mesh,uv,candidate,owner)
            if collision:raise TexelError(f"Появится пересечение островов {collision[0]} и {collision[1]}. Ничего не изменено.")
        _,_,verified=_orientation_data(mesh,obj,candidate,width,height,axis,fallback_axis,epsilon,angle_tolerance)
        for detail in verified:
            if (fix_mirror and detail['mirrored']) or (fix_upright and not detail['upright']):
                raise TexelError("Не удалось достичь заданной ориентации с нужной точностью. Ничего не изменено.")
        _commit_uv(obj,mesh,uv_name,uv,candidate,temporary,single_user)
        report.update(applied=True,changed_islands=changed,after=verified,
                      outside_0_1=any(c<0 or c>1 for xy in candidate for c in xy))
        return report
    finally:
        if temporary:bpy.data.meshes.remove(mesh)


REPORT_NAME = 'Texel_Equalizer_Report.json'


def _store(report):
    text = bpy.data.texts.get(REPORT_NAME) or bpy.data.texts.new(REPORT_NAME)
    text.clear()
    text.write(json.dumps(report,ensure_ascii=False,indent=2))


def _settings(context, apply):
    p = context.scene.texel_equalizer
    return dict(apply=apply,uv_name=p.uv_name,width=p.width,height=p.height,
                average=p.average,strict=p.strict,angle_limit=p.angle_limit,
                anisotropy_limit=1+p.stretch_percent/100,
                local_density_limit=p.stretch_percent/100,tolerance=p.tolerance,
                respect_pins=p.respect_pins,single_user=p.single_user,
                protect_overlaps=p.protect_overlaps)


def _orientation_settings(context,apply):
    p=context.scene.texel_equalizer
    return dict(apply=apply,uv_name=p.uv_name,width=p.width,height=p.height,
                axis=p.up_axis,fallback_axis=p.fallback_axis,angle_tolerance=p.orientation_tolerance,
                fix_mirror=p.fix_mirror,fix_upright=p.fix_upright,tolerance=p.tolerance,
                respect_pins=p.respect_pins,single_user=p.single_user,protect_overlaps=p.protect_overlaps)


class TEXEL_PG_Settings(bpy.types.PropertyGroup):
    uv_name: StringProperty(name='UV-слой',description='Пусто — активный UV-слой',default='')
    width: IntProperty(name='Ширина, px',default=2048,min=1,max=65536)
    height: IntProperty(name='Высота, px',default=2048,min=1,max=65536)
    average: EnumProperty(name='Среднее',items=[
        ('AREA_RMS','С сохранением площади UV','Квадратичное среднее с весом по площади 3D'),
        ('ARITHMETIC','Арифметическое по островам','Каждый остров имеет одинаковый вес'),
        ('AREA_MEAN','Арифметическое по площади','Вес острова равен его площади 3D')],default='AREA_RMS')
    strict: BoolProperty(name='Остановиться при исходных искажениях',default=True)
    angle_limit: FloatProperty(name='Допуск угла, °',default=1.,min=.001,max=90.)
    stretch_percent: FloatProperty(name='Допуск растяжения, %',default=1.,min=.001,max=100.)
    tolerance: FloatProperty(name='Допуск плотности (доля)',default=1e-5,min=1e-7,max=.01,precision=7)
    respect_pins: BoolProperty(name='Защитить закреплённые UV',default=True)
    single_user: BoolProperty(name='Отделить общее Mesh Data',default=True)
    protect_overlaps: BoolProperty(name='Запретить новые пересечения островов',default=True)
    up_axis: EnumProperty(name='Верх модели',items=[('Z','Мировая Z',''),('Y','Мировая Y',''),('X','Мировая X','')],default='Z')
    fallback_axis: EnumProperty(name='Для горизонтальных граней',items=[('Y','Мировая Y',''),('X','Мировая X',''),('Z','Мировая Z','')],default='Y')
    orientation_tolerance: FloatProperty(name='Допуск ориентации, °',default=1.,min=.01,max=45.)
    fix_mirror: BoolProperty(name='Исправлять зеркальность',default=True)
    fix_upright: BoolProperty(name='Направлять верх модели вверх по V',default=True)


class TEXEL_OT_Audit(bpy.types.Operator):
    bl_idname = 'uv.texel_equalizer_audit'
    bl_label = 'Проверить плотность и растяжения'
    bl_options = {'REGISTER'}
    @classmethod
    def poll(cls, context):
        return context.active_object is not None and context.active_object.type == 'MESH'
    def execute(self, context):
        try:
            r = equalize(context.active_object,**_settings(context,False))
            r['orientation']=orient(context.active_object,**_orientation_settings(context,False))
            _store(r)
            self.report({'WARNING'} if r['blocked'] else {'INFO'},
                        f"Островов: {r['islands']}; среднее {r['target_px_m']:.6g} px/m; "
                        f"отклонение {r['max_relative_error_before']*100:.6g}%; "
                        f"растянутых граней: {len(r['stretched_faces'])}; "
                        f"зеркальных островов: {len(r['orientation']['mirrored_islands'])}. Отчёт: {REPORT_NAME}")
            return {'FINISHED'}
        except Exception as error:
            self.report({'ERROR'},str(error));return {'CANCELLED'}


class TEXEL_OT_Equalize(bpy.types.Operator):
    bl_idname = 'uv.texel_equalizer_apply'
    bl_label = 'Выровнять тексель всех островов'
    bl_options = {'REGISTER','UNDO'}
    @classmethod
    def poll(cls, context):
        return TEXEL_OT_Audit.poll(context)
    def execute(self, context):
        try:
            r = equalize(context.active_object,**_settings(context,True))
            _store(r)
            self.report({'INFO'},f"{r['islands']} островов: {r['target_px_m']:.6g} px/m; "
                        f"ошибка {r['max_relative_error_after']*100:.6g}%. "
                        "Упаковка не выполнялась: проверьте пересечения UV.")
            return {'FINISHED'}
        except Exception as error:
            self.report({'ERROR'},str(error));return {'CANCELLED'}


class TEXEL_OT_SelectIssues(bpy.types.Operator):
    bl_idname = 'uv.texel_equalizer_select_issues'
    bl_label = 'Выделить растянутые грани'
    bl_options = {'REGISTER','UNDO'}
    @classmethod
    def poll(cls, context):
        return TEXEL_OT_Audit.poll(context)
    def execute(self, context):
        try:
            obj = context.active_object
            r = equalize(obj,**_settings(context,False));_store(r)
            bad = {i-1 for i in r['stretched_faces']}
            if obj.mode != 'EDIT':
                bpy.ops.object.mode_set(mode='EDIT')
            bm = bmesh.from_edit_mesh(obj.data);bm.faces.ensure_lookup_table()
            context.tool_settings.mesh_select_mode = (False,False,True)
            for face in bm.faces:
                face.select_set(face.index in bad)
            bmesh.update_edit_mesh(obj.data,loop_triangles=False,destructive=False)
            self.report({'INFO'},f"Выделено граней: {len(bad)}")
            return {'FINISHED'}
        except Exception as error:
            self.report({'ERROR'},str(error));return {'CANCELLED'}


class TEXEL_OT_OrientationAudit(bpy.types.Operator):
    bl_idname='uv.texel_equalizer_orientation_audit'
    bl_label='Проверить ориентацию островов'
    bl_options={'REGISTER'}
    @classmethod
    def poll(cls,context):return TEXEL_OT_Audit.poll(context)
    def execute(self,context):
        try:
            r=orient(context.active_object,**_orientation_settings(context,False));_store(r)
            self.report({'WARNING'} if r['ambiguous_islands'] else {'INFO'},
                        f"Зеркальных: {len(r['mirrored_islands'])}; повёрнутых: {len(r['rotated_islands'])}; "
                        f"неоднозначных: {len(r['ambiguous_islands'])}. Отчёт: {REPORT_NAME}")
            return {'FINISHED'}
        except Exception as error:self.report({'ERROR'},str(error));return {'CANCELLED'}


class TEXEL_OT_OrientationFix(bpy.types.Operator):
    bl_idname='uv.texel_equalizer_orientation_fix'
    bl_label='Исправить зеркальность и верх UV'
    bl_options={'REGISTER','UNDO'}
    @classmethod
    def poll(cls,context):return TEXEL_OT_Audit.poll(context)
    def execute(self,context):
        try:
            r=orient(context.active_object,**_orientation_settings(context,True));_store(r)
            self.report({'INFO'},f"Исправлено островов: {len(r.get('changed_islands',[]))}. "
                        "Плотность и форма сохранены.")
            return {'FINISHED'}
        except Exception as error:self.report({'ERROR'},str(error));return {'CANCELLED'}


class TEXEL_PT_Panel(bpy.types.Panel):
    bl_label = 'Одинаковый тексель без растяжений'
    bl_space_type = 'IMAGE_EDITOR'
    bl_region_type = 'UI'
    bl_category = 'Texel'
    def draw(self, context):
        p = context.scene.texel_equalizer;l = self.layout
        l.label(text='Один активный меш, все его грани')
        l.prop(p,'uv_name');row=l.row(align=True);row.prop(p,'width');row.prop(p,'height')
        l.prop(p,'average');l.prop(p,'strict');l.prop(p,'angle_limit');l.prop(p,'stretch_percent')
        l.prop(p,'tolerance');l.prop(p,'respect_pins');l.prop(p,'single_user');l.prop(p,'protect_overlaps')
        l.operator(TEXEL_OT_Audit.bl_idname);l.operator(TEXEL_OT_SelectIssues.bl_idname)
        l.separator();l.operator(TEXEL_OT_Equalize.bl_idname,icon='UV')
        box=l.box();box.label(text='Ориентация UV относительно модели')
        box.prop(p,'up_axis');box.prop(p,'fallback_axis');box.prop(p,'orientation_tolerance')
        box.prop(p,'fix_mirror');box.prop(p,'fix_upright')
        box.operator(TEXEL_OT_OrientationAudit.bl_idname)
        box.operator(TEXEL_OT_OrientationFix.bl_idname,icon='FILE_REFRESH')
        l.label(text='Без unwrap и упаковки; Undo: Ctrl+Z')
        l.label(text='Размер изображения должен быть верным')


CLASSES = (TEXEL_PG_Settings,TEXEL_OT_Audit,TEXEL_OT_Equalize,TEXEL_OT_SelectIssues,
           TEXEL_OT_OrientationAudit,TEXEL_OT_OrientationFix,TEXEL_PT_Panel)


def unregister():
    if hasattr(bpy.types.Scene,'texel_equalizer'):
        del bpy.types.Scene.texel_equalizer
    for cls in reversed(CLASSES):
        base=cls.__bases__[0]
        identifier=cls.__name__
        if issubclass(cls,bpy.types.Operator):
            prefix,name=cls.bl_idname.split('.',1)
            identifier=prefix.upper()+'_OT_'+name
        registered=base.bl_rna_get_subclass_py(identifier,None)
        if registered is not None and getattr(registered,'is_registered',False):
            bpy.utils.unregister_class(registered)


def register():
    unregister()
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.texel_equalizer = PointerProperty(type=TEXEL_PG_Settings)


if __name__ == '__main__':
    register()
