"""Hard fee spend cap.

Two independent guards:
 1. Ledger guard (pre-send): every transaction's worst-case fee is *booked and
    persisted to disk before it is sent*. A send that would push the booked
    total over the cap raises SpendCapExceeded and is never sent. The ledger
    survives restarts, so the cap is global across sessions, not per process.
 2. Balance guard (live only): before each window the runner sums the balances
    of the master key and all sub-payers; if the drop since the first ever
    measurement exceeds the cap, it stops. This catches anything the ledger
    could miss (e.g. a bug in fee computation).
Fees are only charged for landed txs, so booked >= actual; the report states both.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from .log import log

LAMPORTS_PER_SOL = 1_000_000_000


class SpendCapExceeded(Exception):
    pass


class SpendLedger:
    def __init__(self, path: Path, cap_lamports: int):
        self.path = path
        self.cap = cap_lamports
        self.state = {"booked": 0, "entries": 0, "baseline_balance": None}
        if path.exists():
            self.state.update(json.loads(path.read_text()))

    @property
    def booked(self) -> int:
        return self.state["booked"]

    @property
    def remaining(self) -> int:
        return self.cap - self.booked

    def can_book(self, lamports: int) -> bool:
        return self.booked + lamports <= self.cap

    def book(self, lamports: int, kind: str, ref: str) -> None:
        if not self.can_book(lamports):
            log("spend_refused", kind=kind, ref=ref, lamports=lamports, booked=self.booked, cap=self.cap)
            raise SpendCapExceeded(f"booking {lamports} would exceed cap {self.cap} (booked {self.booked})")
        self.state["booked"] += lamports
        self.state["entries"] += 1
        self.state["updated_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self._save()

    def set_baseline(self, balance: int) -> None:
        if self.state.get("baseline_balance") is None:
            self.state["baseline_balance"] = balance
            self._save()

    def check_balance(self, balance_now: int) -> None:
        base = self.state.get("baseline_balance")
        if base is not None and base - balance_now > self.cap:
            log("spend_balance_guard", baseline=base, now=balance_now, cap=self.cap)
            raise SpendCapExceeded(f"balance dropped {base - balance_now} > cap {self.cap}")

    def _save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(self.state, indent=1))
        os.replace(tmp, self.path)
