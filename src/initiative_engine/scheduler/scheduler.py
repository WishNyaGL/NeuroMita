"""Гибридный планировщик: события + периодическая оценка.

Минимальная реализация для Этапа 1: запускает периодический тик в фоне и
позволяет запускать немедленную оценку по событию. Не содержит сложной логики
частоты — это добавится на более поздних этапах.
"""
from __future__ import annotations

import asyncio
import threading
from typing import Any, Callable, Optional


class InitiativeScheduler:
    def __init__(
        self,
        *,
        interval_sec: float = 30.0,
        on_tick: Optional[Callable[[], None]] = None,
        loop: Optional[asyncio.AbstractEventLoop] = None,
    ) -> None:
        self._interval = max(1.0, float(interval_sec))
        self._on_tick = on_tick
        self._loop = loop
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._interval_lock = threading.Lock()

    def reschedule(self, interval_sec: float) -> None:
        """Динамически изменить минимальный интервал тика (влияет на следующий)."""
        new_interval = max(1.0, float(interval_sec))
        with self._interval_lock:
            self._interval = new_interval

    @property
    def running(self) -> bool:
        return self._running

    def start(self) -> None:
        if self._running:
            return
        if self._loop is None or self._loop.is_closed() or not self._loop.is_running():
            # Нет живого loop — запускаем свой потоковый event loop.
            self._thread = threading.Thread(target=self._run_isolated, daemon=True)
            self._thread.start()
            return
        self._running = True
        self._task = self._loop.create_task(self._tick_loop())

    def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            self._task = None

    def trigger_async(self) -> None:
        """Немедленно запросить оценку (например, по важному событию)."""
        if not self._running:
            return
        if self._loop is not None and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._fire_tick)

    async def _tick_loop(self) -> None:
        while self._running:
            try:
                with self._interval_lock:
                    interval = self._interval
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break
            if self._running:
                self._fire_tick()

    def _run_isolated(self) -> None:
        own_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(own_loop)
        self._loop = own_loop
        self._running = True
        try:
            own_loop.run_until_complete(self._tick_loop())
        finally:
            self._running = False
            own_loop.close()

    def _fire_tick(self) -> None:
        if self._on_tick is not None and self._running:
            try:
                self._on_tick()
            except Exception:
                pass
