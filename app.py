import pandas as pd
import streamlit as st

import nse
import strategy as sg

st.set_page_config("Nifty Options", layout="centered")
st.markdown("<style>.block-container{padding-top:1rem}</style>"
            "<div style='font-size:13px;font-weight:600;letter-spacing:1px;opacity:.7'>NIFTY OPTIONS</div>",
            unsafe_allow_html=True)


@st.cache_data(ttl=3600)
def get_syms(): return nse.symbols()
@st.cache_data(ttl=3600)
def get_lots(): return nse.lot_sizes()
@st.cache_data(ttl=300)
def get_hist(s): return nse.history(s)
@st.cache_data(ttl=15)
def get_chain(s, e): return nse.chain(s, e)


@st.cache_data(ttl=600)
def get_exp(s):
    e = nse.expiries(s)
    if not e:
        raise RuntimeError("no expiries")  # errors are not cached, so Search retries
    return e


a, b = st.columns(2)
sym = a.selectbox("Symbol (type to search)", get_syms())
try:
    exps = get_exp(sym)
except Exception:
    exps = []
ex = b.selectbox("Expiry", exps) if exps else None
c, d = st.columns([2, 1])
go = c.button("🔍 Search", type="primary", use_container_width=True)
auto = d.toggle("Auto-run")

with st.expander("⚙ Settings"):
    lot = st.number_input("Lot size", 1, 100000, get_lots().get(sym, nse.DEFAULT_LOT.get(sym, 1)))
    budget = st.number_input("Budget per lot (₹)", 0, 10_000_000, 10_000, 500)
    th = st.slider("Signal threshold (|score| >=)", 1, 6, 3)
    off = st.slider("Strike offset (0 = ATM)", 0, 3, 0)
    sl = st.slider("Stop-loss on premium (%)", 10, 60, 30)
    rr = st.slider("Reward : risk", 1.0, 4.0, 2.0, 0.5)
    mx_sp = st.slider("Max bid-ask spread (%)", 1, 20, 5)
    mn_vol = st.number_input("Min volume", 0, value=1000, step=500)
    mn_oi = st.number_input("Min OI", 0, value=10000, step=1000)
    every = st.number_input("Auto-run every (sec)", 10, 300, 30)

if go:
    st.session_state.run = True
if not (st.session_state.get("run") or auto):
    st.caption("Symbol aur expiry chuno, phir Search dabao.")
    st.stop()
if not ex:
    st.error("NSE se expiry nahi mili (block ya rate-limit). Thodi der baad Search dabao.")
    st.stop()


@st.fragment(run_every=every if auto else None)
def view():
    try:
        spot, ch, ts = get_chain(sym, ex)
        h = get_hist(sym)
    except Exception as e:
        st.error(f"Data error: {e}")
        return
    done = h[h.index.date < pd.Timestamp.now(tz="Asia/Kolkata").date()]
    piv = sg.pivots(done.iloc[-1])
    sc, rv = sg.price_scores(h)
    cs, pcr, atm_iv, win = sg.chain_scores(ch, spot)
    sc.update(cs)
    total = sum(v[0] for v in sc.values())
    side = "ce" if total >= th else "pe" if total <= -th else None
    dte = (pd.to_datetime(ex, format="%d-%b-%Y") - pd.Timestamp.now().normalize()).days

    mood = "🟢 BULLISH" if side == "ce" else "🔴 BEARISH" if side == "pe" else "🟡 SIDEWAYS"
    st.markdown(f"**{sym} {spot:,.1f}** · {mood} ({total:+d}) · Trend {sc['Trend'][0]:+d} · "
                f"Structure {sc['Structure'][0]:+d} · Momentum {sc['Momentum'][0]:+d} · PCR {pcr:.2f}")
    st.markdown(" · ".join(f"R{i} {piv[f'R{i}']:,.1f}" for i in (1, 2, 3)) + "  |  "
                + " · ".join(f"S{i} {piv[f'S{i}']:,.1f}" for i in (1, 2, 3)))

    if side is None:
        st.warning(f"NO TRADE · score {total:+d}, need ±{th} or more")
    else:
        row = sg.pick(ch, spot, side, off)
        checks, sp, q = sg.liquidity(row, side, mx_sp, mn_vol, mn_oi)
        entry = row[f"{side}_ask"] if q else row[f"{side}_ltp"]
        kind = "CALL" if side == "ce" else "PUT"
        if entry <= 0 or not all(checks.values()):
            st.warning(f"WAIT · {kind} bias ({total:+d}) but {int(row.strike)} {side.upper()} fails: "
                       + (", ".join(k for k, v in checks.items() if not v) or "no price"))
        else:
            slp, tgt, cost = entry * (1 - sl / 100), entry * (1 + sl * rr / 100), entry * lot
            st.success(f"BUY {kind} · {sym} {int(row.strike)} {side.upper()} · {ex}")
            st.markdown(f"**Entry** ₹{entry:.2f} ({'ask' if q else 'LTP'}) · **Exit (SL)** ₹{slp:.2f} · **Target** ₹{tgt:.2f}")
            lv = sorted((v, k) for k, v in piv.items())
            up = [(v, k) for v, k in lv if v > spot]
            dn = [(v, k) for v, k in lv if v < spot][::-1]
            stop, tgts = (dn[:1], up[:2]) if side == "ce" else (up[:1], dn[:2])
            fmt = lambda L: " / ".join(f"{k} {v:,.1f}" for v, k in L) or "n/a"
            st.markdown(f"**Spot exit:** close {'below' if side == 'ce' else 'above'} {fmt(stop)} · **Spot target:** {fmt(tgts)}")
            st.caption(f"Cost/lot ₹{cost:,.0f} · Max loss ≈ ₹{(entry - slp) * lot:,.0f} · Spread {sp:.1f}% · "
                       f"Vol {row[side + '_vol']:,.0f} · OI {row[side + '_oi']:,.0f} · IV {row[side + '_iv']}%")
            notes = [n for n in (
                cost > budget and f"cost above budget ₹{budget:,.0f}",
                not q and "bid/ask unavailable (market closed?), LTP used",
                rv and atm_iv > 1.5 * rv and f"IV {atm_iv:.0f}% rich vs realised {rv:.0f}%",
                dte <= 1 and "expiry within a day: heavy theta, keep size tiny",
            ) if n]
            if notes:
                st.caption("⚠ " + " · ".join(notes))

    cols = {"ce_oi": "CE OI", "ce_chg": "CE ΔOI", "ce_vol": "CE Vol", "ce_iv": "CE IV", "ce_bid": "CE Bid",
            "ce_ask": "CE Ask", "strike": "Strike", "pe_bid": "PE Bid", "pe_ask": "PE Ask", "pe_iv": "PE IV",
            "pe_vol": "PE Vol", "pe_chg": "PE ΔOI", "pe_oi": "PE OI"}
    with st.expander("Chain near ATM (bid · ask · volume · OI · IV)"):
        st.dataframe(win[list(cols)].rename(columns=cols), hide_index=True)
    with st.expander("Why this signal"):
        st.dataframe(pd.DataFrame([{"Factor": k, "Score": v[0], "Reading": v[1]} for k, v in sc.items()]),
                     hide_index=True)
    st.caption(f"NSE {ts} · Rule-based, not backtested, not advice. Most option buyers lose money.")


view()
