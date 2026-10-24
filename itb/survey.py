"""Cluster survey: who runs which client, with how much stake, and the panel we measure.

Client identity comes from gossip (`getClusterNodes` -> `clientId` + `version`),
i.e. what each node itself advertises at the time of measurement. Stake comes
from `getVoteAccounts`. Both are snapshotted to data/survey/ so the panel's
client labels are frozen at measurement time and can be re-checked.
"""
from __future__ import annotations

import gzip
import json
import time
from collections import defaultdict
from pathlib import Path

from .log import log
from .rpc import Rpc

# Client groups we try to cover, in priority order. Group = gossip clientId.
WANTED_CLIENTS = [
    "Agave", "JitoLabs", "AgaveBam", "HarmonicAgave",
    "Firedancer", "HarmonicFiredancer", "FireBAM", "Rakurai",
]


async def snapshot(rpc: Rpc) -> dict:
    nodes = await rpc.call("getClusterNodes")
    votes = await rpc.call("getVoteAccounts", [{"commitment": "finalized"}])
    epoch = await rpc.call("getEpochInfo", [{"commitment": "finalized"}])
    return {"taken_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "epoch": epoch,
            "nodes": nodes, "votes": votes}


def validators_table(snap: dict) -> list[dict]:
    nodes = {n["pubkey"]: n for n in snap["nodes"]}
    rows = []
    for v in snap["votes"]["current"]:
        n = nodes.get(v["nodePubkey"], {})
        rows.append({
            "identity": v["nodePubkey"], "vote": v["votePubkey"],
            "stake": int(v["activatedStake"]), "commission": v["commission"],
            "client": n.get("clientId") or "unknown", "version": n.get("version") or "unknown",
            "tpuQuic": n.get("tpuQuic"),
        })
    rows.sort(key=lambda r: -r["stake"])
    return rows


def client_mix(rows: list[dict]) -> list[dict]:
    total = sum(r["stake"] for r in rows) or 1
    agg: dict[tuple, list] = defaultdict(lambda: [0, 0])
    for r in rows:
        agg[(r["client"], r["version"])][0] += 1
        agg[(r["client"], r["version"])][1] += r["stake"]
    out = [{"client": c, "version": v, "validators": n, "stake_share": s / total} for (c, v), (n, s) in agg.items()]
    out.sort(key=lambda x: -x["stake_share"])
    return out


def pick_panel(rows: list[dict], per_client: int = 2) -> list[dict]:
    """Top-`per_client` validators by stake for each wanted client, restricted to the
    most common version of that client (so one group = one client+version) and to
    nodes that advertise a QUIC TPU address."""
    panel = []
    for client in WANTED_CLIENTS:
        cand = [r for r in rows if r["client"] == client and r["tpuQuic"]]
        if not cand:
            continue
        by_ver: dict[str, int] = defaultdict(int)
        for r in cand:
            by_ver[r["version"]] += r["stake"]
        ver = max(by_ver, key=by_ver.get)
        panel += [dict(r, group=f"{client} {ver}") for r in cand if r["version"] == ver][:per_client]
    return panel


async def run_survey(rpc: Rpc, outdir: Path, per_client: int = 2, write_panel: Path | None = None) -> dict:
    snap = await snapshot(rpc)
    rows = validators_table(snap)
    mix = client_mix(rows)
    stamp = snap["taken_utc"].replace(":", "")
    outdir.mkdir(parents=True, exist_ok=True)
    raw = outdir / f"cluster-{stamp}.json.gz"
    with gzip.open(raw, "wt") as f:
        json.dump(snap, f)
    summary = {"taken_utc": snap["taken_utc"], "epoch": snap["epoch"]["epoch"], "validators": len(rows),
               "client_mix": mix, "raw": raw.name}
    (outdir / f"mix-{stamp}.json").write_text(json.dumps(summary, indent=1))
    log("survey", validators=len(rows), groups=len(mix), raw=str(raw))
    result = {"summary": summary, "rows": rows}
    if write_panel:
        panel = pick_panel(rows, per_client)
        write_panel.write_text(json.dumps({"chosen_utc": snap["taken_utc"], "epoch": snap["epoch"]["epoch"],
                                           "source": raw.name, "validators": panel}, indent=1))
        log("panel", n=len(panel), groups=sorted({p["group"] for p in panel}))
        result["panel"] = panel
    return result
