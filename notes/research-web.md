# Web research: how Solana leaders order transactions inside a block

Date of research: 2026-10-24. Scope: Q1-Q7 from the brief. Q8 (github.com/zdfgu113/inside-the-block) skipped on purpose.
Legend: [P] = primary source (source code or official page). [S] = secondary (blog, news, search summary). UNVERIFIED = not confirmed from a primary source.
Source code was read from downloaded copies of the files; the URLs point to the upstream repositories (branch/tag noted where known).

---

## Q1. Agave scheduler (the "normal" validator)

### Default block-production method
- Default is `CentralSchedulerGreedy`. `CentralScheduler` (the older prio-graph scheduler) is still selectable but marked deprecated. [P]
  - `enum BlockProductionMethod { CentralScheduler, #[default] CentralSchedulerGreedy }` in `validator/src/...`/`core/src/validator.rs`.
  - https://github.com/anza-xyz/agave/blob/master/core/src/validator.rs
- Greedy became the default from v2.3 and is still the default at v3.0.0 and v4.3.2 (checked in the tags). [P]
  - https://github.com/anza-xyz/agave/blob/v3.0.0/core/src/validator.rs
  - https://github.com/anza-xyz/agave/releases (v2.3 notes; helius summary: https://www.helius.dev/blog/agave-v23-update--all-you-need-to-know [S])

### Priority formula
- Priority of a transaction: `P = reward * 1_000_000 / (cost + 1)` (saturating integer maths). [P]
  - `reward` = priority fee plus the (share of the) base fee that goes to the validator.
  - `cost` is computed by the cost model from the REQUESTED compute-unit limit (`SetComputeUnitLimit`, or the default if none is set), NOT from CUs actually used.
  - https://github.com/anza-xyz/agave/blob/master/core/src/banking_stage/transaction_scheduler/transaction_priority_id.rs
  - https://github.com/anza-xyz/agave/blob/master/core/src/banking_stage/transaction_scheduler/transaction_state.rs (transaction_priority.rs in the downloaded copy)
- Consequence: a transaction that requests too many CUs is penalised even if it uses few. A transaction with zero priority fee has priority from base fee only (non-zero reward), so all "no tip" transactions sit in a low band ordered by cost. [P, derived]
- Ties: the priority id also carries the transaction id; ties are broken by that id (arrival counter). Exact tie semantics UNVERIFIED in detail.

### Batch size, look-ahead, workers
- Batches handed to a worker: 64 transactions max. [P]
- Per scheduling pass the greedy scheduler scans at most 100_000 candidates from the priority queue. [P]
- Default number of banking worker threads: 4 (flag `--block-production-num-workers`). [P]
  - https://github.com/anza-xyz/agave/blob/master/core/src/banking_stage/transaction_scheduler/greedy_scheduler.rs
  - https://github.com/anza-xyz/agave/blob/master/core/src/banking_stage.rs

### Conflict handling
- Greedy scheduler walks the queue from highest priority down. For each transaction it tries to lock accounts. If a lock conflicts with something already scheduled to a worker in this pass, the transaction is NOT scheduled now; it is kept (deferred, re-queued) and the scheduler moves on. [P]
- So lower-priority non-conflicting transactions CAN be executed before a higher-priority conflicting one. Priority order is therefore "best effort", not strict. [P, derived]
- The older prio-graph scheduler instead builds a dependency graph so that conflicting transactions keep priority order per account. That is why greedy trades strict ordering for throughput. [S] (https://www.helius.dev/blog/agave-v23-update--all-you-need-to-know)

### Scheduler frequency / pacing
- The scheduler controller loop runs continuously while the node is leader, receiving packets, buffering, scheduling, and collecting worker results. No fixed "tick"; it is event-loop based. [P]
  - https://github.com/anza-xyz/agave/blob/master/core/src/banking_stage/transaction_scheduler/scheduler_controller.rs
- Pacing: scheduling is spread over a "fill time" of roughly `slot_duration - 50 ms`, i.e. the scheduler does not dump everything in the first milliseconds. Exact constant read from source summary; treat the "-50 ms" as approximately right. UNVERIFIED to the line.

### Threads and entry order
- Each worker executes its batch and records the result to PoH independently. The order of entries in a block is therefore the order in which workers finish and record, not the order the scheduler queued them. [P, derived]
  - Within one entry (a batch/microblock) transactions are in the order scheduled to that worker.
  - Across workers the order is non-deterministic (race between threads).
- Implication: even for a pure-Agave leader, within-block position is only loosely tied to fee priority. The first bytes of the block show the highest-priority non-conflicting transactions, but there is interleaving across 4 workers.

---

## Q2. Firedancer pack tile; Frankendancer vs Firedancer

### Pack tile behaviour
- Pack keeps pending transactions in treaps (balanced trees) ordered by `rewards / compute` (same idea as Agave's reward-per-CU). [P]
  - https://github.com/firedancer-io/firedancer/blob/main/src/ballet/pack/fd_pack.h
  - https://github.com/firedancer-io/firedancer/blob/main/src/disco/pack/fd_pack_tile.c
- It builds microblocks for execution tiles. Header comment: transactions in a scheduled microblock are copied out "in no particular order". [P]
  - Inside a microblock, order is arbitrary; across microblocks order follows scheduling time.
- Execution tiles: called `bank` tiles in older code, now `execle`. Number is configurable (default.toml). [P]
  - https://github.com/firedancer-io/firedancer/blob/main/src/app/fdctl/config/default.toml (and `src/app/firedancer/config/default.toml`)
- Conflicts: pack tracks account use. Transactions that conflict with in-flight microblocks are not scheduled now. Heavily contended accounts have "penalty treaps" so a hot-account transaction does not block the main treap. [P]
- Bundles: pack has a FIFO bundle queue (for Jito-style bundles). Bundles are scheduled atomically and are prioritised ahead of ordinary transactions by the bundle path. Details UNVERIFIED beyond the header comments.
- Strategies: `PERF` and `BALANCED`.
  - PERF: pack as quickly as possible.
  - BALANCED: pace packing against time so the block fills toward the end of the slot (similar to Agave's pacing). [P]

### Frankendancer vs Firedancer
- Frankendancer = Firedancer's networking/QUIC/verify/dedup/pack/shred tiles plus the Agave runtime (execution, consensus, gossip) underneath. Launched in 2024 as the first production hybrid. [S]
  - https://docs.firedancer.io/ (overview) and https://jumpcrypto.com/ posts. Exact doc URL UNVERIFIED.
- Firedancer (full) = all components rewritten, no Agave code. [S]
- For ordering: both use the Firedancer pack tile to order transactions, so ordering behaviour is "Firedancer pack" in both cases. Client labels in gossip differ (see Q5). [derived]
- Full Firedancer reached mainnet in stages during 2026; share of stake: UNVERIFIED (no current figure confirmed).

---

## Q3. Jito bundle stage, BAM, Harmonic, Paladin

### Jito-Solana (Jito-Agave) BundleStage
- Jito-Solana is an Agave fork with a `BundleStage` next to the normal banking stage. [P]
  - https://github.com/jito-foundation/jito-solana
- Bundles: up to 5 transactions, executed atomically and in order, all-or-nothing. A bundle's priority is by its tip (total tip / cost). [S]
  - https://docs.jito.wtf/lowlatencytxnsend/ and https://jito-labs.gitbook.io/jito/ (docs). Exact page UNVERIFIED.
- Block engine auctions run off-chain (about every 200 ms in the classic design); the winning bundles are sent to the leader's validator, which executes them in the bundle stage in addition to normal banking-stage transactions. [S]
- Result: in a Jito-Agave block, bundles are interleaved with normal flow; bundle transactions are contiguous (atomic) inside the block. [derived]

### BAM (Block Assembly Marketplace) and Agave-BAM
- BAM: Jito's newer system. TEE (trusted execution environment) nodes receive transactions, sequence them under a plugin-defined policy and send the ordered batch to the leader. [S]
  - https://bam.dev/ and https://www.jito.network/ (announcement). Exact URLs UNVERIFIED.
- Validator side (Jito-Solana BAM client): `BamScheduler` schedules transactions "in a FIFO, account-aware manner" using a PrioGraph, with 8 workers. [P]
  - https://github.com/jito-foundation/jito-solana (files `bam_scheduler.rs`, `bam_receive_and_buffer.rs` in the banking stage)
- While a validator is connected to BAM, the local greedy scheduler is disabled; if BAM disconnects it falls back. [P]
- Adoption: about 12% of stake and about 205 validators as of Jan 2026 per Blockworks. [S] (https://www.blockworks.com — exact article URL not retained; treat as UNVERIFIED for current numbers.)

### Harmonic
- Harmonic: an alternative block-building system with two validator clients: Samba (Firedancer fork) and Salsa (Agave fork). [S]
  - https://harmonic.gg/validators
- Strategies advertised: FBA + Priority (frequent batch auction, 50 ms batches, double buffered), FIFO, MREV, Custom. [S] (same page)
- Blockworks: shreds are released after an auction roughly 300 ms into the slot, i.e. the block is built in part late. [S]
- Consequence: Harmonic leaders can produce a very different within-block order from fee-priority (FIFO or batch auction). Market share: small; UNVERIFIED.

### Paladin
- Paladin: an Agave fork ("P3") that changes priority handling and ships a sandwich filter. [S]
  - Paladin Substack and https://github.com/paladin-bladesmith/ (repo list). Exact URLs UNVERIFIED.
- Stake share and whether still active in 2026: UNVERIFIED.

---

## Q4. Alpenglow on mainnet

- Official page: https://solana.com/upgrades/alpenglow [P]
- Activation: Alpenglow's Votor replaced TowerBFT on mainnet at epoch 1064, on 2026-10-21 (about 13:36 UTC), slot 459,653,000. [P/S: official page gives the upgrade; exact slot and time came from search summaries + page. Treat slot/time as probably right but verify via RPC `getEpochSchedule`/block time.]
- Rotor (the new data-dissemination layer) is NOT live yet; Turbine still disseminates. [P] (same page)
- Slot time: 200 ms since epoch 1053 (2026-10-09) via SIMD-0525. [P/S]
  - https://github.com/solana-foundation/solana-improvement-documents (SIMD-0525). Exact file URL UNVERIFIED.
- Leader window: still 4 consecutive slots (now ~800 ms). Ticks per slot unchanged. [P/S]
- Block/entry changes visible in `getBlock`:
  - No vote transactions are included in blocks any more. [S]
  - No tick entries (no PoH ticks between entries). [S]
  - Block carries a `bank_id` and a block footer. [S]
  - These items are from search summaries and release notes; UNVERIFIED against an actual `getBlock` response after the switch. Check with a live call.
- Client support: Firedancer and Frankendancer were NOT supported for the migration at activation (conflicting reports, UNVERIFIED). If true, they would be absent from the leader set after 2026-10-21 or running a different path. Must be checked with live `getClusterNodes` data.
- Effects on the experiment:
  - Any dataset spanning 2026-10-09 .. 2026-10-21 has a mixed 400 ms/200 ms history; before 10-09 it is 400 ms.
  - Without votes in blocks, block transaction counts and `position` indexes shift (no vote-tx prefix). Vote-transaction handling in ordering analysis must be dropped for post-switch slots.

---

## Q5. How client type is exposed

### `getClusterNodes`
- Returns for each node: `pubkey`, `gossip`, `tpu`, `rpc`, `version`, `featureSet`, `shredVersion`, and, in recent Agave versions, `clientId` (RpcContactInfo `client_id`). [P]
  - https://github.com/anza-xyz/agave/blob/master/rpc-client-types/src/response.rs (RpcContactInfo)
  - https://github.com/anza-xyz/agave/blob/master/gossip/src/contact_info.rs
- `client_id` is a u16 value from the `ClientId` enum, self-reported by the node in gossip. It can be spoofed or wrong. [P]

### `ClientId` enum (from Agave source)
- Values 0 to 13 are named; anything else is "Unknown". [P] Known members include: SolanaLabs (0), JitoLabs, Firedancer, Agave, Paladin, and others up to 13 (full list read from source; exact names/numbers should be re-read from the file before coding the mapping).
  - https://github.com/anza-xyz/agave/blob/master/gossip/src/contact_info.rs (look for `ClientId`)
- Important gaps (derived, UNVERIFIED with live data):
  - Jito-Agave vs plain Agave can share a client id family or show as one; BAM and Harmonic variants are not clearly separated by the enum.
  - Frankendancer versus Firedancer: distinguished by `version` string pattern (Firedancer major version scheme) rather than reliably by enum. UNVERIFIED.

### validators.app and others
- validators.app API exposes per-validator software client/version and score; it derives from gossip and its own data. [S]
  - https://www.validators.app/api-documentation
- IBRL Explorer (Jito): scores validators on slot time, vote packing, and non-vote packing (even distribution of transactions across the block). Formulas/percentiles not found publicly. [S]
  - https://www.altcoinbuzz.io/jito-launches-ibrl-explorer-to-track-solana-validators
  - https://forum.jito.network/t/jip-23-crack-down-on-lagging-leaders/840 (context on late packing and slot-time games)
- Other sources for identifying BAM/Harmonic validators: Jito/BAM and Harmonic public validator lists. [S] (https://harmonic.gg/validators). A trustworthy machine-readable list: UNVERIFIED.
- Practical approach: combine (a) `getClusterNodes.clientId` + `version`, (b) known-lists from Jito/Harmonic, (c) block-shape fingerprints (see Q7 and implications).

---

## Q6. Transaction path to the leader

- User -> RPC -> leader TPU over QUIC. RPC nodes forward via `SendTransactionService` (STS) with `tpu-client-next` in newer Agave. [P/S]
  - https://github.com/anza-xyz/agave/tree/master/send-transaction-service
  - https://www.helius.dev/blog/agave-v23-update--all-you-need-to-know (TPU client used in ForwardingStage and STS) [S]
- STS defaults: retry every 2000 ms (`retry_rate_ms`), `leader_forward_count` 2, and effectively unlimited retries until the blockhash expires. [P]
  - So a transaction can be re-sent to the next 2 leaders repeatedly; it may land in a later leader's slot than intended.
- Gulf Stream idea: forward to upcoming leaders using the known schedule. [S] (https://www.helius.dev/blog/solana-gulf-stream)
- Stake-weighted QoS (swQoS): a staked validator's connections get TPU capacity proportional to stake; the commonly quoted split is 80% of TPU capacity reserved for stake-weighted connections. [S/P-partial]
  - Via a staked peer connection, transactions from an RPC with stake are more likely to be accepted. Unstaked sources compete for the remaining ~20%.
- Connection limits per source: older posts cite 500 open connections for any RPC and 2000 stake-weighted; UNVERIFIED and possibly outdated.
- Landing latency is affected by the RPC path: which RPC, whether it has a staked peering, plus the sender's own multi-RPC behaviour. [S]
- Forwarding from non-leader validators (the legacy "forward to next leader" in banking stage) has been reduced/disabled in newer Agave; I could not confirm the exact flag state for v3.x. UNVERIFIED (search returned nothing; check Agave 3.0 release notes and `--help`).
- For ordering: a transaction submitted just before a leader boundary may arrive in the next leader's slot (different client), so attribution of "which client ordered this" must use the SLOT in which it landed, not the target.

---

## Q7. Prior empirical studies on ordering

- No peer-reviewed cross-client study of within-block ordering found in this session. [negative result; search was broad but not exhaustive]
- Closest items:
  - Chorus One latency report (landing latency by validator/client). [S] URL not retained; UNVERIFIED which edition. Search "Chorus One Solana latency report".
  - Jito IBRL Explorer scoring (late packing detection through non-vote packing evenness). [S] https://www.altcoinbuzz.io/jito-launches-ibrl-explorer-to-track-solana-validators
  - JIP-23 on lagging leaders, which cites late-packing and timing games. [S] https://forum.jito.network/t/jip-23-crack-down-on-lagging-leaders/840
  - The GitHub repo the user already has (inside-the-block): skipped per brief.
- Gap: nobody (found) has published a priority-fee-vs-position correlation by client version. That is the experiment's novelty. [derived]

---

## Unverified / gaps list
1. Exact "fill time" constant in Agave pacing (about slot - 50 ms).
2. Tie-breaking order for equal priority in Agave.
3. Firedancer bundle queue priority semantics.
4. Current stake share of Firedancer, Frankendancer, Harmonic, Paladin, BAM (only Jan 2026 BAM figure from Blockworks).
5. Alpenglow exact slot and UTC time; `getBlock` shape after activation (no votes, no ticks, `bank_id`, footer).
6. Whether Firedancer/Frankendancer produce blocks after Alpenglow activation.
7. `ClientId` enum names beyond the confirmed set; reliability of Jito/BAM/Harmonic separation via gossip.
8. Agave 3.x forwarding flags (legacy forwarding on/off).
9. swQoS 80% figure and per-peer connection limits for current versions.
10. IBRL score formulas.
11. Chorus One report edition and URL.

---

## Implications for experiment design (10 bullets)
1. Treat fee priority as a weak predictor of position, not a rule: Agave greedy defers conflicting transactions and 4 workers race to PoH; Firedancer pack emits microblock contents "in no particular order". Measure rank correlation, not exact order.
2. Use requested CU limit, not CUs consumed, when computing the expected Agave priority (`reward*1e6/(cost+1)`). Probe transactions should set a deliberate CU limit and record it.
3. Avoid account conflicts in probes (use unique writable accounts per probe) so any deviation from priority is due to scheduler design, not lock conflicts; add a deliberate conflict arm separately to observe deferral.
4. Attribute by the slot where the transaction landed, then by that slot's leader and its client. Retries (2 s, 2 leaders) and swQoS can push a probe into a different leader than planned; log intended vs landed slot.
5. Classify leaders with several signals: `getClusterNodes.clientId` + `version`, Jito/BAM/Harmonic lists, and block-shape fingerprints (bundle contiguity, FIFO-like arrival order, late packing). Do not trust `clientId` alone since it is self-reported and cannot separate BAM/Harmonic.
6. Expect leader-specific modes: BAM and Harmonic leaders can produce FIFO or batch-auction order (shreds released late in Harmonic), so include arrival-time stamps (send time, per-RPC) to test FIFO against priority.
7. Analyse by position within the 4-slot leader window and by slot (first vs last of the window) because late packing and timing games shift where transactions land; IBRL treats uneven packing as a quality signal.
8. Split data at the Alpenglow boundaries: 400 ms before 2026-10-09, 200 ms from 10-09, Votor from 10-21 (epoch 1064). Post-switch blocks have no votes and no ticks, so drop vote-prefix assumptions and recompute positions among non-vote transactions only.
9. Check live whether Firedancer/Frankendancer are still producing blocks after 2026-10-21; if not, their arm may need data from before the switch only, with an explicit regime flag.
10. Plan sample size around client share: small groups (Harmonic, Paladin, BAM, full Firedancer) have few leader slots per epoch, so run across several epochs and report per-client confidence intervals; state that no prior cross-client ordering study exists, so results are exploratory.
