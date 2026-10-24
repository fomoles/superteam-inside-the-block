"""Two numbers per client that the pair arms identify together (round 6; exploratory on run 1, pre-registered for run 2).

Model: a pair of probes either waits in the leader's buffer together and is ordered by the scheduler's rule
(probability s), or is placed in arrival order up to a small reordering noise e. Then, with one payer:
  DISC (cheap first, pricy 2nd)  overtake = s       + (1 - s) e
  CONC (pricy first, cheap 2nd)  overtake =           (1 - s) e
  EQ   (equal fees)              overtake = s * tau + (1 - s) e
so  FDS = DISC - CONC = s (1 - 2e)  -- the share of pairs where the fee, not arrival, decides the order, and
    TAU = (EQ - CONC) / (DISC - CONC) -- how the rule breaks a fee tie: 0 = earlier arrival first (FIFO ties),
          0.5 = coin flip, 1 = later arrival first.
FPI = DISC - EQ = FDS (1 - TAU) mixes the two, which is why it reads ~0 for a client that sorts by fee but breaks
ties for the later arrival. The same two numbers with two payers (DISC_SEP, EQ_SEP; no CONC_SEP arm in run 1,
so CONC is used for the baseline) and the ratio pair (RB_FIRST_SHARE = RATIO_AB - RATIO_BA) follow.
CIs: bootstrap over leader windows (all pairs of one window move together), 2000 draws, seed 20261024.
Run: PYTHONPATH=. uv run python scripts/sort_model.py [data dir] [--run RUN_PREFIX] [--fig report/figures/sort_model.png]
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from itb.analyze import load_runs, pair_table

ap = argparse.ArgumentParser()
ap.add_argument("data", nargs="?", default="data")
ap.add_argument("--run", default="", help="only runs whose name starts with this")
ap.add_argument("--fig", default="")
ap.add_argument("--old-panel", default="data/panel.json", help="validators in it are not 'new' for check C7")
a = ap.parse_args()
RNG = np.random.default_rng(20261024)
N_BOOT = 2000
ARMS = ["DISC", "CONC", "EQ", "DISC_SEP", "EQ_SEP", "RATIO_AB", "RATIO_BA"]

r = load_runs(Path(a.data))
D = pair_table(r)
U = D[D.usable & D.live & D.run.str.startswith(a.run)].copy()
U["window_key"] = U.run + ":" + U.window_slot.astype(str)


def stats(rate: dict) -> dict:
    """Model numbers from arm overtake rates (NaN where an arm is missing)."""
    g = lambda k: rate.get(k, np.nan)
    fds = g("DISC") - g("CONC")
    with np.errstate(invalid="ignore", divide="ignore"):
        tau = np.clip((g("EQ") - g("CONC")) / fds, 0, 1) if fds > 0.05 else np.nan
        tau_sep = np.clip((g("EQ_SEP") - g("CONC")) / (g("DISC_SEP") - g("CONC")), 0, 1) \
            if g("DISC_SEP") - g("CONC") > 0.05 else np.nan
    return {"FDS": fds, "TAU": tau, "FDS_sep": g("DISC_SEP") - g("CONC"), "TAU_sep": tau_sep,
            "FPI": g("DISC") - g("EQ"), "RB_FIRST_SHARE": g("RATIO_AB") - g("RATIO_BA"), "CONC": g("CONC")}


DRAWS = {}


def estimate(d: pd.DataFrame, name: str = "") -> tuple[dict, dict, dict]:
    codes, uniq = pd.factorize(d.window_key)
    k = len(uniq)
    num = {m: np.bincount(codes[d.arm.values == m], weights=d.overtake.values[d.arm.values == m].astype(float),
                          minlength=k) for m in ARMS}
    den = {m: np.bincount(codes[d.arm.values == m], minlength=k).astype(float) for m in ARMS}
    n = {m: int(den[m].sum()) for m in ARMS}
    point = stats({m: num[m].sum() / den[m].sum() for m in ARMS if den[m].sum()})
    if k < 3:
        return point, {key: (np.nan, np.nan) for key in point}, n
    W = RNG.multinomial(k, np.full(k, 1 / k), size=N_BOOT)
    with np.errstate(invalid="ignore", divide="ignore"):
        rates = {m: W @ num[m] / (W @ den[m]) for m in ARMS if den[m].sum()}
    draws = [stats({m: rates[m][i] for m in rates}) for i in range(N_BOOT)]
    DRAWS[name] = {key: np.array([x[key] for x in draws]) for key in point}
    ci = {key: tuple(np.nanquantile([x[key] for x in draws], [0.025, 0.975])) if
          np.isfinite([x[key] for x in draws]).sum() > N_BOOT / 2 else (np.nan, np.nan) for key in point}
    return point, ci, n


def f(v, lo, hi, pct=False):
    if not np.isfinite(v):
        return "–"
    s = (lambda x: f"{x:+.2f}") if not pct else (lambda x: f"{x:.2f}")
    return f"{s(v)} [{s(lo)}, {s(hi)}]" if np.isfinite(lo) else s(v)


rows = []
print("# Fee-decides share and tie rule per client (exploratory model, scripts/sort_model.py)\n")
print(f"Runs: {', '.join(sorted(U.run.unique()))}; {len(U)} usable pairs.\n")
print("| subset | pairs DISC/CONC/EQ | FDS = DISC − CONC | TAU (tie rule) | FDS, two payers | TAU, two payers | "
      "FPI = DISC − EQ | RB-first share |\n|---|---|---|---|---|---|---|---|")
REF = ["HarmonicAgave 4.3.2", "HarmonicFiredancer 26.10.4", "Firedancer 26.10.4", "AgaveBam 4.3.2"]
OLD = {v["identity"] for v in __import__("json").loads(Path(a.old_panel).read_text())["validators"]}
subsets = [("all", U)] + [(f"dt = {v} ms", x) for v, x in U.groupby("dt_ms")] + \
    [(f"phase {v}", x) for v, x in U.groupby("phase")] + [(g, x) for g, x in U.groupby("group")] + \
    [("pooled: Harmonic×2, FD 26.10.4, AgaveBam", U[U.group.isin(REF)]),
     ("pooled: all but FD 26.10.4", U[U.group != "Firedancer 26.10.4"]),
     ("validators not in the run-1 panel", U[~U.target.isin(OLD)])]
for name, d in subsets:
    p, ci, n = estimate(d, name)
    rows.append({"subset": name, **{k: p[k] for k in p}, **{k + "_lo": ci[k][0] for k in ci},
                 **{k + "_hi": ci[k][1] for k in ci}, **{"n_" + m: n[m] for m in ARMS}})
    print(f"| {name} | {n['DISC']}/{n['CONC']}/{n['EQ']} | {f(p['FDS'], *ci['FDS'])} | "
          f"{f(p['TAU'], *ci['TAU'], pct=True)} | {f(p['FDS_sep'], *ci['FDS_sep'])} | "
          f"{f(p['TAU_sep'], *ci['TAU_sep'], pct=True)} | {f(p['FPI'], *ci['FPI'])} | "
          f"{f(p['RB_FIRST_SHARE'], *ci['RB_FIRST_SHARE'])} |")
out = pd.DataFrame(rows)
CI = {}

# Contrasts between clients. Groups use disjoint leader windows, so their bootstrap draws are independent.
CONTRASTS = [("FDS", "JitoLabs 4.3.2", "pooled: Harmonic×2, FD 26.10.4, AgaveBam"),
             ("TAU", "Firedancer 26.10.4", "pooled: all but FD 26.10.4"),
             ("FDS", "JitoLabs 4.3.2", "HarmonicAgave 4.3.2"), ("FDS", "JitoLabs 4.3.2", "AgaveBam 4.3.2"),
             ("FDS", "JitoLabs 4.3.2", "Firedancer 26.10.4"), ("TAU", "Firedancer 26.10.4", "JitoLabs 4.3.2"),
             ("TAU", "Firedancer 26.10.4", "HarmonicFiredancer 26.10.4"), ("TAU", "Firedancer 26.10.4", "AgaveBam 4.3.2")]
print("\n| contrast | difference [95 % CI] | share of draws > 0 |\n|---|---|---|")
for key, g1, g2 in CONTRASTS:
    if g1 in DRAWS and g2 in DRAWS:
        diff = DRAWS[g1][key] - DRAWS[g2][key]
        diff = diff[np.isfinite(diff)]
        point = out.set_index("subset").loc[g1, key] - out.set_index("subset").loc[g2, key]
        lo, hi = np.quantile(diff, [0.025, 0.975])
        print(f"| {key}: {g1} − {g2} | {point:+.2f} [{lo:+.2f}, {hi:+.2f}] | {(diff > 0).mean():.3f} |")
        CI[(key, g1, g2)] = (point, lo, hi)

# Checks C1-C7, fixed in notes/preregistration-v2.md before run 2 (on run 1 they are exploratory).
o = out.set_index("subset")
lo_ = lambda sub, k: o.loc[sub, k + "_lo"] if sub in o.index else np.nan
hi_ = lambda sub, k: o.loc[sub, k + "_hi"] if sub in o.index else np.nan
nn = lambda sub, *arms: min(o.loc[sub, "n_" + m] for m in arms) if sub in o.index else 0
J, F, NEW = "JitoLabs 4.3.2", "Firedancer 26.10.4", "validators not in the run-1 panel"


def verdict(enough, holds, fails=None):
    if not enough:
        return "insufficient data"
    return "holds" if holds else ("fails" if fails is None or fails else "inconclusive")


CHECKS = [
    ("C1 pooled FDS: lower CI > 0.30", verdict(nn("all", "DISC", "CONC") >= 40, lo_("all", "FDS") > 0.30)),
    ("C2 a cheaper later tx rarely passes: pooled CONC overtake upper CI ≤ 0.10",
     verdict(nn("all", "CONC") >= 40, hi_("all", "CONC") <= 0.10)),
    ("C3 Jito FDS below the pooled fee-sorters: CI upper < 0",
     verdict(nn(J, "DISC", "CONC") >= 20, CI.get(("FDS", J, "pooled: Harmonic×2, FD 26.10.4, AgaveBam"),
                                                 (0, 0, 1))[2] < 0,
             CI.get(("FDS", J, "pooled: Harmonic×2, FD 26.10.4, AgaveBam"), (0, 1, 1))[1] > 0)),
    ("C4 FD 26.10.4 tie rule: TAU lower CI > 0.5", verdict(nn(F, "DISC", "CONC", "EQ") >= 20, lo_(F, "TAU") > 0.5,
                                                          hi_(F, "TAU") < 0.5)),
    ("C5 FD 26.10.4 TAU above all other clients pooled: CI lower > 0",
     verdict(nn(F, "EQ") >= 20, CI.get(("TAU", F, "pooled: all but FD 26.10.4"), (0, 0, 0))[1] > 0,
             CI.get(("TAU", F, "pooled: all but FD 26.10.4"), (0, 0, 0))[2] < 0)),
    ("C6 ratio pair with capped loaded data: RB-first share upper CI < −0.2 (fee per estimated cost)",
     verdict(nn("all", "RATIO_AB", "RATIO_BA") >= 40, hi_("all", "RB_FIRST_SHARE") < -0.2,
             lo_("all", "RB_FIRST_SHARE") > 0.2)),
    ("C7 validators new in panel v2: FDS lower CI > 0.30", verdict(nn(NEW, "DISC", "CONC") >= 30, lo_(NEW, "FDS") > 0.30)),
]
print("\n| pre-registered check (run 2) | result on these data |\n|---|---|")
for name, res in CHECKS:
    print(f"| {name} | {res} |")
Path(a.data, "results").mkdir(exist_ok=True)
out.to_csv(Path(a.data, "results", f"sort_model{'_' + a.run if a.run else ''}.csv"), index=False)

if a.fig:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    G = out[~out.subset.str.startswith(("all", "dt", "phase"))]
    G = G[(G.n_DISC >= 10) & (G.n_CONC >= 5) & (G.n_EQ >= 10)].sort_values("FDS")
    fig, ax = plt.subplots(1, 2, figsize=(10, 0.45 * len(G) + 1.6), sharey=True)
    y = np.arange(len(G))
    for i, (key, title) in enumerate([("FDS", "fee decides the order\n(DISC − CONC)"),
                                      ("TAU", "fee tie: share placed later-arrival first\n(0 = arrival order, 0.5 = coin)")]):
        ax[i].errorbar(G[key], y, xerr=[G[key] - G[key + "_lo"], G[key + "_hi"] - G[key]], fmt="o", color="#3b6ea5",
                       ecolor="#9db7d5", capsize=3)
        ax[i].axvline(0 if key == "FDS" else 0.5, color="#888", lw=0.8, ls="--")
        ax[i].set_title(title, fontsize=10)
        ax[i].set_xlim(-0.2, 1.05)
    ax[0].set_yticks(y, [f"{g} ({int(n)})" for g, n in zip(G.subset, G.n_DISC + G.n_CONC + G.n_EQ)])
    fig.suptitle("Self-sent probe pairs, mainnet 24.10.2026: per client, 95 % CI (window bootstrap)", fontsize=10)
    fig.tight_layout()
    fig.savefig(a.fig, dpi=130)
    print(f"\nfigure: {a.fig}")
