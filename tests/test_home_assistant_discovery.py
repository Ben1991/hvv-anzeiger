"""Tests for mDNS device discovery."""

import unittest
from unittest.mock import MagicMock, patch

from hvv_display.home_assistant_discovery import (
    SERVICE_TYPE,
    HomeAssistantAdvertiser,
    local_ipv4_address,
)
from hvv_display.web_transport import run

TEST_ACCESS_TOKEN_HASH = "configured-password-hash"  # noqa: S105 -- test fixture


class HomeAssistantDiscoveryTest(unittest.TestCase):
    def run_web_service(
        self, *, host="0.0.0.0", tls=True, hostname=None  # noqa: S104 -- test fixture
    ):
        server = MagicMock()
        server.serve_forever.side_effect = KeyboardInterrupt
        advertiser = MagicMock()
        with (
            patch("hvv_display.web.WebServer", return_value=server),
            patch("hvv_display.web_transport.WebApplication"),
            patch("hvv_display.web_transport.ssl.SSLContext"),
            patch(
                "hvv_display.home_assistant_discovery.HomeAssistantAdvertiser",
                return_value=advertiser,
            ) as advertiser_class,
        ):
            run(
                host,
                8080,
                access_token=TEST_ACCESS_TOKEN_HASH,
                must_change_password=True,
                tls_certfile="certificate.pem" if tls else None,
                tls_keyfile="key.pem" if tls else None,
                discovery_hostname=hostname,
            )
        return server, advertiser, advertiser_class

    def test_lan_server_advertises_tls_and_closes_service(self):
        server, advertiser, advertiser_class = self.run_web_service(
            hostname="hvv.example.net"
        )
        advertiser_class.assert_called_once_with(8080, "https", "hvv.example.net")
        advertiser.close.assert_called_once()
        server.server_close.assert_called_once()

    def test_mdns_failure_does_not_stop_backend(self):
        server = MagicMock()
        server.serve_forever.side_effect = KeyboardInterrupt
        with (
            patch("hvv_display.web.WebServer", return_value=server),
            patch("hvv_display.web_transport.WebApplication"),
            patch("hvv_display.web_transport.ssl.SSLContext"),
            patch(
                "hvv_display.home_assistant_discovery.HomeAssistantAdvertiser",
                side_effect=OSError("multicast unavailable"),
            ),
        ):
            run(
                "0.0.0.0",  # noqa: S104 -- exercises LAN binding
                8080,
                access_token=TEST_ACCESS_TOKEN_HASH,
                must_change_password=True,
                tls_certfile="certificate.pem",
                tls_keyfile="key.pem",
            )
        server.serve_forever.assert_called_once()
        server.server_close.assert_called_once()

    def test_loopback_server_skips_discovery(self):
        server, advertiser, advertiser_class = self.run_web_service(
            host="127.0.0.1", tls=False
        )
        advertiser_class.assert_not_called()
        advertiser.close.assert_not_called()
        server.server_close.assert_called_once()

    def test_local_ipv4_uses_the_route_for_mdns_multicast(self):
        connection = MagicMock()
        connection.getsockname.return_value = ("192.0.2.12", 0)
        with patch("hvv_display.home_assistant_discovery.socket.socket") as socket:
            socket.return_value.__enter__.return_value = connection
            self.assertEqual(local_ipv4_address(), "192.0.2.12")
        connection.connect.assert_called_once_with(("224.0.0.251", 5353))

    def test_advertisement_contains_only_api_metadata_and_closes_cleanly(self):
        zeroconf = MagicMock()
        with (
            patch(
                "hvv_display.home_assistant_discovery.local_ipv4_address",
                return_value="192.0.2.12",
            ),
            patch(
                "hvv_display.home_assistant_discovery.Zeroconf",
                return_value=zeroconf,
            ),
        ):
            advertiser = HomeAssistantAdvertiser(8080, "https", "hvv.example.net")
            info = zeroconf.register_service.call_args.args[0]
            self.assertEqual(info.type, SERVICE_TYPE)
            self.assertEqual(info.port, 8080)
            self.assertEqual(info.server, "hvv.example.net.")
            self.assertEqual(
                info.properties,
                {
                    b"api": b"/api/smart-home",
                    b"scheme": b"https",
                    b"version": b"1",
                },
            )
            self.assertNotIn(b"password", info.properties)
            advertiser.close()
        zeroconf.unregister_service.assert_called_once_with(info)
        zeroconf.close.assert_called_once()

    def test_registration_failure_closes_zeroconf(self):
        zeroconf = MagicMock()
        zeroconf.register_service.side_effect = OSError("multicast unavailable")
        with (
            patch(
                "hvv_display.home_assistant_discovery.local_ipv4_address",
                return_value="192.0.2.12",
            ),
            patch(
                "hvv_display.home_assistant_discovery.Zeroconf",
                return_value=zeroconf,
            ),
            self.assertRaisesRegex(OSError, "multicast unavailable"),
        ):
            HomeAssistantAdvertiser(8080, "https")
        zeroconf.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
