# Critique log

## Round 1 — v0 (first instinct) vs. the listing and vs. the visible competitor (2026-10-24)

### v0's flaws
1. **Confuses arrival with priority.** Five txs fired at once through RPC arrive at the leader in a random order. A fee/position correlation cannot tell "scheduler sorts by fee" from "higher-fee tx happened to arrive first". Nothing in v0 controls *when* each tx reaches the leader.
2. **No controls.** v0 has no case where the two candidate rules make the *same* prediction, so it can't measure the pure noise floor (how often the path alone flips two txs). It also has no equal-fee case, so it can't measure FIFO among ties.
3. **Single fee payer = forced conflict, never stated.** All v0 probes share one writable account (the payer). In both Agave and Firedancer, conflicting txs are serialized. Non-conflicting txs run in parallel threads, where "order" may not even be meaningful. v0 measures only one of the two regimes and doesn't know it.
4. **Wrong leader attribution.** RPC forwards to the current and next leaders, so a tx aimed at X often lands in Y's block. v0 credits X. (The competitor hit this exact bug; see their "what went wrong #2".)
5. **"Fee" is ambiguous.** The schedulers rank by reward *per cost unit*, not by total fee. v0 can't tell which.
6. **Too few observations, wrong unit of analysis.** Five txs per validator gives 10 dependent pairs. Pairs from the same burst share a block and a path, so they are not independent. A naive binomial test overstates significance.
7. **Survivorship bias.** Only landed txs are seen. If low-fee txs that would have gone early are *dropped* under congestion, the landed set is fee-ordered by selection, not by scheduling. Drops must be logged and reported per arm.
8. **Passive whole-block correlation as evidence.** It is confounded by bundles (Jito bundles are placed as units), by sophisticated senders who pay more AND arrive earlier, and by vote txs. The listing says it is supplementary only.
9. **RPC sampling bias.** Whichever RPC we send through decides the path, and that is not reported.
10. **Unreproducible.** `python main.py` in Docker, no pinned versions, no offline re-analysis from raw data, no verify step.
11. **Typical AI-agent failure modes to avoid.** The "expected conclusion" written before data (v0 literally has one); invented CU/fee numbers; README claims not backed by a file in `data/`; untested Docker; padded README.

### The competitor's design (github.com/zdfgu113/inside-the-block, read 24.10)
- Sends 4 txs per burst *in parallel* through 2 public RPCs, then reads "send order" from millisecond send timestamps. Because the sends are parallel, arrival order at the leader is essentially random. "Send-first ≈ 50%" is therefore expected under *any* rule and identifies nothing. Their fee-vs-arrival separation is much weaker than claimed.
- One payer, so every pair conflicts. Non-conflicting ordering is never tested.
- 135 pairs from 48 bursts, but significance is computed as if the pairs were independent. The 6 pairs per 4-tx burst are correlated.
- No noise-floor control and no equal-fee control.
- They land off-target often (RPC forwarding) and must re-attribute. Strict on-target sample: 40 pairs.
- Docker compose doesn't run analysis or reproduce the report with one command.
- Positive: real live data, a spend cap, honest "what went wrong", correct per-producer attribution.

### Better design (v1), the core ideas
1. **Direct-to-leader QUIC (TPU) sending as the primary path.** Verified on 24.10: a handshake from this Mac to Agave, Jito, Harmonic-Agave and Harmonic-Firedancer TPUs takes 82–117 ms. A tx sent only to the target's TPU can land only in that target's block, or nowhere, and costs nothing if dropped. Attribution is clean by construction. Path noise shrinks to one hop with a measured RTT. Public RPC `sendTransaction` stays as a second, recorded path for comparison.
2. **Controlled send spacing Δt within a pair.** Low-fee tx first, high-fee tx Δt ms later, with Δt ∈ {0, 20, 80, 320} ms. A priority scheduler lets the later high-fee tx overtake while both sit in its buffer; FIFO never does. The "overtake curve" P(overtake | Δt) measures *how strictly* the rule holds and over what time horizon. That is the listing's "how strictly" question.
3. **Built-in controls:** concordant pairs (high fee sent first, where both rules agree, so inversions are pure noise) and equal-fee pairs (measure FIFO among ties).
4. **Conflict arm:** the same discordant pair, but from two different payers (no shared writable account). This answers "interaction of own txs" explicitly.
5. **Ratio arm:** A has a higher price per CU but a lower total fee than B. This separates "per-CU priority" from "total fee".
6. **Timing phase:** pairs that arrive just *before* the window (both buffered before the block starts) vs. *inside* it (streaming block building).
7. **Unit = pair, clustered by window.** Cluster bootstrap CIs, Holm correction across client groups, and a pre-registered decision rule written *before* live data (`notes/preregistration.md`).
8. **Every probe self-describing on-chain:** a memo `itb1:<run>:<pair>:<arm>:<role>`, so a judge can verify the design from the chain alone.
9. **Leader verified from the block itself** (the fee reward recipient in `getBlock` rewards), not only from the schedule.
10. **Drops are first-class data.** Every built and sent tx is logged with its fate (landed in target, landed elsewhere, never landed). Landing rate per arm and per fee is reported to address survivorship bias.
11. **Passive supplement:** for every block a probe landed in, a per-tx table (position, fee/CU, CU, vote, bundle-tip flag, writable-set hash), comparing fee-rank concordance for conflicting vs. non-conflicting pairs.
12. **One command:** `docker compose up` runs survey, mainnet dry-run, offline analysis of committed raw data, report regeneration and an on-chain spot-verification of claims. Live sending: `docker compose run --rm itb live --i-understand-this-spends-sol` plus a keypair volume.

## Round 2: a skeptical judge reads the built pipeline and the first real data (2026-10-24)

Read against the code in `itb/`, a partial passive dataset (268 blocks) and the first 5-minute mainnet dry-run.

### What a judge would attack
1. **No active results.** The core measurement needs a funded key. Without it, the headline is a design plus
   passive correlations, and a judge scores "answers the question with data" low. *Cannot be fixed here*
   (hard limit: no wallets with funds). Mitigation: (a) make the passive layer say something a whole-block
   correlation can't (item 4); (b) prove the active pipeline end-to-end on mainnet *except the send* (dry-run:
   real leader windows, real QUIC handshakes to the real TPUs, logged send times); (c) an exact cost and a
   one-line command for the owner.
2. **The dry-run exposed a real timing bug.** The send-time estimate sat a median **−3.9 slots** before the
   target window, and only 28 % of sends were inside [−1.5, 4). The cause was in the slot clock: the slot length
   came from the *median gap* between websocket notifications. The gaps arrive in uneven bursts (deciles 16…397 ms), so
   the median was 201 ms against a true 210.7 ms (a least-squares fit over 40 s, 190 notifications). A 5 % slope
   error, extrapolated, moves the aim by whole slots. Under v1 the PRE/IN phases would have been mislabeled in live
   runs, and the money spent. **Fix:** least-squares slope over the 400-notification buffer, then re-measure.
3. **`verify` didn't check our own probes.** It re-checked random positions in stored blocks, but not that each
   landed probe sits at the stored index, and that index is the number the whole result rests on. **Fix:** every
   landed probe's signature is checked at its stored index against `getBlock` (finalized).
4. **The whole-block passive Spearman can't show a priority rule even if one exists.** Under streaming block
   building, arrival order dominates across the whole block. A scheduler that sorts its *buffer* by priority would
   show it only where it drains a backlog: the **head of the window's first block**. **Fix:** rank tests on the
   first 64 txs of every block, and separately of the window's first block (slot % 4 == 0).
   - First result (partial data): ρ is ~0 for the whole block but **positive** at the head of the first block
     (Firedancer 26.10.3 +0.30 [0.24, 0.36], Agave 4.3.2 +0.19 [0.07, 0.31]). Higher-fee txs come *later*
     there. That is the opposite of a sorted backlog. Round 3 must rule out artifacts.
5. **Price = 0 txs.** A tx without a SetComputeUnitPrice gets price 0. These are real (lowest priority), but if
   they cluster at a block head for a non-scheduler reason (e.g. leader-produced or oracle txs), they alone could
   create a positive head ρ. A round-3 robustness check is planned.
6. **Unbalanced passive panel.** At 268 blocks some groups have one validator and 4 blocks (AgaveBam). Groups
   with < 2 validators or < 20 blocks must be labelled, not ranked. (The collection is still running, so this
   is re-checked on the full set.)
7. **Many descriptive numbers, no correction.** 9 groups × 5 passive statistics. The report labels passive
   numbers as descriptive, gives CIs and draws no per-group verdict from them. Only the pre-registered active
   H1 gets Holm.

### Applied
- `itb/schedule.py`: regression slot length (item 2).
- `itb/verify.py`: probe-position check (item 3).
- `itb/analyze.py`: head-of-block and head-of-first-block rank tests, plus a timing figure that works without
  landed data (item 4).
- Analysis report labels small groups (item 6), see round 3.
