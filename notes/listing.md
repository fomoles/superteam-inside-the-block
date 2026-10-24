# Listing — exact requirements (re-read 2026-10-24 ~02:16 CEST)

Source: https://superteam.fun/earn/listing/inside-the-block-how-solana-validators-order-transactions
Sponsor: Superteam Ukraine. Regional: Ukraine only. Contact: t.me/KseniiaK2.
Prizes: 2,500 USDC = 800 / 600 / 500 / 300 / 300.
Submissions shown: 3. Countdown on 24.10 02:16 CEST: 12d 21h 44m → deadline ≈ **2026-11-05 ~00:00 UTC** (page gives no exact time; treat Nov 4 evening as safe).
Winners: by 2026-11-19.

## Mission
Order of txs inside a block is decided by the leader's scheduler. Agave code is public; forks holding most stake are not documented. Measurement project: **send real transactions into the leader windows of specific validators** and show from the blocks what rule they landed by.

## Question (per validator)
1. By what rule does it order txs — what decides earlier vs later.
2. How strictly the rule holds.
3. Whether there is a rule at all.

## Hard requirements
- Mainnet only (devnet: one client, empty blocks — "nothing to measure").
- ≥ 6 validators spanning ≥ 3 distinct client software/fork versions (version string or validators.app data at time of measurement).
- Code must enforce a fee spend limit; whole process ≈ 0.05 SOL.
- Jito-Solana validators in scope; Jito **bundles and tips out of scope**.
- **Primary evidence must come from transactions you send yourself**; other block txs = supplementary only.
- Free design: tx type/count, sending method, leader-window detection, repetition.
- Alpenglow upgrade Oct 21: all measurements either before or after, never mixed.
- README must show how design handles (or deliberately doesn't):
  1. leader schedule and leader types
  2. path of tx from backend to executing node (and everything in between)
  3. interaction of own txs with each other
  4. competition inside the block
  5. send order
  6. noise vs rule

## Suggested path (optional)
localnet (solana-test-validator) → devnet e2e free → mainnet dry-run (real schedule, built not sent; "see whether you make it into the window") → mainnet live with cap.

## Submission
- Repo link, any language.
- One command, **Docker Compose expected**.
- Keys only via volume/env, never in repo.
- **Dry-run by default**; real sending only behind explicit flag + spend cap.
- All raw data incl. signatures + slot numbers → judges verify with getBlock.
- README: why this design; how it handles the 6 points; **what it does NOT separate**.
- Report: **date of every measurement** + "what went wrong" section.

## Judging
- Design validity 35% — measures what it claims; addresses the 6 points.
- Verifiability & reproducibility 25% — ease of verifying claims from raw data, reproducing.
- Analysis quality 25% — depth, honesty about noise/limits/null results; "no rule / noise" valid if supported.
- Engineering 15% — dry-run quality, spend cap, logging, containerization.

## Hints read between lines
- Judges explicitly reward a dry-run that shows "whether you make it into the window" → a window-hit metric matters.
- "What it does NOT separate" → they want honest identifiability analysis.
- Sponsor phrase "forks that hold most of the stake" → Jito-Agave / BAM / Harmonic / Firedancer coverage valued.
- Public visible competitor: github.com/zdfgu113/inside-the-block (non-UA author, says can't submit; comment on listing). See research.md.
