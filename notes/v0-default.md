# v0 — the first-instinct design (written fast, before research, on purpose)

1. `getClusterNodes` → map identity → version string. Pick 6 validators: 2 Agave, 2 Jito-Agave, 2 Firedancer.
2. `getLeaderSchedule` → find their upcoming slots.
3. For each target: shortly before their window, send ~5 self-transfer txs with different priority fees (e.g. 0, 1k, 10k, 100k, 1M micro-lamports/CU) via the public RPC `sendTransaction`.
4. After the window: `getBlock` for their slots, find our txs, read their index in the block.
5. Compute Spearman correlation between priority fee and in-block position per validator. If negative (higher fee → earlier), "validator orders by priority fee". Also run the same on all txs in the block (fee vs index).
6. Plot fee vs position scatter per client. README + report. Docker image running `python main.py`.

Expected conclusion: "Agave and Jito order by priority fee; Firedancer orders by fee/CU ratio; correlation strong but noisy."
