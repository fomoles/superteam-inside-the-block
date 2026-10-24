"""The measurement runner: dry-run by default, live only with --live.

For each upcoming leader window of a panel validator:
  1. plan PAIRS_PER_WINDOW probe pairs (itb.plan), book their worst-case fees
     against the spend cap (itb.spend) -- refuse and stop if over the cap;
  2. pre-sign every tx with a fresh blockhash;
  3. open a QUIC connection to the target's TPU ~2.5 s ahead;
  4. at the planned instants send first tx, wait dt, send second tx.
In dry-run, step 4 is replaced by logging the exact instant the tx *would*
have been written to the stream plus the slot the clock believed was current
then, so the dry-run measures whether we hit the window without spending.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import time
from pathlib import Path

from solders.hash import Hash
from solders.keypair import Keypair
from solders.message import Message
from solders.pubkey import Pubkey
from solders.system_program import TransferParams, transfer
from solders.transaction import Transaction

from . import plan as P
from .log import log
from .probe import LEVELS, MAX_FEE, build_probe, derive_payer, encode_tag, BASE_FEE
from .rpc import Rpc
from .schedule import WINDOW, SlotClock, leader_windows
from .spend import LAMPORTS_PER_SOL, SpendCapExceeded, SpendLedger
from .tpu import TpuConn

RENT_MIN = 890_880          # rent-exempt minimum for a 0-byte system account
PAYER_TARGET = 1_400_000    # funded balance of each sub-payer
PAYER_FLOOR = RENT_MIN + 120_000
GROUPS = 2                  # concurrent windows; each owns 2*PAIRS_PER_WINDOW payers
LEAD_S = 2.5                # prepare this long before the first send


def load_keypair(path: str) -> Keypair:
    data = json.loads(Path(path).read_text())
    return Keypair.from_bytes(bytes(data))


async def precise_sleep_until(t: float) -> None:
    d = t - time.time()
    if d > 0.004:
        await asyncio.sleep(d - 0.003)
    while time.time() < t:
        await asyncio.sleep(0)


class Runner:
    def __init__(self, args, rpc: Rpc, outdir: Path):
        self.a = args
        self.rpc = rpc
        self.out = outdir
        self.live = bool(args.live)
        self.clock = SlotClock(args.ws_url)
        self.blockhash: str | None = None
        # Dry-runs book into their own ledger so they exercise the cap logic without eating the live budget.
        ledger = Path(args.ledger) if self.live else outdir / "dry-ledger.json"
        self.ledger = SpendLedger(ledger, int(args.cap_sol * LAMPORTS_PER_SOL))
        self.panel = json.loads(Path(args.panel).read_text())["validators"]
        self.by_id = {v["identity"]: v for v in self.panel}
        self.pairs_file = outdir / "pairs.jsonl"
        self.txs_file = outdir / "txs.jsonl"
        self.next_pair = self._resume_pair_id()
        self.free_groups: asyncio.Queue[int] = asyncio.Queue()
        for g in range(GROUPS):
            self.free_groups.put_nowait(g)
        self.windows_done = 0
        self.stop = False
        if self.live:
            self.master = load_keypair(args.keypair)
        else:
            # Dry-run: throwaway keys; nothing signed with them is ever sent.
            self.master = load_keypair(args.keypair) if args.keypair else Keypair()
        self.payers = [derive_payer(self.master, i) for i in range(GROUPS * 2 * P.PAIRS_PER_WINDOW)]

    def _resume_pair_id(self) -> int:
        # Pair ids are global across all runs that share the same ledger (live) so tags never repeat.
        ids = [0]
        for f in self.out.parent.glob("*/pairs.jsonl"):
            for line in f.read_text().splitlines():
                ids.append(json.loads(line)["pair_id"] + 1)
        return max(ids)

    # ---------- background tasks
    async def blockhash_loop(self) -> None:
        while not self.stop:
            try:
                r = await self.rpc.call("getLatestBlockhash", [{"commitment": "confirmed"}], quiet=True)
                self.blockhash = r["value"]["blockhash"]
            except Exception as e:
                log("blockhash_error", error=str(e)[:200])
            await asyncio.sleep(4)

    async def refresh_tpu(self) -> None:
        nodes = {n["pubkey"]: n for n in await self.rpc.call("getClusterNodes")}
        for v in self.panel:
            n = nodes.get(v["identity"], {})
            v["tpuQuic_now"] = n.get("tpuQuic")
            v["client_now"] = n.get("clientId")
            v["version_now"] = n.get("version")
        (self.out / "panel_at_run.json").write_text(json.dumps(self.panel, indent=1))
        changed = [v["identity"] for v in self.panel if (v.get("client_now"), v.get("version_now")) != (v["client"], v["version"])]
        log("panel_refresh", changed_client_or_version=changed)

    # ---------- money (live only)
    async def balances(self) -> dict[str, int]:
        keys = [str(self.master.pubkey())] + [str(p.pubkey()) for p in self.payers]
        r = await self.rpc.call("getMultipleAccounts", [keys, {"commitment": "confirmed", "encoding": "base64"}])
        return {k: (acc["lamports"] if acc else 0) for k, acc in zip(keys, r["value"])}

    async def send_and_confirm(self, tx: Transaction, what: str) -> bool:
        wire = base64.b64encode(bytes(tx)).decode()
        sig = await self.rpc.call("sendTransaction", [wire, {"encoding": "base64", "preflightCommitment": "confirmed"}])
        for _ in range(60):
            await asyncio.sleep(1)
            st = (await self.rpc.call("getSignatureStatuses", [[sig]], quiet=True))["value"][0]
            if st and st.get("confirmationStatus") in ("confirmed", "finalized"):
                log("funding_tx", what=what, sig=sig, err=st.get("err"))
                return st.get("err") is None
        log("funding_tx_timeout", what=what, sig=sig)
        return False

    async def fund_payers(self) -> None:
        bal = await self.balances()
        total = sum(bal.values())
        self.ledger.set_baseline(total)
        self.ledger.check_balance(total)
        log("balances", master=bal[str(self.master.pubkey())], total=total, booked=self.ledger.booked)
        for p in self.payers:
            b = bal[str(p.pubkey())]
            if b >= PAYER_FLOOR:
                continue
            self.ledger.book(BASE_FEE, "fund", str(p.pubkey()))
            bh = (await self.rpc.call("getLatestBlockhash", [{"commitment": "confirmed"}]))["value"]["blockhash"]
            ix = transfer(TransferParams(from_pubkey=self.master.pubkey(), to_pubkey=p.pubkey(), lamports=PAYER_TARGET - b))
            tx = Transaction([self.master], Message.new_with_blockhash([ix], self.master.pubkey(), Hash.from_string(bh)), Hash.from_string(bh))
            await self.send_and_confirm(tx, f"fund {p.pubkey()} +{PAYER_TARGET - b}")

    # ---------- one window
    async def do_window(self, window_slot: int, target: str, group: int) -> None:
        v = self.by_id[target]
        pairs = P.plan_window(self.a.seed, window_slot, target, self.next_pair, group * 2 * P.PAIRS_PER_WINDOW)
        self.next_pair += len(pairs)
        worst = sum(LEVELS[p.first_level].fee + LEVELS[p.second_level].fee for p in pairs)
        try:
            self.ledger.book(worst, "window" if self.live else "window_dry", f"{window_slot}:{target}")
        except SpendCapExceeded:
            self.stop = True
            return
        t_window = self.clock.slot_start(window_slot) - self.a.clock_lag_ms / 1000
        conn = None
        if pairs[0].path == "TPU":
            addr = v.get("tpuQuic_now") or v["tpuQuic"]
            conn = TpuConn(addr, target)
            ok = await conn.open()
            if not ok:
                conn = None
        one_way = (conn.rtt_ms / 2000) if conn and conn.rtt_ms else 0.04
        bh = self.blockhash
        txs = []
        for p in pairs:
            t1 = t_window + p.offset_ms / 1000 - one_way
            for role, level, payer_idx, t_send in ((1, p.first_level, p.payer_first, t1),
                                                   (2, p.second_level, p.payer_second, t1 + p.dt_ms / 1000)):
                tx = build_probe(self.payers[payer_idx], bh, LEVELS[level], encode_tag(p.pair_id, role))
                txs.append((t_send, p, role, level, payer_idx, tx))
            with self.pairs_file.open("a") as f:
                f.write(json.dumps({**p.asdict(), "group": v["group"], "blockhash": bh,
                                    "live": self.live, "window_est_start": t_window}) + "\n")
        txs.sort(key=lambda x: x[0])
        if pairs[0].path == "TPU" and conn is None:
            for t_send, p, role, level, payer_idx, tx in txs:
                self._log_tx(p, role, level, payer_idx, tx, None, "tpu_unreachable", t_send)
            return
        for t_send, p, role, level, payer_idx, tx in txs:
            await precise_sleep_until(t_send)
            wire = bytes(tx)
            if not self.live:
                t_ns, status = time.time_ns(), "dry"
            elif p.path == "TPU":
                t_ns, status = conn.send(wire), "sent_tpu"
            else:
                t_ns, status = time.time_ns(), "sent_rpc"
                asyncio.create_task(self._rpc_send(wire))
            self._log_tx(p, role, level, payer_idx, tx, t_ns, status, t_send)
        await asyncio.sleep(1.0)
        if conn:
            await conn.close()
        self.windows_done += 1

    async def _rpc_send(self, wire: bytes) -> None:
        try:
            await self.rpc.call("sendTransaction", [base64.b64encode(wire).decode(),
                                                    {"encoding": "base64", "skipPreflight": True, "maxRetries": 0}], quiet=True)
        except Exception as e:
            log("rpc_send_error", error=str(e)[:200])

    def _log_tx(self, p, role, level, payer_idx, tx, t_ns, status, t_planned) -> None:
        est_slot = self.clock.slot_at((t_ns or time.time_ns()) / 1e9 + self.a.clock_lag_ms / 1000)
        rec = {"pair_id": p.pair_id, "role": role, "level": level, "fee": LEVELS[level].fee,
               "cu_limit": LEVELS[level].cu_limit, "cu_price": LEVELS[level].cu_price,
               "payer": str(self.payers[payer_idx].pubkey()), "sig": str(tx.signatures[0]),
               "tag": encode_tag(p.pair_id, role), "window_slot": p.window_slot, "target": p.target,
               "path": p.path, "status": status, "t_send_ns": t_ns, "t_planned": t_planned,
               "est_leader_slot_at_send": round(est_slot, 3), "live": self.live}
        with self.txs_file.open("a") as f:
            f.write(json.dumps(rec) + "\n")

    async def window_task(self, slot: int, ident: str, group: int) -> None:
        try:
            await self.do_window(slot, ident, group)
        except Exception as e:
            log("window_error", slot=slot, target=ident, error=f"{type(e).__name__}: {e}"[:300])
        finally:
            self.free_groups.put_nowait(group)

    # ---------- main loop
    async def run(self) -> None:
        log("run_start", live=self.live, cap_lamports=self.ledger.cap, booked=self.ledger.booked,
            max_windows=self.a.max_windows, minutes=self.a.minutes, panel=len(self.panel), out=str(self.out))
        await self.clock.start()
        await self.refresh_tpu()
        tasks = [asyncio.create_task(self.blockhash_loop())]
        while self.blockhash is None:
            await asyncio.sleep(0.2)
        if self.live:
            await self.fund_payers()
        deadline = time.time() + 60 * self.a.minutes
        windows: list[tuple[int, str]] = []
        horizon_end = 0
        started = 0
        inflight: list[asyncio.Task] = []
        last_start = 0
        while not self.stop and time.time() < deadline and started < self.a.max_windows:
            now_slot = self.clock.current_slot()
            if now_slot + 600 > horizon_end:
                windows = await leader_windows(self.rpc, list(self.by_id), now_slot, 3000)
                horizon_end = now_slot + 3000
                log("windows_loaded", n=len(windows), from_slot=now_slot)
            # first window that starts far enough ahead to prepare, and not overlapping the last one
            cand = [(s, i) for s, i in windows
                    if s > last_start + WINDOW and self.clock.slot_start(s) - time.time() > LEAD_S + 0.6]
            if not cand:
                await asyncio.sleep(0.5)
                continue
            slot, ident = cand[0]
            wait = self.clock.slot_start(slot) - time.time() - LEAD_S - 0.5
            group = await self.free_groups.get()
            if wait > 0:
                await asyncio.sleep(wait)
            if self.live and started % 10 == 0:
                bal = await self.balances()
                self.ledger.check_balance(sum(bal.values()))
                if min(bal[str(p.pubkey())] for p in self.payers) < PAYER_FLOOR:
                    await self.fund_payers()
            inflight.append(asyncio.create_task(self.window_task(slot, ident, group)))
            last_start = slot
            started += 1
        await asyncio.gather(*inflight, return_exceptions=True)
        self.stop = True
        for t in tasks:
            t.cancel()
        await self.clock.stop()
        log("run_end", windows_started=started, windows_done=self.windows_done, booked=self.ledger.booked)
