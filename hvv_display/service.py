from __future__ import annotations

import os
import socket
from collections.abc import Callable, Mapping


class SystemdNotifier:
    """Send readiness and watchdog notifications without an extra dependency."""

    def __init__(
        self,
        *,
        environment: Mapping[str, str] = os.environ,
        process_id: int | None = None,
        socket_factory: Callable[..., socket.socket] = socket.socket,
    ) -> None:
        notify_socket = environment.get("NOTIFY_SOCKET", "")
        watchdog_pid = environment.get("WATCHDOG_PID")
        current_pid = process_id if process_id is not None else os.getpid()
        if watchdog_pid and watchdog_pid != str(current_pid):
            notify_socket = ""

        self._address = (
            "\0" + notify_socket[1:] if notify_socket.startswith("@") else notify_socket
        )
        self._socket_factory = socket_factory
        self._last_watchdog_at: float | None = None
        try:
            watchdog_seconds = int(environment.get("WATCHDOG_USEC", "0")) / 1_000_000
        except ValueError:
            watchdog_seconds = 0
        self._watchdog_interval = (
            max(1.0, watchdog_seconds / 2) if watchdog_seconds > 0 else None
        )

    def _send(self, message: str) -> bool:
        if not self._address:
            return False
        notifier_socket = self._socket_factory(socket.AF_UNIX, socket.SOCK_DGRAM)
        try:
            notifier_socket.sendto(message.encode("utf-8"), self._address)
        except OSError:
            return False
        finally:
            notifier_socket.close()
        return True

    def ready(self) -> bool:
        return self._send("READY=1")

    def ping_if_due(self, now_monotonic: float) -> bool:
        if self._watchdog_interval is None:
            return False
        if (
            self._last_watchdog_at is not None
            and now_monotonic - self._last_watchdog_at < self._watchdog_interval
        ):
            return False
        if not self._send("WATCHDOG=1"):
            return False
        self._last_watchdog_at = now_monotonic
        return True
