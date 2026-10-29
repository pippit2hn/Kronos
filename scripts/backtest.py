#!/usr/bin/env python3
"""Walk-forward backtest of Kronos + indicator signals.

At each decision candle t (every --step candles) it
  * samples Kronos paths from the candles up to t and scores them (share of paths ending higher),
  * scores EMA/RSI/MACD/KDJ at t,
  * goes long (BUY), short (SELL) or flat (HOLD) at close[t] and exits at close[t + horizon].
Strategies compared: indicators only, Kronos only, combined, and buy & hold.
Nothing from after t is used to make the decision. The Kronos pre-training data may overlap the
test period, so results can be optimistic.

Examples:
    python scripts/backtest.py BINANCE:BTCUSDT.P --interval 15m --bars 5000 --horizon 96 --samples 50
    python scripts/backtest.py --csv data/BTCUSDT_perp_1h.csv --interval 1h --samples 50
"""

import argparse
import os
import sys
import time

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "webui"))

from indicators import add_indicators          # noqa: E402
from signals import (THRESHOLD, combine, decide, indicator_scores, kronos_score)  # noqa: E402
from forecast_service import FREQ, sample_paths  # noqa: E402

MODELS = {
    "kronos-mini": ("NeoQuasar/Kronos-mini", "NeoQuasar/Kronos-Tokenizer-2k", 2048),
    "kronos-small": ("NeoQuasar/Kronos-small", "NeoQuasar/Kronos-Tokenizer-base", 512),
    "kronos-base": ("NeoQuasar/Kronos-base", "NeoQuasar/Kronos-Tokenizer-base", 512),
}


def load_data(args):
    if args.csv:
        df = pd.read_csv(args.csv)
        col = next(c for c in ("timestamps", "timestamp", "date") if c in df.columns)
        df["timestamps"] = pd.to_datetime(df[col])
    else:
        from tradingview_client import fetch_ohlcv
        df = fetch_ohlcv(args.symbol, args.interval, args.bars)
    if "volume" not in df.columns:
        df["volume"] = 0.0
    df = df.sort_values("timestamps").reset_index(drop=True)
    step = pd.Timedelta(FREQ[args.interval])
    if df["timestamps"].iloc[-1] + step > pd.Timestamp.now("UTC").tz_localize(None):
        df = df.iloc[:-1]  # drop the still-forming candle
    return df


def load_predictor(name, device):
    from model import Kronos, KronosTokenizer, KronosPredictor
    model_id, tok_id, ctx = MODELS[name]
    return KronosPredictor(Kronos.from_pretrained(model_id), KronosTokenizer.from_pretrained(tok_id),
                           device=device, max_context=ctx)


def stats(name, pos, actual_ret, fee, bh):
    pos = np.asarray(pos, float)
    net = pos * actual_ret - np.abs(pos) * 2 * fee
    trades = pos != 0
    equity = np.cumprod(1 + net)
    peak = np.maximum.accumulate(equity)
    return {
        "strategy": name, "trades": int(trades.sum()),
        "win_rate_%": round(float((net[trades] > 0).mean() * 100), 1) if trades.any() else float("nan"),
        "avg_trade_%": round(float(net[trades].mean() * 100), 3) if trades.any() else float("nan"),
        "total_return_%": round(float((equity[-1] - 1) * 100), 2),
        "max_drawdown_%": round(float(((equity / peak) - 1).min() * 100), 2),
    }


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("symbol", nargs="?", help="TradingView symbol, e.g. BINANCE:BTCUSDT.P")
    p.add_argument("--csv", help="Use a local CSV instead of downloading")
    p.add_argument("--interval", default="15m", choices=list(FREQ))
    p.add_argument("--bars", type=int, default=5000, help="Candles to download")
    p.add_argument("--model", default="kronos-small", choices=list(MODELS))
    p.add_argument("--device", default="cuda")
    p.add_argument("--horizon", type=int, default=96, help="Candles to forecast and hold")
    p.add_argument("--samples", type=int, default=50)
    p.add_argument("--history", type=int, default=500)
    p.add_argument("--step", type=int, default=0, help="Candles between decisions (default = horizon)")
    p.add_argument("--warmup", type=int, default=250, help="Candles skipped at the start (indicator warmup)")
    p.add_argument("--fee", type=float, default=0.0005, help="Fee+slippage per side, e.g. 0.0005 = 0.05%%")
    p.add_argument("--threshold", type=float, default=THRESHOLD)
    p.add_argument("--max-decisions", type=int, default=0, help="Use only the most recent N decisions")
    args = p.parse_args()
    if not args.symbol and not args.csv:
        p.error("give a symbol or --csv")

    step = args.step or args.horizon
    df = load_data(args)
    ind = add_indicators(df)
    n = len(df)
    ts = list(range(args.warmup, n - args.horizon, step))
    if args.max_decisions:
        ts = ts[-args.max_decisions:]
    if not ts:
        sys.exit(f"Not enough data: {n} candles for warmup {args.warmup} + horizon {args.horizon}")
    print(f"{n} candles, {len(ts)} decisions, model {args.model} on {args.device}, "
          f"{args.samples} samples, horizon {args.horizon}")

    predictor = load_predictor(args.model, args.device)
    freq = FREQ[args.interval]
    rows, t0 = [], time.time()
    for k, t in enumerate(ts):
        hist = min(args.history, predictor.max_context)
        x = df.iloc[max(0, t - hist + 1): t + 1]
        x_ts = x["timestamps"].reset_index(drop=True)
        y_ts = pd.Series(pd.date_range(x_ts.iloc[-1] + pd.Timedelta(freq), periods=args.horizon, freq=freq))
        paths = sample_paths(predictor, x[["open", "high", "low", "close", "volume"]].reset_index(drop=True),
                             x_ts, y_ts, args.samples)
        last, end = float(df["close"].iloc[t]), paths[:, -1]
        p10, med, p90 = np.percentile(end, [10, 50, 90])
        actual = float(df["close"].iloc[t + args.horizon])
        sc = {name: v[0] for name, v in indicator_scores(ind, t).items()}
        sc["kronos"] = kronos_score(float((end > last).mean() * 100))
        rows.append({
            "time": df["timestamps"].iloc[t], "price": last, "actual_end": actual,
            "actual_ret": actual / last - 1, "p10": p10, "median": med, "p90": p90, **sc,
            "s_ind": combine(sc, use=["ema", "rsi", "macd", "kdj"]),
            "s_kronos": sc["kronos"], "s_comb": combine(sc),
        })
        eta = (time.time() - t0) / (k + 1) * (len(ts) - k - 1)
        print(f"  decision {k + 1}/{len(ts)}  eta {eta / 60:.1f} min", end="\r")
    print()

    r = pd.DataFrame(rows)
    sign = {"BUY": 1, "SELL": -1, "HOLD": 0}
    results = [stats(label, [sign[decide(v, args.threshold)] for v in r[col]], r["actual_ret"].values, args.fee, None)
               for label, col in [("indicators only", "s_ind"), ("kronos only", "s_kronos"), ("combined", "s_comb")]]
    results.append(stats("buy & hold (per-period)", np.ones(len(r)), r["actual_ret"].values, 0.0, None))
    print("\nStrategy results (long/short, exit after horizon, fee {:.3f}% per side)".format(args.fee * 100))
    print(pd.DataFrame(results).to_string(index=False))

    inside = ((r["actual_end"] >= r["p10"]) & (r["actual_end"] <= r["p90"])).mean() * 100
    dir_ok = (np.sign(r["median"] - r["price"]) == np.sign(r["actual_end"] - r["price"])).mean() * 100
    print(f"\nKronos calibration: actual end price inside P10-P90 in {inside:.0f}% of cases (ideal ~80%)")
    print(f"Kronos median direction correct in {dir_ok:.0f}% of cases (50% = coin flip)")
    print("Trades are non-overlapping only when --step >= --horizon; few trades = noisy statistics.")

    out_dir = os.path.join(ROOT, "data")
    os.makedirs(out_dir, exist_ok=True)
    name = (args.symbol or os.path.basename(args.csv)).replace(":", "_").replace(".", "_").replace("/", "_")
    path = os.path.join(out_dir, f"backtest_{name}_{args.interval}.csv")
    r.to_csv(path, index=False)
    print(f"Decisions saved to {path}")


if __name__ == "__main__":
    main()
