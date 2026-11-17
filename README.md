# Expiry Zero-to-Hero Dashboard (Streamlit, free live data, no account, no API key)

Works only on an option's expiry day. Picks CALL or PUT from a score (Trend, Structure, Momentum on 5-minute candles,
PCR, OI build-up, day move, max pain), then finds a liquid OTM strike priced Rs 3-5 and shows entry, targets and exit.

Data: NSE option chain (bid/ask, OI, volume, IV, live) + Yahoo Finance 5-minute candles. Nothing is estimated.

## Run on your laptop / PC (Indian internet)
1. Install Python 3.10+ from python.org (tick "Add Python to PATH").
2. Put all files in one folder and open a terminal there (Windows: type `cmd` in the folder's address bar).
3. `pip install -r requirements.txt`
4. `streamlit run app.py`
5. Open the Local URL. A phone on the same Wi-Fi can open the Network URL Streamlit prints.

NSE blocks cloud servers (Streamlit Cloud included), so this must run on your own device.
Optional: set an Upstox free Analytics token as `UPSTOX_TOKEN` (env variable or Streamlit secret) to use Upstox data instead; that works on Streamlit Cloud.

Add `?test=1` to the URL to check live data on a non-expiry day (market hours).
Rule-based, not backtested, not investment advice. Zero-to-Hero usually loses the whole premium.
