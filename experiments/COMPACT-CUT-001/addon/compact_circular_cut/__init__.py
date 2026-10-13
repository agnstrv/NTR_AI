bl_info = {
    'name': 'Compact Circular Cut',
    'author': 'NPM Tools',
    'version': (1, 1, 1),
    'blender': (5, 0, 0),
    'location': 'View3D > Sidebar > NPM; Object menu; F3',
    'description': 'Cylinder subtraction with short paired spokes on curved surfaces',
    'category': 'Mesh',
}

import bpy
import importlib
from bpy.props import BoolProperty, FloatProperty, PointerProperty
from . import core

# Blender can reload __init__ after a ZIP update while keeping a cached core.
# Reload the backend as well so the displayed version and executed code agree.
core = importlib.reload(core)
MESH_OT_compact_circular_cut = core.MESH_OT_compact_circular_cut


class NPM_PG_compact_cut(bpy.types.PropertyGroup):
    transition_ratio: FloatProperty(
        name='Ширина перехода', description='Длина коротких рёбер относительно радиуса резака',
        default=.16, min=.02, max=.8, precision=3)
    hide_cutter: BoolProperty(name='Скрыть резак после выреза', default=True)


class VIEW3D_PT_compact_circular_cut(bpy.types.Panel):
    bl_label = 'Compact Circular Cut'
    bl_idname = 'VIEW3D_PT_compact_circular_cut'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'NPM'

    def draw(self, context):
        layout = self.layout
        settings = context.scene.npm_compact_cut
        layout.label(text='Версия 1.1.1 — сохранение исходных рёбер')
        layout.label(text='Сначала резак, затем объект выреза.')
        layout.label(text='С сохранением исходной поверхности.')
        selected = [obj for obj in context.selected_objects if obj.type == 'MESH']
        target = context.active_object
        valid = context.mode == 'OBJECT' and len(selected) == 2 and target in selected
        if valid:
            cutter = next(obj for obj in selected if obj != target)
            layout.label(text='Объект: ' + target.name, icon='MESH_DATA')
            layout.label(text='Резак: ' + cutter.name, icon='MESH_CYLINDER')
        else:
            layout.label(text='Выделите два меша в Object Mode.', icon='INFO')
        layout.prop(settings, 'transition_ratio')
        layout.prop(settings, 'hide_cutter')
        row = layout.row()
        row.enabled = valid
        op = row.operator('mesh.compact_circular_cut', text='Сделать вырез', icon='MOD_BOOLEAN')
        op.transition_ratio = settings.transition_ratio
        op.hide_cutter = settings.hide_cutter


def _object_menu(self, context):
    settings = context.scene.npm_compact_cut
    op = self.layout.operator('mesh.compact_circular_cut', icon='MOD_BOOLEAN')
    op.transition_ratio = settings.transition_ratio
    op.hide_cutter = settings.hide_cutter


_classes = (NPM_PG_compact_cut, MESH_OT_compact_circular_cut, VIEW3D_PT_compact_circular_cut)


def register():
    registered = []
    try:
        stale = getattr(bpy.types, 'MESH_OT_compact_circular_cut', None)
        if stale is not None and stale is not MESH_OT_compact_circular_cut:
            if stale.__module__ == core.__name__:
                bpy.utils.unregister_class(stale)
        for cls in _classes:
            bpy.utils.register_class(cls)
            registered.append(cls)
        bpy.types.Scene.npm_compact_cut = PointerProperty(type=NPM_PG_compact_cut)
        bpy.types.VIEW3D_MT_object.append(_object_menu)
    except Exception:
        if hasattr(bpy.types.Scene, 'npm_compact_cut'):
            del bpy.types.Scene.npm_compact_cut
        for cls in reversed(registered):
            bpy.utils.unregister_class(cls)
        raise


def unregister():
    bpy.types.VIEW3D_MT_object.remove(_object_menu)
    if hasattr(bpy.types.Scene, 'npm_compact_cut'):
        del bpy.types.Scene.npm_compact_cut
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
