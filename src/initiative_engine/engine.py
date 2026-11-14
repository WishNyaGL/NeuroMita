"""Ядро Initiative Engine.

Координатор системы: управляет жизненным циклом, связывает scheduler, систему
наблюдения и точки входа для событий. На этапе 2 подключено наблюдение за
диалогом (EventBus) и Windows (MCP). Принятие решений добавляется позже.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Dict, List, Optional

from main_logger import logger

from .config import InitiativeConfig
from .scheduler import InitiativeScheduler
from .observation import ObservationManager
from .perception import PerceptionEngine
from .motivation import MotivationSystem
from .decision import DecisionContext, DecisionEngine
from .intentions import IntentionManager
from .actions import InitiativeActionManager
from .feedback import FeedbackSystem
from .interaction import InitiativeGate, TraitsProfile, UserInteractionState
from .internal_state import InternalStateAdapter


class InitiativeEngine:
    def __init__(
        self,
        config: Optional[InitiativeConfig] = None,
        *,
        loop: Optional[Any] = None,
        event_bus: Optional[Any] = None,
        mcp_service: Optional[Any] = None,
        character_registry: Optional[Any] = None,
        intentions_db_path: Optional[str] = None,
        tool_manager: Optional[Any] = None,
        chat_api: Optional[Any] = None,
        activity_service: Optional[Any] = None,
    ) -> None:
        self.config = config or InitiativeConfig()
        self._loop = loop
        self._event_bus = event_bus
        self._mcp_service = mcp_service
        self._character_registry = character_registry
        self._intentions_db_path = intentions_db_path
        self._tool_manager = tool_manager
        self._chat_api = chat_api
        self._activity_service = activity_service
        self._scheduler: Optional[InitiativeScheduler] = None
        self._observation: Optional[ObservationManager] = None
        self._perception: Optional[PerceptionEngine] = None
        self._motivation: Optional[MotivationSystem] = None
        self._decision: Optional[DecisionEngine] = None
        self._intentions: Optional[IntentionManager] = None
        self._actions: Optional[InitiativeActionManager] = None
        self._feedback: Optional[FeedbackSystem] = None
        self._lock = threading.RLock()
        self._running = False
        self._pending_events: List[Dict[str, Any]] = []
        self._last_window_context = ""
        self._last_decision: Optional[Dict[str, Any]] = None
        self._last_perception: Optional[Dict[str, Any]] = None
        self._recent_initiative: Dict[str, float] = {}
        self._last_user_message: Optional[Dict[str, Any]] = None
        self._followed_up_message_key: Optional[str] = None
        self._last_assistant_ts: float = 0.0
        # Последнее сообщение персонажа (текст) — из UPDATE_CHAT_UI. Нужно,
        # чтобы реакция учитывала контекст последней реплики (вопрос, мысль,
        # тема), а не только факт ответа.
        self._last_assistant_message: Optional[Dict[str, Any]] = None
        # Флаг: комментарий об отсутствии пользователя уже отправлен для текущей
        # серии отсутствия (чтобы персонаж комментировал один раз, а не каждый тик).
        self._absent_comment_sent = False
        # История неотвеченных вопросов персонажа. Каждая запись:
        #   {key, text, attempts, first_ts, last_ts}
        # key — ключ вопроса; attempts — сколько раз персонаж уже переспрашивал.
        # Используется, чтобы LLM знал, что персонаж не в первый раз пытается
        # достучаться, и выбирал поведение по характеру/настроению.
        self._unanswered_questions: List[Dict[str, Any]] = []
        # Ключ вопроса персонажа, на который движок уже отреагировал
        # (чтобы не зацикливаться: не переспрашивать один и тот же вопрос).
        self._handled_own_question_key: Optional[str] = None
        # (Защита от повторов — через _allow_initiative cooldown по ключу,
        #  а не по сообщению пользователя: так не блокируются новые события/вопросы.)
        # Ключ последнего сообщения пользователя, на которое движок уже отреагировал
        # инициативой. Защита от ПОВТОРНЫХ ответов на одно и то же сообщение
        # (реактивные мотивы), но НЕ для respond_to_own_question (накопление попыток).
        self._last_initiative_user_key: Optional[str] = None
        # Метка ЛЮБОЙ активности в диалоге (любой send_message). Используется,
        # чтобы состояние «отсутствия» пользователя не зависало, когда источник
        # сообщений отличается от "player" (например, мини-чат/другие эмиттеры).
        self._last_activity_ts: float = 0.0
        # Динамический интервал тика: отслеживаем длительность генерации ответа,
        # чтобы следующий потенциальный запрос отложился после её завершения.
        self._last_response_duration: float = 0.0
        self._generation_start_ts: float = 0.0
        # Инициативы, запущенные самим движком (char_id -> ts). Позволяет
        # коррелировать последующие ответы с собственными инициативами, не
        # полагаясь на sender/event_type и не меняя штатный цикл диалога.
        self._in_flight_initiative: Dict[str, float] = {}
        # Данные для мониторинга (последний цикл оценки).
        self._last_motives: List[Dict[str, Any]] = []
        self._last_events: List[Dict[str, Any]] = []
        self._last_action: Optional[Dict[str, Any]] = None
        # Накопление системных событий (окна/фокус/игра) с описаниями — для
        # контекста модели. Ограниченный буфер (последние ~12 событий).
        self._recent_system_events: List[Dict[str, Any]] = []
        # Числовое внутреннее состояние персонажа (например, {любопытство: ...}).
        # Заполняется на Этапе 4 (Internal State Adapter); мониторинг рендерит при наличии.
        self._internal_state: Dict[str, Any] = {}
        # Этап 3: состояние взаимодействия с пользователем и Initiative Gate.
        self._user_state = UserInteractionState()
        self._gate = InitiativeGate()
        self._last_user_state: Dict[str, Any] = {}
        # Этап 4: связь с реальным внутренним состоянием персонажа.
        self._internal_adapter = InternalStateAdapter()
        # Этап 7: профиль характера персонажа (из личности).
        self._last_traits: Dict[str, float] = {}
        self._stats = {
            "ticks": 0,
            "events_total": 0,
            "events_filtered": 0,
            "decisions": {},
            "actions_executed": 0,
            "intentions_active": 0,
            "intentions_completed": 0,
            "last_decision": None,
            "last_perception": None,
            "started_at": None,
        }

    # ------------------------------------------------------------- lifecycle

    @property
    def running(self) -> bool:
        return self._running

    def start(self) -> None:
        with self._lock:
            if self._running:
                return
            if not self.config.enabled:
                return
            self._running = True
            self._scheduler = InitiativeScheduler(
                interval_sec=self.config.scheduler_interval_sec,
                on_tick=self._on_tick,
                loop=self._loop,
            )
            self._scheduler.start()
            self._init_observation()
            self._perception = PerceptionEngine(self._character_registry)
            self._motivation = MotivationSystem()
            self._decision = DecisionEngine(
                max_initiatives_per_minute=self.config.max_actions_per_minute
            )
            self._intentions = IntentionManager(self._intentions_db_path)
            self._intentions.start()
            self._actions = InitiativeActionManager(
                tool_manager=self._tool_manager,
                chat_api=self._chat_api,
            )
            self._feedback = FeedbackSystem()
            logger.info(
                "[InitiativeEngine] started (autonomy=%s, scheduler=%ss, "
                "observe_dialogue=%s, observe_windows=%s)",
                self.config.autonomy_level,
                self.config.scheduler_interval_sec,
                self.config.observe_dialogue,
                self.config.observe_windows,
            )
            if self._observation is not None:
                logger.info("[InitiativeEngine] monitoring attached (EventBus)")
            if self._intentions is not None:
                logger.info(
                    "[InitiativeEngine] intentions restored (%d active)",
                    len(self._intentions.list_active()),
                )

    def stop(self) -> None:
        with self._lock:
            if not self._running:
                return
            self._running = False
            if self._scheduler is not None:
                self._scheduler.stop()
                self._scheduler = None
            if self._observation is not None:
                self._observation.detach()
                self._observation = None
            if self._intentions is not None:
                try:
                    self._intentions.prune_expired()
                    self._intentions.consolidate()
                    self._intentions.close()
                except Exception:
                    pass
                self._intentions = None
            logger.info("[InitiativeEngine] stopped")

    def apply_config(self, config: Optional[InitiativeConfig] = None) -> None:
        """Применить новую конфигурацию на лету (без перезапуска приложения).

        Пересоздаёт scheduler и decision с новыми параметрами, если движок
        запущен. Остальные параметры читаются из config каждый тик, поэтому
        подхватываются автоматически.
        """
        if config is not None:
            self.config = config
        with self._lock:
            if not self._running:
                return
            # Пересоздаём scheduler с новым интервалом.
            if self._scheduler is not None:
                self._scheduler.stop()
            self._scheduler = InitiativeScheduler(
                interval_sec=self.config.scheduler_interval_sec,
                on_tick=self._on_tick,
                loop=self._loop,
            )
            self._scheduler.start()
            # Обновляем решение с новым лимитом.
            if self._decision is not None:
                self._decision = DecisionEngine(
                    max_initiatives_per_minute=self.config.max_actions_per_minute
                )
            logger.info(
                "[InitiativeEngine] config applied (scheduler=%ss, max_actions=%d)",
                self.config.scheduler_interval_sec,
                self.config.max_actions_per_minute,
            )

    # --------------------------------------------------------------- events

    def receive_event(self, name: str, data: Optional[Dict[str, Any]] = None) -> None:
        """Внешний вход события (если наблюдение отключено)."""
        if not self._running:
            return
        with self._lock:
            self._pending_events.append({"type": name, "data": data or {}})
        if self._scheduler is not None:
            self._scheduler.trigger_async()

    # ------------------------------------------------------------ observation

    def _init_observation(self) -> None:
        if self._observation is not None:
            return
        self._observation = ObservationManager(
            event_bus=self._event_bus,
            mcp_service=self._mcp_service,
        )
        self._observation.set_hook(self._on_observation)
        self._observation.attach()

    def _on_observation(self, event: Dict[str, Any]) -> None:
        """Обработанное событие из системы наблюдения."""
        etype = str(event.get("type") or "")
        # Ответы ассистента/персонажа никогда не должны становиться триггером
        # инициативы — фиксируем только время последней активности персонажа.
        if etype == "on_started_response_generation":
            # Засекаем начало генерации — для расчёта длительности ответа.
            self._generation_start_ts = time.time()
            return
        if etype == "on_successful_response":
            self._last_assistant_ts = time.time()
            # Длительность последней генерации ответа.
            if self._generation_start_ts > 0:
                self._last_response_duration = time.time() - self._generation_start_ts
                self._generation_start_ts = 0.0
            # Корреляция: если для активного персонажа была запущена собственная
            # инициатива — её ответ получен. Снимаем маркер «в полёте» и считаем
            # завершённый цикл инициативы (для мониторинга).
            char_id = self._active_character_id()
            if char_id and char_id in self._in_flight_initiative:
                self._stats.setdefault("initiative_responses", 0)
                self._stats["initiative_responses"] += 1
                del self._in_flight_initiative[char_id]
            return
        # Текст последнего сообщения персонажа — из UPDATE_CHAT_UI (role=assistant).
        # Сохраняем его, чтобы реакция могла учитывать контекст последней реплики
        # (например, что персонаж задал вопрос).
        if etype == "update_chat_ui":
            data = event.get("data") or {}
            if str(data.get("role") or "") == "assistant":
                text = str(data.get("response") or "").strip()
                if text:
                    self._last_assistant_message = {
                        "text": text,
                        "ts": time.time(),
                        "character_id": str(data.get("character_id") or ""),
                    }
                    # Если персонаж задал вопрос — фиксируем попытку достучаться.
                    self._record_unanswered_question()
            return
        # Сообщения игрока: обычный конвейер отвечает сразу, поэтому в очередь
        # мы их НЕ ставим (чтобы не дублировать реплики). Вместо этого запоминаем
        # как контекст — движок сможет продолжить тему, если игрок замолчит.
        # Системные события (окна/фокус) — накапливаем с описаниями для контекста.
        if etype == "windows.active_window":
            data = event.get("data") or {}
            summary = str(data.get("summary") or "").strip()
            if summary:
                self._recent_system_events.append(
                    {
                        "kind": "window",
                        "description": summary[:120],
                        "ts": time.time(),
                    }
                )
                if len(self._recent_system_events) > 12:
                    self._recent_system_events.pop(0)
        if etype == "send_message":
            data = event.get("data") or {}
            source = str(event.get("source") or "unknown")
            # Любое сообщение в диалоге — признак активности (чтобы absent не
            # зависал, даже если источник не "player"). Контекст для follow-up
            # остаётся только для player.
            self._last_activity_ts = max(self._last_activity_ts, time.time())
            text = str(data.get("user_input") or data.get("text") or "").strip()
            # Только достоверное ПОЛЬЗОВАТЕЛЬСКОЕ сообщение становится контекстом
            # пользователя. Системный/неизвестный источник — это контекст, но НЕ
            # пользовательская активность: он не должен влиять на follow-up
            # (продолжение темы).
            if text and source == "player":
                self._last_user_message = {
                    "key": f"{time.time()}:{text[:60]}",
                    "text": text,
                    "ts": time.time(),
                    "source": source,
                }
                # Пользователь отреагировал → завершаем «исполняемые» намерения
                # (цель достигнута, а не только доставлена) и сбрасываем историю
                # неотвеченных вопросов (пользователь ответил).
                self._complete_executing_intentions()
                self._clear_unanswered_questions()
            return
        with self._lock:
            self._pending_events.append(event)
        if self._scheduler is not None:
            self._scheduler.trigger_async()

    # ------------------------------------------------------------ internals

    def _on_tick(self) -> None:
        """Периодическая оценка: наблюдение + восприятие (заглушка решения)."""
        if not self._running:
            return
        self._stats["ticks"] += 1
        if self.config.observe_windows and self._observation is not None:
            try:
                self._observation.poll_windows()
                self._last_window_context = self._last_window_context
            except Exception:
                pass
        with self._lock:
            pending = self._pending_events
            self._pending_events = []
        self._stats["events_total"] += len(pending)
        if self.config.filter_events and pending:
            filtered = [e for e in pending if not self._is_noise_event(e)]
            self._stats["events_filtered"] += len(pending) - len(filtered)
            pending = filtered
        # Анализ цикла для мониторинга: события, дошедшие до оценки.
        self._last_events = list(pending)
        # Этап 3: оценка доступности пользователя для инициативы.
        self._last_user_state = self._user_state.update(
            last_user_message=self._last_user_message,
            activity_ts=self._last_activity_ts or None,
        )
        # Корреляция инициатив: снимаем устаревшие маркеры «в полёте».
        _inflight_cutoff = time.time() - 120.0
        self._in_flight_initiative = {
            c: t for c, t in self._in_flight_initiative.items() if t >= _inflight_cutoff
        }
        char_id = self._active_character_id()
        # Если персонаж занят генерацией — не принимать инициативных решений.
        # Тик пропускается, а интервал не сокращается (минимальный остаётся).
        if self.config.respect_busy_character and self._is_character_busy(char_id):
            if self.config.enable_logging:
                logger.info("[InitiativeEngine] tick skipped: character busy (%s)", char_id)
            self._reschedule_interval(self.config.scheduler_interval_sec)
            return
        # Динамический интервал: если пользователь отсутствует — очень редко.
        if self._last_user_state.get("absent"):
            self._reschedule_interval(self.config.scheduler_interval_sec * 4.0)
            # Комментарий персонажа об отсутствии — ТОЛЬКО один раз за серию
            # отсутствия (флаг сбрасывается при возобновлении разговора).
            if not self._absent_comment_sent:
                self._absent_comment_sent = True
                self._execute_absent_comment(char_id)
            if self.config.enable_logging:
                logger.info("[InitiativeEngine] tick skipped: user absent")
            return
        # Пользователь вернулся/активен — сбрасываем флаг комментария об отсутствии.
        self._absent_comment_sent = False
        # Формируем понимание ситуации и принимаем решение.
        if self._perception is not None and self._decision is not None:
            try:
                perception = self._perception.perceive(
                    character_id=char_id,
                    events=pending,
                    window_context=self._last_window_context or None,
                    extra_context={
                        "last_user_message": self._last_user_message,
                        "last_assistant_message": self._last_assistant_message,
                        "system_events": self._recent_system_events,
                        "unanswered_questions": list(self._unanswered_questions),
                    },
                )
                self._last_perception = perception
                # Этап 4: внутреннее состояние персонажа (реальные переменные).
                char_obj = self._character_for(char_id)
                self._internal_state = self._internal_adapter.evaluate(char_obj, perception)
                perception["internal_state"] = dict(self._internal_state)
                # Этап 7: профиль характера из личности персонажа.
                self._last_traits = TraitsProfile.from_personality(
                    perception.get("personality") or ""
                )
                # Этап 6: актуализация намерений по контексту.
                if self._intentions is not None:
                    ctx_text = " ".join(
                        [
                            str(perception.get("working_state") or ""),
                            " ".join(perception.get("open_loops") or []),
                        ]
                    ).strip()
                    if ctx_text:
                        self._intentions.promote_by_relevance(
                            self._keywords_from_text(ctx_text)
                        )
                        self._intentions.mark_ready(
                            character_id=str(perception.get("character_id") or ""),
                            context=ctx_text,
                        )
                motives = self._motivation.evaluate(perception) if self._motivation else []
                # Защита от петли: не переспрашиваем вопрос, на который уже
                # отреагировали (ключ вопроса неизменен).
                if self._handled_own_question_key is not None:
                    motives = [
                        m for m in motives
                        if m.get("type") != "respond_to_own_question"
                        or self._assistant_question_key() != self._handled_own_question_key
                    ]
                followup = self._idle_followup_motive(char_id)
                if followup:
                    motives.append(followup)
                # Этап 6: вовлечение готовых намерений в мотивы.
                if self._intentions is not None:
                    existing_types = {m.get("type") for m in motives}
                    for itn in self._intentions.list_active(char_id):
                        if (
                            itn.status in ("ready", "created")
                            and int(itn.priority) >= 2
                            and itn.type not in existing_types
                        ):
                            motives.append(
                                {
                                    "type": itn.type,
                                    "description": itn.description,
                                    "priority": min(5, int(itn.priority)),
                                    "source": "working_state",
                                }
                            )
                            existing_types.add(itn.type)
                self._last_motives = list(motives)
                ctx = DecisionContext(
                    character_id=str(perception.get("character_id") or ""),
                    perception=perception,
                    motives=motives,
                    can_initiate_dialogue=self.config.allow_initiate_dialogue,
                    actions_available=self.config.autonomy_level in ("subtle", "full"),
                )
                self._last_decision = self._decision.decide(ctx)
                action = str(self._last_decision.get("action") or "")
                self._stats["decisions"].setdefault(action, 0)
                self._stats["decisions"][action] += 1
                self._stats["last_decision"] = {
                    "action": action,
                    "reason": self._last_decision.get("reason"),
                    "char": perception.get("character_id"),
                }
                if self.config.enable_logging:
                    logger.info(
                        "[InitiativeEngine] tick#%d events:%d decision=%s reason=%s char=%s",
                        self._stats["ticks"],
                        len(pending),
                        action,
                        self._last_decision.get("reason"),
                        perception.get("character_id"),
                    )
                if action != "silence":
                    # Защита от ПОВТОРНЫХ ответов на одно и то же сообщение пользователя.
                    # Реактивные мотивы (react_to_event/continue_focus и т.п.) не должны
                    # запускать инициативу снова, пока сообщение не сменилось. Но
                    # respond_to_own_question (накопление попыток) — исключение: он
                    # обязан повторяться, чтобы персонаж «достучался».
                    motive_type = str(
                        (((self._last_decision.get("meta") or {}).get("motive")) or {}).get("type") or ""
                    )
                    user_repeat = (
                        action == "initiate_dialogue"
                        and motive_type != "respond_to_own_question"
                        and self._last_user_message is not None
                        and self._last_initiative_user_key == self._last_user_message["key"]
                    )
                    if user_repeat:
                        self._stats["decisions"].setdefault("suppressed_repeat_user", 0)
                        self._stats["decisions"]["suppressed_repeat_user"] += 1
                        if self.config.enable_logging:
                            logger.info(
                                "[InitiativeEngine] tick#%d suppress repeat-user (%s)",
                                self._stats["ticks"],
                                self._last_user_message["key"],
                            )
                    else:
                        key = self._initiative_key(perception, self._last_decision)
                        if not self._allow_initiative(key):
                            if self.config.enable_logging:
                                logger.info(
                                    "[InitiativeEngine] tick#%d suppress repeat (%s)",
                                    self._stats["ticks"],
                                    key,
                                )
                            self._stats["decisions"].setdefault("suppressed_repeat", 0)
                            self._stats["decisions"]["suppressed_repeat"] += 1
                        else:
                            self._execute_decision(
                                self._last_decision,
                                character_id=str(perception.get("character_id") or ""),
                            )
                # Инициатива сработала — считаем, что по последнему сообщению игрока
                # тему уже продолжили (не повторяем это для одного и того же сообщения).
                if action != "silence" and self._last_user_message is not None:
                    self._followed_up_message_key = self._last_user_message["key"]
                # Сохраняем мотивы как намерения (для долгосрочного поведения).
                self._materialize_intentions(
                    character_id=str(perception.get("character_id") or ""),
                    motives=motives,
                )
            except Exception:
                pass
        # Динамический интервал: учитываем длительность последнего ответа.
        self._reschedule_interval(self._compute_next_interval())

    def stats(self) -> Dict[str, Any]:
        """Снимок статистики движка для мониторинга."""
        with self._lock:
            intentions = self._intentions.list_active() if self._intentions else []
            stats = dict(self._stats)
            stats["intentions_active"] = len(intentions)
            stats["intentions"] = [i.to_dict() for i in intentions]
            stats["last_perception"] = self._last_perception
            stats["last_motives"] = list(self._last_motives)
            stats["last_events"] = list(self._last_events)
            stats["last_action"] = self._last_action
            stats["internal_state"] = dict(self._internal_state)
            stats["in_flight_initiative"] = dict(self._in_flight_initiative)
            stats["user_state"] = dict(self._last_user_state)
            stats["traits"] = dict(getattr(self, "_last_traits", {}))
            stats["running"] = self._running
            stats["config"] = {
                "enabled": self.config.enabled,
                "autonomy_level": self.config.autonomy_level,
                "scheduler_interval_sec": self.config.scheduler_interval_sec,
                "max_actions_per_minute": self.config.max_actions_per_minute,
                "filter_events": self.config.filter_events,
                "respect_busy_character": self.config.respect_busy_character,
            }
            return stats

    def set_logging(self, enabled: bool) -> None:
        self.config = self.config.__class__(
            **{**self.config.__dict__, "enable_logging": bool(enabled)}
        )

    def _reschedule_interval(self, interval_sec: float) -> None:
        """Динамически изменить минимальный интервал тика."""
        if self._scheduler is not None:
            try:
                self._scheduler.reschedule(float(interval_sec))
            except Exception:
                pass

    def _compute_next_interval(self) -> float:
        """Рассчитать следующий минимальный интервал тика.

        Идея: интервал — это МИНИМУМ. Если персонаж только что завершил долгую
        генерацию ответа (например, облачная модель шла 60с), следующий
        потенциальный запрос откладывается на паузу пропорционально длительности.
        При этом НЕ сломаны непрерывные цепочки (инструменты): пока идёт
        активная генерация, тик пропускается через busy-проверку, и пауза
        применяется только после фактического завершения ответа.
        """
        base = max(1.0, float(self.config.scheduler_interval_sec))
        # Если только что был длинный ответ — добавим паузу (не более 90с).
        if self._last_response_duration > base:
            return min(90.0, max(base, self._last_response_duration))
        return base

    def _is_character_busy(self, character_id: Optional[str]) -> bool:
        if self._activity_service is None:
            return False
        try:
            return self._activity_service.active_generation_count(character_id) > 0
        except Exception:
            return False

    def _idle_followup_motive(self, character_id: Optional[str]) -> Optional[Dict[str, Any]]:
        """Мотив продолжить тему по последнему сообщению игрока, если он замолчал."""
        if self.config.autonomy_level not in ("subtle", "full"):
            return None
        if not self.config.allow_initiate_dialogue:
            return None
        msg = self._last_user_message
        if not msg:
            return None
        if self._followed_up_message_key == msg["key"]:
            return None
        if self.config.respect_busy_character and self._is_character_busy(character_id):
            return None
        # Продолжать тему можно только после реального молчания: и игрока, и
        # персонажа. Иначе движок «повторно отвечает» на свежее сообщение.
        last_activity = max(msg["ts"], self._last_assistant_ts)
        idle = time.time() - last_activity
        threshold = max(45.0, float(self.config.scheduler_interval_sec) * 1.5)
        if idle < threshold:
            return None
        return {
            "type": "continue_topic",
            "description": "Продолжить тему по последнему сообщению игрока",
            "priority": 3,
            "source": "events",
        }

    @staticmethod
    def _is_noise_event(event: Dict[str, Any]) -> bool:
        """Отфильтровать технические/повторяющиеся события низкой значимости."""
        etype = str(event.get("type") or "")
        # События, которые не должны триггерить инициативу в одиночку.
        if etype in (
            "on_compression_started",
            "on_compression_finished",
            "on_tool_done",
            "on_failed_attempt_for_response",
            # Сообщения игрока обрабатывает обычный конвейер — инициатива по ним
            # дублирует ответы персонажа.
            "send_message",
            # Ответы ассистента/персонажа не должны запускать инициативу сами по
            # себе — иначе движок «догоняет» собственные реплики и зацикливается
            # (повторяет/соглашается с последним действием).
            "on_successful_response",
        ):
            return True
        # Пустые события.
        data = event.get("data") or {}
        if not data:
            return True
        return False

    def _initiative_key(self, perception: Dict[str, Any], decision: Dict[str, Any]) -> str:
        """Ключ инициативы для дедупликации повторяющихся решений."""
        char_id = str(perception.get("character_id") or "")
        action = str(decision.get("action") or "")
        reason = str(decision.get("reason") or "")
        # Для повторного вопроса («попыток достучаться») включаем счётчик попыток
        # в ключ, чтобы каждая НОВАЯ попытка не блокировалась cooldown'ом —
        # иначе персонаж не смог бы накапливать попытки (они бы подавлялись).
        if "respond_to_own_question" in reason:
            meta = decision.get("meta") or {}
            motive = meta.get("motive") or {}
            attempts = int(motive.get("attempts") or 1)
            return f"{char_id}|{action}|{reason}|attempts={attempts}"
        return f"{char_id}|{action}|{reason}"

    def _allow_initiative(self, key: str) -> bool:
        """Пропустить инициативу, если такой же ключ недавно исполнялся."""
        now = time.time()
        cooldown = max(30.0, min(120.0, float(self.config.scheduler_interval_sec) * 2))
        last = self._recent_initiative.get(key)
        if last is not None and now - last < cooldown:
            return False
        cutoff = now - 120.0
        self._recent_initiative = {
            k: v for k, v in self._recent_initiative.items() if v >= cutoff
        }
        self._recent_initiative[key] = now
        return True

    def _active_character_id(self) -> Optional[str]:
        if self._character_registry is None:
            return None
        try:
            return self._character_registry.current_id()
        except Exception:
            return None

    def _character_for(self, character_id: Optional[str]):
        if self._character_registry is None or not character_id:
            return None
        try:
            return self._character_registry.get(character_id)
        except Exception:
            return None

    @staticmethod
    def _keywords_from_text(text: str) -> List[str]:
        """Извлечь ключевые слова из текста (для релевантности намерений)."""
        if not text:
            return []
        import re as _re

        words = _re.findall(r"[а-яА-Яa-zA-Z]{4,}", text)
        stop = {
            "это", "чтобы", "есть", "что", "как", "для", "при", "без",
            "его", "ее", "или", "но", "не", "ни", "все", "было", "будет",
            "который", "которая", "которые", "через", "после", "пока",
        }
        return sorted({w.lower() for w in words if w.lower() not in stop})[:20]

    def _consume_intention_type(self, mtype: str) -> None:
        """Пометить первое активное намерение данного типа как 'executing'."""
        if not mtype or self._intentions is None:
            return
        try:
            for itn in self._intentions.list_active():
                if itn.type == mtype:
                    self._intentions.set_status(itn.id, "executing")
                    return
        except Exception:
            pass

    def _complete_executing_intentions(self) -> None:
        """Завершить намерения, ожидающие реакции пользователя (status=executing).

        Вызывается при поступлении достоверного пользовательского сообщения:
        пользователь отреагировал → цель достигнута, а не только доставлена.
        """
        if self._intentions is None:
            return
        try:
            char_id = self._active_character_id()
            for itn in self._intentions.list_active(char_id):
                if itn.status == "executing":
                    self._intentions.set_status(itn.id, "completed")
        except Exception:
            pass

    def _assistant_question_key(self) -> Optional[str]:
        """Ключ текущего вопроса персонажа (для защиты от зацикливания)."""
        msg = self._last_assistant_message
        if not msg:
            return None
        return f"{msg.get('ts')}:{str(msg.get('text') or '')[:60]}"

    def _record_unanswered_question(self) -> None:
        """Зафиксировать попытку персонажа достучаться до пользователя.

        В отличие от старой версии, счётчик не зависит от дословного текста
        вопроса (Мита может переформулировать). Считается СЕРИЯ попыток:
        если с последней попытки прошло мало времени (порог), а пользователь
        так и не ответил — та же попытка не считается новой. Новая попытка
        засчитывается только после реальной паузы (персонаж попробовал снова).
        """
        text = str(self._last_assistant_message.get("text") or "").strip() if self._last_assistant_message else ""
        if not text or "?" not in text:
            return
        now = time.time()
        # Порог «новой попытки»: если с прошлой прошло больше ~90с, значит
        # персонаж реально предпринял ещё одну попытку достучаться.
        NEW_ATTEMPT_GAP = 90.0
        if self._unanswered_questions:
            q = self._unanswered_questions[-1]
            # Обновляем ключ/текст последней попытки (это последний вопрос).
            if now - q["last_ts"] > NEW_ATTEMPT_GAP:
                self._unanswered_questions.append(
                    {
                        "key": f"q:{text[:80].strip().lower()}",
                        "text": text[:160],
                        "attempts": q["attempts"] + 1,
                        "first_ts": q["first_ts"],
                        "last_ts": now,
                    }
                )
                if len(self._unanswered_questions) > 5:
                    self._unanswered_questions.pop(0)
            else:
                # Пока не прошла пауза — это продолжение той же попытки,
                # просто обновляем текст.
                q["text"] = text[:160]
                q["last_ts"] = now
            return
        # Первая попытка.
        self._unanswered_questions.append(
            {
                "key": f"q:{text[:80].strip().lower()}",
                "text": text[:160],
                "attempts": 1,
                "first_ts": now,
                "last_ts": now,
            }
        )

    def _clear_unanswered_questions(self) -> None:
        """Сбросить историю неотвеченных попыток (пользователь ответил)."""
        self._unanswered_questions = []

    def _build_initiative_instruction(
        self, motive: Optional[Dict[str, Any]], character_id: str
    ) -> str:
        """Сформировать инструкцию для модели при запуске инициативы.

        Важно: явно помечаем роли (кто говорил), чтобы модель не путала
        последнюю реплику персонажа с ответом пользователя (баг путаницы ролей).
        """
        mtype = str((motive or {}).get("type") or "")
        parts: List[str] = []
        if self._last_assistant_message:
            txt = str(self._last_assistant_message.get("text") or "").strip()
            if txt:
                parts.append(f"Твоя последняя реплика: «{txt}»")
        if mtype == "respond_to_own_question":
            attempts = int((motive or {}).get("attempts") or 1)
            # Явно объясняем, что пользователь НЕ отвечал. Его последняя фраза —
            # СТАРАЯ (она была ДО твоих вопросов), а не новое сообщение.
            # Это ключевое уточнение: иначе модель думает, что пользователь
            # каждый раз повторяет одну и ту же фразу.
            if self._last_user_message:
                txt = str(self._last_user_message.get("text") or "").strip()
                if txt:
                    parts.append(
                        "Пользователь НЕ ответил на твой вопрос. Его последняя "
                        f"фраза (была сказана ДО твоих вопросов): «{txt}». "
                        "Это СТАРАЯ фраза, пользователь не пишет её повторно."
                    )
            # Тексты прошлых вопросов — чтобы модель знала, о чём спрашивала.
            past_questions = []
            for q in self._unanswered_questions:
                qt = str(q.get("text") or "").strip()
                if qt and qt not in past_questions:
                    past_questions.append(qt)
            if past_questions:
                parts.append(
                    "Ты уже неоднократно пытался(ась) достучаться: "
                    + "; ".join(f"«{t}»" for t in past_questions[-4:])
                )
            if attempts >= 4:
                parts.append(
                    f"Ты задал(а) вопрос уже {attempts} раз, и пользователь так и "
                    "не ответил. Есть несколько вариантов: (1) настойчиво позвать "
                    "через инструменты (уведомление); (2) обидеться/замолчать; "
                    "(3) предположить, что пользователь ушёл, и спокойно заняться "
                    "своим делом. Выбери поведение, соответствующее твоему "
                    "характеру и настроению, и НЕ повторяй один и тот же вопрос."
                )
            elif attempts >= 3:
                parts.append(
                    f"Ты задал(а) вопрос уже {attempts} раза, а пользователь не "
                    "ответил ни разу. Пользователь, видимо, отвлёкся или ушёл. "
                    "Реши сам(а): продолжить настойчиво (например, позвать/показать "
                    "уведомление) или проявить обиду/смирение."
                )
            elif attempts == 2:
                parts.append(
                    "Ты спрашиваешь повторно, а пользователь всё ещё не ответил. "
                    "Настойчивее или с лёгким укором."
                )
            else:
                parts.append(
                    "Ты задал(а) вопрос, а пользователь не ответил. "
                    "Переспроси вежливо или мягко продолжи тему."
                )
        elif mtype == "continue_topic":
            parts.append("Пользователь замолчал — можно мягко продолжить тему.")
        else:
            desc = str((motive or {}).get("description") or "").strip()
            if desc:
                parts.append(desc)
        return " ".join(parts).strip()

    def _execute_absent_comment(self, character_id: str) -> None:
        """Запустить комментарий персонажа о том, что пользователь отсутствует.

        Один раз на серию отсутствия. Комментарий зависит от характера и
        настроения (формируется в инструкции). Использует initiate_dialogue,
        но с отдельным мотивом, чтобы не конфликтовать с обычным диалогом.
        """
        if not character_id or self._actions is None:
            return
        if self.config.respect_busy_character and self._is_character_busy(character_id):
            return
        try:
            instruction = self._build_absent_comment_instruction(character_id)
            ok = self._actions.initiate_dialogue(character_id, instruction)
            if ok:
                self._in_flight_initiative[character_id] = time.time()
                self._last_action = {
                    "action": "initiate_dialogue",
                    "character_id": character_id,
                    "ts": time.time(),
                    "status": "executed",
                    "detail": "[InitiativeAction] absent comment",
                    "reason": "комментарий об отсутствии пользователя",
                }
        except Exception:
            pass

    def _build_absent_comment_instruction(self, character_id: str) -> str:
        """Сформировать инструкцию для комментария об отсутствии пользователя.

        Учитывает характер (traits) и настроение (internal_state). Пользователь
        неактивен — персонаж может заметить это по-разному: мягко, с тревогой,
        с обидой, игриво и т.д. (Решение — за моделью, но с подсказкой.)
        """
        traits = getattr(self, "_last_traits", {}) or {}
        internal = self._internal_state or {}
        persistence = float(traits.get("persistence", 0.3))
        touchiness = float(traits.get("touchiness", 0.3))
        boredom = float(internal.get("boredom", 0.1))
        stress = float(internal.get("stress", 0.05))

        parts = [
            "Пользователь сейчас отсутствует (неактивен дольше обычного).",
        ]
        if stress >= 0.6:
            parts.append("Ты немного расстроен(а)/встревожен(а) его отсутствием.")
        elif touchiness >= 0.6:
            parts.append("Ты можешь слегка обидеться или пошутить про его отсутствие.")
        elif persistence >= 0.6:
            parts.append("Ты настойчив(а) — можешь мягко позвать или напомнить о себе.")
        else:
            parts.append("Отреагируй естественно: мягко отметь его отсутствие.")
        if boredom >= 0.5:
            parts.append("Тебе скучно без него — дай это понять.")
        # Явно указываем: это НЕ вопрос, а комментарий (не ждать ответа сразу).
        parts.append("Это комментарий, а не вопрос — не требуй немедленного ответа.")
        return " ".join(parts)

    def _execute_decision(self, decision: Dict[str, Any], *, character_id: str) -> None:
        """Исполнить принятое решение (если это действие), затем обработать feedback."""
        if self._actions is None or not character_id:
            return
        action = str(decision.get("action") or "")
        # Защита от конкуренции генераций: перепроверяем занятость непосредственно
        # перед исполнением, чтобы инициатива не стартовала, если прямо сейчас
        # идёт штатная генерация (не блокируем обычный ответ).
        # Фактическая атомарность обеспечивается ОБЩИМ механизмом синхронизации:
        # и инициатива (ChatAPI.initiate → _submit_request → _run_request), и штатный
        # диалог идут в model_controller, который сериализует генерации через
        # character_generation_lock. Проверка занятости здесь — оптимизация, чтобы
        # не ставить в очередь при активной генерации, а не единственная защита.
        if action in ("initiate_dialogue", "act") and self.config.respect_busy_character:
            if self._is_character_busy(character_id):
                # Инициатива отложена из-за активной штатной генерации.
                self._last_action = {
                    "action": action,
                    "character_id": character_id,
                    "ts": time.time(),
                    "status": "deferred_by_busy",
                    "reason": str(decision.get("reason") or ""),
                }
                return
        # Этап 3: Initiative Gate — проверка допустимости инициативы.
        if action == "initiate_dialogue":
            allowed, gate_reason = self._gate.allow(
                "initiate_dialogue",
                self._last_user_state,
                internal=self._internal_state,
                traits=getattr(self, "_last_traits", {}),
            )
            if not allowed:
                self._stats["decisions"].setdefault("blocked_by_gate", 0)
                self._stats["decisions"]["blocked_by_gate"] += 1
                self._last_action = {
                    "action": action,
                    "character_id": character_id,
                    "ts": time.time(),
                    "status": "blocked_by_gate",
                    "reason": str(decision.get("reason") or ""),
                    "detail": gate_reason,
                }
                return
        result = None
        try:
            if action == "initiate_dialogue":
                # Инструкция с явной разметкой ролей (кто говорил), чтобы модель
                # не путала последнюю реплику персонажа с ответом пользователя.
                meta = decision.get("meta") or {}
                motive = meta.get("motive") or {}
                instruction = self._build_initiative_instruction(motive, character_id)
                ok = self._actions.initiate_dialogue(character_id, instruction)
                # Разговор начат — считаем успехом (подтверждение придёт из событий).
                if ok:
                    self._in_flight_initiative[character_id] = time.time()
                    # Запоминаем сообщение пользователя, на которое отреагировали,
                    # чтобы не запускать реактивную инициативу повторно по тому же
                    # сообщению. НЕ применяется к respond_to_own_question (накопление).
                    if (
                        self._last_user_message is not None
                        and str(motive.get("type") or "") != "respond_to_own_question"
                    ):
                        self._last_initiative_user_key = self._last_user_message["key"]
                    # Если отвечаем на свой вопрос — запоминаем, чтобы не
                    # зациклиться и не переспрашивать одно и то же.
                    if str(motive.get("type") or "") == "respond_to_own_question":
                        self._handled_own_question_key = self._assistant_question_key()
                result = "[InitiativeAction] dialogue initiated"
            elif action == "act":
                meta = decision.get("meta") or {}
                motive = meta.get("motive") or {}
                tool = str(motive.get("type") or "")
                if tool in ("comment_on_window", "comment_on_environment"):
                    tool = "show_notification"
                result = self._actions.execute_tool(character_id, tool, {})
        except Exception as exc:
            logger.warning("[InitiativeEngine] execute decision failed: %s", exc)
            result = f"[ошибка] {exc}"
        if action in ("initiate_dialogue", "act") and result is not None:
            self._last_action = {
                "action": action,
                "character_id": character_id,
                "ts": time.time(),
                "status": "executed",
                "detail": result,
                "reason": str(decision.get("reason") or ""),
            }
            # Жизненный цикл намерения ведёт Feedback (delivery/goal), см. ниже.

        if self._feedback is not None and result is not None and action != "silence":
            try:
                feedback = self._feedback.process(
                    intention=decision.get("meta") or {},
                    action_result=result,
                    delivered=(action == "initiate_dialogue"),
                    user_available=self._last_user_state.get("signal")
                    not in ("do_not_disturb", "busy", "sleep"),
                )
                _feed_action = feedback.get("action")
                _mtype = str(((decision.get("meta") or {}).get("motive")) or {}).get("type") or ""
                if _feed_action == "retry":
                    # Провал: помечаем намерение для пересмотра (уменьшаем приоритет).
                    self._degrade_active_intention(character_id, decision.get("meta") or {})
                elif _feed_action == "await_reaction":
                    # Доставка успешна, но цель ещё не подтверждена пользователем:
                    # намерение переходит в 'executing' и ждёт реакции пользователя.
                    self._consume_intention_type(_mtype)
                elif _feed_action == "complete":
                    self._complete_active_intention(character_id, decision.get("meta") or {})
                elif _feed_action == "cancel" and _mtype and self._intentions is not None:
                    for itn in self._intentions.list_active(character_id):
                        if itn.type == _mtype:
                            self._intentions.cancel(itn.id)
                            break
            except Exception:
                pass

    def _degrade_active_intention(self, character_id: str, meta: Dict[str, Any]) -> None:
        if self._intentions is None:
            return
        motive = meta.get("motive") or {}
        mtype = str(motive.get("type") or "")
        for intention in self._intentions.list_active(character_id):
            if intention.type == mtype:
                self._intentions.set_priority(intention.id, max(0, intention.priority - 1))
                break

    def _complete_active_intention(self, character_id: str, meta: Dict[str, Any]) -> None:
        if self._intentions is None:
            return
        motive = meta.get("motive") or {}
        mtype = str(motive.get("type") or "")
        for intention in self._intentions.list_active(character_id):
            if intention.type == mtype:
                self._intentions.set_status(intention.id, "completed")
                break

    def _materialize_intentions(
        self, *, character_id: str, motives: List[Dict[str, Any]]
    ) -> None:
        """Превратить значимые мотивы в намерения (если ещё нет таких).

        Дедупликация: на один (character_id, type) создаётся не более одного
        намерения. Если такое уже есть — лишь обновляем приоритет/описание.
        """
        if not character_id or self._intentions is None:
            return
        try:
            active = self._intentions.list_active(character_id)
            existing = {}
            for i in active:
                existing.setdefault(i.type, []).append(i)
            for motive in motives:
                mtype = str(motive.get("type") or "")
                if not mtype:
                    continue
                if int(motive.get("priority", 0)) < 2:
                    continue  # только значимые мотивы становятся намерениями
                prio = int(motive.get("priority", 1))
                desc = str(motive.get("description") or "")
                if mtype in existing:
                    # Обновляем существующее (максимальный приоритет/свежее описание).
                    for i in existing[mtype]:
                        if prio > int(i.priority):
                            self._intentions.set_priority(i.id, prio)
                        if desc and i.description != desc:
                            # не перезаписываем описание, если оно не пустое
                            pass
                    continue
                self._intentions.create(
                    character_id=character_id,
                    type=mtype,
                    description=desc,
                    priority=prio,
                    context={"source": motive.get("source", "")},
                )
                existing[mtype] = []
        except Exception:
            pass
