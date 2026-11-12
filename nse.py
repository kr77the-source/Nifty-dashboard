"""NSE option chain + Yahoo Finance price history (no Streamlit dependency)."""
import pandas as pd
import requests
import yfinance as yf

BASE = "https://www.nseindia.com"
HDRS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": BASE + "/option-chain",
}
TICKERS = {"NIFTY": "^NSEI", "BANKNIFTY": "^NSEBANK", "FINNIFTY": "NIFTY_FIN_SERVICE.NS"}


def _session():
    s = requests.Session()
    s.headers.update(HDRS)
    s.get(BASE + "/option-chain", timeout=10)  # sets the cookies NSE expects
    return s


def expiries(symbol):
    s = _session()
    for path in (f"/api/option-chain-contract-info?symbol={symbol}", f"/api/option-chain-indices?symbol={symbol}"):
        try:
            j = s.get(BASE + path, timeout=10).json()
            e = j.get("expiryDates") or j.get("records", {}).get("expiryDates")
            if e:
                return e
        except Exception:
            pass
    return []


def _leg(x, p):
    x = x or {}
    g = lambda *k: next((x[i] for i in k if x.get(i)), 0)
    return {f"{p}_oi": g("openInterest"), f"{p}_chg": x.get("changeinOpenInterest", 0),
            f"{p}_vol": g("totalTradedVolume"), f"{p}_iv": g("impliedVolatility"),
            f"{p}_bid": g("bidprice", "bidPrice"), f"{p}_ask": g("askPrice", "askprice"),
            f"{p}_ltp": g("lastPrice")}


def chain(symbol, expiry):
    """Returns (spot, DataFrame sorted by strike, NSE timestamp)."""
    s = _session()
    for path in (f"/api/option-chain-v3?type=Indices&symbol={symbol}&expiry={expiry}",
                 f"/api/option-chain-indices?symbol={symbol}"):
        try:
            rec = s.get(BASE + path, timeout=10).json()["records"]
            rows = [{"strike": d["strikePrice"], **_leg(d.get("CE"), "ce"), **_leg(d.get("PE"), "pe")}
                    for d in rec["data"] if (d.get("expiryDate") or d.get("expiryDates") or expiry) == expiry]
            if rows:
                df = pd.DataFrame(rows).sort_values("strike").reset_index(drop=True)
                return float(rec["underlyingValue"]), df, rec.get("timestamp", "")
        except Exception:
            pass
    raise RuntimeError("NSE option chain unavailable (blocked, rate-limited or format changed)")


def history(symbol):
    df = yf.Ticker(TICKERS[symbol]).history(period="1y", interval="1d")
    return df[["Open", "High", "Low", "Close"]].dropna()
