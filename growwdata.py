"""Live NSE market data via the Groww Trade API (needs Groww's Live Data subscription). No Streamlit dependency."""
import io
import time
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests

CSV = "https://growwapi-assets.groww.in/instruments/instrument.csv"
IST = timezone(timedelta(hours=5, minutes=30))
INDEX = ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50")
_S = {}


def login(api_key, totp_secret="", secret=""):
    creds = (api_key, totp_secret, secret)
    if _S.get("creds") != creds:  # keep the cached client across Streamlit reruns
        _S.update(creds=creds, api_key=api_key, totp=totp_secret, secret=secret, client=None, born=0.0)


def _client(fresh=False):
    if fresh or _S.get("client") is None or time.time() - _S["born"] > 4 * 3600:
        from growwapi import GrowwAPI
        if _S["totp"]:
            import pyotp
            tok = GrowwAPI.get_access_token(api_key=_S["api_key"], totp=pyotp.TOTP(_S["totp"]).now())
        else:
            tok = GrowwAPI.get_access_token(api_key=_S["api_key"], secret=_S["secret"])
        _S["client"], _S["born"] = GrowwAPI(tok), time.time()
    return _S["client"]


def _call(f):
    """Run f(client); on any failure rebuild the client (the token may have expired) and retry once."""
    try:
        return f(_client())
    except Exception:
        return f(_client(fresh=True))


def universe():
    """{symbol: {sym, gsym, lot, type, exp}} for every NSE underlying with options (Groww instrument file)."""
    text = requests.get(CSV, timeout=90).text
    df = pd.read_csv(io.StringIO(text), usecols=["exchange", "trading_symbol", "groww_symbol", "segment",
                                                  "instrument_type", "underlying_symbol", "expiry_date", "lot_size"])
    today = datetime.now(IST).strftime("%Y-%m-%d")
    df["expiry_date"] = df["expiry_date"].astype(str)
    fno = df[(df.exchange == "NSE") & (df.segment == "FNO") & df.instrument_type.isin(["CE", "PE"]) & (df.expiry_date >= today)]
    cash = df[(df.exchange == "NSE") & (df.segment == "CASH")].drop_duplicates("trading_symbol").set_index("trading_symbol").groupby(level=0).first()
    out = {}
    for sym, g in fno.groupby("underlying_symbol"):
        out[sym] = {"sym": sym, "gsym": cash.groww_symbol.get(sym, f"NSE-{sym}"), "lot": int(g.lot_size.iloc[0]),
                    "type": "INDEX" if sym in INDEX else "EQUITY", "exp": sorted(g.expiry_date.unique())}
    if not out:
        raise RuntimeError("no option underlyings found in the Groww instrument file")
    return out


def minutes(info, interval=5, days=8):
    """N-minute candles for the last few sessions up to now (oldest first, IST)."""
    now = datetime.now(IST)

    def f(g):
        return g.get_historical_candles(
            exchange="NSE", segment="CASH", groww_symbol=info["gsym"],
            start_time=(now - timedelta(days=days)).strftime("%Y-%m-%d 09:15:00"),
            end_time=now.strftime("%Y-%m-%d %H:%M:%S"),
            candle_interval=getattr(g, f"CANDLE_INTERVAL_MIN_{interval}", f"{interval}minute"))

    c = pd.DataFrame(_call(f)["candles"]).iloc[:, :5]
    c.columns = ["t", "Open", "High", "Low", "Close"]
    t = c.pop("t")
    if pd.api.types.is_numeric_dtype(t):
        t = pd.to_datetime(t, unit="s", utc=True).dt.tz_convert(IST)
    else:
        t = pd.to_datetime(t)
        t = t.dt.tz_localize(IST) if t.dt.tz is None else t.dt.tz_convert(IST)
    c.index = pd.DatetimeIndex(t)
    return c.astype(float).sort_index()


def chain(info, expiry):
    """Live option chain: (spot, DataFrame by strike). Groww's chain has LTP, OI, volume and IV but no bid/ask."""
    j = _call(lambda g: g.get_option_chain(exchange="NSE", underlying=info["sym"], expiry_date=expiry))
    rows = []
    for k, v in j["strikes"].items():
        r = {"strike": float(k)}
        for p, leg in (("ce", v.get("CE")), ("pe", v.get("PE"))):
            leg = leg or {}
            r |= {f"{p}_oi": leg.get("open_interest") or 0, f"{p}_chg": 0, f"{p}_vol": leg.get("volume") or 0,
                  f"{p}_iv": (leg.get("greeks") or {}).get("iv") or 0, f"{p}_bid": 0, f"{p}_ask": 0,
                  f"{p}_ltp": leg.get("ltp") or 0, f"{p}_sym": leg.get("trading_symbol")}
        rows.append(r)
    if not rows or not j.get("underlying_ltp"):
        raise RuntimeError("Groww returned an empty option chain")
    return float(j["underlying_ltp"]), pd.DataFrame(rows).sort_values("strike").reset_index(drop=True)


def enrich(info, expiry, ch, side, strikes):
    """Fill live bid/ask (and refresh LTP, volume, OI) for the given strikes from per-contract quotes."""
    for s in strikes:
        i = ch.index[ch.strike == s][0]
        sym = ch.at[i, f"{side}_sym"]
        q = _call(lambda g: g.get_quote(exchange="NSE", segment="FNO", trading_symbol=sym))
        ch.at[i, f"{side}_bid"] = q.get("bid_price") or 0
        ch.at[i, f"{side}_ask"] = q.get("offer_price") or 0
        for col, key in (("ltp", "last_price"), ("vol", "volume"), ("oi", "open_interest")):
            ch.at[i, f"{side}_{col}"] = q.get(key) or ch.at[i, f"{side}_{col}"]
    return ch
