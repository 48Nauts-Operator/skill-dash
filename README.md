# Skills × Jev

Local dashboard over the Claude skill tree. Same shell as the inbox × jev dashboard, rows are skills instead of emails. It answers one question per skill: keep, rewrite, merge or delete.

## Open

http://localhost:3345

A user LaunchAgent `ch.naut.skilldash` keeps it running and starts it on login. Binds to 127.0.0.1 only.

## What it shows

- Every `SKILL.md` under `~/.claude/skills` plus the skills of enabled plugins (from `~/.claude/settings.json`). Name, description, source (own / imported / plugin), body size, scripts, install date.
- Evidence from `~/.claude/projects/**/*.jsonl`: Skill-tool invocations with the last date, slash-command mentions, and mentions of the skill's own script filenames. Skill names alone are not counted, because the skill list is in every session prompt. Files are cached by mtime and size; a rescan only re-reads what changed.
- Pairwise overlap from the `skill-audit` script, run from Settings; each row shows its strongest partner.
- Jev judgments, editable on the Judges page: usefulness 0 to 3, redundancy (CLAUDE.md / hook / other skill / tooling / none), description clarity 0 to 3, recommended action. Each skill is judged with its description, body excerpt, evidence, your global CLAUDE.md excerpt and hook config as state.
- Your decision per skill with a note, persisted in SQLite, exported as JSON. Nothing on disk is edited or deleted by the app.

## Review any skill repo

```sh
python3 server.py --port 3346 --roots ~/path/to/some-skills-repo
```

Loads every `SKILL.md` under the roots (hidden dirs and `node_modules` skipped), keyed by path so repeated names stay distinct. Transcript evidence is off (it is not evidence for someone else's tree) and the Judges page defaults to the content-only preset: usefulness on content alone, a duplicate-of question fed by the top three overlap partners, clarity, action. Run the overlap audit from Settings first; it walks the roots recursively and runs in parallel. Each root set gets its own SQLite file under `.data/roots-<hash>/`.

## Run from source

```sh
python3 server.py --port 3345
python3 -m unittest discover -s tests -v
```

Jev credential: `TYPESAFE_API_KEY` or macOS Keychain service `xnaut`, account `plugin/typesafe/TYPESAFE_API_KEY`. Model `jev-1.13.0`, override with `TYPESAFE_MODEL`.

Ticket 48NAUTS-7. Design: `work:Development/48Nauts/features/2026-09-20_Skill-Dash-Design.md`.
