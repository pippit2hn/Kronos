"""Minimal TradingView chart-data client (unofficial websocket protocol).

TradingView has no official public market-data API; this speaks the same
websocket protocol the website uses, anonymously. It can change or be rate
limited without notice, and its use may be restricted by TradingView's terms.
"""

import json
import random
import re
import string
import pandas as pd
from websocket import create_connection

WS_URL = "wss://data.tradingview.com/socket.io/websocket"
INTERVALS = {
    "1m": "1", "3m": "3", "5m": "5", "15m": "15", "30m": "30",
    "1h": "60", "2h": "120", "4h": "240", "1d": "1D", "1w": "1W",
}
_FRAME = re.compile(r"~m~(\d+)~m~")


def _pack(name, params):
    body = json.dumps({"m": name, "p": params}, separators=(",", ":"))
    return f"~m~{len(body)}~m~{body}"


def _unpack(raw):
    """Split a websocket payload into its frames (JSON strings or heartbeats)."""
    frames, pos = [], 0
    while True:
        m = _FRAME.match(raw, pos)
        if not m:
            return frames
        start = m.end()
        end = start + int(m.group(1))
        frames.append(raw[start:end])
        pos = end


def _session(prefix):
    return prefix + "".join(random.choices(string.ascii_lowercase, k=12))


def fetch_ohlcv(symbol, interval="1h", bars=5000, timeout=20):
    """Return a DataFrame [timestamps, open, high, low, close, volume] (UTC).

    symbol: e.g. "BINANCE:BTCUSDT.P" (perpetual) or "BINANCE:BTCUSDT" (spot).
    """
    if interval not in INTERVALS:
        raise ValueError(f"Unsupported interval '{interval}'. Use one of {list(INTERVALS)}")
    bars = max(1, min(int(bars), 20000))

    ws = create_connection(WS_URL, origin="https://www.tradingview.com", timeout=timeout)
    chart = _session("cs_")
    try:
        ws.send(_pack("set_auth_token", ["unauthorized_user_token"]))
        ws.send(_pack("chart_create_session", [chart, ""]))
        ws.send(_pack("resolve_symbol", [chart, "sds_sym_1",
                 "=" + json.dumps({"symbol": symbol, "adjustment": "splits"})]))
        ws.send(_pack("create_series", [chart, "sds_1", "s1", "sds_sym_1", INTERVALS[interval], bars, ""]))

        rows = {}
        while True:
            for frame in _unpack(ws.recv()):
                if frame.startswith("~h~"):          # heartbeat: echo it back
                    ws.send(f"~m~{len(frame)}~m~{frame}")
                    continue
                msg = json.loads(frame)
                name = msg.get("m")
                if name in ("symbol_error", "critical_error"):
                    raise RuntimeError(f"TradingView error for '{symbol}': {msg.get('p')}")
                if name == "timescale_update":
                    series = msg["p"][1].get("sds_1", {}).get("s", [])
                    for item in series:
                        v = item["v"]
                        rows[int(v[0])] = v[1:6]
                elif name == "series_completed":
                    if not rows:
                        raise RuntimeError(f"No data returned for '{symbol}'")
                    df = pd.DataFrame(
                        [[t, *vals] for t, vals in sorted(rows.items())],
                        columns=["t", "open", "high", "low", "close", "volume"])
                    df.insert(0, "timestamps", pd.to_datetime(df.pop("t"), unit="s"))
                    return df
    finally:
        ws.close()
