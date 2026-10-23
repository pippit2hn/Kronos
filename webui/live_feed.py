"""Server-side live candle feed from TradingView, fanned out to browsers via SSE."""

import json
import threading
import time
from websocket import create_connection

from tradingview_client import WS_URL, INTERVALS, _pack, _unpack, _session


class LiveFeed(threading.Thread):
    """Keeps one TradingView chart session open and tracks the newest candle."""

    def __init__(self, symbol, interval):
        super().__init__(daemon=True)
        self.symbol, self.interval = symbol, interval
        self.cond = threading.Condition()
        self.version = 0
        self.candle = None   # [epoch_s, open, high, low, close, volume]
        self.error = None
        self.subscribers = 0
        self.stopped = False

    def _publish(self, v):
        with self.cond:
            self.candle = [v[0], *v[1:6]]
            self.error = None
            self.version += 1
            self.cond.notify_all()

    def run(self):
        while not self.stopped:
            try:
                self._session()
            except Exception as e:
                with self.cond:
                    self.error = str(e)
                    self.version += 1
                    self.cond.notify_all()
            for _ in range(30):  # back off 3s before reconnecting
                if self.stopped:
                    return
                time.sleep(0.1)

    def _session(self):
        ws = create_connection(WS_URL, origin="https://www.tradingview.com", timeout=30)
        chart = _session("cs_")
        try:
            ws.send(_pack("set_auth_token", ["unauthorized_user_token"]))
            ws.send(_pack("chart_create_session", [chart, ""]))
            ws.send(_pack("resolve_symbol", [chart, "sds_sym_1",
                     "=" + json.dumps({"symbol": self.symbol, "adjustment": "splits"})]))
            ws.send(_pack("create_series", [chart, "sds_1", "s1", "sds_sym_1", INTERVALS[self.interval], 2, ""]))
            while not self.stopped:
                for frame in _unpack(ws.recv()):
                    if frame.startswith("~h~"):
                        ws.send(f"~m~{len(frame)}~m~{frame}")
                        continue
                    msg = json.loads(frame)
                    name = msg.get("m")
                    if name in ("symbol_error", "critical_error"):
                        raise RuntimeError(f"TradingView error for '{self.symbol}'")
                    if name in ("timescale_update", "du"):
                        series = msg["p"][1].get("sds_1", {}).get("s", [])
                        for item in series:
                            self._publish(item["v"])
        finally:
            ws.close()


_feeds = {}
_hub_lock = threading.Lock()


def subscribe(symbol, interval):
    with _hub_lock:
        key = (symbol, interval)
        feed = _feeds.get(key)
        if feed is None or feed.stopped:
            feed = LiveFeed(symbol, interval)
            _feeds[key] = feed
            feed.start()
        feed.subscribers += 1
        return feed


def unsubscribe(feed):
    with _hub_lock:
        feed.subscribers -= 1
        if feed.subscribers <= 0:
            feed.stopped = True
            _feeds.pop((feed.symbol, feed.interval), None)


def stream(symbol, interval):
    """Generator of SSE chunks."""
    feed = subscribe(symbol, interval)
    seen = -1
    try:
        while True:
            with feed.cond:
                if feed.version == seen:
                    feed.cond.wait(timeout=15)
                version, candle, error = feed.version, feed.candle, feed.error
            if version == seen:
                yield ": keep-alive\n\n"
                continue
            seen = version
            if error:
                yield f"event: feed_error\ndata: {json.dumps({'error': error})}\n\n"
            elif candle:
                yield f"data: {json.dumps({'t': candle[0], 'o': candle[1], 'h': candle[2], 'l': candle[3], 'c': candle[4], 'v': candle[5]})}\n\n"
    finally:
        unsubscribe(feed)
