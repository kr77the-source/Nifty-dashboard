"""Free live NSE data with no account and no API key: NSE option chain (bid/ask, OI, volume, IV) + Yahoo Finance candles.
NSE blocks cloud servers, so run this on your own laptop/PC with an Indian internet connection."""
import io
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import pandas as pd
import requests

BASE = "https://www.nseindia.com"
HDRS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": BASE + "/option-chain",
}
IST = timezone(timedelta(hours=5, minutes=30))
NAME = "NSE direct"
MAX_LAG = 30  # minutes: Yahoo candles can run a few minutes late
YF_INDEX = {"NIFTY": "^NSEI", "BANKNIFTY": "^NSEBANK", "FINNIFTY": "NIFTY_FIN_SERVICE.NS"}
DEFAULT_LOT = {"NIFTY": 65, "BANKNIFTY": 30, "FINNIFTY": 60}  # used only if NSE's lot file can't be read
FALLBACK = ["RELIANCE", "HDFCBANK", "ICICIBANK", "INFY", "TCS", "SBIN", "AXISBANK", "KOTAKBANK", "LT", "ITC", "BHARTIARTL",
            "TATASTEEL", "MARUTI", "SUNPHARMA", "BAJFINANCE", "HINDUNILVR", "ADANIENT", "ADANIPORTS", "WIPRO", "HCLTECH",
            "ONGC", "NTPC", "POWERGRID", "COALINDIA", "M&M", "TITAN", "ASIANPAINT", "ULTRACEMCO", "JSWSTEEL", "SBILIFE"]
_S = {}


def login(*a, **k):
    pass  # nothing to log into


def _api(path):
    err = "no response"
    for attempt in (0, 1):
        try:
            if attempt or _S.get("s") is None or time.time() - _S["t"] > 300:
                s = requests.Session()
                s.headers.update(HDRS)
                s.get(BASE + "/option-chain", timeout=10)  # NSE hands out cookies here
                _S.update(s=s, t=time.time())
            r = _S["s"].get(BASE + path, timeout=12)
            if r.status_code == 200:
                return r.json()
            err = f"HTTP {r.status_code}"
        except Exception as e:
            err = str(e)[:120]
    raise RuntimeError(f"NSE se data nahi aaya ({err}). NSE cloud/VPN IP ko block karta hai: ghar ke internet se laptop par chalao.")


def _lots():
    try:
        t = requests.get("https://nsearchives.nseindia.com/content/fo/fo_mktlots.csv", headers=HDRS, timeout=10).text
        df = pd.read_csv(io.StringIO(t), skipinitialspace=True)
        sym, first = df.iloc[:, 1].astype(str).str.strip(), pd.to_numeric(df.iloc[:, 2], errors="coerce")
        return {s: int(v) for s, v in zip(sym, first) if pd.notna(v)}
    except Exception:
        return {}


def universe():
    """Indices + F&O stocks. Expiries are fetched per symbol when selected (see expiries)."""
    stocks = []
    try:
        d = _api("/api/underlying-information")["data"]
        stocks = sorted({x["symbol"] for x in d["UnderlyingList"]})
    except Exception:
        pass
    lots, out = _lots(), {}
    for s in list(YF_INDEX) + (stocks or sorted(FALLBACK)):
        out[s] = {"sym": s, "type": "INDEX" if s in YF_INDEX else "EQUITY", "yf": YF_INDEX.get(s, f"{s}.NS"),
                  "exp": [], "lot": lots.get(s) or DEFAULT_LOT.get(s)}
    return out


def expiries(info):
    j = _api(f"/api/option-chain-contract-info?symbol={quote(info['sym'])}")
    return sorted(datetime.strptime(e, "%d-%b-%Y").strftime("%Y-%m-%d") for e in j["expiryDates"])


def chain(info, expiry):
    """Live option chain: (spot, DataFrame sorted by strike). IV in %, chg = change in OI."""
    exp = datetime.strptime(expiry, "%Y-%m-%d").strftime("%d-%b-%Y")
    kind = "Indices" if info["type"] == "INDEX" else "Equity"
    rec = _api(f"/api/option-chain-v3?type={kind}&symbol={quote(info['sym'])}&expiry={exp}")["records"]
    rows = []
    for d in rec["data"]:
        e = d.get("expiryDate") or d.get("expiryDates") or exp
        if isinstance(e, list):
            e = e[0] if e else exp
        if e != exp:
            continue
        r = {"strike": float(d["strikePrice"])}
        for p, leg in (("ce", d.get("CE")), ("pe", d.get("PE"))):
            x = leg or {}
            r |= {f"{p}_oi": x.get("openInterest") or 0, f"{p}_chg": x.get("changeinOpenInterest") or 0,
                  f"{p}_vol": x.get("totalTradedVolume") or 0, f"{p}_iv": x.get("impliedVolatility") or 0,
                  f"{p}_bid": x.get("bidprice") or x.get("bidPrice") or 0, f"{p}_ask": x.get("askPrice") or x.get("askprice") or 0,
                  f"{p}_ltp": x.get("lastPrice") or 0}
        rows.append(r)
    if not rows or not rec.get("underlyingValue"):
        raise RuntimeError("NSE ki option chain khali aayi")
    df = pd.DataFrame(rows).sort_values("strike").reset_index(drop=True)
    return float(rec["underlyingValue"]), df.astype(float)


def minutes(info, interval=5):
    """Recent N-minute candles from Yahoo Finance (free, no key)."""
    import yfinance as yf
    df = yf.Ticker(info["yf"]).history(period="8d", interval=f"{interval}m")[["Open", "High", "Low", "Close"]].dropna()
    if df.empty:
        raise RuntimeError("Yahoo se candles nahi aayi")
    df.index = df.index.tz_convert(IST) if df.index.tz is not None else df.index.tz_localize(IST)
    return df.astype(float)
