"""Return every sub-payer's balance to the master key (live runs leave ~1.4M lamports per sub-payer)."""
from __future__ import annotations

import base64

from solders.hash import Hash
from solders.message import Message
from solders.system_program import TransferParams, transfer
from solders.transaction import Transaction

from .log import log
from .plan import PAIRS_PER_WINDOW
from .probe import BASE_FEE, derive_payer
from .rpc import Rpc
from .run import GROUPS, load_keypair


async def sweep(rpc: Rpc, keypair_path: str, dry: bool = True) -> None:
    master = load_keypair(keypair_path)
    payers = [derive_payer(master, i) for i in range(GROUPS * 2 * PAIRS_PER_WINDOW)]
    lamports = await rpc.balances([str(p.pubkey()) for p in payers])
    bh = (await rpc.call("getLatestBlockhash", [{"commitment": "confirmed"}]))["value"]["blockhash"]
    total = 0
    for p, lam in zip(payers, lamports):
        if lam <= BASE_FEE:
            continue
        amount = lam - BASE_FEE  # closes the account to 0 (allowed for system accounts)
        total += amount
        if dry:
            log("sweep_dry", payer=str(p.pubkey()), lamports=amount)
            continue
        ix = transfer(TransferParams(from_pubkey=p.pubkey(), to_pubkey=master.pubkey(), lamports=amount))
        tx = Transaction([p], Message.new_with_blockhash([ix], p.pubkey(), Hash.from_string(bh)), Hash.from_string(bh))
        sig = await rpc.call("sendTransaction", [base64.b64encode(bytes(tx)).decode(), {"encoding": "base64"}])
        log("sweep", payer=str(p.pubkey()), lamports=amount, sig=sig)
    log("sweep_total", lamports=total, dry=dry)
