import shutil
import socket
import ssl
import subprocess
import tempfile
import time
import unittest
from http.client import HTTPConnection, HTTPSConnection
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from threading import Thread

from hvv_display.web import WebServer, hash_web_password, run


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *args):
        pass


class WebServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        openssl = shutil.which("openssl")
        if openssl is None:
            raise RuntimeError("openssl required for actual TLS regression tests")
        root = Path(cls.temporary.name)
        cert, key = root / "cert.pem", root / "key.pem"
        subprocess.run(  # noqa: S603
            [
                openssl,
                "req",
                "-x509",
                "-nodes",
                "-newkey",
                "rsa:2048",
                "-days",
                "1",
                "-keyout",
                str(key),
                "-out",
                str(cert),
                "-subj",
                "/CN=localhost",
            ],
            check=True,
            capture_output=True,
        )
        cls.context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        cls.context.minimum_version = ssl.TLSVersion.TLSv1_2
        cls.context.load_cert_chain(cert, key)
        cls.client_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        cls.client_context.check_hostname = False
        cls.client_context.verify_mode = ssl.CERT_NONE

    def start_server(self, *, tls=True, max_workers=8):
        server = WebServer(
            ("127.0.0.1", 0),
            Handler,
            tls_context=self.context if tls else None,
            connection_timeout=0.5,
            max_workers=max_workers,
        )
        thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.02})
        thread.start()

        def cleanup():
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

        self.addCleanup(cleanup)
        return server

    def request(self, server, *, tls=True):
        connection = (
            HTTPSConnection(
                "127.0.0.1", server.server_port, context=self.client_context, timeout=1
            )
            if tls
            else HTTPConnection("127.0.0.1", server.server_port, timeout=1)
        )
        try:
            connection.request("GET", "/")
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            self.assertEqual(response.read(), b"ok")
        finally:
            connection.close()

    def test_incomplete_handshakes_do_not_block_https_and_expire(self):
        server = self.start_server()
        for incomplete in (b"", b"\x16\x03\x03\x00\x20\x01"):
            with self.subTest(incomplete=incomplete):
                with socket.create_connection(server.server_address, timeout=2) as held:
                    if incomplete:
                        held.sendall(incomplete)
                    started = time.monotonic()
                    self.request(server)
                    self.assertLess(time.monotonic() - started, 1)
                    # The held connection is closed by its worker's handshake deadline.
                    self.assertEqual(held.recv(1), b"")
                self.request(server)

    def test_plain_http_still_works_and_idle_headers_expire(self):
        server = self.start_server(tls=False)
        with socket.create_connection(server.server_address, timeout=2) as held:
            held.sendall(b"GET / HTTP/1.1\r\nHost:")
            self.request(server, tls=False)
            self.assertEqual(held.recv(1), b"")
        self.request(server, tls=False)

    def test_worker_capacity_is_bounded_and_recovers(self):
        server = self.start_server(max_workers=1)
        with socket.create_connection(server.server_address, timeout=2) as held:
            # Let the server accept the earlier connection before the next one.
            deadline = time.monotonic() + 1
            while server._workers.acquire(blocking=False):
                server._workers.release()
                if time.monotonic() > deadline:
                    self.fail("idle connection was not accepted")
                time.sleep(0.005)
            with socket.create_connection(server.server_address, timeout=2) as refused:
                self.assertEqual(refused.recv(1), b"")
            self.assertEqual(held.recv(1), b"")
        # Worker releases capacity immediately after closing the expired socket.
        deadline = time.monotonic() + 1
        while True:
            try:
                self.request(server)
                break
            except (OSError, ssl.SSLError):
                if time.monotonic() > deadline:
                    raise
                time.sleep(0.005)

    def test_lan_start_rejects_shared_initial_password(self):
        with self.assertRaisesRegex(ValueError, "individuelles Webpasswort"):
            run("0.0.0.0", 0, access_token=hash_web_password("hvv-anzeiger"))  # noqa: S104
