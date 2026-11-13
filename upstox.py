"""Live NSE market data via Upstox (read-only Analytics Token). No Streamlit dependency."""
import gzip
import io
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import ijson
import pandas as pd
import requests

API = "https://api.upstox.com"
INSTRUMENTS = "https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz"
IST = timezone(timedelta(hours=5, minutes=30))
_T = {}


def login(token):
    _T["t"] = token


def universe():
    """{symbol: {key, lot, type, exp}} for every NSE underlying with options, from Upstox's instrument file."""
    raw = requests.get(INSTRUMENTS, timeout=120).content
    today, out = datetime.now(IST).strftime("%Y-%m-%d"), {}
    with gzip.GzipFile(fileobj=io.BytesIO(raw)) as f:
        for it in ijson.items(f, "item"):
            if it.get("segment") != "NSE_FO" or it.get("instrument_type") not in ("CE", "PE") or not it.get("expiry"):
                continue
            exp = datetime.fromtimestamp(int(it["expiry"]) / 1000, IST).strftime("%Y-%m-%d")
            if exp >= today:
                u = out.setdefault(it["underlying_symbol"], {"key": it["underlying_key"], "lot": int(it["lot_size"]),
                                                              "type": it.get("underlying_type"), "exp": set()})
                u["exp"].add(exp)
    for u in out.values():
        u["exp"] = sorted(u["exp"])
    if not out:
        raise RuntimeError("no option underlyings found in the Upstox instrument file")
    return out


def _get(path):
    r = requests.get(API + path, headers={"Authorization": f"Bearer {_T['t']}", "Accept": "application/json"}, timeout=15)
    if r.status_code == 401:
        raise PermissionError("Upstox token invalid or expired")
    r.raise_for_status()
    return r.json()["data"]


def chain(info, expiry):
    """Live option chain: (spot, DataFrame sorted by strike). IV in %, chg = OI - previous OI."""
    rows, spot = [], None
    for d in _get(f"/v2/option/chain?instrument_key={quote(info['key'], safe='')}&expiry_date={expiry}"):
        spot = d.get("underlying_spot_price") or spot
        r = {"strike": float(d["strike_price"])}
        for p, leg in (("ce", d.get("call_options")), ("pe", d.get("put_options"))):
            m, g = (leg or {}).get("market_data") or {}, (leg or {}).get("option_greeks") or {}
            r |= {f"{p}_oi": m.get("oi") or 0, f"{p}_chg": (m.get("oi") or 0) - (m.get("prev_oi") or 0),
                  f"{p}_vol": m.get("volume") or 0, f"{p}_iv": g.get("iv") or 0,
                  f"{p}_bid": m.get("bid_price") or 0, f"{p}_ask": m.get("ask_price") or 0,
                  f"{p}_ltp": m.get("ltp") or 0}
        rows.append(r)
    if not rows or not spot:
        raise RuntimeError("Upstox returned an empty option chain")
    return float(spot), pd.DataFrame(rows).sort_values("strike").reset_index(drop=True)


def _candles(d):
    df = pd.DataFrame(d["candles"], columns=["t", "Open", "High", "Low", "Close", "Vol", "OI"])
    df.index = pd.DatetimeIndex(pd.to_datetime(df.pop("t")))
    return df.sort_index()[["Open", "High", "Low", "Close"]].astype(float)


def minutes(info, interval=5, days=8):
    """N-minute candles for the last few sessions, including today's live candles (oldest first)."""
    today, k = datetime.now(IST).date(), quote(info["key"], safe="")
    old = _candles(_get(f"/v3/historical-candle/{k}/minutes/{interval}/{today}/{today - timedelta(days=days)}"))
    new = _candles(_get(f"/v3/historical-candle/intraday/{k}/minutes/{interval}"))
    df = pd.concat([old, new])
    return df[~df.index.duplicated(keep="last")].sort_index()


def enrich(info, expiry, ch, side, strikes):
    return ch  # Upstox's chain already carries bid/ask
