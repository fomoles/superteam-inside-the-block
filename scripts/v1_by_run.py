"""The v1 pre-registered per-group test (FPI with Holm, itb/analyze.py) on one live run only.

`itb analyze` pools every run in data/; notes/preregistration-v2.md also asks for the v1 verdicts on run 2
alone. Usage: PYTHONPATH=. python scripts/v1_by_run.py data <run-name-prefix>
"""
import sys
from pathlib import Path

from itb.analyze import active_summary, load_runs, pair_table

data, run = Path(sys.argv[1]), sys.argv[2]
r = load_runs(data)
r = {k: (v[v.run.str.startswith(run)] if k != "groups" else v) for k, v in r.items()}
S, _ = active_summary(pair_table(r))


def ci(x):
    return f"[{x[0]:+.2f}, {x[1]:+.2f}]" if isinstance(x, tuple) else ""


print(f"# v1 pre-registered test on run {run} only\n")
print("| group | val. | windows | usable pairs | FPI = DISC − EQ | FIFO | Holm p | verdict |")
print("|---|---|---|---|---|---|---|---|")
for x in S.to_dict("records"):
    fpi = f"{x['FPI']:+.2f} {ci(x['FPI_ci'])}" if x.get("FPI") == x.get("FPI") and "FPI" in x else "–"
    fifo = f"{x['FIFO']:+.2f} {ci(x['FIFO_ci'])}" if x.get("FIFO") == x.get("FIFO") and "FIFO" in x else "–"
    print(f"| {x['group']} | {x['validators']} | {x['windows']} | {x['usable_pairs']} | {fpi} | {fifo} | "
          f"{x.get('p_H1_holm', float('nan')):.3g} | {x.get('verdict', '–')} |")
