# NTR — разработка цифровых двойников с ИИ

Общая база команды НПМ / ВПМ / ППТ / IFC: исследования, инструменты, сценарии и проверенные решения.

## Начать здесь

**[Первый запуск — инструкция для каждого участника](docs/start-here.md)**

| Что нужно сделать | Открыть |
|---|---|
| Понять порядок работы | [Блок-схемы](docs/team-workflow/README.md) |
| Разобраться с GitHub и локальным агентом | [Памятка команды](process/team-quickstart.md) |
| Выгрузить накопленные наработки с ПК | [Промпт №1](prompts/01-collect-local-work.md) |
| Начать задачу, продолжить или проверить чужую | [Промпт №2](prompts/02-start-or-continue.md) |
| Найти существующее решение | [Каталог разработок](tools/README.md) |
| Подключить навыки Matt | [Навыки и проверка подключения](process/agent-skills.md) |
| Опубликовать наработки текущего чата | [`/push` — команда проекта](.agents/skills/push/SKILL.md) |

## Как работаем

**Карточка Trello → своя ветка → исследование и разработка → commit + push → проверка коллегой → PR → main.**

- Автор публикует рабочие и незавершённые результаты.
- Другой участник проверяет решение на своём проекте и принимает его для указанной области.
- Исследования могут храниться в main с явной незавершённостью. Наличие файла в main не означает готовность инструмента.
- Trello хранит задачи и статусы; GitHub — код, правила и историю; Drive — клиентские материалы и результаты.

[Правила команды](process/team-workflow.md) · [Цикл агента](process/agent-harness.md) · [Структура и имена](process/repository-structure.md)

## Разделы

| Раздел | Назначение |
|---|---|
| [tools/](tools/README.md) | Каталог; новые инструменты по операциям, внутри jobs и cases |
| [docs/team-workflow/](docs/team-workflow/README.md) | Блок-схемы трёх рабочих сценариев |
| [process/](process/README.md) | Правила разработки и производственные процессы |
| [prompts/](prompts/README.md) | Два промпта для агентов команды |
| [templates/](templates/README.md) | Шаблоны tool, job, case, review и передачи |
| [standards/](standards/README.md) | Требования с указанием источника и степени подтверждения |
| [resources/](resources/README.md) | Каталог входных материалов и проверяющих инструментов |
| [interviews/](interviews/README.md) | Исходные выводы и потребности команды |
| [tasks/](tasks/README.md) | Личные реестры и указатели |

Общие инструкции агента: [AGENTS.md](AGENTS.md). Claude Code: [CLAUDE.md](CLAUDE.md).

## Существующие разработки

- [НПМ ОКС Ромы — лёгкая и средняя версии](tools/textures/npm-oks/README.md).
- [COMPACT-CUT-001](tools/geometry/compact-circular-cut/README.md) — круговые вырезы, эксперимент.
- [VPM-GRID-001](tools/uv/vpm-grid/README.md) — прототип с опубликованными испытаниями.
- [Реестр интервью Артёма](tasks/artem-safro/README.md).
- [Навигационный пилот NAV-001](tools/infrastructure/navigation-pilot/README.md).

Разработки собраны в tools; [карта переноса и проверки](process/repository-migration.md). Пилот нового порядка на двух ПК ещё предстоит.
