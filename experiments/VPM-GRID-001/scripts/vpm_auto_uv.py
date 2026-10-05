"""VPM: world-aligned UV preparation and conforming XYZ cuts.
Tested in Blender 5.0.0; other versions unverified. Install as legacy add-on, or run in Text Editor.
Projection density is exact on axis-aligned planes; slopes are compressed.
No UV packing or wrapping: this stage deliberately retains grid coordinates.
"""
bl_info = {
    'name': 'VPM Auto UV', 'author': 'VPM team', 'version': (0, 2, 0),
    'blender': (4, 4, 0), 'location': 'View3D > Sidebar > VPM',
    'description': 'World grid UV preparation and shared XYZ cuts', 'category': 'UV',
}
import math
import json
from collections import Counter


def dominant_axis(normal):
    return max(range(3), key=lambda i: abs(normal[i]))


def projected_uv(point_m, normal, density=1000.0, resolution=2048, origin_m=(0, 0, 0)):
    """Global, metric cube projection. Integers coincide with XYZ grid planes."""
    if density <= 0 or resolution <= 0:
        raise ValueError('Density and resolution must be positive')
    axis = dominant_axis(normal)
    components = ((1, 2), (0, 2), (0, 1))[axis]
    # Keep the mapping's handedness consistent with the outward normal.
    expected_sign = (1, -1, 1)[axis]
    sign = 1 if normal[axis] * expected_sign >= 0 else -1
    factor = density / resolution
    u, v = components
    return (sign * (point_m[u] - origin_m[u]) * factor,
            (point_m[v] - origin_m[v]) * factor)


def projection_metrics(normal, density=1000.0):
    """Singular values on the tangent plane: 1 and |dominant normal|."""
    length = math.sqrt(sum(x*x for x in normal))
    if length < 1e-15:
        raise ValueError('Degenerate normal')
    c = abs(normal[dominant_axis(normal)]) / length
    return {'density_min_direction': density*c,
            'density_max_direction': density,
            'density_area': density*math.sqrt(c),
            'stretch_ratio': 1/c}


def grid_values(lo, hi, step, origin=0.0, epsilon=1e-8):
    """Strictly interior grid planes; robust for signed coordinates."""
    if step <= 0:
        raise ValueError('Grid step must be positive')
    first = math.floor((lo-origin+epsilon)/step)+1
    last = math.ceil((hi-origin-epsilon)/step)-1
    return [origin+i*step for i in range(first, last+1)]


try:
    import bpy
    import bmesh
    from mathutils import Matrix, Vector
    from bpy.props import FloatProperty, IntProperty, FloatVectorProperty, BoolProperty
except ImportError:
    bpy = None


if bpy is not None:
    UV_NAME = 'VPM_GRID'

    def write_uv(mesh, scale_length, density, resolution, origin):
        mesh.update()
        uv = mesh.uv_layers.get(UV_NAME) or mesh.uv_layers.new(name=UV_NAME)
        mesh.uv_layers.active = uv
        uv.active_render = True
        values = [0.0] * (2 * len(mesh.loops))
        normals = []
        for face in mesh.polygons:
            normal = tuple(face.normal)
            if sum(c*c for c in normal) < 1e-20:
                raise ValueError('Degenerate polygon: %s' % face.index)
            normals.append(normal)
            for li in face.loop_indices:
                co = mesh.vertices[mesh.loops[li].vertex_index].co
                point = tuple(c * scale_length for c in co)
                values[2*li:2*li+2] = projected_uv(point, normal, density, resolution, origin)
        uv.data.foreach_set('uv', values)
        mesh.update()
        metrics = [projection_metrics(n, density) for n in normals]
        return {
            'faces': len(normals), 'vertices': len(mesh.vertices),
            'projection_counts_X_Y_Z': dict(Counter(str(dominant_axis(n)) for n in normals)),
            'sloped_faces': sum(m['stretch_ratio'] > 1.00001 for m in metrics),
            'density_min_direction': min((m['density_min_direction'] for m in metrics), default=0),
            'density_max_direction': max((m['density_max_direction'] for m in metrics), default=0),
            'density_area_min': min((m['density_area'] for m in metrics), default=0),
            'max_stretch_ratio': max((m['stretch_ratio'] for m in metrics), default=0),
        }

    def new_work_copy(context, source):
        if source.data.shape_keys:
            raise ValueError('Shape keys: create a static mesh snapshot first')
        result = source.copy()
        if any(m.show_viewport for m in source.modifiers):
            depsgraph = context.evaluated_depsgraph_get()
            evaluated = source.evaluated_get(depsgraph)
            result.data = bpy.data.meshes.new_from_object(
                evaluated, preserve_all_data_layers=True, depsgraph=depsgraph)
            result.modifiers.clear()
            world = evaluated.matrix_world.copy()
        else:
            result.data = source.data.copy()
            world = source.matrix_world.copy()
        result.name = source.name + '_VPM'
        result.data.name = result.name + '_Mesh'
        result.parent = None
        result.animation_data_clear()
        for constraint in list(result.constraints):
            result.constraints.remove(constraint)
        # Bake ALL transforms into the copied mesh. No source mutation.
        result.data.transform(world)
        result.matrix_world = Matrix.Identity(4)
        # Preserve outward winding under mirrored source transforms.
        if world.to_3x3().determinant() < 0:
            result.data.flip_normals()
        context.collection.objects.link(result)
        return result

    def add_report(obj, stats, density, resolution, scale_length, origin, cut=False):
        report = {
            'stage': 'cut' if cut else 'prepare', 'object': obj.name,
            'density_setting_px_per_m': density,
            'texture_resolution_px': resolution,
            'grid_step_m': resolution/density,
            'scene_scale_length': scale_length, 'grid_origin_m': list(origin),
            'policy': 'shared XYZ grid; slope distortion accepted and measured',
            **stats,
        }
        obj['vpm_density'] = density
        obj['vpm_resolution'] = resolution
        obj['vpm_unit_scale'] = scale_length
        obj['vpm_grid_origin_m'] = list(origin)
        obj['vpm_prepared'] = True
        obj['vpm_cut'] = cut
        text = bpy.data.texts.get(obj.name+'_report.json') or bpy.data.texts.new(obj.name+'_report.json')
        text.clear()
        text.write(json.dumps(report, ensure_ascii=False, indent=2))
        return report

    def activate(context, obj):
        for selected in list(context.selected_objects):
            selected.select_set(False)
        obj.hide_set(False)
        obj.hide_viewport = False
        obj.select_set(True)
        context.view_layer.objects.active = obj

    def discard_object(obj):
        """Remove a replaced object and its mesh when no other object uses it."""
        mesh = obj.data if obj.type == 'MESH' else None
        bpy.data.objects.remove(obj, do_unlink=True)
        if mesh is not None and mesh.users == 0:
            bpy.data.meshes.remove(mesh)

    def prepare_object(context, source, density=1000, resolution=2048, origin=(0, 0, 0)):
        if context.mode != 'OBJECT':
            raise ValueError('Switch to Object Mode')
        scale = context.scene.unit_settings.scale_length
        if scale <= 0 or density <= 0 or resolution <= 0:
            raise ValueError('Invalid scene units, density or resolution')
        result = new_work_copy(context, source)
        try:
            stats = write_uv(result.data, scale, density, resolution, origin)
            report = add_report(result, stats, density, resolution, scale, origin)
        except Exception:
            mesh = result.data
            bpy.data.objects.remove(result, do_unlink=True)
            bpy.data.meshes.remove(mesh)
            raise
        activate(context, result)
        discard_object(source)
        return result, report

    def cut_object(context, source, max_planes=2000, max_faces=2000000):
        if context.mode != 'OBJECT' or not source.get('vpm_prepared'):
            raise ValueError('First prepare UV in Object Mode')
        if source.get('vpm_cut'):
            raise ValueError('This copy is already cut; use the prepared copy')
        if any(abs(source.matrix_world[i][j] - (1 if i == j else 0)) > 1e-7
               for i in range(4) for j in range(4)):
            raise ValueError('Object moved after preparation; prepare it again')
        scale = context.scene.unit_settings.scale_length
        if abs(scale-source['vpm_unit_scale']) > 1e-10:
            raise ValueError('Scene units changed; prepare UV again')
        density, resolution = source['vpm_density'], source['vpm_resolution']
        origin = tuple(source['vpm_grid_origin_m'])
        step = resolution / density / scale
        eps = min(step*1e-7, 1e-5/scale)
        coordinates = [v.co for v in source.data.vertices]
        if not coordinates:
            raise ValueError('Mesh is empty')
        planes = [(axis, value) for axis in range(3)
                  for value in grid_values(min(v[axis] for v in coordinates),
                                           max(v[axis] for v in coordinates),
                                           step, origin[axis]/scale, eps)]
        if len(planes) > max_planes:
            raise ValueError('Too many grid planes (%s); split the job spatially' % len(planes))
        bm = bmesh.new()
        result = None
        try:
            bm.from_mesh(source.data)
            # One BMesh, not one object per triangle. Shared edges remain shared.
            # Keep planar polygons intact, so square cells stay quadrilateral.
            # Only nonplanar polygons need triangulation before clipping.
            bm.normal_update()
            nonplanar = [f for f in bm.faces if len(f.verts) > 3 and
                         any(abs((v.co-f.verts[0].co).dot(f.normal)) > eps
                             for v in f.verts)]
            if nonplanar:
                bmesh.ops.triangulate(bm, faces=nonplanar)
            original_area = sum(f.calc_area() for f in bm.faces)
            for axis, value in planes:
                point = [0., 0., 0.]; point[axis] = value
                normal = [0., 0., 0.]; normal[axis] = 1.
                res = bmesh.ops.bisect_plane(
                    bm, geom=list(bm.verts)+list(bm.edges)+list(bm.faces),
                    dist=eps, plane_co=Vector(point), plane_no=Vector(normal),
                    use_snap_center=False, clear_outer=False, clear_inner=False)
                for elem in res.get('geom_cut', []):
                    if isinstance(elem, bmesh.types.BMEdge):
                        elem.seam = True
                if len(bm.faces) > max_faces:
                    raise ValueError('Face budget exceeded; source and prepared copy preserved')
            bm.normal_update()
            after_area = sum(f.calc_area() for f in bm.faces)
            if original_area > 0 and abs(after_area-original_area)/original_area > 1e-4:
                raise ValueError('Cut area check failed')
            result = source.copy()
            result.data = source.data.copy()
            result.name = source.name+'_CUT'
            bm.to_mesh(result.data)
            context.collection.objects.link(result)
            stats = write_uv(result.data, scale, density, resolution, origin)
            stats.update(grid_planes=len(planes),
                         area_before_m2=original_area*scale*scale,
                         area_after_m2=after_area*scale*scale)
            report = add_report(result, stats, density, resolution, scale, origin, cut=True)
        except Exception:
            if result:
                mesh = result.data
                bpy.data.objects.remove(result, do_unlink=True)
                bpy.data.meshes.remove(mesh)
            raise
        finally:
            bm.free()
        activate(context, result)
        discard_object(source)
        return result, report

    def stack_tiles(obj):
        """Translate each cut cell into 1001 without changing its texel density."""
        if not obj.get('vpm_cut'):
            raise ValueError('Cut the shared grid before stacking tiles')
        mesh = obj.data
        grid = mesh.uv_layers.get(UV_NAME)
        if grid is None:
            raise ValueError('VPM_GRID UV layer is missing')
        values = [0.0] * (2 * len(mesh.loops))
        epsilon = 1e-5
        for face in mesh.polygons:
            loops = list(face.loop_indices)
            coordinates = [grid.data[i].uv.copy() for i in loops]
            offset = [math.floor(sum(co[a] for co in coordinates)/len(coordinates))
                      for a in range(2)]
            for i, co in zip(loops, coordinates):
                local = [co[a]-offset[a] for a in range(2)]
                if any(v < -epsilon or v > 1+epsilon for v in local):
                    raise ValueError('A polygon crosses a tile boundary; cut it first')
                values[2*i:2*i+2] = [max(0.0, min(1.0, v)) for v in local]
        tiled = mesh.uv_layers.get('VPM_TILE_1001') or mesh.uv_layers.new(name='VPM_TILE_1001')
        tiled.data.foreach_set('uv', values)
        mesh.uv_layers.active = tiled
        tiled.active_render = True
        mesh.update()
        obj['vpm_stacked_1001'] = True
        return tiled

    class VPM_OT_stack(bpy.types.Operator):
        bl_idname = 'vpm.stack_1001'
        bl_label = 'Сложить квадраты в 1001'
        bl_options = {'REGISTER', 'UNDO'}

        @classmethod
        def poll(cls, context):
            return (context.mode == 'OBJECT' and context.active_object and
                    context.active_object.type == 'MESH' and context.active_object.get('vpm_cut'))

        def execute(self, context):
            try:
                stack_tiles(context.active_object)
            except Exception as exc:
                self.report({'ERROR'}, str(exc))
                return {'CANCELLED'}
            self.report({'INFO'}, 'UV сложена в 1001; плотность сохранена')
            return {'FINISHED'}

    class VPM_OT_prepare(bpy.types.Operator):
        bl_idname = 'vpm.prepare_uv'
        bl_label = 'Подготовить UV'
        bl_options = {'REGISTER', 'UNDO'}

        @classmethod
        def poll(cls, context):
            return context.mode == 'OBJECT' and context.active_object and context.active_object.type == 'MESH'

        def execute(self, context):
            scene = context.scene
            try:
                result, stats = prepare_object(context, context.active_object, scene.vpm_density,
                                                scene.vpm_resolution, scene.vpm_origin)
            except Exception as exc:
                self.report({'ERROR'}, str(exc))
                return {'CANCELLED'}
            self.report({'INFO'}, 'UV готова: %s; наклонных граней: %s' % (result.name, stats['sloped_faces']))
            return {'FINISHED'}

    class VPM_OT_cut(bpy.types.Operator):
        bl_idname = 'vpm.cut_grid'
        bl_label = 'Нарезать общую сетку XYZ'
        bl_options = {'REGISTER', 'UNDO'}

        @classmethod
        def poll(cls, context):
            return (context.mode == 'OBJECT' and context.active_object and
                    context.active_object.type == 'MESH' and context.active_object.get('vpm_prepared')
                    and not context.active_object.get('vpm_cut'))

        def execute(self, context):
            try:
                result, stats = cut_object(context, context.active_object)
            except Exception as exc:
                self.report({'ERROR'}, str(exc))
                return {'CANCELLED'}
            self.report({'INFO'}, 'Нарезано: %s; граней: %s' % (result.name, stats['faces']))
            return {'FINISHED'}

    class VPM_OT_cut_weld_main009(bpy.types.Operator):
        bl_idname = 'vpm.cut_weld_main009'
        bl_label = 'Нарезать .009 и сварить с Main'
        bl_description = 'Полный шаг сетки Main по XYZ; сохранить UV Main и сварить стык'
        bl_options = {'REGISTER', 'UNDO'}

        @classmethod
        def poll(cls, context):
            main = context.scene.objects.get('Main')
            part = context.scene.objects.get('VPM.009')
            return (context.mode == 'OBJECT' and main and part and
                    main.type == 'MESH' and part.type == 'MESH' and
                    not main.get('vpm_main009_merged'))

        def execute(self, context):
            from pathlib import Path
            import importlib.util
            path = Path(__file__).resolve().parent / 'vpm_cut_weld_main009.py'
            if not path.is_file():
                self.report({'ERROR'}, 'Рядом с аддоном отсутствует vpm_cut_weld_main009.py')
                return {'CANCELLED'}
            try:
                spec = importlib.util.spec_from_file_location('vpm_cut_weld_helper', path)
                helper = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(helper)
                report = helper.run(write_report=False)
            except Exception as exc:
                self.report({'ERROR'}, str(exc))
                return {'CANCELLED'}
            self.report({'INFO'}, 'Сварено вершин: %s; общих рёбер: %s' %
                        (report['welded_vertices'], report['shared_edges']))
            return {'FINISHED'}

    class VPM_PT_panel(bpy.types.Panel):
        bl_label = 'VPM Auto UV'
        bl_idname = 'VPM_PT_auto_uv'
        bl_space_type = 'VIEW_3D'
        bl_region_type = 'UI'
        bl_category = 'VPM'

        def draw(self, context):
            layout = self.layout
            layout.prop(context.scene, 'vpm_density')
            layout.prop(context.scene, 'vpm_resolution')
            layout.prop(context.scene, 'vpm_origin')
            layout.label(text='Шаг: %.3f м' % (context.scene.vpm_resolution/context.scene.vpm_density))
            layout.operator('vpm.prepare_uv')
            layout.operator('vpm.cut_grid')
            layout.operator('vpm.stack_1001')
            layout.separator()
            layout.operator('vpm.cut_weld_main009')
            layout.label(text='Полный шаг ячейки; общие вершины стыка')
            layout.label(text='Наклоны: сжатие UV, отчёт в Text Editor')
            layout.label(text='После успеха исходник заменяется результатом')

    classes = (VPM_OT_prepare, VPM_OT_cut, VPM_OT_stack, VPM_OT_cut_weld_main009, VPM_PT_panel)

    def register():
        for cls in classes:
            bpy.utils.register_class(cls)
        bpy.types.Scene.vpm_density = FloatProperty(name='Тексель, px/м', default=1000, min=600, max=1500)
        bpy.types.Scene.vpm_resolution = IntProperty(name='Текстура, px', default=2048, min=256, max=16384)
        bpy.types.Scene.vpm_origin = FloatVectorProperty(name='Начало сетки, м', size=3, default=(0, 0, 0))

    def unregister():
        for name in ('vpm_density', 'vpm_resolution', 'vpm_origin'):
            delattr(bpy.types.Scene, name)
        for cls in reversed(classes):
            bpy.utils.unregister_class(cls)

    if __name__ == '__main__':
        # Allow re-running a Text Editor prototype without duplicate class errors.
        for cls in reversed(classes):
            base = bpy.types.Panel if issubclass(cls, bpy.types.Panel) else bpy.types.Operator
            old = base.bl_rna_get_subclass_py(cls.__name__)
            if old:
                bpy.utils.unregister_class(old)
        register()
