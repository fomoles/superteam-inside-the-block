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
2. **The dry-run exposed a real timing bug.** In the first 36 sends, the estimated slot at send sat a median
   **−3.9 slots** before the target window, and only 28 % were inside [−1.5, 4). Over all 234 sends the median
   aim was fine (TPU, IN: +0.65 slots, target +0.5…+2.4; PRE: −1.57, target −1.2), but the tails reached
   −12.8 slots, and some sends left up to **856 ms after plan**. One cause was in the slot clock: the slot length
   came from the *median gap* between websocket notifications. The gaps arrive in uneven bursts (deciles 16…397 ms), so
   the median was 201 ms against a true 210.7 ms (a least-squares fit over 40 s, 190 notifications). A 5 % slope
   error, extrapolated, moves the aim by whole slots. Under v1 the PRE/IN phases would have been mislabeled in live
   runs, and the money spent. **Fix:** least-squares slope over the 400-notification buffer, then re-measure.
   A second cause is that a send can wait behind the QUIC handshake or a busy event loop. **Fix:**
   pre-registered amendment A1: pairs sent > 50 ms after plan are not usable, and their share is reported.
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
8. **The biggest find of this round: a parser bug, found by chasing item 5.** About 60 % of passive txs had
   price 0. Most of them were **v1 transactions**: 11,456 v1 rows had no price and only 135 had one. v1 txs
   carry their compute budget in `transactionConfig` (`computeUnitLimit` and `priorityFee`, a *total* in
   lamports), not in ComputeBudget instructions, so the parser read them as "no priority fee". The positive
   head ρ of item 4 was largely this artifact: zero-priced v1 txs were mostly real paying txs. **Fix:** read
   `transactionConfig` and convert the total into the equivalent µL/CU (`priorityFee·10⁶ / computeUnitLimit`).
   Added a regression test, deleted the affected blocks and collected them again. Every passive number from
   before this fix is discarded.
9. **Dry-run 2 (after the clock fix), 25 windows, 150 planned sends.**

   | path, phase | aim, median (dry-run 1 → 2) | range in dry-run 2 | sends > 50 ms late (1 → 2) |
   |---|---|---|---|
   | TPU, IN | +0.65 → +1.84 | −0.09 … +4.27 | 2/90 → 0/52 |
   | TPU, PRE | −1.57 → −0.74 | −1.80 … +1.25 | 17/120 → 4/68 |
   | RPC, IN | −1.93 → +1.56 | +0.88 … +2.27 | 0 → 0 |
   | RPC, PRE | −3.56 → −1.18 | −1.57 … +0.54 | 0 → 0 |

   Aim is in slots relative to the window start; the target is −1.2 for PRE and +0.5…+2.4 for IN. The tails
   of −8 to −13 slots are gone. Late sends dropped from 8 % to 2.7 %, and they cluster: all 4 late sends of dry-run 2 fall in one
   window (19 in 4 windows in dry-run 1), starting with that window's first send. A slow connection to one
   leader delays a whole window. A1 drops such pairs; the window clustering is reported.

### Applied
- `itb/schedule.py`: regression slot length (item 2).
- `itb/verify.py`: probe-position check (item 3).
- `itb/analyze.py`: head-of-block and head-of-first-block rank tests, plus a timing figure that works without
  landed data (item 4).
- Analysis report labels small groups (item 6), see round 3.
- `itb/collect.py`: v1 `transactionConfig` parsing plus a test (item 8); passive blocks collected again.
- `itb/rpc.py`: rotation between two no-sign-up public endpoints, each paced separately (halves the 429 waits).
- `notes/preregistration.md` amendment A1 and `itb/analyze.py`: late sends are not usable (item 2).

## Round 3: a skeptical judge reads the final passive results (2026-10-24)

Data: 480 slots (475 blocks) from 20 validators, 6 recent leader windows each, collected again after the
v1 parser fix. Numbers: `report/results.md` and `data/results/robustness_head.txt`
(`scripts/robustness_head.py`).

### What the data now say
- Whole-block rank ρ(position, µL/CU) is ≈ 0 in every group (−0.08 … +0.02).
- At the **head of the window's first block** it is clearly negative (higher fee → earlier) for
  **AgaveBam −0.57 [−0.64, −0.49], FireBAM −0.41 [−0.55, −0.26], Firedancer 26.10.3 −0.29 [−0.41, −0.19]**,
  weaker for Jito −0.16 and Agave 4.3.2 −0.15, and ≈ 0 for Firedancer 26.10.4, both Harmonic groups and
  Rakurai.

### What a judge would attack
1. **"Head ρ is just who arrives first."** Senders paying high fees are also the ones who aim at the slot
   start. Passive data cannot separate a sorted buffer from fee-correlated arrival. *This is the core limit
   and the reason the active design exists.* Mitigation: a middle-of-block placebo window (txs 128–191). If
   the head were just "early, sophisticated traffic", the effect would not stop abruptly. It does: middle ρ is
   −0.08 … +0.02 for the three strong groups. This makes a buffer drain at slot start the more likely
   reading, but does not prove it.
2. **Small samples.** 6 windows × 2 validators = up to 12 first blocks per group, in ≈ 6.5 hours. The
   bootstrap CIs are by block. The robustness script (which also needs ≥ 256 txs per block) keeps only 2–12
   blocks per group, and Rakurai drops out. **Applied:** the report calls the head result *exploratory* and
   gives no per-group verdict from it.
3. **Client or operator?** In the three strong groups both validators agree (AgaveBam −0.51/−0.56, FireBAM
   −0.47/−0.56, Firedancer 26.10.3 −0.41/−0.30). In Firedancer 26.10.4 they disagree (+0.26 vs −0.11), so
   there the operator, not the client, may drive it. **Applied:** per-validator values are published.
4. **Zero-price txs.** With price-0 txs dropped, the head ρ stays negative in the three strong groups
   (−0.31, −0.43, −0.56). It also turns clearly negative for Agave 4.3.2 (−0.46) and 4.5 (−0.30): there, many
   unpriced txs sit early in the head and mask a fee order among priced ones. **Applied:** reported as a
   second row, not merged.
5. **Bundles.** Jito-tip txs are excluded, but BAM bundles that pay no Jito tip account are not detectable
   and may sit at the head. The two BAM groups being the strongest fits a "sorted auction batch first"
   reading, and also a bundle artifact. *Not separable here*; stated as a limit.
6. **Harmonic ≈ 0.** Harmonic blocks are built by external builders, so their order reflects the
   winning builder's choices, not the validator's scheduler. No claim is made.
7. **Multiplicity.** 10 groups × 3 head statistics. Nothing passive is Holm-corrected, because nothing
   passive is a verdict. Only pre-registered active H1 gets the correction.

### Applied
- `scripts/robustness_head.py` plus its output in `data/results/robustness_head.txt` (items 1, 3, 4).
- REPORT.md section 3.1: "exploratory" label, placebo, per-validator values, the bundle and arrival limits.

## Round 4: the passive finding under attack, and the first live data (2026-10-24, night)

The owner funded a key (0.116 SOL) and started the 3-hour live run (`scripts/live.sh`, cap 0.08 SOL).
Passive blocks were extended towards 20 windows per validator (896 blocks so far; paused during the live run so
the public RPC quota goes to it).

### What a judge would attack
1. **"You found it in the data you then reported."** The head-of-window statistic was added after seeing
   blocks (round 2). **Applied:** `scripts/replication_head.py` re-computes it on blocks fetched *after* the
   finding was committed (hold-out, not in 133c919). The three strong groups replicate: AgaveBam −0.57 → −0.56,
   FireBAM −0.41 → −0.38, Firedancer 26.10.3 −0.29 → −0.26; Agave 4.3.2 −0.15 → −0.17. Two groups move:
   Rakurai ≈ 0 → −0.14 and Harmonic-Firedancer −0.03 → −0.10, so for them the discovery sample was not
   representative and no claim is made. Output: `data/results/replication_head.txt`.
2. **"Bots just aim at every slot start."** If so, the head order would be equally strong in all four blocks
   of a window. **Applied:** `scripts/backlog_head.py`. In the three strong groups the order is stronger in
   the window's 1st block than in blocks 2–4 by ≈ 0.23 (CIs exclude 0), but blocks 2–4 are still negative
   (AgaveBam −0.31, FireBAM −0.18). This fits "the leader drains a backlog in priority order, and the backlog
   is biggest when its window opens", and it does not rule out a smaller slot-start effect.
   Output: `data/results/backlog_head.txt`.
3. **Landing of unstaked probes.** A quick status check on the first 90 pairs said 43 of 156 direct-TPU sends
   landed (28 %) and 0 of 24 RPC-path sends. **That was wrong, and the RPC claim drawn from it is withdrawn.**
   The quick check asked a load-balanced public RPC with `searchTransactionHistory: false` minutes after the
   sends; `itb collect` (history search, then the block itself) on a copy of the first 60 windows finds 76 % of
   the direct-TPU probes and 30 of 30 RPC-path probes in blocks. Lesson: landing is read from blocks, never
   from a status cache. Final per-arm landing: see the live analysis below.
