import importlib
import sys
import unittest
from argparse import Namespace
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from hvv_display.config import ConfigError, load_config
from hvv_display.geofox import HAMBURG_TZ, GeofoxError
from hvv_display.main import (
    MAX_REFRESH_BACKOFF_SECONDS,
    _arguments,
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
                patch("hvv_display.main.signal.signal"),
            ):
                result = run()

            self.assertEqual(result, 1)
            self.assertTrue(output.is_file())

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
                    "hvv_display.main.signal.signal",
                    side_effect=lambda _signal, handler: handlers.append(handler),
                ),
                patch(
                    "hvv_display.main.time.monotonic",
                    side_effect=[0, 0, 0, 15, 1, 1, 1, 1],
                ),
                patch(
                    "hvv_display.main.time.sleep",
                    side_effect=stop_during_sleep,
                ) as sleep,
            ):
                self.assertEqual(run(), 0)
        client.departure_list.assert_called_once()
        sleep.assert_called_once_with(1.0)

    def test_main_exits_with_run_result(self) -> None:
        with (
            patch("hvv_display.main.run", return_value=7),
            patch("hvv_display.main.sys.exit") as exit_process,
        ):
            main()
        exit_process.assert_called_once_with(7)


if __name__ == "__main__":
    unittest.main()
