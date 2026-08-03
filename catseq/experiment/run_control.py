"""Cooperative pause and cancellation at experiment checkpoints."""

from __future__ import annotations

from threading import Condition


class RunControl:
    """In-process control for starting, pausing, stopping, and finishing a run."""

    def __init__(self) -> None:
        self._condition = Condition()
        self._active = False
        self._paused = False
        self._stop_requested = False

    def start(self) -> None:
        with self._condition:
            self._active = True

    def finish(self) -> None:
        with self._condition:
            self._active = False
            self._paused = False
            self._condition.notify_all()

    def request_pause(self) -> None:
        with self._condition:
            self._paused = True

    def resume(self) -> None:
        with self._condition:
            self._paused = False
            self._condition.notify_all()

    def request_stop(self) -> None:
        with self._condition:
            self._stop_requested = True
            self._condition.notify_all()

    def should_continue(self) -> bool:
        with self._condition:
            return self._active and not self._stop_requested

    def checkpoint(self) -> bool:
        while True:
            if not self.should_continue():
                return False
            with self._condition:
                if not self._active or self._stop_requested:
                    return False
                if not self._paused:
                    return True
                self._condition.wait()


__all__ = ["RunControl"]
