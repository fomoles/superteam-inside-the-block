"""Probe transactions.

A probe is a legacy transaction with exactly three instructions:
  1. ComputeBudget.SetComputeUnitLimit(limit)
  2. ComputeBudget.SetComputeUnitPrice(price_micro_lamports)
  3. System.Transfer(payer -> payer, tag lamports)
The self-transfer moves no money; its lamport amount is a *tag* that encodes
(pair id, role), so every probe is identifiable from the chain alone.
Its only writable account is the payer, so two probes conflict iff they share
a payer. Measured on mainnet 24.10: 450 CU consumed (simulateTransaction).
A Memo instruction was rejected as the tag carrier: a 20-byte memo needs >4,700 CU.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

from solders.compute_budget import set_compute_unit_limit, set_compute_unit_price
from solders.hash import Hash
from solders.keypair import Keypair
from solders.message import Message
from solders.system_program import TransferParams, transfer
from solders.transaction import Transaction

BASE_FEE = 5000  # lamports per signature
PROBE_CU_USED = 450


@dataclass(frozen=True)
class FeeLevel:
    name: str
    cu_limit: int
    cu_price: int  # micro-lamports per CU

    @property
    def priority_fee(self) -> int:
        # Agave/Firedancer: ceil(price * limit / 1e6)
        return (self.cu_price * self.cu_limit + 999_999) // 1_000_000

    @property
    def fee(self) -> int:
        return BASE_FEE + self.priority_fee


LEVELS = {
    "LOW": FeeLevel("LOW", 600, 1_000),            # 1 lamport priority
    "MID": FeeLevel("MID", 600, 1_000_000),        # 600
    "HIGH": FeeLevel("HIGH", 600, 10_000_000),     # 6,000
    # Ratio arm: A pays more per CU, B pays more in total.
    "RA": FeeLevel("RA", 600, 5_000_000),          # 3,000 total, 5.0M uL/CU
    "RB": FeeLevel("RB", 6_000, 1_000_000),        # 6,000 total, 1.0M uL/CU
}
MAX_FEE = max(l.fee for l in LEVELS.values())


def encode_tag(pair_id: int, role: int) -> int:
    assert role in (1, 2) and 0 <= pair_id < 200_000
    return pair_id * 4 + role


def decode_tag(tag: int) -> tuple[int, int]:
    return tag // 4, tag % 4


def build_probe(payer: Keypair, blockhash: str, level: FeeLevel, tag: int) -> Transaction:
    ixs = [
        set_compute_unit_limit(level.cu_limit),
        set_compute_unit_price(level.cu_price),
        transfer(TransferParams(from_pubkey=payer.pubkey(), to_pubkey=payer.pubkey(), lamports=tag)),
    ]
    msg = Message.new_with_blockhash(ixs, payer.pubkey(), Hash.from_string(blockhash))
    return Transaction([payer], msg, Hash.from_string(blockhash))


def derive_payer(master: Keypair, index: int) -> Keypair:
    """Deterministic sub-payer, recoverable from the master key alone (see `sweep`)."""
    seed = hashlib.sha256(bytes(master) + f"itb-payer-{index}".encode()).digest()
    return Keypair.from_seed(seed)
