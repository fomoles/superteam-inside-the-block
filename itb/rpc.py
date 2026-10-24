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

DEFAULT_MAINNET = ["https://api.mainnet-beta.solana.com"]
DEFAULT_DEVNET = ["https://api.devnet.solana.com"]
# Public RPC tiers drop requests without a browser-like User-Agent.
HEADERS = {"content-type": "application/json", "user-agent": "Mozilla/5.0 inside-the-block/1.0"}


def endpoints_for(network: str) -> list[str]:
    env = os.environ.get("ITB_RPC_URLS")
    if env:
        return [u.strip() for u in env.split(",") if u.strip()]
    return DEFAULT_MAINNET if network == "mainnet" else DEFAULT_DEVNET


DETERMINISTIC = (-32007, -32009, -32602, -32015, -32016)


class RpcError(Exception):
    def __init__(self, method: str, error: dict):
        super().__init__(f"{method}: {error}")
        self.error = error


class Rpc:
    def __init__(self, urls: list[str], timeout: float = 60.0, retries: int = 5):
        self.urls = urls
        self.retries = retries
        self.client = httpx.AsyncClient(timeout=timeout, headers=HEADERS, http2=False)
        self._id = 0

    async def close(self) -> None:
        await self.client.aclose()

    async def call(self, method: str, params: list | None = None, *, quiet: bool = False):
        last: Exception | None = None
        for attempt in range(self.retries):
            url = self.urls[attempt % len(self.urls)]
            self._id += 1
            t0 = time.perf_counter()
            try:
                r = await self.client.post(url, json={"jsonrpc": "2.0", "id": self._id, "method": method, "params": params or []})
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
            await asyncio.sleep(min(8.0, 0.5 * 2 ** attempt) + random.random() * 0.3)
        raise RuntimeError(f"RPC {method} failed after {self.retries} attempts: {last}")
