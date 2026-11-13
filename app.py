import os
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import streamlit as st

import strategy as sg

TH, LO, HI, LOTS = 4, 3.0, 5.0, 2  # signal threshold, premium band in Rs, lots (article: 2-3 at most)
MIN_VOL, MIN_OI, MAX_SP = 1000, 10000, 15
IST = timezone(timedelta(hours=5, minutes=30))
ORDER = {"NIFTY": 0, "BANKNIFTY": 1, "FINNIFTY": 2}
dfmt = lambda e: datetime.strptime(e, "%Y-%m-%d").strftime("%d-%b-%Y")
pct = lambda p: "<0.1%" if p < 0.001 else f"{p:.1%}"

st.set_page_config("Nifty Options", layout="centered")
st.markdown("<style>.block-container{padding-top:4.5rem}</style>"
            "<div style='font-size:13px;font-weight:600;letter-spacing:1px;opacity:.7'>NIFTY OPTIONS · EXPIRY ZERO-TO-HERO</div>",
            unsafe_allow_html=True)


def secret(name):
    try:
        return str(st.secrets[name])
    except Exception:
        return os.environ.get(name, "")


if secret("UPSTOX_TOKEN"):
    import upstox as prov
    prov.login(secret("UPSTOX_TOKEN"))
    SRC = "Upstox"
elif secret("GROWW_API_KEY") and (secret("GROWW_TOTP_SECRET") or secret("GROWW_API_SECRET")):
    import growwdata as prov
    prov.login(secret("GROWW_API_KEY"), secret("GROWW_TOTP_SECRET"), secret("GROWW_API_SECRET"))
    SRC = "Groww"
else:
    st.error("Live data ke liye broker API chahiye. Streamlit → Manage app → Settings → Secrets mein Groww ke ye do daalo:")
    st.code('GROWW_API_KEY = "..."\nGROWW_TOTP_SECRET = "..."')
    st.stop()


def hint(e):
    t = str(e).lower()
    if "403" in t or "forbidden" in t:
        return "Access nahi mila: Groww Live Data subscription active hai? (Groww app → Settings → Trading APIs)"
    if "401" in t or "unauthor" in t or "expired" in t or "invalid" in t:
        return "Credentials ya token galat/expire. Secrets check karo."
    return str(e)


@st.cache_data(ttl=43200, show_spinner="Instrument list load ho rahi hai (pehli baar 30-60 sec lag sakte hain)...")
def get_uni(): return prov.universe()
@st.cache_data(ttl=20)
def get_m(sym): return prov.minutes(uni[sym])
@st.cache_data(ttl=10)
def get_chain(sym, exp): return prov.chain(uni[sym], exp)


try:
    uni = get_uni()
except Exception as e:
    st.error(f"Instrument list nahi mili: {hint(e)}")
    st.stop()

syms = sorted(uni, key=lambda s: (uni[s]["type"] != "INDEX", ORDER.get(s, 3), s))
now0 = datetime.now(IST)
today = now0.strftime("%Y-%m-%d")
a, b = st.columns(2)
sym = a.selectbox("Symbol (type to search)", syms)
exps = [e for e in uni[sym]["exp"] if e >= today]
ex = b.selectbox("Expiry", exps, format_func=dfmt)
c, d = st.columns([2, 1])
go = c.button("🔍 Search", type="primary", use_container_width=True)
auto = d.toggle("Auto-run")
if not ex:
    st.warning("Is symbol ke liye koi expiry nahi mili.")
    st.stop()
if ex != today and not st.query_params.get("test"):  # add ?test=1 to the URL to check live data on a non-expiry day
    st.info(f"Aaj {sym} ki expiry nahi hai. Next expiry {dfmt(ex)} "
            f"({(datetime.strptime(ex, '%Y-%m-%d').date() - now0.date()).days} din baad). "
            "Ye app sirf expiry-day Zero-to-Hero ke liye hai.")
    tod = [s for s in syms if today in uni[s]["exp"]]
    if tod:
        st.caption("Aaj expiry wale symbols: " + ", ".join(tod[:15]))
    st.stop()
if go:
    st.session_state.run = True
if not (st.session_state.get("run") or auto):
    st.caption("Aaj expiry hai. Search dabao.")
    st.stop()


@st.fragment(run_every=30 if auto else None)
def view():
    now = datetime.now(IST)
    t0, t1 = (now.replace(hour=h_, minute=m_, second=0, microsecond=0) for h_, m_ in ((9, 15), (15, 30)))
    if now < t0:
        st.info("Market 9:15 par khulega. Tab Search dabao.")
        return
    if now > t1:
        st.info("Aaj ki expiry khatam ho chuki hai (3:30 PM).")
        return
    info = uni[sym]
    try:
        m = get_m(sym)
        spot, ch = get_chain(sym, ex)
    except Exception as e:
        st.error(f"Live data nahi aaya: {hint(e)}")
        return
    if len(m) < 60 or m.index[-1] < now - timedelta(minutes=20) and now - t0 > timedelta(minutes=20):
        st.error(f"Intraday candles fresh nahi hain (last candle {m.index[-1]:%d-%b %H:%M}). Purane data par trade nahi dikhaunga.")
        return
    day = np.array(m.index.date)
    prev, td = m[day < now.date()], m[day == now.date()]
    if prev.empty:
        st.error("Pichle session ka data nahi mila, signal nikalna mumkin nahi.")
        return
    last = prev[np.array(prev.index.date) == prev.index.date[-1]]
    piv = sg.pivots({"High": last.High.max(), "Low": last.Low.min(), "Close": last.Close.iloc[-1]})
    sc, _ = sg.price_scores(m)
    cs, pcr, atm_iv, _ = sg.chain_scores(ch, spot)
    sc.update(cs)
    chg = spot / td.Open.iloc[0] - 1 if len(td) else 0.0
    sc["Day"] = (1 if chg > 0.0015 else -1 if chg < -0.0015 else 0, f"{chg:+.2%} from open")
    mp = sg.max_pain(ch)
    dmp = (mp - spot) / spot
    sc["MaxPain"] = (1 if dmp > 0.002 else -1 if dmp < -0.002 else 0, f"Max pain {mp:,.0f}")
    total = sum(v[0] for v in sc.values())
    mx = 10 if ch[["ce_chg", "pe_chg"]].to_numpy().any() else 9  # OI build-up needs previous OI (Groww's chain has none)
    side = "ce" if total >= TH else "pe" if total <= -TH else None

    left = t1 - now
    st.caption(f"🟢 LIVE · {SRC} · {now:%H:%M:%S} IST · expiry close mein {left.seconds // 3600}h {left.seconds % 3600 // 60}m")
    mood = "🟢 BULLISH" if side == "ce" else "🔴 BEARISH" if side == "pe" else "🟡 SIDEWAYS"
    st.markdown(f"**{sym} {spot:,.1f}** · {mood} ({total:+d}/{mx}) · Trend {sc['Trend'][0]:+d} · "
                f"Structure {sc['Structure'][0]:+d} · Momentum {sc['Momentum'][0]:+d} · PCR {pcr:.2f} · Max pain {mp:,.0f}")
    st.markdown(" · ".join(f"R{i} {piv[f'R{i}']:,.1f}" for i in (1, 2, 3)) + "  |  "
                + " · ".join(f"S{i} {piv[f'S{i}']:,.1f}" for i in (1, 2, 3)))

    if side is None:
        st.warning(f"NO TRADE · score {total:+d}, need ±{TH} or more. Zero-to-Hero mein direction pakki chahiye.")
    else:
        call, kind = side == "ce", "CALL" if side == "ce" else "PUT"
        ok, miss = sg.pick_zero(ch, spot, side, LO, HI, MIN_VOL, MIN_OI, MAX_SP)
        if not ok.empty:  # chains without bid/ask (Groww): fetch live quotes for the top candidates, then re-pick
            try:
                ch = prov.enrich(info, ex, ch, side, ok.strike.head(4).tolist())
                ok, miss = sg.pick_zero(ch, spot, side, LO, HI, MIN_VOL, MIN_OI, MAX_SP)
            except Exception as e:
                st.caption(f"⚠ Bid/ask quote nahi aaya ({hint(e)}), LTP use ho raha hai.")
        if ok.empty:
            near = [f"{int(r.strike)} @ ₹{r.px:.2f}" for x in miss for r in x.itertuples()]
            st.warning(f"{kind} bias hai, par abhi ₹{LO:g}-{HI:g} wala liquid strike nahi."
                       + (f" Nearest: {' / '.join(near)}." if near else "") + " Thodi der baad dobara dekho.")
        else:
            r, lot = ok.iloc[0], info["lot"]
            entry, strike = float(r.px), int(r.strike)
            st.success(f"ZERO-TO-HERO · BUY {kind} · {sym} {strike} {side.upper()} · {dfmt(ex)}")
            st.markdown(f"**Entry** ₹{entry:.2f} ({'ask' if r[f'{side}_ask'] > 0 else 'LTP'}) · **Cost/lot** ₹{entry * lot:,.0f} · "
                        f"**{LOTS} lots** ₹{entry * lot * LOTS:,.0f} (yehi max loss)")
            st.markdown(f"**Target 1** ₹{entry * 3:.2f} (3x, aadha becho) · **Target 2** ₹{entry * 8:.2f} (8x, baaki) · "
                        f"**Exit:** spot {strike:,} touch kare ya 3:15 PM, jo pehle")
            need = abs(strike - spot)
            tc = sg.touch_chance(spot, strike, r[f"{side}_iv"] or atm_iv, left.total_seconds() / (365 * 24 * 3600), call)
            st.caption(f"Spot ko {need:,.0f} pts ({need / spot:.2%}) {'upar' if call else 'neeche'} jana hoga"
                       + (f" · market-implied chance: expiry par ITM ≈ {pct(tc[0])}, beech mein touch ≈ {pct(tc[1])}" if tc else "")
                       + f" · Bid {r[f'{side}_bid']:.2f} / Ask {r[f'{side}_ask']:.2f} · Vol {r[f'{side}_vol']:,.0f} · "
                       f"OI {r[f'{side}_oi']:,.0f} · IV {r[f'{side}_iv']:.1f}% · Lot {lot}")
            more = [f"{int(x.strike)} (₹{x.px:.2f})" for x in ok.iloc[1:4].itertuples()]
            if more:
                st.caption("Band mein aur: " + ", ".join(more))
            if left.total_seconds() > 4 * 3600:
                st.caption("⏳ Abhi expiry mein 4 ghante se zyada hain. Article ke hisab se last 2-3 ghante mein explosion hota hai.")
    st.caption("Zero-to-Hero lottery hai: aksar poora premium zero hota hai. Sirf wahi paisa lagao jo doob jaye. "
               "Rule-based, not backtested, not advice.")


view()
