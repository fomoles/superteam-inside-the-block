# Submission text (draft — the owner submits; nothing here has been posted)

**Link:** https://github.com/<owner>/superteam-inside-the-block  ← the owner fills this in after pushing

**Tweet / short description (≤ 280 chars):**

> How do Solana validators order txs after Alpenglow? 20 mainnet validators, 10 client versions, real blocks
> + a direct-to-leader probe design with controlled fee, send gap and write-lock conflict. One command:
> `docker compose up`. {{SHORT_FINDING}}

**Description field:**

Inside the Block measures how validator clients order transactions inside their own blocks on mainnet,
after Alpenglow (epoch 1066, 24.10.2026).

- **Panel:** 20 validators in 10 client/version groups, taken from gossip `clientId` + `version`: Agave
  4.3.2 and 4.5-alpha, Jito, Agave-BAM, Harmonic-Agave, Rakurai, Firedancer 26.10.3 and 26.10.4,
  Harmonic-Firedancer, FireBAM.
- **Passive layer:** {{N_BLOCKS}} blocks from these validators' own leader windows. {{LONG_FINDING}}
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
