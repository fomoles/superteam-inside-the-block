# Inside the Block — how Solana validators order transactions (mainnet, after Alpenglow)

A reproducible experiment to measure **how different validator clients order transactions within a block**:
by priority fee, by arrival time, or something else. It uses self-sent probe transactions with controlled
fees and send times, aimed **directly at one leader's TPU** (its transaction-ingest port), plus a passive
dataset of real blocks from the same validators.

- Network: Solana **mainnet-beta**. Every measurement is dated, and all were taken **after** the Alpenglow
  activation (epoch 1064, 21.10.2026). Nothing before and after is mixed.
- Panel: **20 validators in 10 client/version groups**: Agave 4.3.2, Agave 4.5.0-alpha.2, JitoLabs 4.3.2,
  AgaveBam 4.3.2, HarmonicAgave 4.3.2, Rakurai 4.3.2, Firedancer 26.10.4, Firedancer 26.10.3,
  HarmonicFiredancer 26.10.4, FireBAM 26.10.4. Clients are taken from gossip `clientId` + `version` and frozen
  in [data/panel.json](data/panel.json).
- Results: [report/REPORT.md](report/REPORT.md) (the write-up) and [report/results.md](report/results.md)
  (generated tables and figures).
- Design and analysis rules were fixed in [notes/preregistration.md](notes/preregistration.md) before any
  live data existed. The critique log is in [notes/critique.md](notes/critique.md).

## Reproduce in one command (spends nothing)

```bash
docker compose up
```

This runs `python -m itb all`, which does the following:

1. Takes a fresh cluster survey (clients and stake).
2. Collects passive blocks from the panel's latest leader windows.
3. Runs a 3-minute **dry-run**: it plans real probe pairs into upcoming leader windows, opens QUIC
   connections to the leaders' TPUs and times every send, but **sends nothing**.
4. Collects the results, analyzes them, and verifies them against the chain.

Output goes to `report/results.md`, `report/figures/` and `data/results/*.csv`.

Without Docker: `make all` (needs [uv](https://docs.astral.sh/uv/)). Tests: `make test` or
`docker compose --profile test run --rm test`.

By default it uses two public endpoints that need no sign-up (`api.mainnet-beta.solana.com` and
`solana-rpc.publicnode.com`) and rotates between them. Public RPC is rate-limited, so the run paces heavy
calls and takes about 15 min. With your own endpoint,
set `ITB_RPC_URLS=https://…` and `ITB_WS_URL=wss://…`, plus `ITB_RPC_HEAVY_INTERVAL_S=0`. Free tiers that
need a sign-up include Helius, Triton and QuickNode; any of them works, and none is required.

## Running live (real probes, real but capped SOL)

```bash
ITB_KEYPAIR_FILE=/abs/path/outside/repo/keypair.json docker compose --profile live run --rm live
docker compose run --rm itb collect --skip-done
docker compose run --rm itb analyze
docker compose run --rm itb sweep --keypair /run/secrets/itb_keypair --yes   # return deposits
```

Without Docker, the same in one script, with a read-only check first (`itb preflight`: balances, cap,
a `simulateTransaction` of a probe; sends nothing):

```bash
ITB_KEYPAIR=/abs/path/outside/repo/keypair.json scripts/live.sh
```

Run 2, the confirmatory run fixed in [notes/preregistration-v2.md](notes/preregistration-v2.md) (47-validator
panel, probes that cap their loaded account data, its own ledger and a 0.06 SOL cap), is one script; it ends by
printing the pre-registered checks C1–C7:

```bash
ITB_KEYPAIR=/abs/path/outside/repo/keypair.json scripts/live2.sh
```

Safety rules enforced in code:

- **Dry-run is the default.** Sending needs `--live` **and** `--yes-spend` **and** a keypair passed through
  `$ITB_KEYPAIR` or a Docker secret. The key is never in the repo, which ignores `*keypair*.json`.
- **Hard spend cap**, 0.05 SOL by default (`ITB_CAP_SOL`). Every transaction's worst-case fee is booked and
  saved to `data/spend-ledger.json` *before* it is sent. A send that would exceed the cap is refused and the
  run stops, and the ledger survives restarts. A second guard sums the on-chain balances every 10 windows
  and stops if the drop since the start exceeds the cap.
- **Cost estimate:** the mean fee per pair is ~15,400 lamports, so 350 windows × 3 pairs ≈ **0.016 SOL**.
  Txs that never land cost nothing. On top of that, 12 sub-payer deposits of 0.0014 SOL each
  (≈ 0.017 SOL) are needed because accounts must hold the rent minimum. They are returned by `sweep`.
  Fund the keypair with **≈ 0.07 SOL**. Measured: the default `scripts/live.sh` run (1100 windows, 6600
  probes, cap 0.08 SOL) spent **0.0389 SOL** on 24.10.2026.
- No Jito bundles or tips are used.

## Design

**Unit:** a *pair* of probe txs sent `dt` ms apart to the same leader. Each probe is a legacy tx:
SetComputeUnitLimit, then SetComputeUnitPrice, then a self-transfer of *tag* lamports. The tag encodes
pair id and role, so a probe is identifiable on chain. A probe consumes 450 CU. Its only writable account is
its payer, so **two probes conflict exactly when they share a payer.**

**Arms** (randomised per pair, 3 pairs per leader window):

| arm | first → second | payer | isolates |
|---|---|---|---|
| EQ | MID → MID | shared | send-order noise, conflicting txs (strict FIFO ⇒ never overtaken) |
| EQ_SEP | MID → MID | separate | same, non-conflicting (parallel execution) |
| DISC | LOW → HIGH | shared | fee rule vs arrival order disagree |
| DISC_SEP | LOW → HIGH | separate | same without the write-lock conflict |
| CONC | HIGH → LOW | shared | both rules agree ⇒ remaining overtakes = pure noise |
| RATIO_AB/BA | RA ↔ RB | shared | RA: higher fee *per CU*; RB: higher *total* fee |

Fee levels:

| level | price (µL/CU) | CU limit | priority fee (lamports) |
|---|---|---|---|
| LOW | 1,000 | 600 | 1 |
| MID | 10⁶ | 600 | 600 |
| HIGH | 10⁷ | 600 | 6,000 |
| RA | 5·10⁶ | 600 | 3,000 |
| RB | 10⁶ | 6,000 | 6,000 |

**Factors** randomised per pair:

- `dt ∈ {0, 30, 150} ms`, which gives the "overtake curve";
- phase **PRE** (arrive ~250 ms before the window, so both txs wait in the buffer) or **IN**
  (100–500 ms into the window, while the block streams);
- path **TPU** (direct QUIC to the target) for 85 % of windows or **RPC** (public `sendTransaction`,
  no retries) for 15 %. There is one path per window, so the paths never mix within a block.

**Outcome:** `overtake = 1` when the second-sent tx sits earlier in the block than the first-sent. A pair
counts only if both txs landed in the **same block** and the block's `Fee` reward goes to the targeted
leader, so the leader is checked from the block itself.

**Statistics:**

- Pre-registered quantities: the fee-priority index `FPI = overtake(DISC) − overtake(EQ)`,
  `FIFO = 1 − 2·overtake(EQ)`, and `P(RA before RB)`.
- 95 % confidence intervals use a **cluster bootstrap over leader windows**, because pairs in one block are
  not independent.
- The fee-priority test (H1) is corrected for multiple groups with the **Holm** method.
- Found in run 1 and pre-registered for run 2: `FDS = overtake(DISC) − overtake(CONC)`, the share of pairs
  where the fee decides, and `TAU = (EQ − CONC) / FDS`, how a fee tie is broken (`scripts/sort_model.py`).
- A group gets a verdict only with at least 20 usable pairs per arm; otherwise it is reported as
  "insufficient data".

**Passive layer** (no money):

- Real blocks from the panel's recent leader windows (`itb passive`).
- Within each block, the rank correlation between position and µL/CU, and the pairwise "fee order holds"
  rate, computed separately for transactions that share a writable account and those that don't.
- This layer is descriptive: other senders' arrival times are unknown.

## The six considerations from the listing

1. **Leader schedule and validator types.**
   - Windows are 4 slots (~840 ms at ~210 ms per slot after Alpenglow).
   - We read the schedule per identity with `getLeaderSchedule(slot, {identity})` and aim only at windows
     of panel validators.
   - The client comes from gossip, is re-checked at run time and saved as `panel_at_run.json`.
   - The leader is also confirmed from each block's `Fee` reward.
2. **Path to the leader.** Probes go straight to the leader's QUIC TPU, so they can only land in that
   leader's block or nowhere. The public-RPC path forwards to the next leaders and retries, so it is a
   separate arm and is never pooled with the TPU path.
3. **Interaction of our own txs.**
   - Shared-payer and separate-payer arms separate write-lock conflicts from ordering policy.
   - Sub-payers are derived deterministically and used in alternating pools, so consecutive windows never
     touch the same accounts.
4. **Competition inside the block.** We measure the *relative* order of our two probes, not their absolute
   position, so other traffic shifts both. Block size, Jito-tip share and slot-in-window are logged for
   every usable pair.
5. **Send order.** It is controlled: `dt` is set and logged in nanoseconds per tx. The EQ and CONC arms
   measure how often the send order is *not* preserved even with no fee difference (noise floor).
6. **Noise vs rule.** Control arms give the noise floor, and the verdict rule asks for an effect clearly
   above it (FPI lower CI bound > 0.2, Holm-corrected).

## What this design does NOT separate

- **Arrival time at the leader** is estimated as send time + RTT/2 and is not observed. Different network
  paths to different validators are part of the "client" effect we measure.
- **Admission vs ordering.** Unstaked senders get a small QUIC quota (stake-weighted QoS), so a tx that
  never lands may have been dropped by QoS, not by the scheduler. Landing rates are reported per arm, but
  the cause of a drop is not identified.
- **Client vs operator.** One group = one client version on 2 validators. Operator-specific settings
  (block-engine use, custom patches, hardware) are not separated from the client itself. Validators are
  also reported one by one.
- **Behaviour under other fee scales.** Only the tested fee levels are covered, from 1 to 6,000 lamports
  of priority fee.
- The **passive layer** is correlation only.

## Repository layout

```
itb/            survey, schedule (leader windows + slot clock), probe, spend (cap), tpu (QUIC), plan (arms),
                run (dry-run/live), collect, analyze, verify, sweep, __main__ (CLI)
data/           panel.json, survey/ (raw gossip+stake snapshots), passive/blocks/, runs/<stamp>/ (pairs,
                txs with signatures + slots, landed, events log, blocks), results/*.csv, logs/
report/         REPORT.md (write-up), results.md + figures/ (generated)
notes/          listing, v0 default answer, research, critique log, preregistration (v1, cross-section, v2)
scripts/        live.sh / live2.sh (owner's live runs), sort_model.py, live_analysis.py, passive follow-ups
tests/          spend cap, fee formula, tags, plan, block parsing, analysis on synthetic data
```

**Checking a claim by hand.** Every probe row in `data/runs/*/txs.jsonl` has a `sig`, and every block file
has `slot` plus each tx's `sig` and index. To confirm the order yourself:

```bash
curl -s https://api.mainnet-beta.solana.com -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"getBlock","params":[SLOT,{"transactionDetails":"signatures","maxSupportedTransactionVersion":1,"rewards":true}]}'
```

`itb verify` does the same check for a random sample of blocks.
