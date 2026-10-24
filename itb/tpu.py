"""Direct-to-leader sending over QUIC (the TPU path).

Solana leaders accept transactions on their `tpuQuic` port: one transaction
per unidirectional QUIC stream, ALPN "solana-tpu", self-signed Ed25519 client
certificate (unstaked senders get a small but non-zero stream quota). Sending
only to the target leader's TPU means a probe can land only in that leader's
block -- or nowhere (no fee is charged for a tx that never lands).

Verified 24.10.2026 from this machine: handshakes to Agave, Jito-Agave,
Harmonic-Agave and Harmonic-Firedancer TPUs complete in 82-117 ms.
"""
from __future__ import annotations

import asyncio
import datetime
import ssl
import time

from aioquic.asyncio import connect
from aioquic.asyncio.protocol import QuicConnectionProtocol
from aioquic.quic.configuration import QuicConfiguration
from cryptography import x509
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.x509.oid import NameOID

from .log import log


def _client_cert():
    key = ed25519.Ed25519PrivateKey.generate()
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Solana node")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1)).not_valid_after(now + datetime.timedelta(days=365))
            .sign(key, None))
    return cert, key


class TpuConn:
    def __init__(self, addr: str, identity: str):
        self.addr = addr
        self.identity = identity
        self._cm = None
        self.proto: QuicConnectionProtocol | None = None
        self.rtt_ms: float | None = None

    async def open(self, timeout: float = 3.0) -> bool:
        host, port = self.addr.rsplit(":", 1)
        cfg = QuicConfiguration(is_client=True, alpn_protocols=["solana-tpu"], verify_mode=ssl.CERT_NONE,
                                idle_timeout=20.0)
        cfg.certificate, cfg.private_key = _client_cert()
        t0 = time.perf_counter()
        try:
            self._cm = connect(host, int(port), configuration=cfg, wait_connected=True)
            self.proto = await asyncio.wait_for(self._cm.__aenter__(), timeout)
            t1 = time.perf_counter()
            await asyncio.wait_for(self.proto.ping(), timeout)
            self.rtt_ms = 1000 * (time.perf_counter() - t1)
            log("tpu_open", identity=self.identity, addr=self.addr, handshake_ms=round(1000 * (t1 - t0), 1),
                rtt_ms=round(self.rtt_ms, 1))
            return True
        except Exception as e:
            log("tpu_open_failed", identity=self.identity, addr=self.addr, error=f"{type(e).__name__}: {e}"[:200])
            self.proto = None
            return False

    def send(self, wire: bytes) -> int:
        """Write one tx on a fresh uni stream and flush. Returns wall-clock ns of the flush."""
        assert self.proto is not None
        q = self.proto._quic
        sid = q.get_next_available_stream_id(is_unidirectional=True)
        q.send_stream_data(sid, wire, end_stream=True)
        self.proto.transmit()
        return time.time_ns()

    async def close(self) -> None:
        if self._cm is not None and self.proto is not None:
            try:
                await asyncio.wait_for(self._cm.__aexit__(None, None, None), 2)
            except Exception:
                pass
        self.proto = None
