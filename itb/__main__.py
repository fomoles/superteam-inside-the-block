"""Command line: python -m itb <command>.  `python -m itb all` = the whole reproducible pipeline.

Safety defaults: nothing is ever sent to mainnet unless `run --live` is given AND a keypair path is
supplied via --keypair / $ITB_KEYPAIR AND the persisted spend cap still has room.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

from .log import log, set_sink
from .rpc import Rpc, endpoints_for

DATA = Path(os.environ.get("ITB_DATA", "data"))
REPORT = Path(os.environ.get("ITB_REPORT", "report"))
WS = {"mainnet": "wss://api.mainnet-beta.solana.com", "devnet": "wss://api.devnet.solana.com"}


def _rpc(a) -> Rpc:
    return Rpc(endpoints_for(a.network))


async def cmd_survey(a) -> None:
    rpc = _rpc(a)
    sub = DATA / ("survey" if a.network == "mainnet" else f"survey-{a.network}")
    panel = Path(a.panel) if a.write_panel else None
    from .survey import run_survey
    await rpc_close(rpc, run_survey(rpc, sub, a.per_client, panel))


async def rpc_close(rpc: Rpc, coro):
    try:
        return await coro
    finally:
        await rpc.close()


async def cmd_run(a) -> None:
    from .run import Runner
    if a.live:
        a.keypair = a.keypair or os.environ.get("ITB_KEYPAIR")
        if not a.keypair or not Path(a.keypair).exists():
            sys.exit("--live needs --keypair PATH or $ITB_KEYPAIR pointing to a keypair JSON (never inside the repo)")
        if a.network == "mainnet" and not a.yes_spend:
            sys.exit(f"--live on mainnet also needs --yes-spend (cap {a.cap_sol} SOL, ledger {a.ledger})")
    a.ws_url = a.ws_url or os.environ.get("ITB_WS_URL") or WS[a.network]
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    out = DATA / "runs" / f"{stamp}-{a.network}-{'live' if a.live else 'dry'}"
    out.mkdir(parents=True, exist_ok=True)
    set_sink(out / "events.jsonl")
    (out / "args.json").write_text(json.dumps({k: v for k, v in vars(a).items() if k not in ("func", "keypair")}, indent=1))
    rpc = _rpc(a)
    await rpc_close(rpc, Runner(a, rpc, out).run())
    print(out)


async def cmd_collect(a) -> None:
    from .collect import collect_run
    rpc = _rpc(a)
    runs = [Path(a.run)] if a.run else sorted(p for p in (DATA / "runs").glob(f"*-{a.network}-*") if p.is_dir())
    try:
        for rd in runs:
            if a.skip_done and (rd / "landed.jsonl").exists():
                continue
            await collect_run(rpc, rd, passive=not a.no_blocks)
    finally:
        await rpc.close()


async def cmd_passive(a) -> None:
    from .collect import collect_passive
    rpc = _rpc(a)
    panel = json.loads(Path(a.panel).read_text())["validators"]
    await rpc_close(rpc, collect_passive(rpc, panel, a.per_validator, DATA / "passive" / "blocks"))


async def cmd_analyze(a) -> None:
    from .analyze import run_analysis
    run_analysis(DATA, REPORT)


async def cmd_verify(a) -> None:
    from .verify import verify
    rpc = _rpc(a)
    r = await rpc_close(rpc, verify(rpc, DATA, a.n))
    if r["mismatches"]:
        sys.exit(f"verify: {len(r['mismatches'])} mismatching blocks")


async def cmd_sweep(a) -> None:
    from .sweep import sweep
    a.keypair = a.keypair or os.environ.get("ITB_KEYPAIR")
    rpc = _rpc(a)
    await rpc_close(rpc, sweep(rpc, a.keypair, dry=not a.yes))


async def cmd_all(a) -> None:
    """Reproduce: fresh survey + passive blocks + a short mainnet dry-run + collect + analyze + verify.

    Uses the committed panel (data/panel.json) so the measured validators stay the same; pass
    --new-panel to re-select from today's survey.
    """
    a.write_panel = a.new_panel
    await cmd_survey(a)
    await cmd_passive(a)
    if a.dry_minutes > 0:
        a.live, a.keypair, a.yes_spend, a.ledger = False, None, False, str(DATA / "spend-ledger.json")
        a.minutes, a.max_windows = a.dry_minutes, 10_000
        await cmd_run(a)
        a.run, a.skip_done, a.no_blocks = None, True, False
        await cmd_collect(a)
    await cmd_analyze(a)
    await cmd_verify(a)


def main() -> None:
    p = argparse.ArgumentParser(prog="itb", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--network", default=os.environ.get("ITB_NETWORK", "mainnet"), choices=["mainnet", "devnet"])
    p.add_argument("--panel", default=os.environ.get("ITB_PANEL", str(DATA / "panel.json")))
    sp = p.add_subparsers(dest="cmd", required=True)

    s = sp.add_parser("survey", help="snapshot gossip clients + stake")
    s.add_argument("--per-client", type=int, default=2)
    s.add_argument("--write-panel", action="store_true", help="(re)select the measured panel")
    s.set_defaults(func=cmd_survey)

    r = sp.add_parser("run", help="plan and (dry-)send probe pairs into panel leader windows")
    r.add_argument("--live", action="store_true", help="really send (default: dry-run, nothing sent)")
    r.add_argument("--yes-spend", action="store_true", help="required with --live on mainnet")
    r.add_argument("--keypair", default=None, help="master keypair JSON; or $ITB_KEYPAIR")
    r.add_argument("--cap-sol", type=float, default=float(os.environ.get("ITB_CAP_SOL", "0.05")))
    r.add_argument("--ledger", default=os.environ.get("ITB_LEDGER", str(DATA / "spend-ledger.json")))
    r.add_argument("--minutes", type=float, default=10)
    r.add_argument("--max-windows", type=int, default=400)
    r.add_argument("--seed", type=int, default=20261024)
    r.add_argument("--clock-lag-ms", type=float, default=float(os.environ.get("ITB_CLOCK_LAG_MS", "0")),
                   help="how much the RPC slot notification lags the leader's slot start")
    r.add_argument("--ws-url", default=None)
    r.set_defaults(func=cmd_run)

    c = sp.add_parser("collect", help="statuses + blocks for runs")
    c.add_argument("--run", default=None)
    c.add_argument("--no-blocks", action="store_true")
    c.add_argument("--skip-done", action="store_true")
    c.set_defaults(func=cmd_collect)

    ps = sp.add_parser("passive", help="fetch recent past blocks of panel leaders (no money)")
    ps.add_argument("--per-validator", type=int, default=int(os.environ.get("ITB_PASSIVE_WINDOWS", "6")))
    ps.set_defaults(func=cmd_passive)

    sp.add_parser("analyze", help="stats, figures, report/results.md").set_defaults(func=cmd_analyze)

    v = sp.add_parser("verify", help="re-check stored blocks against the chain")
    v.add_argument("--n", type=int, default=20)
    v.set_defaults(func=cmd_verify)

    w = sp.add_parser("sweep", help="return sub-payer deposits to the master key")
    w.add_argument("--keypair", default=None)
    w.add_argument("--yes", action="store_true", help="really send the sweep transfers")
    w.set_defaults(func=cmd_sweep)

    al = sp.add_parser("all", help="survey + passive + dry-run + collect + analyze + verify")
    al.add_argument("--per-client", type=int, default=2)
    al.add_argument("--per-validator", type=int, default=int(os.environ.get("ITB_PASSIVE_WINDOWS", "6")))
    al.add_argument("--dry-minutes", type=float, default=float(os.environ.get("ITB_DRY_MINUTES", "3")))
    al.add_argument("--new-panel", action="store_true")
    al.add_argument("--n", type=int, default=20)
    al.add_argument("--seed", type=int, default=20261024)
    al.add_argument("--cap-sol", type=float, default=0.05)
    al.add_argument("--clock-lag-ms", type=float, default=float(os.environ.get("ITB_CLOCK_LAG_MS", "0")))
    al.add_argument("--ws-url", default=None)
    al.set_defaults(func=cmd_all)

    a = p.parse_args()
    if a.cmd != "run":
        set_sink(DATA / "logs" / f"{a.cmd}-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}.jsonl")
    asyncio.run(a.func(a))


if __name__ == "__main__":
    main()
