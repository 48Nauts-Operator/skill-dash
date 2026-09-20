# skill-dash

Judge a tree of Claude Code and Codex skills with [Jev](https://typesafe.ai), TypeSafe's typed-judgment model. One row per skill, one question per row: keep, rewrite, merge or delete. Also the pipeline behind [whichskills.dev](https://whichskills.dev), a public census of 18,041 skills from the 200 most-starred repos.

Python standard library and SQLite, no dependencies, no build step. Runs on 127.0.0.1 only. Nothing leaves your machine except the Jev calls you choose to make.

## You need

- **A Jev API key.** Sign in at [console.typesafe.ai](https://console.typesafe.ai/), create a key, export it as `TYPESAFE_API_KEY` (on macOS the Keychain entry service `xnaut`, account `plugin/typesafe/TYPESAFE_API_KEY` also works). Docs: [docs.typesafe.ai](https://docs.typesafe.ai/). Jev was in early access when this was built; hello@typesafe.ai is the listed contact if you have no access yet. The loader, the evidence scan and the static safety pre-scan run without a key; judgments and the overlap audit need one.
- **Python 3.** Standard library only.

Cost, for orientation: TypeSafe listed $42 per billion input tokens on 2026-09-20. A content-only pass over 78 skills is well under a cent; the full-text safety read of 545 bodies for whichskills.dev was about 18 cents. The dashboard shows the token count of every run.

## Quick start

```sh
git clone https://github.com/48Nauts-Operator/skill-dash && cd skill-dash
export TYPESAFE_API_KEY=...
python3 server.py --port 3345       # your own ~/.claude/skills tree plus enabled plugins
python3 server.py --port 3346 --roots ~/some/skills-repo   # any repo of SKILL.md files
```

Open the port in a browser. Settings runs the overlap audit; Judges edits the questions; the drawer on each row holds the evidence, the Jev distributions, a radar against the tree average and your decision.

## What it shows

- Every `SKILL.md` under `~/.claude/skills` plus the skills of enabled plugins (from `~/.claude/settings.json`). Name, description, source (own / imported / plugin), body size, scripts, install date.
- Evidence from `~/.claude/projects/**/*.jsonl`: Skill-tool invocations with the last date, slash-command mentions, and mentions of the skill's own script filenames. Skill names alone are not counted, because the skill list is in every session prompt. Files are cached by mtime and size; a rescan only re-reads what changed.
- Pairwise overlap from the `skill-audit` script, run from Settings; each row shows its strongest partner.
- Jev judgments, editable on the Judges page: usefulness 0 to 3, redundancy (CLAUDE.md / hook / other skill / tooling / none), description clarity 0 to 3, recommended action. Each skill is judged with its description, body excerpt, evidence, your global CLAUDE.md excerpt and hook config as state.
- Your decision per skill with a note, persisted in SQLite, exported as JSON. Nothing on disk is edited or deleted by the app.

## Review any skill repo

```sh
python3 server.py --port 3346 --roots ~/path/to/some-skills-repo [--exclude generated-folder]
```

Loads every `SKILL.md` under the roots (hidden dirs and `node_modules` skipped), keyed by path so repeated names stay distinct. Transcript evidence is off (it is not evidence for someone else's tree) and the Judges page defaults to the content-only preset: usefulness on content alone, a duplicate-of question fed by the top three overlap partners, clarity, action. Run the overlap audit from Settings first; it walks the roots recursively and runs in parallel. Each root set gets its own SQLite file under `.data/roots-<hash>/`.

## Tests

```sh
python3 -m unittest discover -s tests -v
NODE_PATH=/path/to/node_modules/with/playwright node tests/screenshot.mjs   # headless smoke against a running server
```

Jev credential: `TYPESAFE_API_KEY` or macOS Keychain service `xnaut`, account `plugin/typesafe/TYPESAFE_API_KEY`. Model `jev-1.13.0`, override with `TYPESAFE_MODEL`.

## Find what is missing

The Find view (own tree only, not under `--roots`) profiles your tree locally: your CLAUDE.md, your skills and how often you use them, and, only if you tick the box, the opening prompt of your last 60 sessions. It downloads the public index from whichskills.dev, drops copies, twins by name or body, and bodies at risk 1.5 or above, cuts to the closest 200 by TF-IDF from your profile, fetches each candidate's SKILL.md at its pinned commit, and asks Jev two questions per candidate: fit against your profile (0 to 3) and whether one of your own skills already does the job. Ranked by fit discounted by twin probability. Each row shows the install command; the tool never writes to your tree. About 2M tokens per run.

## Corpus tools

The same loader, pre-scan and judge run at corpus scale for [whichskills.dev](https://whichskills.dev):

```sh
python3 scripts/crawl.py discover --out corpus.json --limit 200        # GitHub repo search via gh, sorted by stars
python3 scripts/crawl.py clone corpus.json --dest repos                # blobless clones with history
python3 scripts/crawl.py scan --dest repos --corpus corpus.json --out report.json --md report.md
python3 scripts/judge_queue.py --dest repos --out jev-risk.json        # Jev safety read, deduplicated by body
python3 scripts/build_site.py --corpus . --out website                 # the static site, every number from the JSON
```

`crawl.py` makes no Jev calls; it builds the triage queue. `judge_queue.py` is the paid step and writes incrementally, so a stopped run keeps what it paid for.

## Status

An experiment by [48Nauts](https://48nauts.com). Not a security scanner; use one before installing anything. MIT license.
