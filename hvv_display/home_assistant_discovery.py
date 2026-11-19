"""mDNS advertisement for the local Home Assistant integration."""

from __future__ import annotations

import logging
import socket

from zeroconf import ServiceInfo, Zeroconf

LOG = logging.getLogger(__name__)
SERVICE_TYPE = "_hvv-anzeiger._tcp.local."


def local_ipv4_address() -> str:
    """Return the IPv4 address used to reach the LAN multicast network."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as connection:
        connection.connect(("224.0.0.251", 5353))
        return str(connection.getsockname()[0])


class HomeAssistantAdvertiser:
    """Advertise the backend without exposing credentials over multicast."""

    def __init__(self, port: int, scheme: str, hostname: str | None = None) -> None:
        address = local_ipv4_address()
        server = (
            hostname.rstrip(".") + "."
            if hostname
            else socket.gethostname().rstrip(".") + ".local."
        )
        self._zeroconf = Zeroconf(interfaces=[address])
        self._service = ServiceInfo(
            SERVICE_TYPE,
            f"HVV-Anzeiger-{socket.gethostname()}.{SERVICE_TYPE}",
            addresses=[socket.inet_aton(address)],
            port=port,
            properties={
                "api": "/api/smart-home",
                "scheme": scheme,
                "version": "1",
            },
            server=server,
        )
        try:
            self._zeroconf.register_service(self._service)
        except Exception:
            self._zeroconf.close()
            raise

    def close(self) -> None:
        """Unregister the service and close the multicast sockets."""
        try:
            self._zeroconf.unregister_service(self._service)
        finally:
            self._zeroconf.close()
