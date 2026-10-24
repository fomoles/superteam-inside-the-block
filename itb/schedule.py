"""Leader windows of panel validators, and a slot clock to time sends into them.

Leader windows are 4 consecutive slots starting at a slot divisible by 4
(verified on mainnet 24.10: getSlotLeaders shows runs of 4). The slot clock is
fed by `slotSubscribe` (processed) and estimates when a future slot starts.
"""
from __future__ import annotations

import asyncio
import json
import statistics
import time
from collections import deque

import websockets

from .log import log
from .rpc import Rpc

WINDOW = 4


async def leader_windows(rpc: Rpc, identities: list[str], from_slot: int, horizon: int) -> list[tuple[int, str]]:
    """[(window_start_slot, identity)] for windows fully inside [from_slot, from_slot+horizon)."""
    epoch = await rpc.call("getEpochInfo", [{"commitment": "processed"}])
    epoch_start = epoch["absoluteSlot"] - epoch["slotIndex"]
    n = epoch["slotsInEpoch"]
    out = []
    seen_epochs = set()
    for s in (from_slot, from_slot + horizon):
        first = epoch_start + ((s - epoch_start) // n) * n  # first slot of the epoch containing s
        if first in seen_epochs:
            continue
        seen_epochs.add(first)
        for ident in identities:
            # getLeaderSchedule takes a SLOT (any slot in the epoch), not an epoch number.
            sched = await rpc.call("getLeaderSchedule", [s, {"identity": ident}], quiet=True)
            for idx in (sched or {}).get(ident, []):
                slot = first + idx
                if slot % WINDOW == 0 and from_slot <= slot < from_slot + horizon:
                    out.append((slot, ident))
    out.sort()
    return out


class SlotClock:
    """Estimates wall-clock start of slots from a websocket slot stream.

    t(slot) = t_ref + (slot - slot_ref) * slot_ms, with slot_ms the median
    inter-notification gap over the last 200 notifications. Note: this is the
    time *the RPC node tells us* about the slot, so it lags the leader's actual
    slot start by the RPC's shred-propagation + our network latency. The lag is
    an unknown constant offset that the live data calibrates (`landed slot
    index within window`), reported in the report.
    """

    def __init__(self, ws_url: str):
        self.ws_url = ws_url
        self.obs: deque[tuple[int, float]] = deque(maxlen=400)
        self.slot_ms = 400.0
        self._task: asyncio.Task | None = None
        self.ready = asyncio.Event()

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run())
        await asyncio.wait_for(self.ready.wait(), 30)

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()

    async def _run(self) -> None:
        while True:
            try:
                async with websockets.connect(self.ws_url, ping_interval=20, max_size=2**20,
                                              user_agent_header="Mozilla/5.0 inside-the-block/1.0") as ws:
                    await ws.send(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "slotSubscribe"}))
                    async for msg in ws:
                        d = json.loads(msg)
                        if d.get("method") != "slotNotification":
                            continue
                        slot = d["params"]["result"]["slot"]
                        now = time.time()
                        if self.obs and slot <= self.obs[-1][0]:
                            continue
                        self.obs.append((slot, now))
                        self._fit()
                        if len(self.obs) >= 20:
                            self.ready.set()
            except asyncio.CancelledError:
                raise
            except Exception as e:  # reconnect on any websocket failure
                log("clock_reconnect", error=str(e)[:200])
                await asyncio.sleep(1)

    def _fit(self) -> None:
        if len(self.obs) < 10:
            return
        pts = list(self.obs)
        rates = [(t2 - t1) / (s2 - s1) for (s1, t1), (s2, t2) in zip(pts, pts[1:]) if s2 > s1]
        self.slot_ms = 1000 * statistics.median(rates)

    def current_slot(self) -> int:
        return self.obs[-1][0]

    def slot_start(self, slot: int) -> float:
        """Estimated wall time (s) at which the RPC will announce `slot`.

        Robust anchor: median of (t_i - (s_i)*slot_ms) over recent observations.
        """
        pts = list(self.obs)[-60:]
        k = self.slot_ms / 1000
        anchor = statistics.median(t - s * k for s, t in pts)
        return anchor + slot * k

    def slot_at(self, t: float) -> float:
        pts = list(self.obs)[-60:]
        k = self.slot_ms / 1000
        anchor = statistics.median(tt - s * k for s, tt in pts)
        return (t - anchor) / k
