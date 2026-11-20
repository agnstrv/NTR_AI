# Промпт сводки работ Артёма Нагорнова

Скопируйте текст ниже в Codex. Ссылки комплектов относятся к опубликованной рабочей ветке, не означают слияние в main или приёмку инструментов. Библиотека растений требует приглашения GitHub.

---

Подготовь по-русски сводку по пяти работам Артёма Нагорнова (nagornov-artem). Для каждой укажи назначение, версию, подтверждённый статус, ограничения, краткий запуск и кликабельные ссылки на скачивание и инструкцию. Используй ссылки ниже; не заменяй их локальными путями с компьютера автора. При недоступности GitHub прямо сообщи об этом, не выдумывай содержимое или результаты проверки.

## 1 Коллизия здания

НЕ ЗАВЕРШЕНА. Сохранён подход и промпт для построения коллизии на новом проекте. Это workflow с участием агента; опубликованный CLI не является полным автоматическим генератором. Не выдавай ZIP аддона вместо этого сценария. Не запускай моделирование при запросе сводки.

- [Инструкция workflow](https://github.com/agnstrv/NTR_AI/blob/efdf377de681400823a0d024747f40c7d2070b9c/tools/collisions/building-ucx/workflow.md)
- [Скачать инструкцию](https://raw.githubusercontent.com/agnstrv/NTR_AI/efdf377de681400823a0d024747f40c7d2070b9c/tools/collisions/building-ucx/workflow.md)
- [README и материалы инструмента](https://github.com/agnstrv/NTR_AI/tree/efdf377de681400823a0d024747f40c7d2070b9c/tools/collisions/building-ucx)

## 2 Compact Circular Cut 1.1.1

Аддон для круглого выреза на выпуклой поверхности. Опубликован 13.10.2026; prototype, общая приёмка командой не подтверждена. Object Mode: цилиндр выделяется первым, поверхность последней и становится активной; N → NPM → «Сделать вырез». Резак сохраняется и по умолчанию скрывается; отмена Ctrl+Z. Работать на копии.

- [Скачать ZIP](https://raw.githubusercontent.com/agnstrv/NTR_AI/a507d2ddd77869388ee0761c1d22ca02bdc7bfb7/tools/geometry/compact-circular-cut/dist/compact_circular_cut_v1.1.1.zip)
- [Инструкция](https://github.com/agnstrv/NTR_AI/blob/a507d2ddd77869388ee0761c1d22ca02bdc7bfb7/tools/geometry/compact-circular-cut/README.md)
- [Скачать инструкцию](https://raw.githubusercontent.com/agnstrv/NTR_AI/a507d2ddd77869388ee0761c1d22ca02bdc7bfb7/tools/geometry/compact-circular-cut/README.md)

## 3 UV Texel Equalizer 1.2.2

Выравнивает плотность UV-островов активного меша, отдельно проверяет зеркальность и направление. Допуск плотности 0.00002 = 0,002%, это не значение целевого текселя. Панель UV Editor → N → Texel. По передаче автора пройден 51 тест; публикация не является повторным запуском тестов или приёмкой на проекте коллеги. Инструкция есть также внутри ZIP. Unwrap и упаковка не выполняются; подробные ограничения и происхождение адаптированных принципов — в инструкции.

- [Скачать ZIP](https://raw.githubusercontent.com/agnstrv/NTR_AI/refs/heads/work/nagornov-artem/repository/draft-download-summary/tools/uv/uv-texel-equalizer/dist/uv-texel-equalizer-v1-2-2.zip)
- [Инструкция](https://github.com/agnstrv/NTR_AI/blob/work/nagornov-artem/repository/draft-download-summary/tools/uv/uv-texel-equalizer/docs/guide-1-2-2.md)
- [Скачать инструкцию](https://raw.githubusercontent.com/agnstrv/NTR_AI/refs/heads/work/nagornov-artem/repository/draft-download-summary/tools/uv/uv-texel-equalizer/docs/guide-1-2-2.md)

## 4 VPM Auto UV 0.2.0

Исходный ZIP передан без изменения кода. Панель N → VPM. По инструкции регистрация, подготовка UV, нарезка и укладка в 1001 проверены в Blender 5.0.0 на синтетическом кубе; это не проверка на рабочем проекте. Остальные самостоятельные скрипты в архив не добавлены. Инструкция отдельная, скачайте оба файла. Специальная кнопка .009 требует точного имени объекта из инструкции, не является универсальной сваркой. Обычная последовательность применяется к активному мешу и заменяет его результатом; сначала сохранить копию .blend.

- [Скачать ZIP](https://raw.githubusercontent.com/agnstrv/NTR_AI/refs/heads/work/nagornov-artem/repository/draft-download-summary/tools/uv/vpm-grid/dist/VPM_Auto_UV_0_2.zip)
- [Инструкция](https://github.com/agnstrv/NTR_AI/blob/work/nagornov-artem/repository/draft-download-summary/tools/uv/vpm-grid/docs/instruction-0-2-0.txt)
- [Скачать инструкцию](https://raw.githubusercontent.com/agnstrv/NTR_AI/refs/heads/work/nagornov-artem/repository/draft-download-summary/tools/uv/vpm-grid/docs/instruction-0-2-0.txt)

Для трёх аддонов установка: Edit → Preferences → Add-ons → Install from Disk → выбрать ZIP без распаковки и включить аддон. Уточнения обновления и ограничения версий Blender брать из соответствующих инструкций.

## 5 Библиотека растений

Закрытый каталог команды. Нужны GitHub-аккаунт с принятым приглашением, Git с Git LFS, Node.js 22+ и Python 3. Для публикации растений нужны права записи. Это приложение и LFS-каталог, не Blender-аддон; не предлагай обычный Download ZIP как полноценную установку с текстурами.

- [Репозиторий библиотеки](https://github.com/agnstrv/plant-texture-library)
- [Инструкция подключения](https://github.com/agnstrv/plant-texture-library/blob/d8631d020dc0d7be568cb3217d096d41fbcf2e00/README.md)
- [Работа с каталогом и публикация](https://github.com/agnstrv/plant-texture-library/blob/d8631d020dc0d7be568cb3217d096d41fbcf2e00/docs/team-library.md)

Подключение:

```bash
git lfs install
git clone https://github.com/agnstrv/plant-texture-library.git
cd plant-texture-library
python -m pip install -r requirements.txt
node server.mjs
```

Альтернативный запуск: start-library.cmd. Каталог http://127.0.0.1:4173/ работает только на компьютере, где запущен сервер. Для Codex: открыть папку библиотеки как проект и попросить открыть этот адрес во встроенном браузере.

Поиск по названию/категории; скачиваются оригинальные Diffuse и Opacity. При добавлении Diffuse должна иметь собственную прозрачность, Opacity — непрозрачные чёрно-белые пиксели без полутонов; отсутствующая Opacity создаётся из альфы. Лимит в опубликованной инструкции — 45 МиБ на карту. Кнопка «Обновить» получает дополнения коллег; без сети доступны загруженные растения, а добавления ждут публикации в локальной очереди.

## Правила ответа

Прочитай доступные инструкции, сохрани различие между сообщением автора и проверкой, которую ты действительно выполнил. Не утверждай, что запускал Blender или тесты. Не повышай статус коллизии без более нового документированного подтверждения. Если найдёшь более новую версию инструмента, покажи её отдельно; запрошенные версии и ссылки сохрани. Не устанавливай и не запускай инструменты при запросе сводки. В конце перечисли только фактически недоступные ссылки или необходимые права доступа.
