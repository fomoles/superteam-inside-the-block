"""Read-only check before a live run: is the key loadable, funded enough, and does a probe simulate?

Sends nothing. Uses getMultipleAccounts, getLatestBlockhash and simulateTransaction (free, not broadcast).
Exit code 0 = ready for `run --live`, 1 = not ready (the reason is printed).
"""
from __future__ import annotations

import base64
from pathlib import Path

from . import plan as P
from .probe import BASE_FEE, LEVELS, build_probe, derive_payer
from .rpc import Rpc
from .run import GROUPS, PAYER_FLOOR, PAYER_TARGET, load_keypair
from .spend import LAMPORTS_PER_SOL, SpendLedger


def sol(lamports: int) -> str:
    return f"{lamports / LAMPORTS_PER_SOL:.6f} SOL"


async def preflight(rpc: Rpc, keypair_path: str, ledger_path: str, cap_sol: float, windows: int) -> bool:
    if not keypair_path or not Path(keypair_path).exists():
        print(f"NOT READY: keypair file not found ({keypair_path!r}); set --keypair or $ITB_KEYPAIR")
        return False
    master = load_keypair(keypair_path)
    payers = [derive_payer(master, i) for i in range(GROUPS * 2 * P.PAIRS_PER_WINDOW)]
    keys = [str(master.pubkey())] + [str(p.pubkey()) for p in payers]
    bal = await rpc.balances(keys)
    m, sub = bal[0], bal[1:]

    # What the live run will move out of the master key: top-ups of every sub-payer below the floor
    # (each a 5000-lamport transfer), then the probes' fees, paid by the sub-payers.
    topup = sum(PAYER_TARGET - b for b in sub if b < PAYER_FLOOR)
    topup_fees = BASE_FEE * sum(1 for b in sub if b < PAYER_FLOOR)
    # Booked (worst-case) fee per window, averaged over the plan's own arm mix.
    sample = [sum(LEVELS[p.first_level].fee + LEVELS[p.second_level].fee for p in P.plan_window(20261024, s * 4, keys[0], 0, 0))
              for s in range(400)]
    per_window = sum(sample) // len(sample)
    fees = per_window * windows
    ledger = SpendLedger(Path(ledger_path), int(cap_sol * LAMPORTS_PER_SOL))
    print(f"master      {keys[0]}  {sol(m)}")
    print(f"sub-payers  {len(sub)}, holding {sol(sum(sub))} (each is topped up to {sol(PAYER_TARGET)}, refundable by `sweep`)")
    print(f"ledger      {ledger_path}: booked {sol(ledger.booked)} of cap {sol(ledger.cap)}")
    print(f"needed now  top-ups {sol(topup)} + their fees {sol(topup_fees)}")
    print(f"fees        worst case {sol(per_window)} per window x {windows} windows = {sol(fees)} (only landed txs pay)")

    ok = True
    if m < topup + topup_fees + 10 * BASE_FEE:
        print(f"NOT READY: master holds {sol(m)}, needs at least {sol(topup + topup_fees + 10 * BASE_FEE)} to fund the sub-payers")
        ok = False
    if ledger.remaining < per_window:
        print(f"NOT READY: spend cap exhausted (remaining {sol(ledger.remaining)})")
        ok = False
    elif ledger.remaining < fees:
        print(f"note: the cap allows ~{ledger.remaining // per_window} windows, the run will stop there")

    # A probe signed by the master key, simulated (not sent): checks the tx format against today's runtime.
    bh = (await rpc.call("getLatestBlockhash", [{"commitment": "confirmed"}]))["value"]["blockhash"]
    tx = build_probe(master, bh, LEVELS["MID"], 1)
    sim = (await rpc.call("simulateTransaction", [base64.b64encode(bytes(tx)).decode(),
                                                  {"encoding": "base64", "sigVerify": True, "commitment": "confirmed"}]))["value"]
    if sim.get("err") is None:
        print(f"simulate    probe OK, {sim.get('unitsConsumed')} CU (limit {LEVELS['MID'].cu_limit})")
    elif m == 0:
        print(f"simulate    probe not checkable yet: {sim['err']} (the key holds no SOL)")
    else:
        print(f"NOT READY: probe simulation failed: {sim['err']}  logs: {(sim.get('logs') or [])[-3:]}")
        ok = False
    print("READY for `run --live`" if ok else "fix the items above, then run preflight again")
    return ok
