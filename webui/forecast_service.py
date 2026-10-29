"""Live forecast: fetch recent candles from TradingView and sample many Kronos paths."""

import datetime
import numpy as np
import pandas as pd

from indicators import add_indicators
from signals import build_signal
from tradingview_client import fetch_ohlcv

FREQ = {"1m": "1min", "3m": "3min", "5m": "5min", "15m": "15min", "30m": "30min",
        "1h": "1h", "2h": "2h", "4h": "4h", "1d": "1D"}
CLOSE = 3  # index of 'close' in [open, high, low, close, volume, amount]


def sample_paths(predictor, x_df, x_ts, y_ts, samples, chunk=20, T=1.0, top_p=0.9, progress=None):
    """Sample `samples` price paths; returns close prices, shape (samples, len(y_ts))."""
    out, done = [], 0
    while done < samples:
        n = min(chunk, samples - done)
        res = predictor.predict(x_df, x_ts, y_ts, pred_len=len(y_ts), T=T, top_p=top_p,
                                sample_count=n, verbose=False, return_samples=True)
        out.append(res[:, :, CLOSE])
        done += n
        if progress:
            progress(done, samples)
    return np.concatenate(out, axis=0)


def run_forecast(predictor, symbol, interval, horizon, samples, history=500,
                 chunk=20, T=1.0, top_p=0.9, progress=None):
    if interval not in FREQ:
        raise ValueError(f"Unsupported interval '{interval}'")
    history = min(history, predictor.max_context)

    df = fetch_ohlcv(symbol, interval, history + 2)
    step = pd.Timedelta(FREQ[interval])
    now = pd.Timestamp.now('UTC').tz_localize(None)

    # The newest candle may still be forming: show it, but don't feed it to the model.
    forming = bool(df["timestamps"].iloc[-1] + step > now)
    closed = df.iloc[:-1] if forming else df
    closed = closed.iloc[-history:].reset_index(drop=True)
    if len(closed) < 64:
        raise RuntimeError(f"Only {len(closed)} candles available for {symbol}; need at least 64")

    x_ts = closed["timestamps"]
    y_ts = pd.Series(pd.date_range(x_ts.iloc[-1], periods=horizon + 1, freq=FREQ[interval])[1:])
    x_df = closed[["open", "high", "low", "close", "volume"]]

    paths = sample_paths(predictor, x_df, x_ts, y_ts, samples, chunk, T, top_p, progress)

    last_price = float(df["close"].iloc[-1])
    p10, med, p90 = np.percentile(paths, [10, 50, 90], axis=0)
    end = paths[:, -1]

    def pct(v):
        return (v / last_price - 1) * 100

    signal = build_signal(add_indicators(closed), float((end > last_price).mean() * 100))

    return {
        "signal": signal,
        "symbol": symbol, "interval": interval, "horizon": horizon, "samples": int(samples),
        "history_count": int(len(closed)),
        "now": {"time": df["timestamps"].iloc[-1].strftime("%m-%d %H:%M"), "price": last_price,
                "forming": forming},
        "candles": {
            "t": df["timestamps"].dt.strftime("%Y-%m-%d %H:%M:%S").tolist(),
            "open": df["open"].tolist(), "high": df["high"].tolist(),
            "low": df["low"].tolist(), "close": df["close"].tolist(),
            "volume": df["volume"].tolist(),
        },
        "forecast": {
            "t": y_ts.dt.strftime("%Y-%m-%d %H:%M:%S").tolist(),
            "p10": p10.tolist(), "median": med.tolist(), "p90": p90.tolist(),
        },
        "stats": {
            "median_end": float(med[-1]), "median_pct": float(pct(med[-1])),
            "p10_end": float(p10[-1]), "p90_end": float(p90[-1]),
            "p10_pct": float(pct(p10[-1])), "p90_pct": float(pct(p90[-1])),
            "half_width_pct": float((p90[-1] - p10[-1]) / 2 / last_price * 100),
            "higher_pct": float((end > last_price).mean() * 100),
        },
    }
