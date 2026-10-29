"""Combine technical indicators and the Kronos forecast into a buy/sell score.

Every component is scored in [-1, 1] (+1 = bullish). The total is the weighted mean of the
components in use. Weights and the threshold are plain defaults, not tuned values.
"""

import math

WEIGHTS = {"ema": 0.20, "rsi": 0.15, "macd": 0.20, "kdj": 0.15, "kronos": 0.30}
THRESHOLD = 0.30


def _clip(x):
    return float(max(-1.0, min(1.0, x)))


def indicator_scores(ind, pos=-1):
    """Scores from the indicator DataFrame at row `pos`. Returns {name: (score, detail)}."""
    r = ind.iloc[pos]
    trend = ((r.close > r.ema20) + (r.ema20 > r.ema50) + (r.ema50 > r.ema200)) * 2 - 3
    hist_std = r.hist_std if r.hist_std == r.hist_std and r.hist_std > 0 else None
    macd_score = math.tanh(r.macd_hist / hist_std) if hist_std else 0.0
    kdj_score = _clip(0.5 * _clip((50 - r.j) / 50) + (0.5 if r.k > r.d else -0.5))
    return {
        "ema": (trend / 3, f"close vs EMA20/50/200: {int(trend + 3) // 2}/3 bullish conditions"),
        "rsi": (_clip((50 - r.rsi) / 20), f"RSI {r.rsi:.1f} (below 30 = oversold, above 70 = overbought)"),
        "macd": (macd_score, f"MACD hist {r.macd_hist:+.4g} ({'above' if r.macd > r.macd_signal else 'below'} signal)"),
        "kdj": (kdj_score, f"K {r.k:.1f} D {r.d:.1f} J {r.j:.1f}"),
    }


def kronos_score(higher_pct):
    """+1 when >=80% of sampled paths end higher, -1 when <=20%."""
    return _clip((higher_pct - 50) / 30)


def combine(scores, use=None, weights=None):
    """scores: {name: float}. Weighted mean over the components in `use` (default all given)."""
    w = weights or WEIGHTS
    names = [n for n in (use or scores) if n in scores]
    total_w = sum(w[n] for n in names)
    return sum(w[n] * scores[n] for n in names) / total_w if total_w else 0.0


def decide(total, threshold=THRESHOLD):
    return "BUY" if total >= threshold else "SELL" if total <= -threshold else "HOLD"


def build_signal(ind, higher_pct, threshold=THRESHOLD):
    """Full signal for the UI: components with details, total score and decision."""
    comps = indicator_scores(ind)
    comps["kronos"] = (kronos_score(higher_pct), f"{higher_pct:.0f}% of sampled paths end higher")
    total = combine({k: v[0] for k, v in comps.items()})
    return {
        "decision": decide(total, threshold), "total": total, "threshold": threshold,
        "components": [{"name": k, "score": v[0], "weight": WEIGHTS[k], "detail": v[1]}
                       for k, v in comps.items()],
    }
