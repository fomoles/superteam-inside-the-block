"""Collect what landed: statuses of our probes and the blocks they (and the panel windows) landed in.

Writes, per run directory:
  landed.jsonl   one row per probe: sig, landed slot (or null), err, index in block, block leader
  blocks/<slot>.json.gz   slim per-block table: every tx's index, signature, fee, priority fee,
                 compute-unit limit/price, consumed CU, cost units, writable accounts, Jito tip flag.
Everything is keyed by signature + slot so a judge can re-check it with `getBlock`.
"""
from __future__ import annotations

import asyncio
import base64
import gzip
import json
import struct
from pathlib import Path

import base58

from .log import log
from .rpc import Rpc, RpcError
from .schedule import WINDOW

COMPUTE_BUDGET = "ComputeBudget111111111111111111111111111111"
# Jito tip accounts (public list, docs.jito.wtf) -- a tx paying one is (almost always) part of a bundle.
JITO_TIP_ACCOUNTS = {
    "96gYZGLnJYVFmbjzopPSU6QiEV5fGqZNyN9nmNhvrZU5", "HFqU5x63VTqvQss8hp11i4wVV8bD44PvwucfZ2bU7gRe",
    "Cw8CFyM9FkoMi7K7Crf6HNQqf4uEMzpKw6QNghXLvLkY", "ADaUMid9yfUytqMBgopwjb2DTLSokTSzL1zt6iGPaS49",
    "DfXygSm4jCyNCybVYYK6DwvWqjKee8pbDmJGcLWNDXjh", "ADuUkR4vqLUMWXxW9gh6D6L8pMSawimctcNZ5pGwDcEt",
    "DttWaMuVvTiduZRnguLF7jNxTgiMBZ1hyAumKUiL2KRL", "3AVi9Tg9Uo68tJfuvoKvqKNWKkC5wPdSSdeBnizKZ6jT",
}


def _cb_params(tx: dict) -> tuple[int | None, int | None]:
    """(cu_limit, cu_price) from ComputeBudget instructions of a jsonParsed/json tx; v1 config wins."""
    msg = tx["transaction"]["message"]
    keys = msg["accountKeys"]
    keys = [k["pubkey"] if isinstance(k, dict) else k for k in keys]
    limit = price = None
    for ix in msg.get("instructions", []):
        pid = ix.get("programId") or keys[ix["programIdIndex"]]
        if pid != COMPUTE_BUDGET or "data" not in ix:
            continue
        raw = base58.b58decode(ix["data"])
        if raw[:1] == b"\x02" and len(raw) >= 5:
            limit = struct.unpack("<I", raw[1:5])[0]
        elif raw[:1] == b"\x03" and len(raw) >= 9:
            price = struct.unpack("<Q", raw[1:9])[0]
    cfg = tx["transaction"].get("transactionConfig") or msg.get("transactionConfig")
    if cfg:
        limit = cfg.get("computeUnitLimit", limit)
    return limit, price


def _writable(tx: dict) -> list[str]:
    msg = tx["transaction"]["message"]
    keys = msg["accountKeys"]
    if keys and isinstance(keys[0], dict):
        w = [k["pubkey"] for k in keys if k.get("writable")]
    else:
        h = msg["header"]
        n, ns, nr = len(keys), h["numRequiredSignatures"], h["numReadonlySignedAccounts"]
        nru = h["numReadonlyUnsignedAccounts"]
        w = [k for i, k in enumerate(keys) if (i < ns - nr) or (ns <= i < n - nru)]
    w += (tx["meta"].get("loadedAddresses") or {}).get("writable", [])
    return w


def slim_block(slot: int, blk: dict) -> dict:
    leader = next((r["pubkey"] for r in blk.get("rewards") or [] if r.get("rewardType") == "Fee"), None)
    rows = []
    for i, tx in enumerate(blk["transactions"]):
        meta = tx["meta"]
        limit, price = _cb_params(tx)
        w = _writable(tx)
        keys = tx["transaction"]["message"]["accountKeys"]
        keys = [k["pubkey"] if isinstance(k, dict) else k for k in keys]
        rows.append({
            "i": i, "sig": tx["transaction"]["signatures"][0], "fee": meta["fee"],
            "cu_limit": limit, "cu_price": price, "cu_used": meta.get("computeUnitsConsumed"),
            "cost": meta.get("costUnits"), "err": meta["err"] is not None, "version": tx.get("version"),
            "writable": w, "jito_tip": bool(JITO_TIP_ACCOUNTS.intersection(keys)),
        })
    return {"slot": slot, "blockhash": blk["blockhash"], "parent_slot": blk["parentSlot"],
            "block_time": blk.get("blockTime"), "leader": leader, "n_tx": len(rows), "txs": rows}


async def fetch_block(rpc: Rpc, slot: int, outdir: Path) -> dict | None:
    path = outdir / f"{slot}.json.gz"
    if path.exists():
        with gzip.open(path, "rt") as f:
            return json.load(f)
    try:
        blk = await rpc.call("getBlock", [slot, {"encoding": "json", "maxSupportedTransactionVersion": 1,
                                                 "transactionDetails": "full", "rewards": True,
                                                 "commitment": "confirmed"}], quiet=True)
    except RpcError as e:
        # -32007 / -32009: slot skipped or not available -> recorded as such
        log("block_missing", slot=slot, error=str(e)[:160])
        blk = None
    if blk is None:
        slim = {"slot": slot, "skipped": True}
    else:
        slim = slim_block(slot, blk)
    outdir.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt") as f:
        json.dump(slim, f)
    return slim


async def _statuses(rpc: Rpc, sigs: list[str]) -> dict[str, dict | None]:
    out = {}
    for i in range(0, len(sigs), 256):
        chunk = sigs[i:i + 256]
        r = await rpc.call("getSignatureStatuses", [chunk, {"searchTransactionHistory": True}], quiet=True)
        out.update(zip(chunk, r["value"]))
    return out


async def collect_run(rpc: Rpc, rundir: Path, passive: bool = True, concurrency: int = 4) -> None:
    txs = [json.loads(l) for l in (rundir / "txs.jsonl").read_text().splitlines()] if (rundir / "txs.jsonl").exists() else []
    pairs = [json.loads(l) for l in (rundir / "pairs.jsonl").read_text().splitlines()] if (rundir / "pairs.jsonl").exists() else []
    blocks_dir = rundir / "blocks"
    sent = [t for t in txs if t["status"].startswith("sent")]
    st = await _statuses(rpc, [t["sig"] for t in sent]) if sent else {}
    slots = {s["slot"] for s in st.values() if s}
    if passive:
        for w in {p["window_slot"] for p in pairs}:
            slots.update(range(w, w + WINDOW))
    sem = asyncio.Semaphore(concurrency)
    blocks: dict[int, dict] = {}

    async def one(s: int) -> None:
        async with sem:
            blocks[s] = await fetch_block(rpc, s, blocks_dir)

    await asyncio.gather(*(one(s) for s in sorted(slots)))
    index = {}
    for s, b in blocks.items():
        for r in (b or {}).get("txs", []):
            index[r["sig"]] = (s, r["i"], b["leader"], b["n_tx"])
    with (rundir / "landed.jsonl").open("w") as f:
        for t in txs:
            s = st.get(t["sig"])
            pos = index.get(t["sig"])
            f.write(json.dumps({"sig": t["sig"], "pair_id": t["pair_id"], "role": t["role"],
                                "landed_slot": s["slot"] if s else None, "err": s.get("err") if s else None,
                                "index": pos[1] if pos else None, "block_leader": pos[2] if pos else None,
                                "block_n_tx": pos[3] if pos else None}) + "\n")
    n_landed = sum(1 for t in txs if st.get(t["sig"]))
    log("collect", run=rundir.name, txs=len(txs), sent=len(sent), landed=n_landed, blocks=len(blocks),
        skipped=sum(1 for b in blocks.values() if b and b.get("skipped")))


async def collect_passive(rpc: Rpc, panel: list[dict], per_validator: int, outdir: Path,
                          concurrency: int = 2) -> None:
    """Blocks from the most recent *past* leader windows of every panel validator (current epoch).

    Needs no money and no waiting: the leader schedule is public and recent blocks are served by RPC.
    Deterministic choice: the `per_validator` latest complete windows that ended >= 64 slots ago.
    """
    now = await rpc.call("getSlot", [{"commitment": "confirmed"}])
    epoch = await rpc.call("getEpochInfo", [{"commitment": "confirmed"}])
    first = epoch["absoluteSlot"] - epoch["slotIndex"]
    slots = []
    for v in panel:
        sched = await rpc.call("getLeaderSchedule", [now, {"identity": v["identity"]}], quiet=True)
        starts = sorted(first + i for i in (sched or {}).get(v["identity"], [])
                        if (first + i) % WINDOW == 0 and first + i + WINDOW < now - 64)
        for w in starts[-per_validator:]:
            slots += range(w, w + WINDOW)
    log("passive_plan", validators=len(panel), windows=len(slots) // WINDOW, slots=len(slots), now=now)
    sem = asyncio.Semaphore(concurrency)
    done = 0

    async def one(s: int) -> None:
        nonlocal done
        async with sem:
            await fetch_block(rpc, s, outdir)
            done += 1
            if done % 50 == 0:
                log("passive_progress", done=done, of=len(slots))

    await asyncio.gather(*(one(s) for s in sorted(slots)))
