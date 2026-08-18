import importlib
import json
import sys
import unittest
from argparse import Namespace
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from PIL import Image

from hvv_display.config import ConfigError, load_config
from hvv_display.geofox import HAMBURG_TZ, GeofoxError
from hvv_display.main import (
    MAX_REFRESH_BACKOFF_SECONDS,
    _arguments,
    departures_for_display,
    log_success,
    main,
    refresh_delay,
    run,
    update_board,
)
from hvv_display.models import Departure


class MainTest(unittest.TestCase):
    def test_package_entrypoint_is_importable(self) -> None:
        self.assertIsNotNone(importlib.import_module("hvv_display.__main__"))

    def test_arguments_support_environment_defaults_and_flags(self) -> None:
        with (
            patch.dict(
                "os.environ",
                {
                    "HVV_CONFIG": "custom.json",
                    "HVV_STATION_CACHE": "custom-cache.json",
                },
            ),
            patch.object(
                sys,
                "argv",
                ["hvv-anzeiger", "--once", "--output", "board.png"],
            ),
        ):
            arguments = _arguments()
        self.assertEqual(arguments.config, "custom.json")
        self.assertEqual(arguments.cache, "custom-cache.json")
        self.assertTrue(arguments.once)
        self.assertEqual(arguments.output, "board.png")

    def test_normal_refresh_interval_is_used_after_success(self) -> None:
        self.assertEqual(refresh_delay(15, 0), 15)

    def test_failures_use_bounded_exponential_backoff(self) -> None:
        self.assertEqual(refresh_delay(15, 1), 30)
        self.assertEqual(refresh_delay(15, 2), 60)
        self.assertEqual(refresh_delay(15, 3), 120)
        self.assertEqual(refresh_delay(15, 20), MAX_REFRESH_BACKOFF_SECONDS)
        self.assertEqual(refresh_delay(15, 1, retry_after_seconds=600), 600)

    def test_success_is_logged_as_info_at_most_hourly(self) -> None:
        with self.assertLogs("hvv_display.main", level="DEBUG") as logs:
            heartbeat = log_success(
                3,
                now_monotonic=10,
                previous_heartbeat_at=None,
            )
            unchanged = log_success(
                4,
                now_monotonic=20,
                previous_heartbeat_at=heartbeat,
            )
            refreshed = log_success(
                5,
                now_monotonic=3610,
                previous_heartbeat_at=unchanged,
            )
        self.assertEqual(heartbeat, 10)
        self.assertEqual(unchanged, 10)
        self.assertEqual(refreshed, 3610)
        self.assertEqual(
            [entry.split(":")[0] for entry in logs.output],
            ["INFO", "DEBUG", "INFO"],
        )

    def test_stale_departures_expire_after_configured_age(self) -> None:
        now = datetime(2026, 7, 27, 12, 10, tzinfo=HAMBURG_TZ)
        departure = Departure("21", "Ziel", now + timedelta(minutes=2))
        self.assertEqual(
            departures_for_display(
                [departure],
                now=now,
                last_updated=now - timedelta(minutes=4, seconds=59),
                stale=True,
                max_stale_age_minutes=5,
            ),
            [departure],
        )
        self.assertEqual(
            departures_for_display(
                [departure],
                now=now,
                last_updated=now - timedelta(minutes=5),
                stale=True,
                max_stale_age_minutes=5,
            ),
            [],
        )
        self.assertEqual(
            departures_for_display(
                [departure],
                now=now,
                last_updated=None,
                stale=True,
                max_stale_age_minutes=5,
            ),
            [],
        )
        self.assertEqual(
            departures_for_display(
                [departure],
                now=now,
                last_updated=now - timedelta(hours=1),
                stale=False,
                max_stale_age_minutes=5,
            ),
            [departure],
        )

    def test_once_mode_renders_a_complete_successful_cycle(self) -> None:
        config = load_config("config.example.json")
        now = datetime.now(HAMBURG_TZ)

        class SuccessfulClient:
            def departure_list(self, *_args, **_kwargs):
                return [
                    Departure(
                        "21",
                        "U Niendorf Nord",
                        now + timedelta(minutes=3),
                        station_label="R",
                    )
                ]

        with TemporaryDirectory() as directory:
            output = Path(directory) / "board.png"
            arguments = Namespace(
                config="config.example.json",
                cache=str(Path(directory) / "stations.json"),
                once=True,
                output=str(output),
            )
            with (
                patch("hvv_display.main._arguments", return_value=arguments),
                patch("hvv_display.main.GeofoxClient", return_value=SuccessfulClient()),
                patch(
                    "hvv_display.main.resolve_stations",
                    return_value=config.stations,
                ),
                patch(
                    "hvv_display.main.clock_is_synchronized",
                    return_value=True,
                ),
                patch("hvv_display.main.signal.signal"),
            ):
                result = run()

            self.assertEqual(result, 0)
            self.assertTrue(output.is_file())

    def test_once_mode_renders_stale_state_after_api_failure(self) -> None:
        config = load_config("config.example.json")

        class FailingClient:
            def departure_list(self, *_args, **_kwargs):
                raise GeofoxError("vorübergehend nicht erreichbar")

        with TemporaryDirectory() as directory:
            output = Path(directory) / "board.png"
            arguments = Namespace(
                config="config.example.json",
                cache=str(Path(directory) / "stations.json"),
                once=True,
                output=str(output),
            )
            with (
                patch("hvv_display.main._arguments", return_value=arguments),
                patch("hvv_display.main.GeofoxClient", return_value=FailingClient()),
                patch(
                    "hvv_display.main.resolve_stations",
                    return_value=config.stations,
                ),
                patch(
                    "hvv_display.main.clock_is_synchronized",
                    return_value=True,
                ),
                patch("hvv_display.main.signal.signal"),
            ):
                result = run()

            self.assertEqual(result, 1)
            self.assertTrue(output.is_file())

    def test_unsynchronized_time_is_rendered_without_geofox_request(self) -> None:
        config = load_config("config.example.json")
        client = Mock()
        with TemporaryDirectory() as directory:
            output = Path(directory) / "board.png"
            arguments = Namespace(
                config="config.example.json",
                cache=str(Path(directory) / "stations.json"),
                once=True,
                output=str(output),
            )
            with (
                patch("hvv_display.main._arguments", return_value=arguments),
                patch("hvv_display.main.GeofoxClient", return_value=client),
                patch(
                    "hvv_display.main.clock_is_synchronized",
                    return_value=False,
                ),
                patch("hvv_display.main.signal.signal"),
            ):
                result = run()

        self.assertEqual(result, 1)
        client.departure_list.assert_not_called()
        self.assertEqual(config.night_shutdown.start.strftime("%H:%M"), "21:00")

    def test_night_shutdown_blanks_display_and_pauses_geofox(self) -> None:
        client = Mock()
        now = datetime(2026, 7, 27, 22, 0, tzinfo=HAMBURG_TZ)
        with TemporaryDirectory() as directory:
            config_raw = json.loads(
                Path("config.example.json").read_text(encoding="utf-8")
            )
            config_raw["night_shutdown"]["enabled"] = True
            config_path = Path(directory) / "config.json"
            config_path.write_text(json.dumps(config_raw), encoding="utf-8")
            output = Path(directory) / "board.png"
            arguments = Namespace(
                config=str(config_path),
                cache=str(Path(directory) / "stations.json"),
                once=True,
                output=str(output),
            )
            with (
                patch("hvv_display.main._arguments", return_value=arguments),
                patch("hvv_display.main.GeofoxClient", return_value=client),
                patch(
                    "hvv_display.main.clock_is_synchronized",
                    return_value=True,
                ),
                patch("hvv_display.main.datetime") as mocked_datetime,
                patch("hvv_display.main.signal.signal"),
            ):
                mocked_datetime.now.return_value = now
                result = run()

            with Image.open(output) as image:
                self.assertEqual(image.getextrema(), ((0, 0), (0, 0), (0, 0)))
        self.assertEqual(result, 0)
        client.departure_list.assert_not_called()

    def test_startup_error_returns_configuration_exit_code(self) -> None:
        arguments = Namespace(
            config="missing.json",
            cache="stations.json",
            once=True,
            output="board.png",
        )
        with (
            patch("hvv_display.main._arguments", return_value=arguments),
            patch(
                "hvv_display.main.load_config",
                side_effect=ConfigError("invalid"),
            ),
        ):
            self.assertEqual(run(), 2)

    def test_update_board_skips_unchanged_frame(self) -> None:
        now = datetime(2026, 7, 27, 12, 0, tzinfo=HAMBURG_TZ)
        departure = Departure("21", "Ziel", now + timedelta(minutes=3))
        display = Mock()
        arguments = {
            "now": now,
            "last_updated": now,
            "stale": False,
            "error_message": None,
            "wifi_is_connected": True,
            "max_rows": 5,
            "output": None,
            "display": display,
        }
        state = update_board([departure], previous_state=None, **arguments)
        same_state = update_board(
            [departure],
            previous_state=state,
            **arguments,
        )
        self.assertEqual(same_state, state)
        display.show.assert_called_once()

    def test_display_transfer_failure_resets_state_for_reconnect(self) -> None:
        now = datetime(2026, 7, 27, 12, 0, tzinfo=HAMBURG_TZ)
        departure = Departure("21", "Ziel", now + timedelta(minutes=3))
        display = Mock()
        display.show.side_effect = OSError("SPI-Verbindung getrennt")
        with self.assertRaises(OSError):
            update_board(
                [departure],
                now=now,
                last_updated=now,
                stale=False,
                error_message=None,
                wifi_is_connected=True,
                max_rows=5,
                previous_state=None,
                output=None,
                display=display,
            )
        display.show.assert_called_once()

    def test_update_board_writes_output_and_requires_a_destination(self) -> None:
        now = datetime(2026, 7, 27, 12, 0, tzinfo=HAMBURG_TZ)
        with TemporaryDirectory() as directory:
            output = Path(directory) / "nested" / "board.png"
            state = update_board(
                [],
                now=now,
                last_updated=None,
                stale=False,
                error_message=None,
                wifi_is_connected=True,
                max_rows=5,
                previous_state=None,
                output=str(output),
                display=None,
            )
            self.assertTrue(output.is_file())
            with self.assertRaisesRegex(RuntimeError, "Kein Display"):
                update_board(
                    [],
                    now=now + timedelta(minutes=1),
                    last_updated=None,
                    stale=False,
                    error_message=None,
                    wifi_is_connected=True,
                    max_rows=5,
                    previous_state=state,
                    output=None,
                    display=None,
                )

    def test_continuous_mode_stops_cleanly_on_signal(self) -> None:
        config = load_config("config.example.json")
        handlers = []

        class StoppingClient:
            def departure_list(self, *_args, **_kwargs):
                handlers[0](15, None)
                return []

        with TemporaryDirectory() as directory:
            arguments = Namespace(
                config="config.example.json",
                cache=str(Path(directory) / "stations.json"),
                once=False,
                output=str(Path(directory) / "board.png"),
            )
            with (
                patch("hvv_display.main._arguments", return_value=arguments),
                patch("hvv_display.main.GeofoxClient", return_value=StoppingClient()),
                patch(
                    "hvv_display.main.resolve_stations",
                    return_value=config.stations,
                ),
                patch(
                    "hvv_display.main.clock_is_synchronized",
                    return_value=True,
                ),
                patch(
                    "hvv_display.main.signal.signal",
                    side_effect=lambda _signal, handler: handlers.append(handler),
                ),
            ):
                self.assertEqual(run(), 0)

    def test_continuous_mode_waits_and_does_not_poll_before_deadline(self) -> None:
        config = load_config("config.example.json")
        handlers = []
        client = Mock()
        client.departure_list.return_value = []

        def stop_during_sleep(_seconds):
            handlers[0](15, None)

        with TemporaryDirectory() as directory:
            arguments = Namespace(
                config="config.example.json",
                cache=str(Path(directory) / "stations.json"),
                once=False,
                output=str(Path(directory) / "board.png"),
            )
            with (
                patch("hvv_display.main._arguments", return_value=arguments),
                patch("hvv_display.main.GeofoxClient", return_value=client),
                patch(
                    "hvv_display.main.resolve_stations",
                    return_value=config.stations,
                ),
                patch(
                    "hvv_display.main.clock_is_synchronized",
                    return_value=True,
                ),
                patch(
                    "hvv_display.main.signal.signal",
                    side_effect=lambda _signal, handler: handlers.append(handler),
                ),
                patch(
                    "hvv_display.main.time.monotonic",
                    return_value=0,
                ),
                patch(
                    "hvv_display.main.time.sleep",
                    side_effect=stop_during_sleep,
                ) as sleep,
            ):
                self.assertEqual(run(), 0)
        client.departure_list.assert_called_once()
        sleep.assert_called_once_with(1.0)

    def test_continuous_mode_reuses_resolved_stations_after_deadline(self) -> None:
        config = load_config("config.example.json")
        handlers = []
        calls = 0

        def departures(*_args, **_kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                handlers[0](15, None)
            return []

        client = Mock()
        client.departure_list.side_effect = departures
        resolved = Mock(return_value=config.stations)
        with TemporaryDirectory() as directory:
            arguments = Namespace(
                config="config.example.json",
                cache=str(Path(directory) / "stations.json"),
                once=False,
                output=str(Path(directory) / "board.png"),
            )
            with (
                patch("hvv_display.main._arguments", return_value=arguments),
                patch("hvv_display.main.GeofoxClient", return_value=client),
                patch("hvv_display.main.resolve_stations", resolved),
                patch(
                    "hvv_display.main.clock_is_synchronized",
                    return_value=True,
                ),
                patch(
                    "hvv_display.main.signal.signal",
                    side_effect=lambda _signal, handler: handlers.append(handler),
                ),
                patch(
                    "hvv_display.main.time.monotonic",
                    side_effect=[0, 0, 0, 15, 15, 15, 15],
                ),
            ):
                self.assertEqual(run(), 0)

        self.assertEqual(client.departure_list.call_count, 2)
        resolved.assert_called_once()

    def test_continuous_mode_applies_changed_configuration_immediately(self) -> None:
        handlers = []
        clients = []
        client_credentials = []
        departures_calls = 0
        configuration_changes = 0

        def create_client(*args, **_kwargs):
            client = Mock()
            client.departure_list.side_effect = departures
            clients.append(client)
            client_credentials.append(args[1:3])
            return client

        def departures(*_args, **_kwargs):
            nonlocal departures_calls
            departures_calls += 1
            if departures_calls == 4:
                handlers[0](15, None)
            return []

        with TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            config_raw = json.loads(
                Path("config.example.json").read_text(encoding="utf-8")
            )
            config_path.write_text(json.dumps(config_raw), encoding="utf-8")
            credentials_path = Path(directory) / "credentials.env"
            credentials_path.write_text(
                "GEOFOX_USER=old-user\nGEOFOX_PASSWORD=old-password\n",
                encoding="utf-8",
            )
            arguments = Namespace(
                config=str(config_path),
                credentials=str(credentials_path),
                cache=str(Path(directory) / "stations.json"),
                once=False,
                output=None,
            )

            def save_changed_configuration(_seconds):
                nonlocal configuration_changes
                configuration_changes += 1
                if configuration_changes == 1:
                    config_raw["display"]["rotate"] = 1
                    config_path.write_text(json.dumps(config_raw), encoding="utf-8")
                elif configuration_changes == 2:
                    credentials_path.write_text(
                        "GEOFOX_USER=new-user\nGEOFOX_PASSWORD=new-password\n",
                        encoding="utf-8",
                    )
                else:
                    config_raw["display"]["rotate"] = 2
                    config_path.write_text(json.dumps(config_raw), encoding="utf-8")

            monotonic_calls = 0

            def monotonic_after_first_call():
                nonlocal monotonic_calls
                monotonic_calls += 1
                if monotonic_calls == 1:
                    return 0
                if monotonic_calls == 2:
                    return 20
                return 40

            with (
                patch("hvv_display.main._arguments", return_value=arguments),
                patch("hvv_display.main.GeofoxClient", side_effect=create_client),
                patch(
                    "hvv_display.main.resolve_stations",
                    side_effect=lambda _client, stations, _cache: stations,
                ),
                patch(
                    "hvv_display.main.Ili9341Display",
                    side_effect=[Mock(), Mock(), OSError("display disconnected")],
                ),
                patch("hvv_display.main.clock_is_synchronized", return_value=True),
                patch("hvv_display.main.wifi_connected", return_value=True),
                patch(
                    "hvv_display.main.signal.signal",
                    side_effect=lambda _signal, handler: handlers.append(handler),
                ),
                patch(
                    "hvv_display.main.time.monotonic",
                    side_effect=monotonic_after_first_call,
                ),
                patch(
                    "hvv_display.main.time.sleep",
                    side_effect=save_changed_configuration,
                ),
            ):
                self.assertEqual(run(), 0)

        self.assertEqual(len(clients), 4)
        self.assertEqual(client_credentials[0], ("old-user", "old-password"))
        self.assertEqual(client_credentials[1], ("new-user", "new-password"))
        self.assertEqual(client_credentials[2], ("new-user", "new-password"))
        self.assertEqual(client_credentials[3], ("new-user", "new-password"))

    def test_display_transfer_failure_is_recovered_for_next_cycle(self) -> None:
        config = load_config("config.example.json")
        display = Mock()
        display.show.side_effect = OSError("SPI disconnected")
        client = Mock()
        client.departure_list.return_value = []
        with TemporaryDirectory() as directory:
            arguments = Namespace(
                config="config.example.json",
                credentials=str(Path(directory) / "missing.env"),
                cache=str(Path(directory) / "stations.json"),
                once=True,
                output=None,
            )
            with (
                patch("hvv_display.main._arguments", return_value=arguments),
                patch("hvv_display.main.GeofoxClient", return_value=client),
                patch("hvv_display.main.Ili9341Display", return_value=display),
                patch(
                    "hvv_display.main.resolve_stations",
                    return_value=config.stations,
                ),
                patch("hvv_display.main.clock_is_synchronized", return_value=True),
                patch("hvv_display.main.signal.signal"),
            ):
                self.assertEqual(run(), 0)
        display.show.assert_called_once()

    def test_invalid_changed_configuration_keeps_previous_values(self) -> None:
        handlers = []
        departures_calls = 0

        def departures(*_args, **_kwargs):
            nonlocal departures_calls
            departures_calls += 1
            if departures_calls == 2:
                handlers[0](15, None)
            return []

        with TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            config_path.write_text(
                Path("config.example.json").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            output = Path(directory) / "board.png"
            arguments = Namespace(
                config=str(config_path),
                credentials=str(Path(directory) / "missing.env"),
                cache=str(Path(directory) / "stations.json"),
                once=False,
                output=str(output),
            )

            def save_invalid_configuration(_seconds):
                config_path.write_text("{invalid", encoding="utf-8")

            monotonic_calls = 0

            def monotonic_after_first_call():
                nonlocal monotonic_calls
                monotonic_calls += 1
                if monotonic_calls == 1:
                    return 0
                if monotonic_calls == 2:
                    return 20
                return 40

            with (
                patch("hvv_display.main._arguments", return_value=arguments),
                patch("hvv_display.main.GeofoxClient") as client_class,
                patch(
                    "hvv_display.main.resolve_stations",
                    side_effect=lambda _client, stations, _cache: stations,
                ),
                patch("hvv_display.main.clock_is_synchronized", return_value=True),
                patch("hvv_display.main.wifi_connected", return_value=True),
                patch(
                    "hvv_display.main.signal.signal",
                    side_effect=lambda _signal, handler: handlers.append(handler),
                ),
                patch(
                    "hvv_display.main.time.monotonic",
                    side_effect=monotonic_after_first_call,
                ),
                patch(
                    "hvv_display.main.time.sleep",
                    side_effect=save_invalid_configuration,
                ),
            ):
                client_class.return_value.departure_list.side_effect = departures
                self.assertEqual(run(), 0)

        self.assertEqual(client_class.call_count, 1)

    def test_configuration_stat_error_keeps_previous_values(self) -> None:
        handlers = []
        config = load_config("config.example.json")
        with TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            config_path.write_text(
                Path("config.example.json").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            arguments = Namespace(
                config=str(config_path),
                cache=str(Path(directory) / "stations.json"),
                once=False,
                output=str(Path(directory) / "board.png"),
            )
            original_stat = Path.stat
            stat_calls = 0

            def stat_with_one_failure(path, *args, **kwargs):
                nonlocal stat_calls
                if path == config_path:
                    stat_calls += 1
                    if stat_calls == 2:
                        raise OSError("temporarily unavailable")
                return original_stat(path, *args, **kwargs)

            def stop_after_departure(*_args, **_kwargs):
                handlers[0](15, None)
                return []

            with (
                patch("hvv_display.main._arguments", return_value=arguments),
                patch("hvv_display.main.GeofoxClient") as client_class,
                patch(
                    "hvv_display.main.resolve_stations", return_value=config.stations
                ),
                patch("hvv_display.main.clock_is_synchronized", return_value=True),
                patch(
                    "hvv_display.main.signal.signal",
                    side_effect=lambda _signal, handler: handlers.append(handler),
                ),
                patch("hvv_display.main.Path.stat", new=stat_with_one_failure),
            ):
                client_class.return_value.departure_list.side_effect = (
                    stop_after_departure
                )
                self.assertEqual(run(), 0)

            self.assertEqual(stat_calls, 2)

    def test_sleep_stat_error_does_not_stop_the_refresh_loop(self) -> None:
        handlers = []
        config = load_config("config.example.json")
        with TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            config_path.write_text(
                Path("config.example.json").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            arguments = Namespace(
                config=str(config_path),
                cache=str(Path(directory) / "stations.json"),
                once=False,
                output=str(Path(directory) / "board.png"),
            )
            original_stat = Path.stat
            stat_calls = 0

            def stat_with_one_failure(path, *args, **kwargs):
                nonlocal stat_calls
                if path == config_path:
                    stat_calls += 1
                    if stat_calls == 3:
                        raise OSError("temporarily unavailable")
                return original_stat(path, *args, **kwargs)

            def stop_during_sleep(_seconds):
                handlers[0](15, None)

            with (
                patch("hvv_display.main._arguments", return_value=arguments),
                patch("hvv_display.main.GeofoxClient") as client_class,
                patch(
                    "hvv_display.main.resolve_stations", return_value=config.stations
                ),
                patch("hvv_display.main.clock_is_synchronized", return_value=True),
                patch(
                    "hvv_display.main.signal.signal",
                    side_effect=lambda _signal, handler: handlers.append(handler),
                ),
                patch("hvv_display.main.Path.stat", new=stat_with_one_failure),
                patch("hvv_display.main.time.monotonic", return_value=0),
                patch("hvv_display.main.time.sleep", side_effect=stop_during_sleep),
            ):
                client_class.return_value.departure_list.return_value = []
                self.assertEqual(run(), 0)

            self.assertEqual(stat_calls, 3)

    def test_main_exits_with_run_result(self) -> None:
        with (
            patch("hvv_display.main.run", return_value=7),
            patch("hvv_display.main.sys.exit") as exit_process,
        ):
            main()
        exit_process.assert_called_once_with(7)


if __name__ == "__main__":
    unittest.main()
