import unittest
from unittest.mock import Mock, call

from hvv_display.service import SystemdNotifier


class SystemdNotifierTest(unittest.TestCase):
    def test_ready_and_watchdog_use_notify_socket(self) -> None:
        connection = Mock()
        factory = Mock(return_value=connection)
        notifier = SystemdNotifier(
            environment={
                "NOTIFY_SOCKET": "@test-notify",
                "WATCHDOG_USEC": "10000000",
                "WATCHDOG_PID": "42",
            },
            process_id=42,
            socket_factory=factory,
        )

        self.assertTrue(notifier.ready())
        self.assertTrue(notifier.ping_if_due(10))
        self.assertFalse(notifier.ping_if_due(14))
        self.assertTrue(notifier.ping_if_due(15))
        self.assertEqual(
            connection.sendto.call_args_list,
            [
                call(b"READY=1", "\0test-notify"),
                call(b"WATCHDOG=1", "\0test-notify"),
                call(b"WATCHDOG=1", "\0test-notify"),
            ],
        )
        self.assertEqual(connection.close.call_count, 3)

    def test_missing_or_foreign_configuration_is_a_noop(self) -> None:
        factory = Mock()
        missing = SystemdNotifier(environment={}, socket_factory=factory)
        foreign = SystemdNotifier(
            environment={
                "NOTIFY_SOCKET": "/run/notify",
                "WATCHDOG_USEC": "invalid",
                "WATCHDOG_PID": "123",
            },
            process_id=456,
            socket_factory=factory,
        )

        self.assertFalse(missing.ready())
        self.assertFalse(missing.ping_if_due(1))
        self.assertFalse(foreign.ready())
        self.assertFalse(foreign.ping_if_due(1))
        factory.assert_not_called()

    def test_socket_error_does_not_crash_application(self) -> None:
        connection = Mock()
        connection.sendto.side_effect = OSError("not available")
        notifier = SystemdNotifier(
            environment={
                "NOTIFY_SOCKET": "/run/notify",
                "WATCHDOG_USEC": "2000000",
            },
            socket_factory=Mock(return_value=connection),
        )

        self.assertFalse(notifier.ready())
        self.assertFalse(notifier.ping_if_due(1))
        self.assertEqual(connection.close.call_count, 2)


if __name__ == "__main__":
    unittest.main()
