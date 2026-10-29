"""Standard technical indicators (causal: each row only uses data up to that row)."""

import numpy as np
import pandas as pd


def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()


def rsi(close, n=14):
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    out = 100 - 100 / (1 + up / dn.replace(0, np.nan))
    out = out.where(dn != 0, 100.0)
    out[(up == 0) & (dn == 0)] = 50.0
    return out


def macd(close, fast=12, slow=26, signal=9):
    dif = ema(close, fast) - ema(close, slow)
    dea = ema(dif, signal)
    return dif, dea, dif - dea


def kdj(high, low, close, n=9, m1=3, m2=3):
    lo = low.rolling(n, min_periods=1).min()
    hi = high.rolling(n, min_periods=1).max()
    rsv = ((close - lo) / (hi - lo).replace(0, np.nan) * 100).fillna(50.0)
    k = rsv.ewm(alpha=1 / m1, adjust=False).mean()
    d = k.ewm(alpha=1 / m2, adjust=False).mean()
    return k, d, 3 * k - 2 * d


def add_indicators(df):
    """Return a copy of df (open/high/low/close) with EMA 20/50/200, RSI 14, MACD 12-26-9, KDJ 9-3-3."""
    out = df.copy()
    c = out["close"]
    for n in (20, 50, 200):
        out[f"ema{n}"] = ema(c, n)
    out["rsi"] = rsi(c, 14)
    out["macd"], out["macd_signal"], out["macd_hist"] = macd(c, 12, 26, 9)
    out["hist_std"] = out["macd_hist"].rolling(100, min_periods=20).std()
    out["k"], out["d"], out["j"] = kdj(out["high"], out["low"], c, 9, 3, 3)
    return out
