"""Shared TPU ingress (exploratory, round 4): whose "own TPU" is actually a shared front door?

Every validator advertises in gossip the QUIC address where it takes transactions (`tpuQuic`). A probe sent
"straight to the leader's TPU" goes to that address. If many identities advertise the same IP, txs reach a
shared front-end (a block-building relay or engine) first, and that front-end, not the validator client,
decides what is forwarded, in what order, and to which of its leaders.
From the cluster snapshot of the survey: for every client group, how much of its stake sits behind an IP that
>= SHARED staked identities advertise, and the largest shared IPs with their client mix.
Run: PYTHONPATH=. uv run python scripts/shared_tpu.py [survey snapshot .json.gz, default: latest]
"""
import collections
import gzip
import json
import sys
from pathlib import Path

from itb.survey import validators_table

SHARED = 3
snap_path = Path(sys.argv[1]) if len(sys.argv) > 1 else sorted(Path("data/survey").glob("cluster-*.json.gz"))[-1]
rows = validators_table(json.load(gzip.open(snap_path)))
total = sum(r["stake"] for r in rows)
ip = lambda r: (r["tpuQuic"] or "").rsplit(":", 1)[0] or None
by_ip = collections.defaultdict(list)
for r in rows:
    if ip(r):
        by_ip[ip(r)].append(r)
shared = {k for k, v in by_ip.items() if len(v) >= SHARED}

print(f"# Shared TPU ingress ({snap_path.name}, {len(rows)} staked validators)\n")
print(f"An IP counts as shared when >= {SHARED} staked identities advertise it as their tpuQuic.\n")
print("| client version | validators | stake share | validators behind a shared IP | their stake share |"
      "\n|---|---|---|---|---|")
g = collections.defaultdict(lambda: [0, 0, 0, 0])
for r in rows:
    k = f"{r['client']} {r['version']}"
    g[k][0] += 1
    g[k][1] += r["stake"]
    if ip(r) in shared:
        g[k][2] += 1
        g[k][3] += r["stake"]
for k, (n, s, ns, ss) in sorted(g.items(), key=lambda kv: -kv[1][1]):
    if s / total >= 0.001:
        print(f"| {k} | {n} | {100 * s / total:.1f} % | {ns} | {100 * ss / max(s, 1):.0f} % of the group |")
alls = sum(r["stake"] for r in rows if ip(r) in shared)
print(f"| **all** | {len(rows)} | 100 % | {sum(1 for r in rows if ip(r) in shared)} | {100 * alls / total:.0f} % |")

print("\n| shared IP | identities | stake share | client mix |\n|---|---|---|---|")
for k, v in sorted(((k, by_ip[k]) for k in shared), key=lambda kv: -len(kv[1]))[:12]:
    mix = collections.Counter(f"{r['client']} {r['version']}" for r in v).most_common(3)
    print(f"| {k} | {len(v)} | {100 * sum(r['stake'] for r in v) / total:.1f} % | "
          + ", ".join(f"{c} ×{n}" for c, n in mix) + " |")

panel = json.loads(Path("data/panel.json").read_text())["validators"]
idx = {r["identity"]: r for r in rows}
print("\nPanel validators behind a shared IP:")
for v in panel:
    r = idx.get(v["identity"])
    if r and ip(r) in shared:
        print(f"- {v['group']} {v['identity']}: {ip(r)} (shared by {len(by_ip[ip(r)])} identities)")
