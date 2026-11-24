"""Run the unchanged backtest on more out-of-sample coins and merge with backtest_results.json.

Usage: python research/backtest_more_alts.py <out_dir> NAME=<1h_dir>,<funding_dir> [NAME=...]
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from backtest_portfolio import Mkt, evaluate_market, load_funding  # noqa: E402
from btc_edge_stats import load_1h  # noqa: E402

out = Path(sys.argv[1])
res = json.loads((out / "backtest_results.json").read_text())
res.setdefault("alts", [res["alt"]])
for arg in sys.argv[2:]:
    name, dirs = arg.split("=")
    kl, fu = dirs.split(",")
    mk = Mkt(load_1h(kl), load_funding(fu))
    res[name] = evaluate_market(mk, name, out)
    res["funding_extrapolated_from"][name] = mk.funding_extrapolated_from
    if name not in res["alts"]:
        res["alts"].append(name)
(out / "backtest_results.json").write_text(json.dumps(res, indent=1, default=float))
print("alts:", res["alts"])
