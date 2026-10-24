# Submission text (draft — the owner submits; nothing here has been posted)

**Link:** https://github.com/<owner>/superteam-inside-the-block  ← the owner fills this in after pushing

**Tweet / short description (≤ 280 chars):**

> How do Solana validators order txs after Alpenglow? 20 mainnet validators, 10 clients, 475 blocks:
> fee order shows only at the leader window's start (BAM, Firedancer 26.10.3), not across the block.
> Direct-to-leader probe design, one `docker compose up`.

**Description field:**

Inside the Block measures how validator clients order transactions inside their own blocks on mainnet,
after Alpenglow (epoch 1066, 24.10.2026).

- **Panel:** 20 validators in 10 client/version groups, taken from gossip `clientId` + `version`: Agave
  4.3.2 and 4.5-alpha, Jito, Agave-BAM, Harmonic-Agave, Rakurai, Firedancer 26.10.3 and 26.10.4,
  Harmonic-Firedancer, FireBAM.
- **Passive layer:** 475 blocks from these validators' own leader windows. Across whole blocks fee and position are unrelated for every client (ρ ≈ 0). At the start of the leader's window, Agave-BAM (ρ −0.57), FireBAM (−0.41) and Firedancer 26.10.3 (−0.29) put higher-fee txs clearly first, while Firedancer 26.10.4, Harmonic and Rakurai do not. A middle-of-block placebo is ≈ 0. This is exploratory and correlational, and the report says why.
- **Active design:** pairs of probe txs sent over QUIC straight to the target leader's TPU, so they land
  in its block or nowhere. Arms separate the fee rule, the arrival order, the noise floor, write-lock
  conflicts and per-CU vs total fee. The send gap (0/30/150 ms) and the phase (buffered before the window
  vs streaming) are controlled. Statistics use a cluster bootstrap by window and a Holm correction, with
  rules pre-registered in git before any live data.
- **Verified on mainnet without spending:** two dry-runs reached real leader windows over real QUIC
  connections, with every send timed and logged. Live probes cost ≈ 0.016 SOL; the hard cap is enforced in
  code.
- **Honest limits:** the live run needs a funded key and is not included; the passive layer is
  correlation only; the critique log (3 rounds) lists every bug we found in our own work, including a
  post-Alpenglow v1 parsing trap that silently zeroes priority fees.

Reproduce: `docker compose up` (≈ 15 min on public RPC, spends nothing).
