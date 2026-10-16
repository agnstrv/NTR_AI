# Синтетические проверки 1.1.0

Дата: 16.10.2026. Blender 5.0.0 hash `a37564c4df7a`, Windows. Входы создаются тестами в памяти: квадраты, связные/разрезанные плоскости, изогнутый остров; клиентские файлы не открываются, `.blend` не сохраняется. Код проверяется из `src/`, ZIP smoke — прямо из `dist/`.

Из корня repo, для каждого script в `tools/uv/uv-texel-equalizer/tests/`:

```powershell
& 'C:\Program Files\Blender Foundation\Blender 5.0\blender.exe' --background --factory-startup --python-exit-code 1 --python tools/uv/uv-texel-equalizer/tests/test_texel_equalizer.py
& 'C:\Program Files\Blender Foundation\Blender 5.0\blender.exe' --background --factory-startup --python-exit-code 1 --python tools/uv/uv-texel-equalizer/tests/test_texel_orientation.py
& 'C:\Program Files\Blender Foundation\Blender 5.0\blender.exe' --background --factory-startup --python-exit-code 1 --python tools/uv/uv-texel-equalizer/tests/test_zip_install.py
```

Ожидается 15/18 PASS и успешный import/register/unregister 1.1. Фактически получены 15/15 + 18/18 и ZIP smoke PASS, exit code 0. Логи/JSON: `reports/current/`; исходные исторические JSON — `reports/historical/`, они сами по себе не доказывают текущие bytes. Сценарии покрывают world units/transforms, rectangular texture, pin, collapsed UV, shared data, hidden Edit Mode, overlap, float32 guard, orientation ambiguity, reflection и UI operators. Не покрывают реальное стекло пользователя, Blender 4.3/4.4, визуальную оценку или upgrade со старой установленной версии.
