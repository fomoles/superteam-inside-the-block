# Pre-registration v2: the confirmatory run (written 24.10.2026, after run 1, before run 2)

Run 1 (`data/runs/20261024T015728Z-mainnet-live`) found a pattern the v1 pre-registration did not
foresee: one sorting model fits every send gap, and clients differ in two numbers of that model. Those
numbers were found *after* looking at run-1 data, so on run 1 they are exploratory (REPORT §3.3, critique
round 6). This file fixes them as hypotheses for a **new** run, with new data, more validators and a
repaired ratio arm. The git commit of this file predates every run-2 probe. Run-2 data are analysed
by `scripts/sort_model.py` at this commit; any change after the run is listed as a deviation.

## What changes from run 1 (and nothing else)

| | run 1 | run 2 |
|---|---|---|
| panel | 20 validators, top-2 by stake per group (`data/panel.json`) | 47 validators, top-5 per group (`data/panel-v2.json`; contains the 20) |
| probe | 3 instructions | + `SetLoadedAccountsDataSizeLimit(32768)` first: 4 instructions, 600 CU (simulated) |
| spend ledger / cap | `data/spend-ledger.json`, 0.08 SOL | `data/spend-ledger-run2.json`, 0.06 SOL |
| arms, weights, fee levels, dt, phases, paths, usability rule (A1), seed | — | unchanged |

Why the extra instruction: without it the cost model charges every probe a default 64 MiB loaded-data
allowance (16,384 CU), so RB (6,000 CU limit) also had the higher fee per estimated cost and the ratio arm
could not separate "fee per cost" from "total fee". With the cap, the estimated cost is ≈ 1,630 CU (RA) vs
≈ 7,030 CU (RB): RA ranks first by µL/CU and by fee per cost, RB ranks first by total fee only.

## The model (the reason for C1–C5)

A usable pair is either sorted by the scheduler's rule (probability `s`) or left in arrival order up to
noise `e`. With one payer: `DISC = s + (1−s)e`, `CONC = (1−s)e`, `EQ = s·τ + (1−s)e`, so

- `FDS = DISC − CONC` — the share of pairs where the fee, not the arrival order, decides;
- `TAU = (EQ − CONC) / (DISC − CONC)`, clipped to [0, 1] — how a fee tie is broken
  (0 = earlier arrival first, 0.5 = coin flip, 1 = later arrival first).

## Confirmatory checks (run 2 data only)

95 % CIs by bootstrap over leader windows (2000 draws, seed 20261024); differences between clients use
independent draws (their windows are disjoint). Each check is **holds**, **fails** (the opposite bound is
crossed, where defined) or **inconclusive**, or **insufficient data** below the stated minimum.

| id | claim | holds if | minimum data | run 1 (exploratory) |
|---|---|---|---|---|
| C1 | pooled, the fee decides most pairs | FDS lower CI > 0.30 | 40 DISC and 40 CONC pairs | +0.57 [+0.51, +0.62] |
| C2 | a cheaper later tx almost never passes | CONC overtake upper CI ≤ 0.10 | 40 CONC pairs | holds |
| C3 | Jito sorts by fee less often than the other fee-sorting clients | FDS(Jito) − FDS(HarmonicAgave + HarmonicFiredancer + Firedancer 26.10.4 + AgaveBam, pooled) upper CI < 0 | 20 Jito DISC and CONC pairs | −0.28 [−0.44, −0.11] |
| C4 | Firedancer 26.10.4 breaks fee ties for the later arrival | TAU(FD 26.10.4) lower CI > 0.5 | 20 DISC, CONC and EQ pairs | 1.00 [0.72, 1.00] |
| C5 | … and does so more than the other clients | TAU(FD 26.10.4) − TAU(all other groups pooled) lower CI > 0 | 20 FD 26.10.4 EQ pairs | +0.42 [+0.11, +0.54] |
| C6 | with the loaded-data cap, the higher fee *per cost* goes first, not the higher total | RB-first share = overtake(RATIO_AB) − overtake(RATIO_BA): upper CI < −0.2 (fails if lower CI > +0.2) | 40 pairs per RATIO arm | +0.69 (no cap: the confounded design predicts RB first) |
| C7 | the pattern is not a property of the 20 run-1 validators | FDS on validators **not** in `data/panel.json`: lower CI > 0.30 | 30 DISC and 30 CONC pairs | — (no new validators) |

No multiple-comparison correction is applied across C1–C7: they are separate claims, each reported
with its own result, and none is promoted above the others after the fact. The v1 per-group verdicts
(FPI with Holm) are recomputed on run 2 and on runs 1+2 pooled and reported as before.

## Reporting rules

- All seven results go into REPORT.md, failures included, next to the run-1 value.
- A failed or inconclusive check is reported as such; the run-1 finding it tested is then described as
  "did not replicate" (fails) or "not confirmed" (inconclusive).
- Pooled runs 1+2 tables are labelled as such and are not used for C1–C7.
- If run 2 stops early (cap, RPC outage), checks are computed on what landed; a check below its minimum
  is "insufficient data", never extrapolated.
