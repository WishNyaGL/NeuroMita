# Initiative Engine

Отдельная подсистема NeuroMita, которая даёт персонажу **самостоятельное поведение**: наблюдение за окружением, формирование намерений и принятие решений о том, когда заговорить, действовать или промолчать. Движок минимально вмешивается в существующий код NeuroMita и использует его инфраструктуру: `ChatAPI`, `ToolManager`, `Memory/RAG`, `MCP`.

> **Статус:** этапы 0–7 реализованы. Движок отлажен и собран; рекомендуется проверить поведение на устройстве перед дальнейшим развитием.

---

## Оглавление

- [Что умеет сейчас](#что-умеет-сейчас)
- [Архитектура](#архитектура)
- [Поток данных](#поток-данных)
- [Конфигурация](#конфигурация)
- [Защита от зацикливания](#защита-от-зацикливания)
- [Мониторинг](#мониторинг)
- [MCP-инструменты](#mcp-инструменты)
- [Известные ограничения](#известные-ограничения)
- [Отложенные возможности](#отложенные-возможности)

---

## Что умеет сейчас

Цикл: **наблюдение → понимание → мотив → решение → действие → обратная связь** — детерминированные эвристики (без LLM на этапе решения; текст реплик формирует модель).

**Наблюдение (Observation)** — `observation/`
- Подписка на EventBus: `SEND_MESSAGE`, `ON_STARTED_RESPONSE_GENERATION`, `ON_SUCCESSFUL_RESPONSE`, `UPDATE_CHAT_UI`, `ON_TOOL_DONE`.
- Нормализация источника `EventSource` (`player/system/initiative/tool/external/unknown`) — только по метаданным, никогда по тексту.
- Дедупликация/фильтрация шума (`EventProcessor`), опрос активного окна через MCP.

**Восприятие (Perception)** — `perception/`
- Обогащение событий (source/significance), выделение `topic`, `open_loops`, сводка, `confidence`.
- Передача контекста: последнее сообщение пользователя, последняя реплика персонажа, системные события, история неотвеченных вопросов.

**Мотивация (Motivation)** — `motivation/`
- Мотивы: `react_to_event`, `return_to_unfinished_topic`, `ask_followup`, `comment_on_environment`, `want_to_interact`, `share_thought`, `respond_to_own_question` (вопрос без ответа), `continue_topic` (follow-up).
- Учитывает внутреннее состояние (boredom/stress/curiosity), открытые вопросы, неотвеченные вопросы с накоплением попыток.

**Решение (Decision)** — `decision/`
- Явный маппинг «мотив → действие» (`ACTION_BY_TYPE`), стабильный выбор верхнего мотива, лимит инициатив/минуту (`defer`).
- `initiate_dialogue` / `act` / `silence` / `defer`.

**Взаимодействие с пользователем (Interaction)** — `interaction/`
- `UserInteractionState`: сигналы goodbye/sleep/busy/do_not_disturb/away/return + состояние `absent` (нет активности > 5 мин). Сигнал НЕ «залипает» — относится только к текущему сообщению.
- `InitiativeGate`: блокирует инициативу при `absent`/занятости/недопустимых сигналах; `ReactionPolicy` — характер-зависимая реакция (уважить/переопределить).
- Комментарий об отсутствии пользователя — один раз на серию, зависит от характера/настроения.

**Внутреннее состояние (Internal State)** — `internal_state/`
- Читает реальные `attitude`/`boredom`/`stress` (`character.get_stats_dict()`), нормализует в [0,1], добавляет `curiosity`.

**Намерения (Intentions)** — `intentions/`
- RAM + SQLite; условия (`evaluate_conditions`), `mark_ready`, `promote_by_relevance`, дедупликация по (character, type), вовлечение готовых намерений в мотивы.

**Обратная связь (Feedback)** — `feedback.py`
- Разделяет `delivery` (доставлено) и `goal` (цель достигнута); молчание пользователя — не ошибка.

**Действия (Actions)** — `actions/`
- `ChatAPI.initiate()`, инструменты через `ToolManager`/MCP с `PermissionPolicy`, уважение `character_generation_lock`.

---

## Архитектура

```
src/initiative_engine/
├── README.md
├── __init__.py
├── config.py              # InitiativeConfig (dataclass)
├── engine.py              # InitiativeEngine — координатор
├── feedback.py            # FeedbackSystem
├── scheduler/             # гибридный планировщик (период + события, динамический интервал)
├── perception/            # PerceptionEngine
├── motivation/            # MotivationSystem
├── decision/              # DecisionEngine + DecisionContext
├── intentions/            # IntentionManager (RAM + SQLite)
├── interaction/           # UserInteractionState + InitiativeGate + ReactionPolicy
├── internal_state/        # InternalStateAdapter
├── actions/               # InitiativeActionManager + PermissionPolicy
└── observation/           # ObservationManager + EventProcessor + source
```

Этапы (все ✅):
| Этап | Содержание |
|---|---|
| 0 | Аудит взаимодействия со штатным диалогом |
| 1 | Разделение источников/циклов (`EventSource`) |
| 2 | Perception: topic/open_loops/significance |
| 3 | UserInteractionState + InitiativeGate |
| 4 | InternalStateAdapter (attitude/boredom/stress/curiosity) |
| 5 | Motivation + Decision (явный маппинг) |
| 6 | IntentionManager (условия/релевантность/возврат) |
| 7 | Action/Feedback + характер-зависимая реакция |

---

## Поток данных

```
EventBus/MCP ──► ObservationManager ──► EventProcessor (dedup/filter)
                                         │
                                         ▼
                                     InitiativeEngine._on_observation
                                         │  (send_message → контекст/активность;
                                         │   update_chat_ui → последняя реплика персонажа;
                                         │   on_successful_response → активность/корреляция)
                                         ▼
               ┌───────────────  тик планировщика  ───────────────┐
               ▼                                                 ▼
         UserInteractionState.update()                   filter_events
         (absent/signal/activity)                            │
               │                                             │
               ▼                                             │
         PerceptionEngine.perceive() ◄── контекст (user/assistant/system/вопросы)
               │                                             │
               ▼                                             │
         MotivationSystem.evaluate() ◄── internal_state + unanswered_questions
               │                                             │
               ▼                                             │
         DecisionContext ◄── мотивы + autonomy + can_initiate │
               │                                             │
               ▼                                             │
         DecisionEngine.decide() ──► silence/defer/initiate/act ◄─┘
               │
               ├──► initiate_dialogue ► Instruction (роли, контекст, попытки)
               │          ► ChatAPI.initiate() ► Feedback ► намерения
               └──► act ► ToolManager ► Feedback ► намерения
```

---

## Конфигурация

Поля `InitiativeConfig` (полный список — в `config.py`):

| Поле | По умолчанию | Описание |
|---|---|---|
| `enabled` | `False` | Движок выключен по умолчанию |
| `scheduler_interval_sec` | `60.0` | Минимальный интервал тика (сек) |
| `autonomy_level` | `"off"` | `off` / `subtle` / `full` |
| `max_actions_per_minute` | `1` | Лимит инициатив в минуту |
| `min_motive_priority` | `2` | Мин. приоритет мотива для намерения |
| `filter_events` | `True` | Фильтрация шума |
| `respect_busy_character` | `True` | Не стартовать при активной генерации |
| `enable_logging` | `False` | Логирование цикла |
| `allow_initiate_dialogue` | `True` | Разрешить `ChatAPI.initiate()` |
| `observe_dialogue` / `observe_windows` | `True` | Источники наблюдений |
| `use_vision` | `False` | Vision (заготовка) |
| `enabled_characters` | `[]` | Белый список персонажей (пусто = все) |

---

## Защита от зацикливания

- **Лимит инициатив** в минуту (`defer`).
- **Фильтр шума**: `send_message`, `on_successful_response` и технические события — не триггеры.
- **Коoldown по ключу инициативы** (`char|action|reason`; для `respond_to_own_question` ключ включает попытки, чтобы не гасить накопление).
- **`absent`** — персонаж молчит, если пользователь неактивен > 5 мин.
- **`respect_busy_character` + `character_generation_lock`** — нет конкурирующих генераций.
- **Ответ персонажа не триггер** — корреляция инициатив через `_in_flight_initiative`.
- **Сигналы не залипают** — прощание/отошёл относится только к текущему сообщению.
- **Повторная реакция на одно сообщение** — `_last_initiative_user_key` блокирует реактивные мотивы (`react_to_event`, `continue_topic`); `respond_to_own_question` накапливает попытки.

---

## Мониторинг

Окно `initiative_monitor_dialog.py` (запуск из Песочницы):
- статус/конфиг; тики/события; решения; действия; намерения.
- анализ (персонаж/уверенность/тема/открытые вопросы/сводка);
- пользователь (активность/сигнал/отсутствие), характер (traits), внутреннее состояние;
- инициативы в полёте; текст можно выделять и копировать; скролл сохраняется при обновлении.
- память: показывает до 3 блоков (острова/активная память) вместо одного склеенного.

---

## MCP-инструменты

Сервер `scripts/mcp_system_interaction_server.py` (копируется в корень билда отдельно от `.pyz`):

- `change_wallpaper` — установка обоев по пути/поиску/случайно; сохранение в `Pictures/NeuroMita/Wallpapers`.
- `set_wallpaper_from_reactor` — поиск обоев на anime.reactor.cc (query/tags/user), случайная страница/изображение, full-оригинал, скачивание, приоритизация по имени файла, установка. Возвращает JSON.
- `fake_system_hang` / `fake_crash` — безопасные пугалки (скриншот, скрытый курсор, звук уведомления `Windows Background.wav`, затем BSOD).
- `take_screenshot`, `get_active_window`, `show_notification`, `draw_overlay`, `draw_path`, `open_app`, `notepad_write`, `play_sound`, `lock_screen`, `close_process`, `fake_bsod` и др.

> **Сборка:** при изменении сервера обязательно пересобрать билд (`python build.py`) — сервер копируется отдельно от `.pyz`.

Debug-скрипты:
- `scripts/debug_reactor.py` — поиск/скачивание обоев (флаг `--apply` — установка).
- `scripts/debug_crash.py` — запуск пугалки без модели.

---

## Известные ограничения

- **Решение эвристическое, без LLM** — «творческая» оценка мотивов не используется.
- **Unity-доставка инициативы не реализована** — сообщения идут в десктоп-чат.
- **Восприятие базовое** — личность из первой строки промпта, память одним блоком; нет глубокого семантического анализа.
- **Vision (`use_vision`) выключен** — не подключён к реальному скриншоту.
- **Точная формулировка реплик** (например «что молчишь?») остаётся за моделью; движок даёт мотив/контекст.

---

## Отложенные возможности

Interest Profile, Shared Experience, Context Providers, Autonomous Activities, Vision, LLM-провайдеры для Perception/Motivation/Decision, Advanced Action Planning, Unity Delivery Bridge.