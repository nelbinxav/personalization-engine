# LinkedIn through your own account

Recent posts, and anything else LinkedIn shows only to signed-in members, are
read through a real LinkedIn account. A separate container runs
[linkedin-mcp-server](https://github.com/stickerdaniel/linkedin-mcp-server),
the tool Agent Reach uses for LinkedIn: it drives a browser signed in to that
account, and the engine asks it for one page at a time.

## Before you turn it on

- **It is against LinkedIn's User Agreement.** Automated access is prohibited,
  and an account used this way can be restricted or banned. Nobody can promise
  otherwise, including the tool's author.
- **Use an account you can afford to lose.** Not the founder's, and not the one
  your campaigns send from. An established account with a normal history is
  treated better than a brand-new one.
- **It is slow on purpose.** One page at a time, spread over the day at an
  hourly rate (20 reads an hour by default: one about every three minutes, at
  uneven intervals), under a daily cap (150 reads, about 75 prospects, which
  take about seven and a half hours). A 1,000-row sheet takes around two
  weeks. When the day's cap is used up the research job pauses and carries on
  by itself the next day. Both numbers are in Settings; lower is safer.
- **Keep it in one place.** Sign in on the machine that will run it. A session
  that moves between addresses triggers LinkedIn's security checks.

If that is not acceptable, leave the LinkedIn provider on Apify in Settings.
Apify reads profiles and company pages with no account, but not recent posts.

## 1. Start the service

```bash
docker compose --profile linkedin up -d
```

Or put `COMPOSE_PROFILES=linkedin` in `.env`, so every `docker compose up -d`
includes it.

## 2. Connect the account from Settings

**Settings → Research → LinkedIn provider → Your LinkedIn account**, then
**Connect LinkedIn** in the card below it. After about ten seconds the card
shows **Open the sign-in window**. Sign in to LinkedIn there, and approve the
login in the LinkedIn mobile app or solve the captcha if asked. The card turns
to Connected by itself; **Test connection** proves it by reading your own
profile once.

To paste in the sign-in window, click the field and press Cmd+V (or the Paste
button at the top). The window shows a browser inside the engine with its own
clipboard, so the page types your clipboard in as keystrokes; allow clipboard
access if the browser asks, or use the box it offers instead.

The sign-in window is served on `127.0.0.1:6080`, so it opens only on the
machine the engine runs on. On a remote server, forward the port first:
`ssh -L 6080:127.0.0.1:6080 ubuntu@engine`. The password is typed into
LinkedIn's own page; the engine never sees it.

Without the Settings page, the same thing by hand:

```bash
docker compose --profile linkedin stop linkedin
docker compose --profile linkedin run --rm -p 127.0.0.1:6080:6080 \
  --entrypoint "tini -e 143 -- linkedin-mcp-entrypoint python -m linkedin_mcp_server" \
  linkedin --login --login-viewer
docker compose --profile linkedin up -d
```

## 3. Use it

Make sure **Recent LinkedIn posts** is ticked under the sources, and set
**LinkedIn reads per day**. Test with a research job limited to 3 rows. In the
job, each row shows a chip per source; the CSV has a `research_linkedin_posts`
column.

## What the engine does with posts

- Only posts stamped within the last 10 days are kept. LinkedIn shows "1w" for
  anything 7 to 13 days old, so those are kept and marked as such.
- A repost is labelled as someone else's words and is not used as the
  prospect's own.
- A row with no recent post simply has no post to open with; the engine moves
  down the list: podcasts, profile, company page, news, website.

## When it stops working

| Symptom | What to do |
|---|---|
| Rows say "The LinkedIn account is not signed in" | The session expired. Connect again from Settings (step 2). |
| Rows say "The LinkedIn service is not running" | Step 1. |
| Rows say "LinkedIn is rate-limiting the account" | Stop for a day and lower the daily limit. This is LinkedIn's warning. |
| The job shows "Waiting for limit" | The daily cap was reached. It resumes just after midnight UTC. |
| LinkedIn asks the account to verify its identity | Stop using this route on that account. |
