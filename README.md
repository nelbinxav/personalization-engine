# Personalization Engine

Upload a CSV or point at a Google Sheet, research every prospect automatically,
and generate a personalized LinkedIn / email / WhatsApp message per row. Jobs
queue and run unattended; results download as CSV.

## How it works

```
CSV or Google Sheet
      |
      v  confirm what each column means
  SCRAPE JOB ......... website (Jina Reader), blog/RSS, Google News (Serper),
      |                LinkedIn profile + company (Apify)
      v
  PERSONALIZE JOB .... 1. Dossier  raw research -> facts, each tagged by source
      |                2. Angle    facts + what you sell -> angles that cite a fact
      |                3. Draft    angle + your template -> the message
      v
  Download CSV ....... research / personalized / combined
```

Every job runs **one task per row**. A failed row retries by itself, a finished
row is never redone, and the rest of the sheet keeps going.

### Why messages do not invent things

Stage 2 must quote a specific scraped fact as evidence for its angle. If it
cannot, the row is flagged `thin_context` and **no message is generated**. A
flagged row costs nothing to review; a fabricated "I loved your recent post"
costs you the prospect.

## Setup

```bash
cp .env.example .env
# generate the required APP_SECRET_KEY:
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

docker compose up -d --build
docker compose exec api python scripts/create_operator.py you@bighammer.ai
```

Open http://localhost:3000, sign in, then in **Settings**:

1. **Connect Claude.** Click Connect, open the URL it shows, paste the code back.
2. **Fill in "What we sell."** Personalization jobs will not start without it.
3. **Add provider keys** for the sources you want (Serper for news, Apify for
   LinkedIn; Jina is optional).

> **Do not put `ANTHROPIC_API_KEY` in `.env` if you are using OAuth.** The SDK
> puts the environment variable ahead of the OAuth profile, so it would silently
> bill that key's org instead. The worker refuses to start in that state rather
> than quietly doing the wrong thing. To use a key instead, leave the env var
> unset and enter it in Settings — it is stored encrypted.

## Your first run

1. **Uploads → New upload.** Load the file, then confirm the column mapping.
   You need at least one identifier (name or company) **and** at least one thing
   to scrape (website, LinkedIn profile, or LinkedIn company URL).
2. **Jobs → Scrape**, limit **First 3**. Watch it finish, then download the
   `research` CSV and check the columns actually have content.
3. **Prompts → Test on a real row.** Tune the three prompts against a real
   researched prospect before spending on the whole sheet.
4. **Jobs → Personalize**, limit First 3, one channel. Read all three messages.
5. Only then run the full sheet.

## What it costs

Scraping is billed by your providers per row. Personalization is billed by
Anthropic per row and shown per job in the UI.

The three stages share an identical system prompt across every row in a job, so
prompt caching cuts the input cost substantially after the first row. Keep
per-prospect placeholders (`{{identity.*}}`, `{{raw.*}}`) out of the prompt
bodies — the Prompts page warns you when one creeps in and disables caching.

## A note on LinkedIn

Proxycurl, the long-standing default for LinkedIn enrichment, was sued by
LinkedIn in January 2026 and shut down in July 2026. LinkedIn actively litigates
profile scraping. This app therefore treats the LinkedIn vendor as swappable:
`app/sources/linkedin.py` is the only file that knows which one is in use, and
Settings selects it. Apify is implemented; Bright Data, ScrapIn and Unipile are
one function each. Unipile and similar account-based APIs use your own LinkedIn
session, which trades vendor risk for account-ban risk. Which trade-off to take
is your call.

## Stack

FastAPI · MongoDB · Redis/arq · Next.js 16 · Tailwind · Docker Compose.
See `CLAUDE.md` for architecture and the gotchas worth knowing before editing.
