#!/usr/bin/env python3
"""Download Binance spot klines and save them in the format the Kronos web UI expects.

Examples:
    python scripts/download_binance.py BTCUSDT
    python scripts/download_binance.py ETHUSDT --interval 1d --limit 2000
    python scripts/download_binance.py BTCUSDT --interval 15m --start 2025-01-01 --end 2025-03-01

Output: data/<SYMBOL>_<interval>.csv with columns
timestamps, open, high, low, close, volume, amount (UTC).
Uses only the standard library plus pandas (already a dependency).
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

import pandas as pd

BASE_URLS = ["https://api.binance.com", "https://data-api.binance.vision"]
MAX_PER_REQUEST = 1000


def fetch(path, params):
    last_err = None
    for base in BASE_URLS:
        url = f"{base}{path}?{urllib.parse.urlencode(params)}"
        for attempt in range(3):
            try:
                with urllib.request.urlopen(url, timeout=30) as resp:
                    return json.load(resp)
            except urllib.error.HTTPError as e:
                if e.code == 400:
                    sys.exit(f"Binance rejected the request (check symbol/interval): {e.read().decode()}")
                last_err = e
            except Exception as e:  # network errors
                last_err = e
            time.sleep(2 ** attempt)
    sys.exit(f"Could not reach Binance: {last_err}")


def to_ms(text):
    return int(pd.Timestamp(text, tz="UTC").timestamp() * 1000)


def download(symbol, interval, limit, start, end):
    end_ms = to_ms(end) if end else None
    if start:
        cursor = to_ms(start)
    else:
        # Walk backwards from now until `limit` rows are collected.
        cursor = None

    rows = []
    if cursor is not None:
        while True:
            params = {"symbol": symbol, "interval": interval, "startTime": cursor, "limit": MAX_PER_REQUEST}
            if end_ms:
                params["endTime"] = end_ms
            batch = fetch("/api/v3/klines", params)
            if not batch:
                break
            rows.extend(batch)
            cursor = batch[-1][0] + 1
            print(f"  fetched {len(rows)} rows", end="\r")
            if len(batch) < MAX_PER_REQUEST or (limit and len(rows) >= limit):
                break
        if limit:
            rows = rows[:limit]
    else:
        end_cursor = end_ms
        while len(rows) < limit:
            params = {"symbol": symbol, "interval": interval,
                      "limit": min(MAX_PER_REQUEST, limit - len(rows))}
            if end_cursor:
                params["endTime"] = end_cursor
            batch = fetch("/api/v3/klines", params)
            if not batch:
                break
            rows = batch + rows
            end_cursor = batch[0][0] - 1
            print(f"  fetched {len(rows)} rows", end="\r")
            if len(batch) < params["limit"]:
                break
    print()
    return rows


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("symbol", help="Trading pair, e.g. BTCUSDT")
    p.add_argument("--interval", default="1h", help="1m,5m,15m,30m,1h,4h,1d,... (default 1h)")
    p.add_argument("--limit", type=int, default=5000,
                   help="Max number of candles (default 5000). With --start, 0 means up to --end/now")
    p.add_argument("--start", help="Start date, e.g. 2025-01-01 (UTC)")
    p.add_argument("--end", help="End date, e.g. 2025-06-01 (UTC)")
    p.add_argument("--out-dir", default=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data"))
    args = p.parse_args()

    symbol = args.symbol.upper().replace("/", "")
    print(f"Downloading {symbol} {args.interval} from Binance...")
    rows = download(symbol, args.interval, args.limit, args.start, args.end)
    if not rows:
        sys.exit("No data returned.")

    df = pd.DataFrame(rows, columns=[
        "open_time", "open", "high", "low", "close", "volume", "close_time",
        "amount", "trades", "taker_base", "taker_quote", "ignore"])
    df["timestamps"] = pd.to_datetime(df["open_time"], unit="ms")
    for col in ["open", "high", "low", "close", "volume", "amount"]:
        df[col] = pd.to_numeric(df[col])
    df = df[["timestamps", "open", "high", "low", "close", "volume", "amount"]]
    df = df.drop_duplicates("timestamps").sort_values("timestamps")

    os.makedirs(args.out_dir, exist_ok=True)
    path = os.path.join(args.out_dir, f"{symbol}_{args.interval}.csv")
    df.to_csv(path, index=False)
    print(f"Saved {len(df)} rows ({df['timestamps'].iloc[0]} -> {df['timestamps'].iloc[-1]}) to {path}")
    if len(df) < 520:
        print("Warning: the web UI needs at least 520 rows (400 history + 120 prediction).")


if __name__ == "__main__":
    main()
