# China SMR Tracker

An open, sourced record of small modular reactor projects in mainland China:
what has been announced, what is under construction, what is generating, and
what has quietly stopped.

The dataset is a single YAML file under version control. Everything else in
this repository exists to validate it, render it, or watch for changes to it.

---

## Scope

In scope: electricity-generating small modular reactors in mainland China,
**300 MWe or less per module**, land-based or floating, at any stage from
announcement to cancellation.

Out of scope, deliberately:

- Large reactors (Hualong One, CAP1400 and similar)
- Pure district-heating reactors with no electrical output (DHR-400 Yanlong,
  HAPPY200, NHR-200)
- Fast reactors and research reactors with no electrical output (TMSR-LF1)
- Naval propulsion and fuel-cycle facilities

Multi-module plants are judged **per module**, the same convention the IAEA
uses. Ruijin is in the file at roughly 105 MWe per module even though the plant
totals around 650 MWe, and the entry says so.

A narrow scope you can actually finish beats a broad one you cannot defend.
Resist widening it.

## What is in here

```
data/reactors.yml          the dataset — the only thing that matters
scripts/validate_data.py   gatekeeper; the build fails if this fails
scripts/build.py           YAML to HTML, CSV and JSON
scripts/news_sweep.py      fortnightly drift check (flags, never edits)
templates/                 Jinja2 page templates
static/style.css           the stylesheet
.github/workflows/         deploy on push, sweep on a fortnightly cron
```

## Getting it running

```bash
git clone <your repo url> && cd china-smr-tracker
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python scripts/validate_data.py     # expect warnings, no errors
python scripts/build.py
python -m http.server -d _site 8000 # open http://localhost:8000
```

Then on GitHub:

1. Push to a repository with the default branch named `main`.
2. Settings → Pages → Source: **GitHub Actions**.
3. Push again, or run the **Build and deploy** workflow by hand.
4. For a custom domain, add it under Settings → Pages and point a CNAME record
   at `<username>.github.io`.

To switch on the fortnightly sweep, add these repository secrets under
Settings → Secrets and variables → Actions:

| Secret | What it is |
| --- | --- |
| `ANTHROPIC_API_KEY` | from console.anthropic.com |
| `SMTP_SERVER`, `SMTP_PORT` | your mail provider's SMTP details |
| `SMTP_USERNAME`, `SMTP_PASSWORD` | an app password, not your account password |
| `NOTIFICATION_EMAIL` | where the digest goes |

The sweep emails you a digest **and** opens an issue labelled
`needs-verification`. Run it manually once from the Actions tab to confirm the
secrets work.

## The seed data is not verified

Every entry currently in `data/reactors.yml` is marked `verified: false` and
cites a landing page rather than a specific document. Those entries were
written from general knowledge to give you a working file, and several details
are likely to be wrong, particularly the Ruijin approval date and the status of
both floating projects.

Before you publish anything publicly, go through each entry and:

1. Check it against the primary record. For reactors that exist, the IAEA Power
   Reactor Information System is authoritative on construction start, grid
   connection and commercial operation dates. The IAEA ARIS design booklet is
   authoritative on ratings. For projects that only exist on paper, use the
   developer's own filings and NNSA licensing notices.
2. Replace each landing-page source with the specific dated document.
3. Set `verified: true` and `last_verified` to today.

The validator enforces step 2: it refuses to let an entry be marked verified
while it still cites only a corporate homepage. It also warns on anything not
re-checked in 180 days.

## Source hierarchy

1. National Nuclear Safety Administration licensing notices, NDRC and State
   Council approvals
2. Listed-company filings and official developer announcements (CNNC, CGN,
   SPIC, Huaneng)
3. IAEA PRIS and ARIS
4. Established trade press, Chinese or English

Never aggregators. The validator rejects Google News proxy URLs, link
shorteners and content-farm republishers, because a source you cannot open in
five years is not a source.

## The one rule

**Automation flags. People commit.**

The sweep cannot edit `data/reactors.yml` and should never be given permission
to. Its job is to tell you where to look. Yours is to check the primary
document and write the commit message explaining what changed. That boundary is
the entire reason a tracker gets cited rather than ignored.

## Licence

Data under CC BY 4.0. Code under MIT. Attribution requested on reuse.
