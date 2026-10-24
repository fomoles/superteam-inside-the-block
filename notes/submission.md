# Submission text (draft — the owner submits; nothing here has been posted)

**Link:** https://github.com/<owner>/superteam-inside-the-block  ← the owner fills this in after pushing

**Tweet / short description (≤ 280 chars):**

> How do Solana validators order txs after Alpenglow? 6600 probes sent straight to the leader, 1100 mainnet
> windows, 10 clients: txs that wait together are fee-sorted; a cheaper later tx passes a pricier one 4 % of
> the time. BAM sorts the window's head. `docker compose up`

**Description field:**

Inside the Block measures how validator clients order transactions inside their own blocks on mainnet after
Alpenglow (epoch 1066, 24.10.2026). Its main evidence comes from transactions we sent ourselves.

- **Panel:** 20 validators in 10 client/version groups, taken from gossip `clientId` + `version`: Agave 4.3.2
  and 4.5-alpha, Jito, Agave-BAM, Harmonic-Agave, Rakurai, Firedancer 26.10.3 and 26.10.4,
  Harmonic-Firedancer, FireBAM. A cross-section adds 110 more validators.
- **Active layer:**
  - **Method.** Pairs of probes go over QUIC straight to the target leader's TPU, with a send gap of 0, 30 or
    150 ms that we control. Arms: equal fee, cheap→pricy, pricy→cheap, shared vs separate payer, and a
    cu_price vs total-fee pair. The rules were pre-registered in git before any live data.
  - **Run.** 6600 probes in 1100 leader windows, 5008 landed, 0.039 SOL.
  - **Result.** Pooled, the pricier second tx gets ahead 61 %, the equal-fee one 41 %, and the cheaper second
    one 4 %. One model fits every gap: txs that wait in the buffer together are fee-sorted, the rest keep
    arrival order.
  - **Where clients differ.** On ties, Jito keeps arrival order (20 % overtaken) and Firedancer 26.10.4 puts
    the later tx first (73 %).
  - **What "fee" means.** All clients rank by fee per estimated cost, not by the cu_price field (85 %).
- **Passive layer:** ≈ 6200 real blocks. Across a whole block, fee and position are unrelated in every client.
  At the start of a leader's window, BAM front-ends sort by fee: Agave-BAM ρ −0.48, FireBAM −0.52, on every
  BAM node. Jito on the same Agave code is −0.09, and Harmonic is flat. This replicated on a hold-out sample,
  in the live windows, and in a pre-registered cross-section of 110 validators.
- **Who you send to is not who builds.** 66 % of stake sits behind shared front-end IPs. Probes that missed
  their target landed with a leader behind the same IP in 596 of 603 cases.
- **Honest limits:**
  - The pre-registered per-client test gives no clean "fee priority" or "FIFO" verdict: five clients are
    "mixed / weak" and five lack data.
  - Two cross-section predictions failed (Firedancer 26.10.4, Agave).
  - The FPI index and the RATIO arm had design flaws, which the report names.
  - A 5-round critique log lists every mistake we found in our own work, including a post-Alpenglow v1
    parsing trap that silently zeroes priority fees.

Reproduce: `docker compose up` (≈ 15 min on public RPC, spends nothing). Every probe and block is keyed by
signature and slot; `itb verify` checks stored positions against the chain.
