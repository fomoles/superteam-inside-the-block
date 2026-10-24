"""Live layer, pooled and by factor (exploratory, round 4; the pre-registered per-group test stays in itb.analyze).

The per-group arms are thin (a few dozen usable pairs per client), so this script asks the questions the data can
answer with all clients pooled, and says which client groups drive each number:
  A. landing: which probes made it into a block at all -- by path (direct TPU vs public RPC), client group,
     phase (sent before / inside the window), fee level, gap dt, role (1st / 2nd of the pair);
  B. order inside a block: overtake rate per arm, pooled, and the fee-priority index DISC - EQ, also by dt;
  C. where in the window the probes land (slot 1..4) by phase.
CIs: bootstrap over leader windows (all probes of one window move together). Same pair definition as itb.analyze.
Run: PYTHONPATH=. uv run python scripts/live_analysis.py [data dir, default data]
"""
import gzip
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from itb.analyze import load_runs, pair_table
from itb.survey import validators_table

DATA = Path(sys.argv[1] if len(sys.argv) > 1 else "data")
RNG = np.random.default_rng(20261024)
N_BOOT = 2000


def boot(df: pd.DataFrame, col: str, a: str | None = None, b: str | None = None, cluster="window_key"):
    """Point estimate and 95 % CI of the mean of 0/1 column `col` (or, with arms a and b, of
    mean over arm a - mean over arm b), resampling whole clusters (multinomial cluster weights)."""
    df = df[df[col].notna()]
    if df.empty:
        return np.nan, np.nan, np.nan
    codes, uniq = pd.factorize(df[cluster])
    k = len(uniq)
    W = RNG.multinomial(k, np.full(k, 1 / k), size=N_BOOT) if k >= 3 else None

    def parts(d):
        c = codes[df.index.get_indexer(d.index)]
        return (np.bincount(c, weights=d[col].astype(float).to_numpy(), minlength=k),
                np.bincount(c, minlength=k).astype(float))

    with np.errstate(invalid="ignore", divide="ignore"):
        if a is None:
            num, den = parts(df)
            est, bs = num.sum() / den.sum(), (W @ num / (W @ den) if W is not None else None)
        else:
            (na, da), (nb, db) = parts(df[df.arm == a]), parts(df[df.arm == b])
            if not da.sum() or not db.sum():
                return np.nan, np.nan, np.nan
            est = na.sum() / da.sum() - nb.sum() / db.sum()
            bs = W @ na / (W @ da) - W @ nb / (W @ db) if W is not None else None
    if bs is None:
        return est, np.nan, np.nan
    lo, hi = np.nanquantile(bs, [0.025, 0.975])
    return est, lo, hi


def fmt(e, lo, hi, pct=True):
    if np.isnan(e):
        return "–"
    f = (lambda v: f"{100 * v:.0f} %") if pct else (lambda v: f"{v:+.2f}")
    return f"{f(e)} [{f(lo)}, {f(hi)}]" if not np.isnan(lo) else f(e)


def table(title, df, by, col, n_label="n", pct=True):
    print(f"\n### {title}\n")
    print(f"| {by} | {n_label} | windows | estimate [95 % CI] |\n|---|---|---|---|")
    for k, d in df.groupby(by):
        print(f"| {k} | {len(d)} | {d.window_key.nunique()} | {fmt(*boot(d, col), pct=pct)} |")
    print(f"| **all** | {len(df)} | {df.window_key.nunique()} | {fmt(*boot(df, col), pct=pct)} |")


r = load_runs(DATA)
P, T, L = r["pairs"], r["txs"], r["landed"]
if L.empty or "live" not in P or not P.live.any():
    sys.exit("no collected live run (need landed.jsonl from `itb collect`)")

# ---- A. landing, one row per sent probe
T = T[T.live & T.status.str.startswith("sent")].copy()
T = T.join(L.set_index("sig")[["landed_slot", "block_leader"]], on="sig")
T = T.merge(P[["run", "pair_id", "arm", "phase", "dt_ms", "group"]], on=["run", "pair_id"], how="left")
T["landed"] = T.landed_slot.notna()
T["window_key"] = T.run + ":" + T.window_slot.astype(str)
T["late_ms"] = (T.t_send_ns / 1e9 - T.t_planned) * 1000
runs = sorted(T.run.unique())
print(f"# Live layer, pooled ({', '.join(runs)})\n")
print(f"{len(T)} probes sent in {T.window_key.nunique()} leader windows of {T.target.nunique()} validators "
      f"({T.group.nunique()} client groups); {int(T.landed.sum())} landed.")
table("A1. Landing by path", T, "path", "landed", "probes")
tpu = T[T.path == "TPU"]
table("A2. Landing by client group (direct TPU only)", tpu, "group", "landed", "probes")
table("A3. Landing by phase (TPU): PRE = sent before the window starts, IN = inside it", tpu, "phase", "landed", "probes")
table("A4. Landing by fee level (TPU)", tpu, "level", "landed", "probes")
table("A5. Landing by gap between the two probes of a pair (TPU)", tpu, "dt_ms", "landed", "probes")
table("A6. Landing by role in the pair (TPU)", tpu, "role", "landed", "probes")
tpu = tpu.assign(late=np.where(tpu.late_ms > 50, "sent > 50 ms late", "on time"))
table("A7. Landing by send punctuality (TPU)", tpu, "late", "landed", "probes")
off = T[T.landed & (T.block_leader != T.target)]
print(f"\nLanded in a block of a different leader than the target: {len(off)} of {int(T.landed.sum())} "
      f"(by target group: {off.group.value_counts().to_dict()}; by path: {off.path.value_counts().to_dict()}).")
snaps = sorted((DATA / "survey").glob("cluster-*.json.gz"))
if snaps and len(off):
    # a direct-TPU probe can only reach another leader through whatever sits behind the target's tpuQuic address
    tip = {r["identity"]: (r["tpuQuic"] or "").rsplit(":", 1)[0] for r in validators_table(json.load(gzip.open(snaps[-1])))}
    ot_ = off[off.path == "TPU"]
    same = sum(tip.get(a) and tip.get(a) == tip.get(b) for a, b in zip(ot_.target, ot_.block_leader))
    print(f"Of the {len(ot_)} direct-TPU probes among them, {same} landed with a leader that advertises the same tpuQuic IP "
          f"as the target (shared front-end, see scripts/shared_tpu.py).")

# ---- B. order inside a block
D = pair_table(r)
U = D[D.usable].copy()
print(f"\n## B. Order inside a block\n\n{len(D)} live pairs, {int(D.same_block.sum())} with both probes in the same "
      f"block, {len(U)} usable (same block, on target, sent <= 50 ms late).")
table("B1. Overtake rate (2nd probe placed before the 1st) by arm, all clients pooled", U, "arm", "overtake", "usable pairs")


print("\n### B2. Fee-priority index (overtake DISC - overtake EQ), pooled and by gap\n")
print("| subset | usable DISC / EQ | FPI [95 % CI] | same, non-conflicting (DISC_SEP - EQ_SEP) |\n|---|---|---|---|")
for k, d in [("all", U)] + [(f"dt = {v} ms", x) for v, x in U.groupby("dt_ms")] + \
        [(f"phase {v}", x) for v, x in U.groupby("phase")] + [(g, x) for g, x in U.groupby("group")]:
    n = f"{(d.arm == 'DISC').sum()} / {(d.arm == 'EQ').sum()}"
    print(f"| {k} | {n} | {fmt(*boot(d, 'overtake', 'DISC', 'EQ'), pct=False)} | {fmt(*boot(d, 'overtake', 'DISC_SEP', 'EQ_SEP'), pct=False)} |")
table("B3. FIFO check: overtake rate of equal-fee pairs (EQ + EQ_SEP) by gap", U[U.arm.isin(["EQ", "EQ_SEP"])],
      "dt_ms", "overtake", "usable pairs")
D["window_key"] = D.run + ":" + D.window_slot.astype(str)
table("B4. Both probes of a pair in the same block, by gap (TPU pairs)", D[D.path == "TPU"], "dt_ms", "same_block", "pairs")

# ---- C. where in the window
lt = T[T.landed & (T.block_leader == T.target)].copy()
s = (lt.landed_slot - lt.window_slot + 1).astype(int)
# past slot 4 the probe sat in the leader's buffer and went into one of its *later* windows
lt["slot_in_window"] = np.where(s <= 4, "slot " + s.astype(str), np.where(s < 1, "earlier", "later window"))
print("\n## C. Slot of the window the probe landed in (slot 1 = window's first block; target leader only)\n")
ct = pd.crosstab(lt.phase, lt.slot_in_window)
print("| phase | " + " | ".join(str(c) for c in ct.columns) + " |\n|---|" + "---|" * len(ct.columns))
for ph, row in ct.iterrows():
    print(f"| {ph} | " + " | ".join(str(v) for v in row.values) + " |")
later = lt[lt.slot_in_window == "later window"]
if len(later):
    gap = (later.landed_slot - later.window_slot).astype(int)
    print(f"\n{len(later)} probes landed in a later window of the same leader (gap {gap.min()}-{gap.max()} slots, "
          f"blockhash still valid); by group: {later.group.value_counts().to_dict()}.")
