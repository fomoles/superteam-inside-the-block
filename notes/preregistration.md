# Pre-registration (written 24.10.2026, before any live probe was sent)

This file fixes what we will measure, the statistics, and the decision rules **before** live data
exists, so the analysis cannot be tuned to the result. Any later deviation is listed in
report/REPORT.md under "Deviations from pre-registration". Git history dates this file.

## Unit, outcome, grouping

- Unit = a **pair** of probe txs (first-sent, second-sent), sent `dt` ms apart to the same leader's TPU.
- A pair is **usable** if both txs landed, in the **same block**, and the block's `Fee` reward goes to the
  pair's target identity (leader verified from the block, not from the schedule).
- Outcome per usable pair: `overtake = 1` if the second-sent tx sits at a lower index in the block's
  transaction list than the first-sent tx, else 0.
- Group = gossip `clientId` + `version` of the target, frozen at panel selection and re-checked at run time.
  Pairs are clustered by **window** (≤ 3 pairs share a window); validators within a group are reported
  separately as a robustness check.

## Arms and what each one isolates

| arm | first → second | payer | overtake rate means |
|---|---|---|---|
| EQ | MID → MID | shared | pure send-order noise for conflicting txs (FIFO ⇒ ≈ 0) |
| EQ_SEP | MID → MID | separate | same for non-conflicting txs (parallel workers ⇒ can be > 0) |
| DISC | LOW → HIGH | shared | fee rule vs arrival order disagree |
| DISC_SEP | LOW → HIGH | separate | same, without write-lock conflict |
| CONC | HIGH → LOW | shared | both rules agree ⇒ overtakes are pure noise |
| RATIO_AB / RATIO_BA | RA ↔ RB | shared | RA = higher fee per CU, RB = higher total fee |

## Pre-registered quantities (per group)

1. **Fee-priority index** `FPI = overtake(DISC) − overtake(EQ)` (conflicting txs).
   `FPI_sep = overtake(DISC_SEP) − overtake(EQ_SEP)` (non-conflicting).
2. **FIFO index** `FIFO = 1 − 2·overtake(EQ)` (1 = strict arrival order, 0 = coin flip).
3. **Per-CU vs total**: `P(RA before RB)` pooled over both RATIO orders (order effect cancels).
   > 0.5 ⇒ the scheduler ranks by fee per compute unit; < 0.5 ⇒ by total fee.
4. **Overtake curve**: overtake(DISC) by `dt ∈ {0, 30, 150}` ms, and by phase PRE vs IN.
5. **Landing**: per arm and group, share of txs that landed and share of pairs usable
   (reported so survivorship bias is visible).

## Statistics

- 95 % CIs by **cluster bootstrap over windows**, 5,000 resamples, seed 1.
- Primary test H1 per group: FPI > 0, one-sided, bootstrap p-value. **Holm** correction across groups.
- Minimum: a group gets a verdict only with ≥ 20 usable DISC pairs and ≥ 20 usable EQ pairs; otherwise
  "insufficient data" is reported, never a guess.

## Decision rules (verdict per group)

- **fee-priority**: Holm-adjusted H1 significant and FPI lower CI bound > 0.2.
- **arrival-order (FIFO)**: FPI CI contains 0 or upper bound < 0.2, **and** FIFO lower CI bound > 0.5.
- **mixed / weak**: neither of the above.
- Per-CU vs total: called only if the 95 % CI of P(RA first) excludes 0.5.

## Passive supplement (no money needed)

For all blocks of panel leaders collected during the run: Spearman correlation between position and
priority per CU, computed separately for (a) all non-vote txs, (b) pairs of txs that share a writable
account vs pairs that don't. This is descriptive only — other senders' arrival times are unknown — and is
never used as the primary evidence.

## What this design does not separate (stated up front)

- Arrival time at the leader is estimated from our send time + measured RTT/2, not observed.
- Effects of the leader's own QoS (unstaked sender quota) on *which* txs are admitted, vs how admitted txs are ordered.
- Behaviour of other leaders' clients beyond the panel; one client version per group.
