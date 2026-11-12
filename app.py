import pandas as pd
import streamlit as st

import nse
import strategy as sg

TH, SL, RR, MAX_SP, MIN_VOL, MIN_OI = 3, 30, 2.0, 5, 1000, 10000
def est_expiries(symbol, n=5):
    """Estimated expiry dates (Tuesdays) when NSE is unreachable; holidays are not adjusted."""
    today = pd.Timestamp.now(tz="Asia/Kolkata").normalize().tz_localize(None)
    out = []
    if symbol == "NIFTY":  # weekly
        d = today + pd.Timedelta(days=(1 - today.weekday()) % 7)
        out = [d + pd.Timedelta(weeks=i) for i in range(n)]
    else:  # monthly: last Tuesday
        m = today.replace(day=1)
        while len(out) < n:
            last = m + pd.offsets.MonthEnd(0)
            tue = last - pd.Timedelta(days=(last.weekday() - 1) % 7)
            if tue >= today:
                out.append(tue)
            m = m + pd.offsets.MonthBegin(1)
    return [d.strftime("%d-%b-%Y") for d in out]


STEP = {"NIFTY": 50, "BANKNIFTY": 100, "FINNIFTY": 50}

st.set_page_config("Nifty Options", layout="centered")
st.markdown("<style>.block-container{padding-top:4.5rem}</style>"
            "<div style='font-size:13px;font-weight:600;letter-spacing:1px;opacity:.7'>NIFTY OPTIONS</div>",
            unsafe_allow_html=True)


@st.cache_data(ttl=3600)
def get_syms(): return nse.symbols()
@st.cache_data(ttl=3600)
def get_lots(): return nse.lot_sizes()
@st.cache_data(ttl=300)
def get_hist(s): return nse.history(s)


@st.cache_data(ttl=120)
def get_exp(s):
    try:
        return nse.expiries(s)
    except Exception:
        return []


@st.cache_data(ttl=20)
def get_chain(s, e):
    try:
        return nse.chain(s, e)
    except Exception:
        return None


a, b = st.columns(2)
sym = a.selectbox("Symbol (type to search)", get_syms())
exps = get_exp(sym)
ex = b.selectbox("Expiry" if exps else "Expiry (estimated)", exps or est_expiries(sym))
c, d = st.columns([2, 1])
go = c.button("🔍 Search", type="primary", use_container_width=True)
auto = d.toggle("Auto-run")
if go:
    st.session_state.run = True
if not (st.session_state.get("run") or auto):
    st.caption("Symbol aur expiry chuno, phir Search dabao.")
    st.stop()


@st.fragment(run_every=30 if auto else None)
def view():
    try:
        h = get_hist(sym)
        assert len(h) > 60
    except Exception:
        st.error("Price history nahi mili (Yahoo). Thodi der baad Search dabao.")
        return
    got = get_chain(sym, ex)
    spot, ch, ts = got if got else (float(h["Close"].iloc[-1]), None, "")
    done = h[h.index.date < pd.Timestamp.now(tz="Asia/Kolkata").date()]
    piv = sg.pivots(done.iloc[-1])
    sc, rv = sg.price_scores(h)
    pcr = atm_iv = 0.0
    if ch is not None:
        cs, pcr, atm_iv, _ = sg.chain_scores(ch, spot)
        sc.update(cs)
    total = sum(v[0] for v in sc.values())
    side = "ce" if total >= TH else "pe" if total <= -TH else None
    dte = (pd.to_datetime(ex, format="%d-%b-%Y") - pd.Timestamp.now().normalize()).days

    mood = "🟢 BULLISH" if side == "ce" else "🔴 BEARISH" if side == "pe" else "🟡 SIDEWAYS"
    st.markdown(f"**{sym} {spot:,.1f}** · {mood} ({total:+d}) · Trend {sc['Trend'][0]:+d} · "
                f"Structure {sc['Structure'][0]:+d} · Momentum {sc['Momentum'][0]:+d}"
                + (f" · PCR {pcr:.2f}" if ch is not None else ""))
    st.markdown(" · ".join(f"R{i} {piv[f'R{i}']:,.1f}" for i in (1, 2, 3)) + "  |  "
                + " · ".join(f"S{i} {piv[f'S{i}']:,.1f}" for i in (1, 2, 3)))

    if side is None:
        st.warning(f"NO TRADE · score {total:+d}, need ±{TH} or more")
    else:
        kind = "CALL" if side == "ce" else "PUT"
        lv = sorted((v, k) for k, v in piv.items())
        up = [(v, k) for v, k in lv if v > spot]
        dn = [(v, k) for v, k in lv if v < spot][::-1]
        stop, tgts = (dn[:1], up[:2]) if side == "ce" else (up[:1], dn[:2])
        fmt = lambda L: " / ".join(f"{k} {v:,.1f}" for v, k in L) or "n/a"
        way = "below" if side == "ce" else "above"
        if ch is None:
            atm = round(spot / STEP[sym]) * STEP[sym] if sym in STEP else None
            st.success(f"BUY {kind} · {sym} {int(atm) if atm else 'ATM'} {side.upper()} · {ex}")
            st.markdown(f"**Entry** spot ≈ {spot:,.1f} · **Exit** close {way} {fmt(stop)} · **Target** {fmt(tgts)}")
            st.caption("NSE chain is unreachable here, so premium, bid/ask, OI and IV were not checked. "
                       "Confirm the premium in your broker app.")
        else:
            row = sg.pick(ch, spot, side, 0)
            checks, sp, q = sg.liquidity(row, side, MAX_SP, MIN_VOL, MIN_OI)
            entry = row[f"{side}_ask"] if q else row[f"{side}_ltp"]
            if entry <= 0 or not all(checks.values()):
                st.warning(f"WAIT · {kind} bias ({total:+d}) but {int(row.strike)} {side.upper()} fails: "
                           + (", ".join(k for k, v in checks.items() if not v) or "no price"))
            else:
                lot = get_lots().get(sym, nse.DEFAULT_LOT.get(sym, 1))
                slp, tgt = entry * (1 - SL / 100), entry * (1 + SL * RR / 100)
                st.success(f"BUY {kind} · {sym} {int(row.strike)} {side.upper()} · {ex}")
                st.markdown(f"**Entry** ₹{entry:.2f} ({'ask' if q else 'LTP'}) · **Exit (SL)** ₹{slp:.2f} · **Target** ₹{tgt:.2f}")
                st.markdown(f"**Spot exit:** close {way} {fmt(stop)} · **Spot target:** {fmt(tgts)}")
                st.caption(f"Cost/lot ₹{entry * lot:,.0f} · Max loss ≈ ₹{(entry - slp) * lot:,.0f} · Spread {sp:.1f}% · "
                           f"Vol {row[side + '_vol']:,.0f} · OI {row[side + '_oi']:,.0f} · IV {row[side + '_iv']}%")
                notes = [n for n in (
                    not q and "bid/ask unavailable (market closed?), LTP used",
                    rv and atm_iv > 1.5 * rv and f"IV {atm_iv:.0f}% rich vs realised {rv:.0f}%",
                ) if n]
                if notes:
                    st.caption("⚠ " + " · ".join(notes))
        if dte <= 1:
            st.caption("⚠ Expiry within a day: heavy theta decay, keep size tiny.")
    st.caption(f"{ts or 'Price data: Yahoo'} · Rule-based, not backtested, not advice.")


view()
