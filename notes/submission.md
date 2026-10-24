# Submission text (submitted on Superteam Earn on 24.10.2026; editable until the deadline)

**Link:** https://github.com/fomoles/superteam-inside-the-block

**Tweet / short description (≤ 280 chars):**

> How do Solana validators order txs after Alpenglow? 13k probes sent straight to the leader in 2200 mainnet
> windows, 10 clients: txs that wait together are sorted by fee per estimated cost. A pre-registered second run
> confirmed all 7 checks. Jito sorts less. `docker compose up`

**Description field:**

Inside the Block measures how validator clients order transactions inside their own blocks on mainnet after
Alpenglow (epoch 1066, 24.10.2026). Its main evidence comes from transactions we sent ourselves.

- **Panel:** 20 validators in run 1 and 47 in run 2 (44 reached, 24 new), in 10 client/version groups, taken from gossip `clientId` + `version`: Agave 4.3.2
  and 4.5-alpha, Jito, Agave-BAM, Harmonic-Agave, Rakurai, Firedancer 26.10.3 and 26.10.4,
  Harmonic-Firedancer, FireBAM. A cross-section adds 110 more validators.
- **Active layer:**
  - **Method.** Pairs of probes go over QUIC straight to the target leader's TPU, with a send gap of 0, 30 or
    150 ms that we control. Arms: equal fee, cheap→pricy, pricy→cheap, shared vs separate payer, and a
    cu_price vs total-fee pair. The rules were pre-registered in git before any live data.
  - **Runs.** Run 1: 6600 probes in 1100 leader windows, 5008 landed, 0.039 SOL. Run 2: 6438 probes in
    another 1100 windows, 4687 landed, ≈ 0.036 SOL.
  - **Result.** Pooled, the pricier second tx gets ahead 61 %, the equal-fee one 41 %, and the cheaper second
    one 4 %. One model fits every gap: txs that wait in the buffer together are fee-sorted, the rest keep
    arrival order.
  - **Two numbers per client** (found in run 1). The share of pairs where the fee decides is +0.57 pooled and
    0.60–0.69 for Firedancer, Harmonic and Agave-BAM. Jito is lower at +0.38: −0.28 [−0.44, −0.11]. Ties are
    close to a coin flip, except in Firedancer 26.10.4, which gives them to the later arrival (1.00
    [0.72, 1.00]).
  - **Run 2 confirmed all seven pre-registered checks** on new data, committed before its first probe: the
    fee decides +0.52 [+0.45, +0.59] (+0.56 on the 24 new validators), a cheaper later tx passes 5 %, Jito
    sorts less (−0.45 [−0.72, −0.20] vs the four fee-sorters), Firedancer 26.10.4 gives ties to the later
    arrival (1.00 [0.68, 1.00]).
  - **What "fee" means.** In run 1 the higher total fee beat the higher cu_price in 85 % of pairs. In run 2 the
    same probes carry one instruction that changes only the scheduler's cost estimate, and the order flipped:
    the higher fee per estimated cost went first in 79 % [74, 84], in every client. The sort key is fee per
    estimated cost unit, as in the Agave and Firedancer scheduler source.
- **Passive layer:** ≈ 6200 real blocks. Across a whole block, fee and position are unrelated in every client.
  At the start of a leader's window, BAM front-ends sort by fee: Agave-BAM ρ −0.48, FireBAM −0.52, on every
  BAM node. Jito on the same Agave code is −0.09, and Harmonic is flat. This replicated on a hold-out sample,
  in the live windows, and in a pre-registered cross-section of 110 validators.
- **Who you send to is not who builds.** 66 % of stake sits behind shared front-end IPs. Probes that missed
  their target landed with a leader behind the same IP in 596 of 603 cases.
- **Honest limits:**
  - The v1 pre-registered per-client test (FPI) gives few clean verdicts: on run 2 alone Harmonic-Agave is
    "fee priority", three clients are "mixed / weak" and six lack data. FPI mixes the fee-decides share with
    the tie rule; run 2's checks measure both directly.
  - Two cross-section predictions failed (Firedancer 26.10.4, Agave).
  - The FPI index and the RATIO arm had design flaws, which the report names and run 2 fixed.
  - A 7-round critique log lists every mistake we found in our own work, including a post-Alpenglow v1
    parsing trap that silently zeroes priority fees.

Reproduce: `docker compose up` (≈ 15 min on public RPC, spends nothing). Every probe and block is keyed by
signature and slot; `itb verify` checks stored positions against the chain.
