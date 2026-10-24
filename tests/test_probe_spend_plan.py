import json

import pytest
from solders.keypair import Keypair

from itb import plan as P
from itb.probe import LEVELS, build_probe, decode_tag, derive_payer, encode_tag
from itb.spend import SpendCapExceeded, SpendLedger

BH = "4uQeVj5tqViQh7yWWGStvkEG1Zmhx6uasJtWCJziofM"  # any valid base58 hash


def test_fee_formula_matches_mainnet_getFeeForMessage():
    # measured 24.10.2026: limit 5000 x price 1000 uL/CU -> getFeeForMessage = 5005
    from itb.probe import FeeLevel
    assert FeeLevel("x", 5000, 1000).fee == 5005
    assert LEVELS["LOW"].priority_fee == 1 and LEVELS["HIGH"].priority_fee == 6000
    # ratio arm: RA higher per-CU price, RB higher total fee
    assert LEVELS["RA"].cu_price > LEVELS["RB"].cu_price and LEVELS["RB"].fee > LEVELS["RA"].fee


@pytest.mark.parametrize("pid,role", [(0, 1), (0, 2), (12345, 1), (199_999, 2)])
def test_tag_roundtrip(pid, role):
    assert decode_tag(encode_tag(pid, role)) == (pid, role)


def test_probe_shape_and_conflict_set():
    kp = Keypair()
    tx = build_probe(kp, BH, LEVELS["MID"], encode_tag(7, 1))
    msg = tx.message
    assert len(msg.instructions) == 3
    # only the payer is writable -> two probes conflict iff they share a payer
    assert msg.header.num_required_signatures == 1
    h, keys = msg.header, msg.account_keys
    ns, nro_s, nro_u = h.num_required_signatures, h.num_readonly_signed_accounts, h.num_readonly_unsigned_accounts
    writable = [k for i, k in enumerate(keys) if i < ns - nro_s or ns <= i < len(keys) - nro_u]
    assert writable == [kp.pubkey()]
    assert len(bytes(tx)) < 300


def test_derived_payers_are_deterministic_and_distinct():
    m = Keypair()
    a = [derive_payer(m, i).pubkey() for i in range(12)]
    assert a == [derive_payer(m, i).pubkey() for i in range(12)]
    assert len(set(a)) == 12


def test_spend_cap_refuses_and_persists(tmp_path):
    p = tmp_path / "ledger.json"
    led = SpendLedger(p, cap_lamports=20_000)
    led.book(11_000, "window", "a")
    with pytest.raises(SpendCapExceeded):
        led.book(10_000, "window", "b")
    assert json.loads(p.read_text())["booked"] == 11_000
    # survives a restart: the cap is global, not per process
    led2 = SpendLedger(p, cap_lamports=20_000)
    with pytest.raises(SpendCapExceeded):
        led2.book(9_001, "window", "c")
    led2.book(9_000, "window", "d")


def test_balance_guard(tmp_path):
    led = SpendLedger(tmp_path / "l.json", cap_lamports=1000)
    led.set_baseline(10_000)
    led.set_baseline(5)  # baseline is set only once
    led.check_balance(9_000)
    with pytest.raises(SpendCapExceeded):
        led.check_balance(8_999)


def test_plan_deterministic_and_payers_in_group():
    a = P.plan_window(1, 1000, "X", 0, payer_base=6)
    b = P.plan_window(1, 1000, "X", 0, payer_base=6)
    assert [x.asdict() for x in a] == [x.asdict() for x in b]
    for x in a:
        assert 6 <= x.payer_first < 12 and 6 <= x.payer_second < 12
        assert (x.payer_first == x.payer_second) == x.shared_payer
        assert len({x.path for x in a}) == 1  # one path per window
    # pairs in one window never share a payer with each other
    used = [x.payer_first for x in a] + [x.payer_second for x in a if not x.shared_payer]
    assert len(used) == len(set(used))


def test_plan_covers_all_arms():
    arms = {p.arm for w in range(0, 4 * 400, 4) for p in P.plan_window(3, w, "X", 0, 0)}
    assert arms == set(P.ARMS)
