# Farescout

A personal flight-deal finder. It watches fares from your home airports, compares each
one with that route's own normal price, re-checks the best ones live on Google Flights,
and emails you a digest of new deals twice a day, with confirmed mistake fares sent right
away. It also pulls posts from free deal-site feeds that leave from your airports. Results
show on a small dashboard hosted on GitHub Pages.

## How it works

1. **Scan.** Six times a day (every 4 hours from 01:00 UTC) a GitHub Action asks the
   [Travelpayouts Data API](https://support.travelpayouts.com/hc/en-us/articles/203956163-Aviasales-Data-API)
   for the cheapest roundtrip from each home airport to every destination, for each of
   the next 10 departure months. Each scan also pulls:
   - the cheapest **nonstop** roundtrips, compared only with nonstop history;
   - Aviasales' **special offers** (fares it flags as abnormally low);
   - more than one data **market** per airport (Indian airports use both `in` and `us`);
   - posts from free deal-site feeds (The Flight Deal, r/flightdeals, Fly4free) that leave
     from a home airport. Feeds that refuse a request are skipped for that run.
2. **Compare.** Each fare is compared with a baseline for the same route and departure month:
   - the median daily low over the last 90 days, once there are 7+ days of history;
   - before that, the median price of the same route's other departure months.

   A fare at least 40% below baseline is a deal. 65%+ below is flagged as a possible
   mistake fare. Both thresholds are in `config.toml`.
3. **Confirm.** Travelpayouts prices are cached from searches in the last 48 hours, so the
   biggest drops are re-checked on Google Flights. Possible mistake fares go through
   [SerpApi](https://serpapi.com/google-flights-api) (free plan: 250 searches a month,
   budgeted at 8 a day), which works reliably from GitHub and also returns Google's typical
   price range for the trip. Other deals use
   [fast-flights](https://github.com/AWeirdDev/flights), which Google often blocks on
   GitHub's servers. Deals that went up are shown faded.
4. **Alert.** A digest of new deals (50%+ below baseline and confirmed live on Google
   Flights) and new deal-site posts goes out with the first scan after 01:00 and 13:00 UTC.
   Confirmed mistake fares and posts that say "error fare" are emailed on any scan. The same
   route and month won't alert again unless the price drops another 10% or 14 days pass.
   Telegram messages are optional.

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

### 3. SerpApi key (recommended, for mistake-fare checks)

Sign up free at [serpapi.com](https://serpapi.com/users/sign_up) and copy your API key from
the dashboard. Without it, mistake fares are checked with fast-flights only.

### 4. Telegram bot (optional)

1. In Telegram, message [@BotFather](https://t.me/BotFather), send `/newbot`, and copy the bot token.
2. Send any message to your new bot.
3. Open `https://api.telegram.org/bot<TOKEN>/getUpdates` and copy `message.chat.id`.

### 5. GitHub

Add repository secrets (**Settings → Secrets and variables → Actions**):

| Secret | Value |
|---|---|
| `TRAVELPAYOUTS_TOKEN` | your Travelpayouts token |
| `SERPAPI_API_KEY` | your SerpApi key (recommended) |
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

### 6. Home airports

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

This is for personal use. It keeps request volume modest (about 190 Travelpayouts calls,
up to 12 Google Flights checks, up to 3 SerpApi searches and 3 feed reads per run, six times a day; Travelpayouts
allows 600 calls a minute) and does not try to get around rate limits or blocks.

## What it can and can't catch

- Mistake fares that last longer than the gap between scans (4 hours) and that someone
  searched on Aviasales in the last 48 hours, which is where Travelpayouts prices come from.
- Deals posted on the free feeds above, usually within 4 hours of posting.
- It won't see fares nobody searched, and it doesn't read Secret Flying (its feed sits
  behind a bot check) or paid newsletters.

## Roadmap

- Point-of-sale comparison: price the same trip in USD and INR.
- Positioning trips: a cheap flight to a hub plus a cheap onward fare from that hub.
- Business-class scans.
