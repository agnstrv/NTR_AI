"""Blender: наружная поверхность рам и отступ плейнов за контур окон.

Запуск в Text Editor: Run Script. Обрабатывает объекты с window_plane=True.
Повторный запуск не накапливает смещение: используются сохранённые исходные
координаты плейна. expansion задаётся в метрах. Исходные рамы/UV/материалы
не редактируются. Для сброса исходной формы удалите свойство
window_plane_base_coordinates у выбранного плейна.
"""
import bpy
import bmesh
import numpy as np
from mathutils import Vector
from mathutils.kdtree import KDTree
from mathutils.bvhtree import BVHTree

SOURCE_NAME = 'WindowFrameSource'


def _matrix(object, anchor, scale):
    m = np.array([list(row) for row in object.matrix_world], dtype=float)
    return m[:3, :3] * scale, (m[:3, 3] - anchor) * scale


def _normal(points):
    center = points.mean(axis=0)
    cross = np.sum(np.cross(points - center, np.roll(points, -1, axis=0) - center), axis=0)
    length = np.linalg.norm(cross)
    if length < 1e-12:
        raise ValueError('Плейн содержит вырожденный полигон')
    return cross / length


def fix_window_plane_normals(planes=None):
    """Направить нормали по фактическому смещению от исходного плейна.

    Проверяются все полигоны, включая участки изгибов. Координаты,
    границы, UV и материалы сохраняются; меняется порядок обхода граней.
    """
    planes = list(planes) if planes is not None else [o for o in bpy.context.scene.objects if o.type == 'MESH' and o.get('window_plane')]
    reports = []
    for obj in planes:
        mesh = obj.data
        stored = obj.get('window_plane_base_coordinates')
        if stored is None or len(stored) != len(mesh.vertices)*3:
            raise ValueError('Нет исходных координат для проверки смещения: '+obj.name)
        linear = np.array([list(row) for row in obj.matrix_world], dtype=float)[:3,:3]
        base = np.array(stored,dtype=float).reshape(-1,3) @ linear.T
        current = np.array([tuple(v.co) for v in mesh.vertices],dtype=float) @ linear.T
        reverse = []
        for polygon in mesh.polygons:
            ids = list(polygon.vertices)
            direction = (current[ids]-base[ids]).mean(axis=0)
            signed = float(_normal(current[ids]) @ direction)
            if abs(signed) < 1e-6:
                raise ValueError('Неоднозначное направление смещения: '+obj.name)
            if signed < 0:reverse.append(polygon.index)
        if reverse:
            if mesh.users > 1:mesh=obj.data=mesh.copy()
            bm=bmesh.new();bm.from_mesh(mesh);bm.faces.ensure_lookup_table()
            bmesh.ops.reverse_faces(bm,faces=[bm.faces[index] for index in reverse])
            bm.to_mesh(mesh);bm.free();mesh.update()
        minimum = min(float(_normal(current[list(p.vertices)]) @ (current[list(p.vertices)]-base[list(p.vertices)]).mean(axis=0)) for p in mesh.polygons)
        if minimum <= 1e-6:raise ValueError('Проверка нормалей не пройдена: '+obj.name)
        obj['window_plane_normals_outward']=True
        reports.append({'object':obj.name,'faces':len(mesh.polygons),'reversed_faces':len(reverse),'minimum_signed_offset':minimum})
    return reports


def adjust_window_planes(planes=None, source_name=SOURCE_NAME, expansion=0.10):
    """Перенести существующие плейны на внешнюю грань рам, расширить контур.

    На изгибах пересекаются смещённые плоскости соседних полигонов;
    расширяются только граничные рёбра, внутренние рёбра сохраняются.
    """
    if expansion < 0:
        raise ValueError('Отступ должен быть неотрицательным')
    source = bpy.data.objects.get(source_name)
    if source is None or source.type != 'MESH':
        raise ValueError('Не найден исходный меш окон: ' + source_name)
    planes = list(planes) if planes is not None else [o for o in bpy.context.scene.objects if o.type == 'MESH' and o.get('window_plane')]
    if not planes:
        raise ValueError('Не найдены плейны окон')
    if any(o.get('window_plane_cutouts') for o in planes):
        raise ValueError('Плейны уже содержат вырезы. Их повторное расширение изменило бы края вырезов; создайте новую коллекцию через main(recreate=True).')
    if bpy.context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    scale = bpy.context.scene.unit_settings.scale_length or 1.0
    anchor = np.array(source.matrix_world.translation, dtype=float)
    sm, st = _matrix(source, anchor, scale)
    frame_points = np.array([tuple(v.co) for v in source.data.vertices], dtype=float) @ sm.T + st
    tree = KDTree(len(frame_points))
    for index, point in enumerate(frame_points):
        tree.insert(Vector(point), index)
    tree.balance()
    vertex_faces = [[] for _ in frame_points]
    frame_face_normals = []
    frame_face_points = []
    for polygon in source.data.polygons:
        ids = list(polygon.vertices)
        try:
            normal = _normal(frame_points[ids])
        except ValueError:
            normal = np.zeros(3)
        frame_face_normals.append(normal)
        frame_face_points.append(frame_points[ids[0]])
        for index in ids:
            vertex_faces[index].append(polygon.index)
    frame_face_normals = np.array(frame_face_normals)
    frame_face_points = np.array(frame_face_points)
    facade = None
    main = bpy.data.objects.get('Main')
    if main is not None and main.type == 'MESH':
        mm, mt = _matrix(main, anchor, scale)
        coords = np.array([tuple(v.co) for v in main.data.vertices], dtype=float) @ mm.T + mt
        facade = BVHTree.FromPolygons([Vector(p) for p in coords], [list(f.vertices) for f in main.data.polygons])
    reports = []
    for obj in planes:
        mesh = obj.data
        if mesh.users > 1:
            mesh = obj.data = mesh.copy()
        count = len(mesh.vertices)
        stored = obj.get('window_plane_base_coordinates')
        if stored is not None and len(stored) == count * 3:
            local = np.array(stored, dtype=float).reshape(count, 3)
        else:
            local = np.array([tuple(v.co) for v in mesh.vertices], dtype=float)
            obj['window_plane_base_coordinates'] = local.ravel().tolist()
        linear, offset = _matrix(obj, anchor, scale)
        points = local @ linear.T + offset
        faces = [list(f.vertices) for f in mesh.polygons]
        normals = [_normal(points[f]) for f in faces]
        if facade is not None:
            vote = 0.0
            for ids, normal in zip(faces, normals):
                center = points[ids].mean(axis=0)
                near = facade.find_nearest(Vector(center))
                if near[0] is None:
                    continue
                candidates = facade.find_nearest_range(Vector(center), near[3] + 0.8)
                aligned = [q for q in candidates if abs(np.dot(normal, q[1])) > 0.65]
                chosen = min(aligned, key=lambda q: q[3]) if aligned else near
                area = np.linalg.norm(np.sum(np.cross(points[ids], np.roll(points[ids], -1, axis=0)), axis=0)) * 0.5
                vote += area * float(np.dot(normal, chosen[1]))
            if vote < 0:
                normals = [-n for n in normals]
        near_vertices = []
        nearby_face_ids = []
        for point in points:
            found = tree.find_range(Vector(point), 0.30)
            if not found:
                found = tree.find_n(Vector(point), 16)
            near_vertices.append(np.array([frame_points[index] for co, index, distance in found]))
            nearby_face_ids.append(list(set(fi for co,index,distance in found for fi in vertex_faces[index])))
        depths = []
        for ids, normal in zip(faces, normals):
            samples = []
            for index in ids:
                face_ids = nearby_face_ids[index]
                fn = frame_face_normals[face_ids]
                denominator = fn @ normal
                aligned = np.abs(denominator) > .9999
                if np.any(aligned):
                    distances = np.sum(fn[aligned] * (frame_face_points[np.array(face_ids)[aligned]] - points[index]), axis=1) / denominator[aligned]
                    valid = distances[(distances>.008)&(distances<.19)]
                    if len(valid):
                        samples.append(float(valid.max()))
                        continue
                delta = near_vertices[index] - points[index]
                distances = delta @ normal
                lateral = np.linalg.norm(delta - distances[:, None] * normal, axis=1)
                valid = distances[(lateral < .21) & (distances > .008) & (distances < .19)]
                if len(valid):
                    samples.append(float(valid.max()))
            if not samples:
                raise ValueError('Не удалось определить наружную грань рамы: ' + obj.name)
            depths.append(float(np.median(samples)))
        # A window uses one profile depth. A shared distance avoids amplifying
        # sub-millimetre triangulation noise at nearly coplanar joins.
        profile_depth = float(np.median(depths))
        depths = [profile_depth for _ in depths]
        incident = [[] for _ in points]
        for fi, ids in enumerate(faces):
            for i in ids:
                incident[i].append(fi)
        shifted = points.copy()
        projectors = []
        for index, fs in enumerate(incident):
            A = np.array([normals[fi] for fi in fs]); d = np.array([depths[fi] for fi in fs])
            if not len(fs):
                projectors.append(np.eye(3));continue
            delta = np.linalg.lstsq(A, d, rcond=1e-5)[0]
            shifted[index] += delta
            projectors.append(np.eye(3) - np.linalg.pinv(A, rcond=1e-5) @ A)
        # Boundary co-normals point outwards within the surface.
        edge_faces = {}
        for fi, ids in enumerate(faces):
            for i, j in zip(ids, ids[1:] + ids[:1]):
                edge_faces.setdefault(tuple(sorted((i, j))), []).append((fi, i, j))
        constraints = [[] for _ in points]
        boundary_details = []
        for uses in edge_faces.values():
            if len(uses) != 1:
                continue
            fi, i, j = uses[0]; normal = normals[fi]
            direction = shifted[j] - shifted[i]; length = np.linalg.norm(direction)
            if length < 1e-8:
                continue
            direction /= length
            outward = np.cross(direction, normal)
            # The normal may have been reversed to face the exterior. The polygon
            # winding still identifies its interior, so orient the co-normal by it.
            center = shifted[faces[fi]].mean(axis=0); midpoint = (shifted[i]+shifted[j])/2
            if np.dot(outward, center-midpoint) > 0:
                outward = -outward
            supports = []
            for fraction in (0.0, .25, .5, .75, 1.0):
                sample = shifted[i] + fraction*(shifted[j]-shifted[i])
                found = tree.find_range(Vector(sample), .30)
                if not found:
                    continue
                candidates = np.array([frame_points[k] for co,k,dist in found])
                delta = candidates-sample; depth = delta@normal; across = delta@outward; along = delta@direction
                # Use front-frame vertices near this border, not another window
                # or a long jamb that continues to a different storey.
                valid = across[(np.abs(depth)<.035)&(across>=-.12)&(across<=.075)&(np.abs(along)<.20)]
                if len(valid):supports.append(float(valid.max()))
            frame_border = float(np.median(supports)) if supports else 0.0
            required = expansion + frame_border
            constraints[i].append((outward, required));constraints[j].append((outward, required))
            boundary_details.append((i,j,outward,required,frame_border))
        final = shifted.copy()
        for index, conditions in enumerate(constraints):
            if not conditions:
                continue
            P = projectors[index];C = np.array([n @ P for n,d in conditions]);rhs = np.array([d for n,d in conditions])
            delta = P @ np.linalg.lstsq(C, rhs, rcond=1e-5)[0]
            # At a folded, sloping corner, use the outer intersection so neither
            # adjoining side receives less than the requested margin.
            for repeat in range(12):
                corrected = False
                for n, required in conditions:
                    shortfall = required - float(n @ delta)
                    projected = P @ n; denominator = float(projected @ projected)
                    if shortfall > 1e-8 and denominator > 1e-12:
                        delta += projected * (shortfall/denominator);corrected = True
                if not corrected:break
            final[index] += delta
        inverse = np.linalg.inv(linear)
        result = (final-offset) @ inverse.T
        if not np.isfinite(result).all():
            raise ValueError('Недопустимые координаты: ' + obj.name)
        for vertex, co in zip(mesh.vertices, result):
            vertex.co = co
        mesh.update()
        min_margin = min((float(n @ ((final[i]+final[j]-shifted[i]-shifted[j])/2))-border for i,j,n,want,border in boundary_details), default=expansion)
        orientation_min = min(float(np.dot(_normal(final[ids]),_normal(points[ids]))) for ids in faces)
        if min_margin < expansion-2e-5 or orientation_min < .99:
            raise ValueError('Проверка расширения не пройдена: '+obj.name+str((min_margin,orientation_min,depths[0])))
        obj['window_plane_margin_m']=float(expansion);obj['window_plane_exterior']=True
        obj['window_plane_outward_offset_min_m']=min(depths);obj['window_plane_outward_offset_max_m']=max(depths)
        fix_window_plane_normals([obj])
        reports.append({'object':obj.name,'offset_min_m':min(depths),'offset_max_m':max(depths),'minimum_border_margin_m':min_margin})
    return reports


if __name__ == '__main__':
    report = adjust_window_planes(expansion=0.10)
    print('WINDOW_PLANES_ADJUSTED',len(report))



