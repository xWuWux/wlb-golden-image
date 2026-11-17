"""Receiver-level checks. VM egress policy and approval remain separate E2E."""

import hashlib
import http.client
import socket
import sys
import unittest
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from channel_receiver import MAX_PAYLOAD_BYTES, receive_canary, transfer_matches  # noqa: E402


class CanaryReceiverTests(unittest.TestCase):
    def post(self, url: str, payload: bytes) -> int:
        conn = http.client.HTTPConnection(url.removeprefix("http://"), timeout=3)
        try:
            conn.request("POST", "/canary", body=payload)
            response = conn.getresponse()
            response.read()
            return response.status
        finally:
            conn.close()

    def test_positive_control_and_duplicates(self):
        payload = b"synthetic-canary:" + uuid4().hex.encode()
        with receive_canary() as receiver:
            self.assertEqual(self.post(receiver.url, payload), 204)
            self.assertTrue(transfer_matches(receiver.snapshot(), payload))
            self.assertFalse(transfer_matches(receiver.snapshot(), payload + b"wrong"))
            self.assertEqual(self.post(receiver.url, payload), 204)
            self.assertFalse(transfer_matches(receiver.snapshot(), payload))

    def test_health_does_not_count_as_transfer(self):
        with receive_canary() as receiver:
            conn = http.client.HTTPConnection(receiver.url.removeprefix("http://"), timeout=3)
            try:
                for _ in range(2):
                    conn.request("GET", "/health")
                    response = conn.getresponse()
                    response.read()
                    self.assertEqual(response.status, 204)
                    self.assertEqual(receiver.snapshot(), ())
            finally:
                conn.close()

    def test_partial_body_is_observed_even_when_sender_fails(self):
        payload = b"partial-canary"
        with receive_canary(read_timeout=0.1) as receiver:
            host, port = receiver.url.removeprefix("http://").split(":")
            with socket.create_connection((host, int(port)), timeout=3) as conn:
                conn.settimeout(3)
                conn.sendall(b"POST /canary HTTP/1.0\r\nContent-Length: 99\r\n\r\n" + payload)
                conn.shutdown(socket.SHUT_WR)
                while conn.recv(4096):
                    pass
            (receipt,) = receiver.snapshot()
            self.assertEqual(receipt.bytes_received, len(payload))
            self.assertEqual(receipt.sha256, hashlib.sha256(payload).hexdigest())
            self.assertFalse(receipt.complete)

    def test_oversized_request_invalidates_observation(self):
        with receive_canary() as receiver:
            self.assertEqual(self.post(receiver.url, b"x" * (MAX_PAYLOAD_BYTES + 1)), 413)
            self.assertFalse(receiver.snapshot()[0].complete)
            self.assertFalse(transfer_matches(receiver.snapshot(), b""))

    def test_stalled_body_preserves_received_prefix(self):
        with receive_canary(read_timeout=0.05) as receiver:
            host, port = receiver.url.removeprefix("http://").split(":")
            with socket.create_connection((host, int(port)), timeout=3) as conn:
                conn.settimeout(3)
                conn.sendall(b"POST /canary HTTP/1.0\r\nContent-Length: 99\r\n\r\nabc")
                while conn.recv(4096):
                    pass
            receipt, = receiver.snapshot()
            self.assertEqual(receipt.bytes_received, 3)
            self.assertFalse(receipt.complete)

    def test_empty_observation_is_not_a_positive_control(self):
        self.assertFalse(transfer_matches((), b"synthetic"))

    def test_sessions_are_isolated(self):
        with receive_canary() as receiver:
            self.assertEqual(self.post(receiver.url, b"synthetic"), 204)
        with receive_canary() as receiver:
            self.assertEqual(receiver.snapshot(), ())


if __name__ == "__main__":
    unittest.main()
