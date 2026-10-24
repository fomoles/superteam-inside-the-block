"""Minimal async JSON-RPC client for Solana with retries and endpoint rotation.

Every call is logged (method, endpoint, latency, error) so that RPC flakiness
is visible in the run log instead of silently shaping the data.
"""
from __future__ import annotations

import asyncio
import os
import random
import time

import httpx

from .log import log

# Two public mainnet endpoints that need no sign-up (checked 24.10.2026); calls rotate between them.
DEFAULT_MAINNET = ["https://api.mainnet-beta.solana.com", "https://solana-rpc.publicnode.com"]
DEFAULT_DEVNET = ["https://api.devnet.solana.com"]
# Public RPC tiers drop requests without a browser-like User-Agent.
HEADERS = {"content-type": "application/json", "user-agent": "Mozilla/5.0 inside-the-block/1.0"}


def endpoints_for(network: str) -> list[str]:
    env = os.environ.get("ITB_RPC_URLS")
    if env:
        return [u.strip() for u in env.split(",") if u.strip()]
    return DEFAULT_MAINNET if network == "mainnet" else DEFAULT_DEVNET


HEAVY = ("getBlock", "getClusterNodes", "getLeaderSchedule", "getVoteAccounts")
DETERMINISTIC = (-32007, -32009, -32602, -32015, -32016)


class RpcError(Exception):
    def __init__(self, method: str, error: dict):
        super().__init__(f"{method}: {error}")
        self.error = error


class Rpc:
    def __init__(self, urls: list[str], timeout: float = 60.0, retries: int = 8):
        self.urls = urls
        self.retries = retries
        # Public endpoints rate-limit heavy methods hard (getBlock: HTTP 429 after a few calls),
        # so heavy calls are paced; a private RPC can set ITB_RPC_HEAVY_INTERVAL_S=0.
        self.heavy_interval = float(os.environ.get("ITB_RPC_HEAVY_INTERVAL_S", "1.0"))
        self._heavy_lock = {u: asyncio.Lock() for u in urls}
        self._heavy_last = {u: 0.0 for u in urls}
        self._rr = 0
        self.client = httpx.AsyncClient(timeout=timeout, headers=HEADERS, http2=False)
        self._id = 0

    async def close(self) -> None:
        await self.client.aclose()

    async def balances(self, keys: list[str]) -> list[int]:
        """Lamports per account; chunked because public RPCs cap getMultipleAccounts at 10 keys."""
        out = []
        for i in range(0, len(keys), 10):
            r = await self.call("getMultipleAccounts", [keys[i:i + 10], {"commitment": "confirmed", "encoding": "base64"}])
            out += [acc["lamports"] if acc else 0 for acc in r["value"]]
        return out

    async def call(self, method: str, params: list | None = None, *, quiet: bool = False):
        last: Exception | None = None
        retry_after = 0.0
        self._rr += 1
        for attempt in range(self.retries):
            url = self.urls[(self._rr + attempt) % len(self.urls)]
            if method in HEAVY:  # paced per endpoint
                async with self._heavy_lock[url]:
                    wait = self._heavy_last[url] + self.heavy_interval - time.monotonic()
                    if wait > 0:
                        await asyncio.sleep(wait)
                    self._heavy_last[url] = time.monotonic()
            self._id += 1
            t0 = time.perf_counter()
            try:
                r = await self.client.post(url, json={"jsonrpc": "2.0", "id": self._id, "method": method, "params": params or []})
                if r.status_code == 429:
                    retry_after = float(r.headers.get("retry-after") or 0)
                if r.status_code == 429 or r.status_code >= 500:
                    raise httpx.HTTPStatusError(f"HTTP {r.status_code}", request=r.request, response=r)
                body = r.json()
                if "error" in body:
                    raise RpcError(method, body["error"])
                if not quiet:
                    log("rpc", method=method, url=url, ms=round(1000 * (time.perf_counter() - t0), 1))
                return body["result"]
            except RpcError as e:
                # Deterministic errors (skipped slot, bad params, unsupported version) are not retried.
                if e.error.get("code") in DETERMINISTIC:
                    raise
                last = e
            except (httpx.HTTPError, ValueError) as e:
                last = e
            log("rpc_retry", method=method, url=url, attempt=attempt, error=str(last)[:200])
            await asyncio.sleep(max(retry_after, min(30.0, 0.5 * 2 ** attempt)) + random.random() * 0.3)
            retry_after = 0.0
        raise RuntimeError(f"RPC {method} failed after {self.retries} attempts: {last}")
