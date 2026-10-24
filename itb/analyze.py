"""Analysis: everything in report/results.md and report/figures/ is produced here from data/ alone.

Three layers, each usable on its own:
  ACTIVE   self-sent probe pairs (needs a live run)   -> pre-registered quantities, verdicts per group
  PASSIVE  blocks of panel leaders (no money needed)   -> descriptive fee-vs-position, conflict vs not
  TIMING   dry-run/live send log                       -> did we aim at the right slot
Statistics follow notes/preregistration.md: cluster bootstrap over windows, Holm across groups.
"""
from __future__ import annotations

import gzip
import json
import math
import random
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

from .log import log
from .probe import LEVELS

B = 5000
SEED = 1
MIN_PAIRS = 20
HEAD = 64  # txs at the start of a block used for the 'head' rank test


def _jsonl(p: Path) -> list[dict]:
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()] if p.exists() else []


def load_runs(data: Path) -> dict[str, pd.DataFrame]:
    pairs, txs, landed, panels = [], [], [], {}
    for rd in sorted((data / "runs").glob("*")):
        if not rd.is_dir():
            continue
        for rows, name in ((pairs, "pairs.jsonl"), (txs, "txs.jsonl"), (landed, "landed.jsonl")):
            for r in _jsonl(rd / name):
                r["run"] = rd.name
                rows.append(r)
        if (rd / "panel_at_run.json").exists():
            for v in json.loads((rd / "panel_at_run.json").read_text()):
                panels[v["identity"]] = v["group"]
    return {"pairs": pd.DataFrame(pairs), "txs": pd.DataFrame(txs), "landed": pd.DataFrame(landed),
            "groups": panels}


def load_blocks(data: Path) -> list[dict]:
    seen, out = set(), []
    for p in sorted(data.glob("**/blocks/*.json.gz")):
        if p.name in seen:
            continue
        seen.add(p.name)
        with gzip.open(p, "rt") as f:
            b = json.load(f)
        if not b.get("skipped"):
            out.append(b)
    return out


# ---------------------------------------------------------------- statistics
def cluster_boot(df: pd.DataFrame, fn, cluster="window_key", n=None, seed=SEED) -> tuple[float, float, float, np.ndarray]:
    """Point estimate, 95% percentile CI and the bootstrap draws, resampling whole clusters."""
    n = n or B
    est = fn(df)
    df = df.reset_index(drop=True)
    idx = [np.asarray(ix) for ix in df.groupby(cluster).indices.values()]
    rng = np.random.default_rng(seed)
    draws = []
    for _ in range(n):
        smp = df.iloc[np.concatenate([idx[k] for k in rng.integers(0, len(idx), len(idx))])]
        v = fn(smp)
        if v is not None and not math.isnan(v):
            draws.append(v)
    d = np.array(draws)
    if len(d) == 0:
        return est, float("nan"), float("nan"), d
    return est, float(np.percentile(d, 2.5)), float(np.percentile(d, 97.5)), d


def holm(pvals: dict[str, float]) -> dict[str, float]:
    items = sorted(pvals.items(), key=lambda kv: kv[1])
    m, out, run = len(items), {}, 0.0
    for i, (k, p) in enumerate(items):
        run = max(run, min(1.0, (m - i) * p))
        out[k] = run
    return out


def rate(arm):
    def f(d):
        x = d[d.arm == arm].overtake
        return float(x.mean()) if len(x) else float("nan")
    return f


def diff(a, b):
    def f(d):
        return rate(a)(d) - rate(b)(d)
    return f


# ---------------------------------------------------------------- active layer
def pair_table(r: dict) -> pd.DataFrame:
    P, T, L = r["pairs"], r["txs"], r["landed"]
    if P.empty or L.empty or "live" not in P or not P.live.any():
        return pd.DataFrame()
    P = P[P.live]
    lt = L.set_index("sig")
    T = T[T.live].copy()
    T = T.join(lt[["landed_slot", "index", "block_leader", "err"]], on="sig")
    first = T[T.role == 1].set_index(["run", "pair_id"])
    second = T[T.role == 2].set_index(["run", "pair_id"])
    df = P.set_index(["run", "pair_id"]).join(first[["landed_slot", "index", "block_leader", "status"]].add_suffix("_1"))
    df = df.join(second[["landed_slot", "index", "block_leader", "status"]].add_suffix("_2")).reset_index()
    df["landed_1"] = df.landed_slot_1.notna()
    df["landed_2"] = df.landed_slot_2.notna()
    df["same_block"] = df.landed_1 & df.landed_2 & (df.landed_slot_1 == df.landed_slot_2)
    df["on_target"] = df.block_leader_1 == df.target
    df["usable"] = df.same_block & df.on_target
    df["overtake"] = np.where(df.usable, (df.index_2 < df.index_1).astype(float), np.nan)
    df["window_key"] = df.run + ":" + df.window_slot.astype(str)
    df["slot_in_window"] = df.landed_slot_1 - df.window_slot
    return df


def active_summary(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows, landing = [], []
    for g, d in df.groupby("group"):
        for arm, da in d.groupby("arm"):
            landing.append({"group": g, "arm": arm, "pairs_sent": len(da),
                            "tx_landed_share": float((da.landed_1.sum() + da.landed_2.sum()) / (2 * len(da))),
                            "usable_share": float(da.usable.mean()), "off_target": int((da.landed_1 & ~da.on_target).sum())})
        u = d[d.usable]
        res = {"group": g, "validators": d.target.nunique(), "windows": u.window_key.nunique(), "usable_pairs": len(u)}
        for arm in ("EQ", "EQ_SEP", "DISC", "DISC_SEP", "CONC"):
            n = int((u.arm == arm).sum())
            res[f"n_{arm}"] = n
            if n:
                e, lo, hi, _ = cluster_boot(u[u.arm == arm], rate(arm))
                res[f"overtake_{arm}"], res[f"ci_{arm}"] = e, (lo, hi)
        if (u.arm == "DISC").sum() >= MIN_PAIRS and (u.arm == "EQ").sum() >= MIN_PAIRS:
            e, lo, hi, d_ = cluster_boot(u[u.arm.isin(["DISC", "EQ"])], diff("DISC", "EQ"))
            res.update(FPI=e, FPI_ci=(lo, hi), p_H1=float((np.sum(d_ <= 0) + 1) / (len(d_) + 1)))
            e, lo, hi, _ = cluster_boot(u[u.arm == "EQ"], lambda x: 1 - 2 * rate("EQ")(x))
            res.update(FIFO=e, FIFO_ci=(lo, hi))
        if (u.arm == "DISC_SEP").sum() >= MIN_PAIRS and (u.arm == "EQ_SEP").sum() >= MIN_PAIRS:
            e, lo, hi, _ = cluster_boot(u[u.arm.isin(["DISC_SEP", "EQ_SEP"])], diff("DISC_SEP", "EQ_SEP"))
            res.update(FPI_sep=e, FPI_sep_ci=(lo, hi))
        rr = u[u.arm.isin(["RATIO_AB", "RATIO_BA"])].copy()
        if len(rr):
            # RA first in block: AB order -> no overtake; BA order -> overtake
            rr["ra_first"] = np.where(rr.arm == "RATIO_AB", 1 - rr.overtake, rr.overtake)
            e, lo, hi, _ = cluster_boot(rr, lambda x: float(x.ra_first.mean()))
            res.update(n_RATIO=len(rr), P_RA_first=e, P_RA_first_ci=(lo, hi))
        rows.append(res)
    S = pd.DataFrame(rows)
    if "p_H1" in S:
        adj = holm({r.group: r.p_H1 for r in S.itertuples() if not pd.isna(r.p_H1)})
        S["p_H1_holm"] = S.group.map(adj)
        S["verdict"] = S.apply(_verdict, axis=1)
    return S, pd.DataFrame(landing)


def _verdict(r) -> str:
    if pd.isna(r.get("FPI")):
        return "insufficient data"
    lo, hi = r.FPI_ci
    if r.p_H1_holm < 0.05 and lo > 0.2:
        return "fee-priority"
    if (lo <= 0 <= hi or hi < 0.2) and r.FIFO_ci[0] > 0.5:
        return "arrival-order (FIFO)"
    return "mixed / weak"


# ---------------------------------------------------------------- passive layer
def passive_table(blocks: list[dict], groups: dict[str, str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Per block: Spearman(position, priority) and pairwise concordance for conflicting vs independent txs."""
    rows, txrows = [], []
    rng = random.Random(SEED)
    for b in blocks:
        g = groups.get(b["leader"])
        if g is None:
            continue
        txs = [t for t in b["txs"] if not t["jito_tip"] and not t["err"]]
        if len(txs) < 20:
            continue
        n = len(b["txs"])
        for t in txs:
            pr = (t["cu_price"] or 0)
            txrows.append({"group": g, "slot": b["slot"], "leader": b["leader"], "rel_pos": t["i"] / max(n - 1, 1),
                           "cu_price": pr, "fee_per_cost": t["fee"] / t["cost"] if t.get("cost") else np.nan})
        pos = np.array([t["i"] for t in txs])
        price = np.array([t["cu_price"] or 0 for t in txs], dtype=float)
        rho = stats.spearmanr(pos, price).statistic if np.ptp(price) > 0 else np.nan
        # The head of the block: if a scheduler drains a buffered backlog in priority order, it shows here first.
        hp = price[np.argsort(pos)][:HEAD]
        rho_head = stats.spearmanr(np.arange(len(hp)), hp).statistic if np.ptp(hp) > 0 else np.nan
        # pairwise concordance on a sample of pairs with different price
        conc = {True: [0, 0], False: [0, 0]}
        ws = [set(t["writable"]) - {"ComputeBudget111111111111111111111111111111"} for t in txs]
        for _ in range(min(4000, len(txs) * 8)):
            a, c = rng.randrange(len(txs)), rng.randrange(len(txs))
            if a == c or price[a] == price[c]:
                continue
            hi, lo_ = (a, c) if price[a] > price[c] else (c, a)
            shared = bool(ws[a] & ws[c])
            conc[shared][0] += int(pos[hi] < pos[lo_])
            conc[shared][1] += 1
        rows.append({"group": g, "slot": b["slot"], "leader": b["leader"], "n_tx": n, "n_used": len(txs),
                     "jito_share": 1 - len([t for t in b["txs"] if not t["jito_tip"]]) / n,
                     "spearman_pos_price": rho, "spearman_head": rho_head,
                     "spearman_head_s0": rho_head if b["slot"] % 4 == 0 else np.nan,
                     "conc_shared": conc[True][0] / conc[True][1] if conc[True][1] else np.nan,
                     "n_shared": conc[True][1],
                     "conc_indep": conc[False][0] / conc[False][1] if conc[False][1] else np.nan,
                     "n_indep": conc[False][1]})
    return pd.DataFrame(rows), pd.DataFrame(txrows)


def passive_summary(pb: pd.DataFrame) -> pd.DataFrame:
    out = []
    for g, d in pb.groupby("group"):
        d = d.assign(window_key=d.slot // 4)
        r = {"group": g, "blocks": len(d), "validators": d.leader.nunique(), "median_tx": int(d.n_tx.median())}
        for col in ("spearman_pos_price", "spearman_head", "spearman_head_s0", "conc_shared", "conc_indep"):
            dd = d.dropna(subset=[col])
            if len(dd) >= 3:
                e, lo, hi, _ = cluster_boot(dd, lambda x, c=col: float(x[c].mean()), n=2000)
                r[col], r[col + "_ci"] = e, (lo, hi)
        out.append(r)
    return pd.DataFrame(out)


# ---------------------------------------------------------------- timing layer
def timing_table(r: dict) -> pd.DataFrame:
    T = r["txs"]
    if T.empty:
        return T
    T = T[T.t_send_ns.notna()].copy()
    T["aim_error_slots"] = T.est_leader_slot_at_send - T.window_slot
    P = r["pairs"]
    if "phase" not in T and not P.empty:
        T = T.merge(P[["run", "pair_id", "phase"]], on=["run", "pair_id"], how="left")
    return T


# ---------------------------------------------------------------- figures + report
def _fmt_ci(e, ci) -> str:
    if e is None or (isinstance(e, float) and math.isnan(e)):
        return "–"
    return f"{e:.2f} [{ci[0]:.2f}, {ci[1]:.2f}]"


def figures(outdir: Path, mix: dict | None, S: pd.DataFrame, pairs: pd.DataFrame, pb: pd.DataFrame,
            ptx: pd.DataFrame, T: pd.DataFrame) -> list[str]:
    outdir.mkdir(parents=True, exist_ok=True)
    made = []
    if mix:
        m = pd.DataFrame(mix["client_mix"])
        m["label"] = m.client + " " + m.version
        m = m.groupby("label").stake_share.sum().sort_values().tail(10)
        fig, ax = plt.subplots(figsize=(7, 3.6))
        ax.barh(m.index, 100 * m.values, color="#4a6fa5")
        ax.set_xlabel("% of active stake")
        ax.set_title(f"Validator clients by stake ({mix['taken_utc'][:10]}, epoch {mix['epoch']})")
        fig.tight_layout(); fig.savefig(outdir / "client_mix.png", dpi=130); plt.close(fig)
        made.append("client_mix.png")
    if not S.empty:
        arms = ["CONC", "EQ", "EQ_SEP", "DISC", "DISC_SEP"]
        fig, ax = plt.subplots(figsize=(8, 3.8))
        w = 0.8 / len(S)
        for k, r in enumerate(S.itertuples()):
            xs, ys, err = [], [], [[], []]
            for j, a in enumerate(arms):
                e = getattr(r, f"overtake_{a}", np.nan)
                if isinstance(e, float) and not math.isnan(e):
                    lo, hi = getattr(r, f"ci_{a}")
                    xs.append(j + k * w); ys.append(e); err[0].append(e - lo); err[1].append(hi - e)
            ax.bar(xs, ys, w, yerr=err, capsize=2, label=r.group)
        ax.set_xticks(np.arange(len(arms)) + 0.4 - w / 2, arms)
        ax.set_ylabel("share of pairs where 2nd-sent\nis placed before 1st-sent")
        ax.set_ylim(0, 1); ax.legend(fontsize=7, ncol=2); ax.set_title("Overtake rate by arm and client")
        fig.tight_layout(); fig.savefig(outdir / "overtake_by_arm.png", dpi=130); plt.close(fig)
        made.append("overtake_by_arm.png")
        u = pairs[pairs.usable & (pairs.arm == "DISC")]
        if len(u):
            fig, ax = plt.subplots(figsize=(6, 3.4))
            for g, d in u.groupby("group"):
                c = d.groupby("dt_ms").overtake.mean()
                ax.plot(c.index, c.values, marker="o", label=g)
            ax.set_xlabel("delay between the two sends (ms)"); ax.set_ylabel("P(high fee placed first)")
            ax.set_ylim(0, 1); ax.legend(fontsize=7); ax.set_title("Overtake curve, DISC arm")
            fig.tight_layout(); fig.savefig(outdir / "overtake_curve.png", dpi=130); plt.close(fig)
            made.append("overtake_curve.png")
    if not ptx.empty:
        fig, ax = plt.subplots(figsize=(7, 3.8))
        for g, d in ptx.groupby("group"):
            d = d[d.cu_price > 0].copy()
            if len(d) < 200:
                continue
            d["dec"] = pd.qcut(d.cu_price.rank(method="first"), 10, labels=False)
            c = d.groupby("dec").rel_pos.mean()
            ax.plot(c.index + 1, c.values, marker=".", label=f"{g} ({d.slot.nunique()} blocks)")
        ax.axhline(0.5, color="grey", lw=0.6, ls=":")
        ax.set_xlabel("priority-fee decile within group (1 = cheapest, 10 = highest µL/CU)")
        ax.set_ylabel("mean relative position\n(0 = block start, 1 = end)")
        ax.set_title("Passive: where do high-priority txs sit in the block?")
        ax.legend(fontsize=6.5); fig.tight_layout(); fig.savefig(outdir / "passive_position_by_fee.png", dpi=130)
        plt.close(fig); made.append("passive_position_by_fee.png")
    if not pb.empty:
        s = pb.groupby("group")[["conc_shared", "conc_indep"]].mean()
        fig, ax = plt.subplots(figsize=(7, 3.6))
        x = np.arange(len(s))
        ax.bar(x - 0.2, s.conc_shared, 0.4, label="txs share a writable account")
        ax.bar(x + 0.2, s.conc_indep, 0.4, label="independent txs")
        ax.axhline(0.5, color="grey", lw=0.6, ls=":")
        ax.set_xticks(x, s.index, rotation=25, ha="right", fontsize=7)
        ax.set_ylabel("P(higher-fee tx comes first)"); ax.set_ylim(0.3, 1)
        ax.set_title("Passive: fee order holds more often when txs conflict?"); ax.legend(fontsize=7)
        fig.tight_layout(); fig.savefig(outdir / "passive_conflict.png", dpi=130); plt.close(fig)
        made.append("passive_conflict.png")
    if not T.empty:
        fig, ax = plt.subplots(figsize=(6, 3.2))
        for ph, d in T.groupby(T.get("phase", pd.Series("all", index=T.index)).fillna("?")):
            ax.hist(d.aim_error_slots.clip(-4, 8), bins=48, alpha=0.6, label=ph)
        for x in (0, 4):
            ax.axvline(x, color="k", lw=0.7)
        ax.set_xlabel("estimated slot at send − window first slot (window = [0, 4))")
        ax.set_ylabel("txs"); ax.legend(); ax.set_title("Send timing vs target window")
        fig.tight_layout(); fig.savefig(outdir / "timing.png", dpi=130); plt.close(fig)
        made.append("timing.png")
    return made


def run_analysis(data: Path, report: Path) -> None:
    r = load_runs(data)
    mixes = sorted((data / "survey").glob("mix-*.json"))
    mix = json.loads(mixes[-1].read_text()) if mixes else None
    groups = dict(r["groups"])
    for pf in sorted((data).glob("**/panel*.json")):
        try:
            for v in json.loads(pf.read_text()).get("validators", []):
                groups.setdefault(v["identity"], v["group"])
        except (AttributeError, json.JSONDecodeError):
            pass
    pairs = pair_table(r)
    S, landing = active_summary(pairs) if not pairs.empty else (pd.DataFrame(), pd.DataFrame())
    blocks = load_blocks(data)
    pb, ptx = passive_table(blocks, groups)
    PS = passive_summary(pb) if not pb.empty else pd.DataFrame()
    T = timing_table(r)
    res = data / "results"
    res.mkdir(parents=True, exist_ok=True)
    for name, df in (("pairs", pairs), ("active_summary", S), ("landing", landing), ("passive_blocks", pb),
                     ("passive_summary", PS), ("timing", T)):
        if not df.empty:
            df.to_csv(res / f"{name}.csv", index=False)
    made = figures(report / "figures", mix, S, pairs, pb, ptx, T)
    _write_results(report / "results.md", mix, r, pairs, S, landing, PS, pb, T, made, blocks)
    log("analyze", pairs=len(pairs), groups=len(S), passive_blocks=len(pb), figures=made)


def _write_results(path, mix, r, pairs, S, landing, PS, pb, T, made, blocks) -> None:
    L = ["# Results (auto-generated by `python -m itb analyze` — do not edit by hand)", ""]
    runs = r["txs"].groupby("run").agg(n=("sig", "size"), live=("live", "max"),
                                       t0=("t_send_ns", "min"), t1=("t_send_ns", "max")) if not r["txs"].empty else pd.DataFrame()
    L += ["## Data and dates", ""]
    if mix:
        L.append(f"- Cluster survey: {mix['taken_utc']} (epoch {mix['epoch']}, {mix['validators']} voting validators).")
    for run, x in runs.iterrows():
        t0 = pd.to_datetime(x.t0, unit="ns", utc=True).strftime("%Y-%m-%d %H:%M") if not pd.isna(x.t0) else "?"
        t1 = pd.to_datetime(x.t1, unit="ns", utc=True).strftime("%H:%M UTC") if not pd.isna(x.t1) else "?"
        L.append(f"- Run `{run}`: {'LIVE' if x.live else 'dry-run'}, {x.n} probe txs, {t0}–{t1}.")
    if blocks:
        bt = [b["block_time"] for b in blocks if b.get("block_time")]
        L.append(f"- Blocks fetched: {len(blocks)} (slots {min(b['slot'] for b in blocks)}–{max(b['slot'] for b in blocks)}, "
                 f"{pd.to_datetime(min(bt), unit='s', utc=True):%Y-%m-%d %H:%M}–{pd.to_datetime(max(bt), unit='s', utc=True):%Y-%m-%d %H:%M} UTC). "
                 "All after the Alpenglow activation (epoch 1064, 21.10.2026).")
    L.append("")
    L += ["## Active layer: self-sent probe pairs", ""]
    if S.empty:
        L += ["**No live probe data yet.** The active path needs a funded keypair (see README → Running live).",
              "Everything below this section is from the passive and timing layers only.", ""]
    else:
        L += ["| group | val. | windows | usable pairs | overtake EQ | overtake DISC | FPI | FIFO | P(RA first) | Holm p | verdict |",
              "|---|---|---|---|---|---|---|---|---|---|---|"]
        for x in S.to_dict("records"):
            L.append(f"| {x['group']} | {x['validators']} | {x['windows']} | {x['usable_pairs']} | "
                     f"{_fmt_ci(x.get('overtake_EQ'), x.get('ci_EQ'))} | {_fmt_ci(x.get('overtake_DISC'), x.get('ci_DISC'))} | "
                     f"{_fmt_ci(x.get('FPI'), x.get('FPI_ci'))} | {_fmt_ci(x.get('FIFO'), x.get('FIFO_ci'))} | "
                     f"{_fmt_ci(x.get('P_RA_first'), x.get('P_RA_first_ci'))} | "
                     f"{x.get('p_H1_holm', float('nan')):.3g} | {x.get('verdict', '–')} |")
        L += ["", "Landing per arm (survivorship check):", "", landing.to_markdown(index=False, floatfmt=".2f"), ""]
    L += ["## Passive layer: blocks produced by panel validators", "",
          "Descriptive only: other senders' arrival times are unknown, so this cannot separate fee ordering from",
          "arrival order. Jito-tip txs and failed txs excluded. Spearman ρ < 0 means higher fee → earlier.", ""]
    if PS.empty:
        L += ["No blocks collected.", ""]
    else:
        L += [f"| group | validators | blocks | median txs/block | Spearman(position, µL/CU) | same, first {HEAD} txs | "
              f"same, first {HEAD} txs of the window's 1st block | P(fee order) conflicting | P(fee order) independent |",
              "|---|---|---|---|---|---|---|---|---|"]
        for x in PS.to_dict("records"):
            small = " (small: <2 validators or <20 blocks)" if x["validators"] < 2 or x["blocks"] < 20 else ""
            L.append(f"| {x['group']}{small} | {x['validators']} | {x['blocks']} | {x['median_tx']} | "
                     f"{_fmt_ci(x.get('spearman_pos_price'), x.get('spearman_pos_price_ci'))} | "
                     f"{_fmt_ci(x.get('spearman_head'), x.get('spearman_head_ci'))} | "
                     f"{_fmt_ci(x.get('spearman_head_s0'), x.get('spearman_head_s0_ci'))} | "
                     f"{_fmt_ci(x.get('conc_shared'), x.get('conc_shared_ci'))} | {_fmt_ci(x.get('conc_indep'), x.get('conc_indep_ci'))} |")
        L.append("")
    L += ["## Timing layer: did sends hit the target window?", ""]
    if T.empty:
        L += ["No send log.", ""]
    else:
        e = T.aim_error_slots
        L += [f"{len(T)} sends. Estimated slot at send relative to window start: median {e.median():.2f}, "
              f"5–95 % [{e.quantile(.05):.2f}, {e.quantile(.95):.2f}] slots. "
              f"Share inside [−1.5, 4): {((e >= -1.5) & (e < 4)).mean():.0%}.", ""]
    L += ["## Figures", ""] + [f"![{m}](figures/{m})" for m in made]
    path.write_text("\n".join(L) + "\n")
