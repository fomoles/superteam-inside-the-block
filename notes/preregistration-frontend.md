# Pre-registration: cross-section test of the head-of-window fee order (round 4)

Written and committed **before** any block of this sample was fetched. The fetch runs only after this file is in
git (`scripts/frontend_sample.py fetch`), so the commit time is proof of order.

## Why

The head-of-window result (REPORT 3.1) uses **one validator per client group**. It replicated on a hold-out
sample of later blocks of the *same* validators. It could still be a property of that one operator rather than
of the client software, or of what sits in front of it. The survey also found that 66 % of stake advertises a
`tpuQuic` address shared by >= 3 identities (`scripts/shared_tpu.py`): 96 % of AgaveBam stake sits behind BAM
nodes, 100 % of Harmonic stake sits behind Harmonic relays. JitoLabs, Firedancer, Agave and Rakurai have their
own TPU. If the order is decided by the shared front-end, it should be the same for every validator behind it.

## Sample (fixed before fetching)

- Source: the survey snapshot `data/survey/cluster-2026-10-24T003342Z.json.gz` (already committed).
- Validators of each group below, **excluding the panel validators**, shuffled with
  `numpy.random.default_rng(20261024)`, in snapshot order before shuffling.
- For each one, in order, take up to the 2 most recent *past* leader windows of the current epoch
  (window ended >= 64 slots ago); skip a validator with none. Stop when the group's quota is filled.
- AgaveBam is spread across BAM nodes: at most 3 validators per `tpuQuic` IP.
- Quota (validators): AgaveBam 4.3.2: 24 · JitoLabs 4.3.2: 20 · HarmonicAgave 4.3.2: 16 ·
  HarmonicFiredancer 26.10.4: 16 · Firedancer 26.10.4: 16 · FireBAM 26.10.4: 12 · Agave 4.3.2: 10 ·
  Rakurai 4.3.2: 8. Firedancer 26.10.3 has one non-panel validator and is left out.
- Only the window's 1st block (slot % 4 == 0) is fetched. That is ≈ 120 validators × 2 = ≈ 240 `getBlock` calls on
  the public RPC.

## Statistic

The same as REPORT 3.1 and `scripts/replication_head.py`: Spearman rho of priority fee per CU against position,
over the first 64 non-failed, non-Jito-tip txs of the block (since Alpenglow, votes are not block txs); blocks with < 20 such txs are dropped.
Each validator gets the mean over its blocks. The group statistic is the mean over validators. The 95 % CI comes
from a bootstrap over validators (2000 draws).

## Predictions (from the panel validators' discovery + hold-out estimates)

- **H1, the group effect generalises.** For each group with >= 8 validators in the sample, the cross-section
  mean is within ±0.15 of the panel validator's hold-out estimate. Those estimates are: AgaveBam −0.57,
  FireBAM −0.40, JitoLabs −0.13, Agave −0.17, Rakurai −0.14, Firedancer 26.10.4 −0.07, HarmonicAgave −0.08,
  HarmonicFiredancer −0.05. We report how many groups pass.
- **H2, BAM and Jito differ.** Both run the same Agave 4.3.2 code base. Prediction: AgaveBam − JitoLabs < −0.2,
  and the 95 % CI (independent bootstraps) excludes 0.
- **H3, Harmonic is flat.** HarmonicAgave and HarmonicFiredancer means are both > −0.15.
- **H4, the order is a property of BAM, not of a single BAM node.** For every BAM IP with >= 3 sampled validators,
  the mean is <= −0.3. This is descriptive: the counts per IP are small.

Any prediction that fails is reported as failed, not re-worded.
