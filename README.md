# Farescout

A personal flight-deal finder. It watches fares from your home airports, compares each
one with that route's own normal price, re-checks the best ones live on Google Flights,
and emails you a digest of new deals twice a day. Results show on a small dashboard
hosted on GitHub Pages.

No deal sites are involved: deals come from fare data, not from someone else's list.

## How it works

1. **Scan.** Twice a day (01:00 and 14:00 UTC: about 6pm and 7am in Seattle, 6:30am and
   7:30pm in India) a GitHub Action asks the
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
4. **Alert.** Each scan emails one digest of new deals that are 50%+ below baseline and
   confirmed live on Google Flights. The same route and month won't alert again unless the
   price drops another 10% or 14 days pass. Telegram messages are optional.

Fare history is stored in SQLite (`data/farescout.db`) and carried between runs in the
GitHub Actions cache, so the repo stays small.

## Setup

### 1. Travelpayouts token (required)

Sign up free at [travelpayouts.com](https://www.travelpayouts.com/), then copy the token
from **Profile → API token**.

### 2. Email alerts (Gmail)

1. Turn on 2-Step Verification for your Google account.
2. Create an app password at https://myaccount.google.com/apppasswords and copy the
   16-character password. Your normal Gmail password won't work here.

Any other SMTP provider works too: set `SMTP_HOST` and `SMTP_PORT` (465 for SSL, 587 for
STARTTLS).

### 3. Telegram bot (optional)

1. In Telegram, message [@BotFather](https://t.me/BotFather), send `/newbot`, and copy the bot token.
2. Send any message to your new bot.
3. Open `https://api.telegram.org/bot<TOKEN>/getUpdates` and copy `message.chat.id`.

### 4. GitHub

Add repository secrets (**Settings → Secrets and variables → Actions**):

| Secret | Value |
|---|---|
| `TRAVELPAYOUTS_TOKEN` | your Travelpayouts token |
| `SMTP_USER` | the Gmail address that sends the digest |
| `SMTP_PASSWORD` | its app password |
| `ALERT_EMAIL_TO` | where to send it, comma-separated (optional; defaults to `SMTP_USER`) |
| `SMTP_HOST`, `SMTP_PORT` | only for providers other than Gmail |
| `TELEGRAM_BOT_TOKEN` | your bot token (optional) |
| `TELEGRAM_CHAT_ID` | your chat id (optional) |

From the repo folder, `gh secret set SMTP_PASSWORD` prompts for the value, so it never
lands in your shell history.

Then set **Settings → Pages → Source** to **GitHub Actions**, and run the
**Scan fares** workflow once from the Actions tab.

### 5. Home airports

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
python -m farescout test-alert        # send a test email (and Telegram message)
python -m http.server -d docs 8000    # dashboard at http://localhost:8000
```

Google often blocks requests from cloud servers, so live checks may fail on GitHub Actions
and show as "not checked". They work more reliably from your own machine.

Run the tests with `python -m unittest`.

## Ground rules

This is for personal use. It keeps request volume low (about 60 API calls and up to 20
Google Flights checks per run, twice a day) and does not try to get around rate limits or blocks.

## Roadmap

- Point-of-sale comparison: price the same trip in USD and INR.
- Positioning trips: a cheap flight to a hub plus a cheap onward fare from that hub.
- Business-class scans.
