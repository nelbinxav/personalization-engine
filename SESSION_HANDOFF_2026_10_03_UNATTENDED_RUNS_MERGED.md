# Handoff: unattended runs and research sources merged (2026-10-03)

You are continuing work on the personalization engine in this repository. Read
`CLAUDE.md` first; it is the source of truth for the architecture and the rules
that must not be loosened. This file records only what `CLAUDE.md` and the git
history do not: where things run, what has been checked, and what is next.

## Where it runs

- **Live address:** https://engine.lakehousemasterclass.com
- **Host:** the operator's Mac. Docker runs under Colima. A Cloudflare tunnel
  (`~/.cloudflared/config.yml`) forwards the hostname to `127.0.0.1:3000`.
- **Kept up by:** `deploy/mac-always-on.sh`, run by the LaunchAgent
  `ai.bighammer.personalization-engine`. It starts Colima, the stack and the
  tunnel. The link is down whenever the Mac sleeps or is signed out.
- **Code changes do not reach the live site until the container is rebuilt.**
  For a frontend change: `docker compose up -d --build --no-deps frontend`.
  `--no-deps` leaves the worker alone, so running jobs are not interrupted.
- **Credential mode:** Claude subscription (`claude_code`). LinkedIn account
  mode is connected.

## Git state

- Work goes to `nelbinxav/personalization-engine` (remote `nelbinxav`, private).
  Local `main` tracks `nelbinxav/main`.
- The `origin` remote is `GrowthClub-org/personalization-engine` and still
  holds only the first scaffold commit. Nothing has been pushed there; do not
  push to it unless asked.
- PR #2 (`unattended-runs-and-research-sources`) carries everything built since
  PR #1: unattended runs, the LinkedIn account source, podcasts and news through
  Exa, per-stage models, ask-first copy, the usage panel, job notices, the tab
  icon and the outreach context document.

## What is checked and what is not

- `cd backend && .venv/bin/python -m pytest -q`: 92 passed.
- `cd frontend && npx next build`: passes.
- The tab icon is served on the live site (`/icon.svg` returns 200).
- Row claiming was tested: a second job on the same upload takes only the rows
  the first has not claimed.
- **Not done yet:** a full LinkedIn-paced research run. The pacing logic has
  unit tests, but no job has run to the hourly rate or the daily cap for real.
- **Not measured:** personalization at 10 rows in parallel. The 14 to 18
  seconds per row figure was measured at 4 in parallel.
- There are no tests of the network paths (scrapers, Claude, LinkedIn service).

## Next: the 500-lead Big Hammer run

As of the last session the 500-lead sheet had not been uploaded. The plan the
operator agreed to:

1. Put the 75 priority leads in the first 75 rows of the sheet.
2. Run a trial first: research and personalize the first 10 rows, and confirm
   that recent LinkedIn posts appear in the results.
3. Research job 1: all sources ticked, row limit 75. At the default 20 LinkedIn
   reads an hour this takes about 7.5 hours (75 leads is about 150 reads, which
   is also the daily cap, so the last leads may finish the next day).
4. Research job 2 on the same upload: untick the three LinkedIn sources, row
   limit All. It picks up the remaining 425 and takes about half an hour. It
   can start straight after job 1.
5. Personalize the whole sheet once both are done.

Things to watch during that run:

- A job that shows `rate_limited` is waiting and restarts by itself at its
  `resume_at`. A job that shows `blocked_auth` needs the operator to sign in.
- The export's `outreach` column says whether a row was personalised or generic,
  and `copy_used` and `fit_evidence` say which copy it got and why.
- Do not raise the LinkedIn pacing to speed the run up. The account is the
  operator's own and can be restricted.

## Reference documents

- `docs/Personalization-Engine-Handbook.docx`: the team handbook.
- `docs/Personalization-Engine-Outreach-Context.docx`: how the tool works, the
  prompts and templates, and Richard's feedback. Written to give context to the
  Big Hammer codebase when preparing templates and Instantly campaigns.
- `deploy/TAILSCALE.md`, `deploy/LINKEDIN.md`: hosting and LinkedIn setup.
