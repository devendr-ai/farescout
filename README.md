# Farescout

A personal flight-deal finder. It watches fares from your home airports, compares each
one with that route's own normal price, re-checks the best ones live on Google Flights,
and sends them to Telegram. Results show on a small dashboard hosted on GitHub Pages.

No deal sites are involved: deals come from fare data, not from someone else's list.

## How it works

1. **Scan.** Every 6 hours a GitHub Action asks the
   [Travelpayouts Data API](https://support.travelpayouts.com/hc/en-us/articles/203956163-Aviasales-Data-API)
   for the cheapest roundtrip from each home airport to every destination, for each of
   the next 10 departure months.
2. **Compare.** Each fare is compared with a baseline for the same route and departure month:
   - the median daily low over the last 90 days, once there are 7+ days of history;
   - before that, the median price of the same route's other departure months.

   A fare at least 40% below baseline is a deal. 65%+ below is flagged as a possible
   mistake fare. Both thresholds are in `config.toml`.
3. **Confirm.** Travelpayouts prices are cached from searches in the last 48 hours, so the
   biggest drops are re-checked on Google Flights with
   [fast-flights](https://github.com/AWeirdDev/flights). Deals that went up are shown faded.
4. **Alert.** Deals 50%+ below baseline that weren't disproved by the live check go to
   Telegram. The same route and month won't alert again unless the price drops another 10%
   or 14 days pass.

Fare history is stored in SQLite (`data/farescout.db`) and carried between runs in the
GitHub Actions cache, so the repo stays small.

## Setup

### 1. Travelpayouts token (required)

Sign up free at [travelpayouts.com](https://www.travelpayouts.com/), then copy the token
from **Profile → API token**.

### 2. Telegram bot (optional, for alerts)

1. In Telegram, message [@BotFather](https://t.me/BotFather), send `/newbot`, and copy the bot token.
2. Send any message to your new bot.
3. Open `https://api.telegram.org/bot<TOKEN>/getUpdates` and copy `message.chat.id`.

### 3. GitHub

Add repository secrets (**Settings → Secrets and variables → Actions**):

| Secret | Value |
|---|---|
| `TRAVELPAYOUTS_TOKEN` | your Travelpayouts token |
| `TELEGRAM_BOT_TOKEN` | your bot token (optional) |
| `TELEGRAM_CHAT_ID` | your chat id (optional) |

Then set **Settings → Pages → Source** to **GitHub Actions**, and run the
**Scan fares** workflow once from the Actions tab.

### 4. Home airports

Edit `config.toml`. Use IATA city codes (`NYC`, `DEL`) to cover every airport in a metro
area, or airport codes (`JFK`, `BLR`). Set `currency` and `market` per origin
(`usd`/`us` for US airports, `inr`/`in` for Indian airports).

## Run locally

Requires Python 3.11+.

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export TRAVELPAYOUTS_TOKEN=...
python -m farescout scan              # scan, detect, live-check, write docs/deals.json
python -m farescout scan --no-verify  # skip Google Flights checks
python -m farescout test-alert        # send a test Telegram message
python -m http.server -d docs 8000    # dashboard at http://localhost:8000
```

Google often blocks requests from cloud servers, so live checks may fail on GitHub Actions
and show as "not checked". They work more reliably from your own machine.

Run the tests with `python -m unittest`.

## Ground rules

This is for personal use. It keeps request volume low (about 30 API calls and up to 15
Google Flights checks per run) and does not try to get around rate limits or blocks.

## Roadmap

- Point-of-sale comparison: price the same trip in USD and INR.
- Positioning trips: a cheap flight to a hub plus a cheap onward fare from that hub.
- Business-class scans.
