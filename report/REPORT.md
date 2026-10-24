# Inside the Block: how Solana validators order transactions — report

Mainnet-beta, 24.10.2026, epoch 1066, three days after Alpenglow was activated (epoch 1064). solana-core 4.3.2
on the RPC side; slots are 210.7 ms; leader windows are 4 slots (≈ 840 ms).
Generated tables and figures: [results.md](results.md). Code and one-command reproduction: [../README.md](../README.md).

## TL;DR

- **The question** is which rule a validator uses to order transactions inside its block: priority fee,
  arrival time, or something else, and how strictly, for each validator client.
- **The answer this repo can give today** comes from 475 real mainnet blocks of **20 validators in 10
  client/version groups** (Agave, Agave 4.5 alpha, Jito, Agave-BAM, Harmonic-Agave, Rakurai, Firedancer
  26.10.3 and 26.10.4, Harmonic-Firedancer, FireBAM). Across a whole block, fee and position are unrelated (rank correlation ≈ 0 in every group). At the
  **start of a leader's window**, three clients put higher-fee txs clearly first: **Agave-BAM, FireBAM and
  Firedancer 26.10.3**. Jito and Agave do so weakly. Firedancer 26.10.4, both Harmonic groups and Rakurai show
  no fee order there. This is exploratory and correlational (section 3.1).
- **The answer this repo is built to give** comes from self-sent probe pairs with controlled fee, send gap,
  phase and write-lock conflict, aimed straight at one leader's TPU. The pipeline runs on mainnet end to end:
  real leader windows, real QUIC handshakes to 16+ distinct leaders, sends timed to the millisecond. The one
  step it does not do is sign the transactions with a funded key. The cost is **≈ 0.016 SOL in fees** for
  350 windows (plus ≈ 0.017 SOL refundable deposits). See "What is missing".

## 1. Why the obvious experiment does not answer the question

The first-instinct design ([notes/v0-default.md](../notes/v0-default.md)) is the one most people will submit:
send a handful of txs with different fees through public RPC, find them in a block, correlate fee with
position. It cannot answer the question, for six reasons ([notes/critique.md](../notes/critique.md), round 1):

1. **Arrival order is unknown.** Txs sent together through RPC arrive in random order. "High fee came first"
   then fits both a fee rule and a FIFO rule with lucky arrival.
2. **No noise floor.** Without equal-fee pairs nobody knows how often order flips for no reason at all.
3. **One payer means every pair conflicts.** Txs that write the same account are serialised; the result
   mixes the ordering policy with lock handling.
4. **RPC forwards to several leaders.** Probes land in other validators' blocks; the "client" being measured
   is not the one targeted.
5. **Pairs in one block are not independent.** Treating them as such makes the confidence intervals too narrow.
6. **Whole-block correlations are ≈ 0 under streaming block building**, even for a scheduler that does sort
   its buffer by priority (shown below with real data).

The one visible competing submission (github.com/zdfgu113/inside-the-block, read 24.10.2026) has points
1–5; its 135 pairs reduce to 40 that landed with the targeted leader.

## 2. Design

Full description: [README → Design](../README.md#design). Pre-registered rules:
[notes/preregistration.md](../notes/preregistration.md) (git-dated before any live data).

- **Direct to the leader.** Each probe goes over QUIC to the target leader's TPU only, so it can land in
  that leader's block or nowhere. The leader is then re-checked from the block's own `Fee` reward.
- **Pairs with a controlled gap.** The first tx is sent, then the second `dt ∈ {0, 30, 150}` ms later, with
  nanosecond send timestamps. The outcome is binary: did the second-sent tx end up earlier in the block?
- **Arms that isolate one thing each.** Equal fees (noise floor), low→high (fee and arrival disagree),
  high→low (they agree), shared vs separate payer (write-lock conflict or not), and a per-CU vs total-fee
  arm (RA has the higher price per CU, RB the higher total fee).
- **Phase.** PRE: both txs arrive ≈ 1.2 slots before the window, so both wait in the leader's buffer. IN:
  they arrive while the block streams.
- **Statistics.** The fee-priority index `FPI = overtake(low→high) − overtake(equal)`. Confidence intervals
  come from a cluster bootstrap over leader windows; the per-group test is Holm-corrected; a group with
  fewer than 20 usable pairs per arm gets "insufficient data", never a guess.

## 3. Results

### 3.1 Passive layer: 475 blocks from the panel's own leader windows

Every block of 6 recent leader windows of each of the 20 validators (480 slots, 5 skipped, 18:09–00:51
UTC 23–24.10.2026). Jito-tip txs and failed txs are excluded. ρ is the Spearman rank correlation between
position and priority fee per CU; **ρ < 0 means higher fee → earlier**. CIs: bootstrap by block.

| group | whole block | first 64 txs, any block | first 64 txs, window's 1st block |
|---|---|---|---|
| AgaveBam 4.3.2 | −0.08 [−0.10, −0.06] | −0.36 [−0.42, −0.31] | **−0.57 [−0.64, −0.49]** |
| FireBAM 26.10.4 | −0.04 [−0.07, −0.01] | −0.26 [−0.33, −0.19] | **−0.41 [−0.55, −0.26]** |
| Firedancer 26.10.3 | −0.04 [−0.06, −0.02] | −0.10 [−0.15, −0.05] | **−0.29 [−0.41, −0.19]** |
| JitoLabs 4.3.2 | +0.00 [−0.02, 0.03] | −0.06 [−0.11, −0.01] | −0.16 [−0.25, −0.08] |
| Agave 4.3.2 | −0.02 [−0.05, 0.02] | −0.08 [−0.13, −0.03] | −0.15 [−0.27, −0.04] |
| Agave 4.5.0-alpha.2 | −0.04 [−0.09, −0.00] | −0.09 [−0.16, −0.04] | −0.10 [−0.23, 0.03] |
| HarmonicAgave 4.3.2 | −0.01 [−0.04, 0.03] | −0.09 [−0.12, −0.06] | −0.03 [−0.12, 0.05] |
| HarmonicFiredancer 26.10.4 | −0.04 [−0.08, −0.01] | −0.11 [−0.18, −0.05] | −0.03 [−0.18, 0.12] |
| Rakurai 4.3.2 | +0.02 [−0.01, 0.05] | −0.02 [−0.07, 0.02] | −0.01 [−0.14, 0.10] |
| Firedancer 26.10.4 | −0.02 [−0.06, 0.01] | −0.01 [−0.08, 0.06] | +0.08 [−0.06, 0.23] |

**How to read it.** After Alpenglow, blocks are built while they stream. A scheduler that keeps its buffer
sorted by priority shows that order only where it drains a backlog: at the start of the leader's window.
Later txs are placed roughly as they arrive, so whole-block correlations are ≈ 0 for every client, including
those that do sort. A whole-block correlation, the usual first analysis, would conclude "no fee ordering
anywhere".

**Robustness** (critique round 3; `scripts/robustness_head.py`, output in
[data/results/robustness_head.txt](../data/results/robustness_head.txt)):
- *Placebo:* the same statistic on txs 128–191 of the same blocks is ≈ 0 (−0.08 … +0.02) for the three
  strong groups. The effect is specific to the head.
- *Both validators agree* in the strong groups (AgaveBam −0.51 / −0.56, FireBAM −0.47 / −0.56,
  Firedancer 26.10.3 −0.41 / −0.30). In Firedancer 26.10.4 they don't (+0.26 / −0.11).
- *Unpriced txs:* dropping price-0 txs keeps the strong groups negative and makes Agave 4.3.2 clearly
  negative too (−0.46): many unpriced txs sit early in Agave's head and mask a fee order among priced ones.
- *Top-fee txs* (block's top 10 %) are 1.5–3.2× over-represented in the head of every group.

**What it does not show.** Other senders' arrival times are unknown. High-fee bots may simply aim at the slot
start, and that alone would give the same head pattern. BAM bundles without a Jito tip cannot be excluded.
Up to 12 first blocks per group were sampled over ≈ 6.5 hours. The head tests were added after seeing data
(**exploratory**), and no group gets a verdict from them. The controlled active layer is what would separate
"sorted buffer" from "early high-fee arrival".

### 3.2 Timing layer: can the pipeline hit a 4-slot window from Ukraine?

Two mainnet dry-runs (real leader schedule, real QUIC connections, sends timed and logged, no signature
broadcast). Aim is the estimated slot at send, relative to the window start.

| path, phase | target | dry-run 1 (39 windows), median | dry-run 2 (25 windows), median [range] |
|---|---|---|---|
| TPU, PRE | −1.2 | −1.57 | −0.74 [−1.80, +1.25] |
| TPU, IN | +0.5…+2.4 | +0.65 | +1.84 [−0.09, +4.27] |
| RPC, PRE | −1.2 | −3.56 | −1.18 [−1.57, +0.54] |
| RPC, IN | +0.5…+2.4 | −1.93 | +1.56 [+0.88, +2.27] |

Between the two runs the slot clock was fixed (least-squares slot length instead of the median gap between
websocket notifications; critique round 2, item 2). Tails of −8 to −13 slots disappeared. QUIC handshakes to
leaders took 27–282 ms, RTT 33–186 ms. 2.7 % of sends in dry-run 2 left more than 50 ms after plan, all in
one window; amendment A1 marks such pairs as not usable.

### 3.3 Active layer

**Not run: needs a funded key** (hard limit of this work: no wallet with real funds was created or asked
for). The command, the cost and the safety rules are in [README → Running live](../README.md#running-live-real-probes-real-but-capped-sol).
The analysis code is tested on synthetic data with known answers (`tests/test_collect_analyze.py`).

## 4. Deviations from pre-registration

- **A1** (before live data): pairs sent > 50 ms late are not usable.
- **Head-of-block rank tests** (first 64 txs of a block, and of the window's first block) were added after
  seeing the first passive data. They are **exploratory**, not pre-registered, and no verdict rests on them.
- **v1 parser fix.** Passive data collected before the fix were discarded and collected again.

## 5. What went wrong, and what it taught

- **v1 transactions hide their priority fee in a new place.** After Alpenglow most txs are version 1, which
  put the compute budget in `transactionConfig`, not in ComputeBudget instructions. Our first parser read them
  as "no fee", and the first passive result (higher-fee txs *later* at the block head) came from that.
  It was found by chasing an oddly high share of zero-price txs. Any analysis on post-Alpenglow blocks that
  only decodes ComputeBudget instructions has the same bug.
- **The median-gap slot clock** was 5 % off and moved the aim by whole slots.
- **Late sends** cluster in windows where the connection to the leader is slow.
- **No test environment for the active path.** The devnet faucet returned 429 and its web faucet needs a
  login; `solana-test-validator` images are amd64-only and need AVX, so they did not run on this M1 machine.

## 6. What is missing, and what it would take

- **Live probes.** A keypair with ≈ 0.07 SOL, then the three commands in the README. ≈ 0.016 SOL is spent
  on fees, the deposits come back with `sweep`. The hard cap is 0.05 SOL, enforced before every send.
- **Admission vs ordering.** Unstaked senders get a small QUIC quota; a probe that never lands may have been
  dropped by QoS. Landing rates are reported per arm, but the cause of a drop cannot be seen.
- **Client vs operator.** Two validators per group cannot separate a client from its operators' settings.

## 7. Reproduce and check

```bash
docker compose up          # survey, passive blocks, dry-run, analysis, verify; spends nothing
```

Every number in [results.md](results.md) is computed from files in `data/`. Every probe and every block is
keyed by signature and slot; `itb verify` re-fetches blocks from the chain and checks stored positions.
