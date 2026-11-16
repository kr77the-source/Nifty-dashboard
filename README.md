# Expiry Zero-to-Hero Dashboard (Streamlit, free live data from Upstox)

Works only on an option's expiry day. Picks CALL or PUT from a score (Trend, Structure, Momentum on 5-minute candles,
PCR, OI build-up, day move, max pain), then finds a liquid OTM strike priced Rs 3-5 and shows entry, targets and exit.
All market data is live from the free Upstox API; nothing is estimated.

## Setup (no paid API)
1. Open an Upstox account (free), then generate an Analytics Token at https://account.upstox.com/developer/apps (Analytics tab).
2. Streamlit Cloud: Manage app -> Settings -> Secrets: `UPSTOX_TOKEN = "your-token"` (locally: environment variable).
3. Never commit the token to GitHub.

Add `?test=1` to the app URL to check live data on a non-expiry day (market hours).

Rule-based, not backtested, not investment advice. Zero-to-Hero usually loses the whole premium.
