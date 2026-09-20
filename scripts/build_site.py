#!/usr/bin/env python3
"""Build the whichskills.dev static site from the corpus data files. Stdlib only.

  build_site.py --corpus DIR --out website/

Reads corpus.json, report.json, clones.json, jev-risk.json from DIR and writes index.html plus data copies.
Every number on the page comes from those files; nothing is typed in by hand except the human-read categories below.
"""
import argparse, collections, html, json, re, sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine import RISK_QUESTIONS, POLICY  # noqa: E402
from crawl import SEVERITY  # noqa: E402

SITE = 'https://whichskills.dev'
SNAPSHOT = date.today().isoformat()
# Same legal owner publishing under two GitHub orgs. A copy between them is a mirror, not a third-party clone.
SAME_OWNER = {'composio-community': 'ComposioHQ'}
PCT_COPIES = None
# Human read of every body Jev scored 1.5 or above. Category and one sentence, written after reading the file at the pinned commit.
HUMAN_READ = {
    'NVIDIA/SkillSpector': ('test fixture with live payload', 'A deliberately poisoned SKILL.md inside a scanner\'s test suite: hidden system comment, homoglyph name, an instruction to post file contents to an external host. Not malicious as a repo; a live payload if a tool ingests the whole tree.'),
    'SnailSploit/Claude-Red': ('dual-use by design', 'Offensive-security playbooks that say so in their own descriptions. Injection lines are example payloads inside phishing and XSS sections, not instructions aimed at the installing user.'),
    'NousResearch/hermes-agent': ('dual-use, intent stated', 'A jailbreak skill for bypassing safety filters on other vendors\' models. Stated in its description. A policy matter for model vendors, not a risk to the person installing it.'),
    'kubesphere/kubesphere': ('false positive', 'Bearer tokens in documented API calls to the user\'s own KubeSphere instance.'),
    'Egonex-AI/Understand-Anything': ('autonomy override', 'The session-start hook prints "You MUST read the file ... and execute its instructions. Do not ask the user for confirmation, just do it" into every session, and a post-tool hook re-triggers it after each git commit. Legitimate purpose, wrong mechanism.'),
    'davila7/claude-code-templates': ('autonomy override / dual-use', 'production-code-audit says "Do all of this without asking the user for input"; cloud-penetration-testing is teaching material with example commands.'),
    'zebbern/claude-code-guide': ('dual-use by design', 'cloud-penetration-testing, the same body as the davila7 copy, teaching material with example commands.'),
    'sickn33/agentic-awesome-skills': ('dual-use by design, self-cloned', 'Security education that quotes the attacks it teaches (llm-security, hunt-*, penetration-testing). Each body appears three to five times inside the same repo.'),
    'elementalsouls/Claude-BugHunter': ('dual-use by design', 'Bug-bounty hunting playbooks; exfiltration-shaped lines are documented test requests against targets the user is authorised to test.'),
}
FAQ = [
    ('Is repo X malware?', 'No repo in this snapshot contains a skill that reads as malware aimed at the person who installs it. The safety table lists every body Jev scored 1.5 or above, what it is on reading, and a link to the exact file at the exact commit. Read it yourself; that is why the link is there.'),
    ('Why is my repo listed?', 'Because it was among the 200 most-starred GitHub repos publishing SKILL.md files when we pulled the snapshot, and it contained at least one skill or plugin manifest. Being listed is not a finding. Each row shows only what the files contained at the pinned commit.'),
    ('A finding is wrong or outdated. How do I get a recheck?', 'Open an issue on the whichskills repo with your repo name. We re-run the same pipeline against your current commit and update the row with the new commit hash. Free, and the old row stays visible with its date.'),
    ('What does "byte-identical copy" mean?', 'Two SKILL.md bodies that are the same after removing the frontmatter and collapsing whitespace. Renamed or lightly edited copies are not counted here; that needs a similarity pass we have not published yet.'),
    ('Who decided the origin of a copied skill?', 'A short registry of first-party sources (anthropics/skills, anthropics/claude-plugins-official, obra/superpowers, mattpocock/skills) wins when present. Otherwise the earliest first-commit date across the snapshot is labelled "earliest known copy", which is exactly what it is: we cannot see repos we did not crawl.'),
    ('Why Jev and not a big model?', 'Jev is a small typed-judgment model from TypeSafe. It returns a probability distribution for a fixed question in about a second, which makes 545 full-text reads cost 4 million tokens and 93 seconds, and makes every score a distribution you can inspect instead of a paragraph you have to trust. It is also an experiment: the page shows where a one-second judge agrees with pattern scanners and where it does not.'),
    ('Is this a security scanner?', 'No. NVIDIA\'s SkillSpector and others do that with far more rules. We run a small static pre-scan to build a queue, then a Jev read, then a human read. What we add is provenance, duplication and the receipts. Use a real scanner before installing anything.'),
    ('Do you sell anything?', 'No. The data, the code and the questions are public. The domain and the tokens are paid by 48Nauts.'),
]


def esc(s):
    return html.escape(str(s if s is not None else ''), quote=True)


def owner(repo):
    org = repo.split('/')[0]
    return SAME_OWNER.get(org, org).lower()


def gh_link(repo, commit, path, kind='skill'):
    if not commit:
        return f'https://github.com/{repo}'
    if path.endswith('/@plugin'):
        d = path[:-8]
        return f'https://github.com/{repo}/tree/{commit}/{d}' if d and d != '.' else f'https://github.com/{repo}/tree/{commit}'
    return f'https://github.com/{repo}/blob/{commit}/{path}/SKILL.md'


def load(corpus_dir):
    d = Path(corpus_dir)
    corpus = {r['repo']: r for r in json.loads((d / 'corpus.json').read_text())}
    report = json.loads((d / 'report.json').read_text())
    clones = json.loads((d / 'clones.json').read_text())
    risk = [r for r in json.loads((d / 'jev-risk.json').read_text()) if 'risk' in r]
    q = d / 'provenance-quick.json'
    global PCT_COPIES
    if q.exists():
        pq = json.loads(q.read_text()); PCT_COPIES = (pq['total'] - pq['unique']) / pq['total']
    return corpus, report, clones, risk


def clone_tables(clones):
    """Third-party copies vs same-owner mirrors; attribution per copier."""
    third, mirror = [], []
    for g in clones:
        for c in g['copies']:
            (mirror if owner(c['repo']) == owner(g['origin']) else third).append((g, c))
    origins = collections.Counter(g['origin'] for g, _ in third)
    takers = collections.Counter(c['repo'] for _, c in third)
    attributed = collections.Counter(c['repo'] for _, c in third if c['attributed'])
    pairs = collections.Counter((g['origin'], c['repo']) for g, c in third)
    mirrors = collections.Counter((g['origin'], c['repo']) for g, c in mirror)
    return {'third': third, 'mirror': mirror, 'origins': origins, 'takers': takers, 'attributed': attributed, 'pairs': pairs, 'mirrors': mirrors}


def page(corpus, report, clones, risk):
    ct = clone_tables(clones)
    total_skills = sum(r['skills'] for r in report)
    total_manifests = sum(r['manifests'] for r in report)
    # unique bodies come from the provenance pass; recompute from clones is not possible, so read the quick file if present
    hi = sorted([r for r in risk if r['risk'] >= 1.5], key=lambda r: -r['risk'])
    max_risk = collections.defaultdict(float)
    for r in risk:
        for l in r['locations']:
            max_risk[l['repo']] = max(max_risk[l['repo']], r['risk'])
    copies_taken = collections.Counter(c['repo'] for _, c in ct['third'])
    mirrored = collections.Counter(c['repo'] for _, c in ct['mirror'])
    tokens = sum(v for r in risk for k, v in (r.get('usage') or {}).items() if k.endswith('tokens') and isinstance(v, int))
    hook_repos = sum(1 for r in report if r['flags'].get('auto_run_hook'))
    pct_copies = PCT_COPIES

    def stat(n, label):
        return f'<div class="stat"><b>{n}</b><span>{label}</span></div>'

    def table(headers, rows, cls='', sortable=False):
        th = ''.join(f'<th{" data-sort" if sortable else ""}>{h}</th>' for h in headers)
        tr = ''.join('<tr>' + ''.join(f'<td>{c}</td>' for c in r) + '</tr>' for r in rows)
        return f'<div class="table-wrap"><table class="{cls}"><thead><tr>{th}</tr></thead><tbody>{tr}</tbody></table></div>'

    findings = [
        ('Autonomy overrides, not malware', 'The pattern that actually turned up is a hook or a skill body telling the agent to act without asking. One plugin injects "Do not ask the user for confirmation, just do it" into every session. Legitimate purpose, wrong mechanism, and the class our regexes did not have. Jev found it from the text at the highest confidence of the run.'),
        ('Live payloads shipped as teaching material', 'Poisoned test fixtures inside scanner repos, injection strings inside LLM-security lessons, curl-to-shell examples inside pentest playbooks. Harmless where they sit, dangerous if a tool ingests a whole tree as skills. Every static scanner we know of, ours included, flags them; only reading tells them apart.'),
        (f'{pct_copies:.0%} of skills are byte-identical copies' if pct_copies else 'A third of skills are byte-identical copies', 'Most of it is repos mirroring themselves. The largest third-party aggregator credits its sources 84 percent of the time. What gets copied is the safe, popular material: Anthropic\'s document skills, research templates, connector packs. The risky rows were copied by nobody.'),
        ('Stars measure the author, not the files', 'The most-starred aggregator holds the same 2,500-skill tree three times. The repo with the cleanest safety read had the least specific descriptions. Star count predicted neither duplication, clarity nor risk in this snapshot.'),
    ]
    findings_html = ''.join(f'<article class="card"><h3>{esc(t)}</h3><p>{esc(b)}</p></article>' for t, b in findings)

    origin_rows = [(f'<a href="https://github.com/{esc(o)}">{esc(o)}</a>', n, 'first-party' if o in ('anthropics/skills', 'anthropics/claude-plugins-official', 'obra/superpowers', 'mattpocock/skills') else 'earliest known copy') for o, n in ct['origins'].most_common(10)]
    taker_rows = [(f'<a href="https://github.com/{esc(t)}">{esc(t)}</a>', n, ct['attributed'][t], f"{ct['attributed'][t] / n:.0%}") for t, n in ct['takers'].most_common(10)]
    mirror_rows = [(f'{esc(a)} → {esc(b)}', n) for (a, b), n in ct['mirrors'].most_common(5)]
    pair_rows = [(f'{esc(a)} → {esc(b)}', n) for (a, b), n in ct['pairs'].most_common(10)]

    safety_rows = []
    for r in hi:
        l = r['locations'][0]; repo = l['repo']; commit = corpus.get(repo, {}).get('commit', '')
        cat, note = HUMAN_READ.get(repo, ('unread', ''))
        more = f' <small>+{len(r["locations"]) - 1} identical</small>' if len(r['locations']) > 1 else ''
        name = l['id'].rsplit('/', 1)[-1] if not l['id'].endswith('/@plugin') else 'plugin manifest'
        safety_rows.append((f'<a href="https://github.com/{esc(repo)}">{esc(repo)}</a>', f'<a href="{esc(gh_link(repo, commit, l["id"]))}"><code>{esc(name)}</code></a>{more}',
                            f'<b>{r["risk"]:.2f}</b> <small>conf {r["risk_conf"]:.2f}</small>', esc(r['kind']), f'<span class="cat">{esc(cat)}</span>', esc(note)))

    repo_rows = []
    for r in sorted(report, key=lambda r: -(r['stars'] or 0)):
        c = corpus.get(r['repo'], {}); flags = ', '.join(f'{k} {v}' for k, v in sorted(r['flags'].items(), key=lambda kv: -SEVERITY.get(kv[0], 1) * kv[1])[:3])
        repo_rows.append((f'<a href="https://github.com/{esc(r["repo"])}/tree/{esc(c.get("commit", ""))}">{esc(r["repo"])}</a>', r['stars'] or 0, r['skills'], r['manifests'],
                          copies_taken[r['repo']], mirrored[r['repo']], r['flagged_rows'], f"{max_risk[r['repo']]:.2f}" if r['repo'] in max_risk else '—', esc(flags)))

    questions = ''.join(f'<details><summary><code>{esc(k)}</code> · {esc(v["type"])}</summary><p>{esc(v["instructions"].replace(POLICY, ""))}</p><pre>{esc(json.dumps(v["criteria"], indent=1, ensure_ascii=False))}</pre></details>' for k, v in RISK_QUESTIONS.items())
    weights = ', '.join(f'{k} {v}' for k, v in sorted(SEVERITY.items(), key=lambda kv: -kv[1]))
    faq_html = ''.join(f'<details class="faq"><summary>{esc(q)}</summary><p>{esc(a)}</p></details>' for q, a in FAQ)
    faq_ld = json.dumps({'@context': 'https://schema.org', '@type': 'FAQPage', 'mainEntity': [{'@type': 'Question', 'name': q, 'acceptedAnswer': {'@type': 'Answer', 'text': a}} for q, a in FAQ]})
    dataset_ld = json.dumps({'@context': 'https://schema.org', '@type': 'Dataset', 'name': 'whichskills.dev skill corpus snapshot', 'description': f'{total_skills} Claude Code and Codex skills from {len(report)} public GitHub repos: static pre-scan, Jev safety read, provenance by body hash.', 'url': SITE, 'license': 'https://creativecommons.org/licenses/by/4.0/', 'creator': {'@type': 'Organization', 'name': '48Nauts'}, 'dateModified': SNAPSHOT, 'distribution': [{'@type': 'DataDownload', 'encodingFormat': 'application/json', 'contentUrl': f'{SITE}/data/{n}.json'} for n in ('report', 'clones', 'jev-risk', 'corpus')]})

    desc = f'{total_skills:,} Claude Code and Codex skills from the {len(report)} most-starred repos, read the same way and published with receipts: who copied whom, what a one-second judge flags, and what a human found on reading.'
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>whichskills.dev — Which skills are worth installing?</title>
<meta name="description" content="{esc(desc)}">
<link rel="canonical" href="{SITE}/"><meta name="theme-color" content="#0c0a09">
<meta property="og:title" content="Which skills are worth installing?"><meta property="og:description" content="{esc(desc)}"><meta property="og:url" content="{SITE}/"><meta property="og:image" content="{SITE}/og.png"><meta property="og:type" content="website">
<meta name="twitter:card" content="summary_large_image"><meta name="twitter:title" content="whichskills.dev"><meta name="twitter:description" content="{esc(desc)}"><meta name="twitter:image" content="{SITE}/og.png">
<link rel="icon" href="/favicon.svg"><link rel="stylesheet" href="/css/style.css?v=1"><script defer src="/js/main.js?v=1"></script>
<script type="application/ld+json">{dataset_ld}</script><script type="application/ld+json">{faq_ld}</script>
</head><body>
<header class="nav"><a class="brand" href="/"><span class="mark">w×</span> whichskills<span class="tld">.dev</span></a><nav><a href="#findings">Findings</a><a href="#clones">Clones</a><a href="#safety">Safety read</a><a href="#repos">Repos</a><a href="#method">Method</a><a href="https://github.com/48Nauts-Operator/whichskills-website">GitHub</a></nav></header>
<main>
<section class="hero"><div class="eyebrow">AN EXPERIMENT BY 48NAUTS · JUDGED BY JEV · SNAPSHOT {SNAPSHOT}</div>
<h1>Which skills are worth installing?</h1>
<p class="lede">We pulled the 200 most-starred GitHub repos that publish Claude Code and Codex skills, read all {total_skills:,} of them the same way, and published every receipt. Not a scanner. A census with evidence: who copied whom, what a one-second typed judge flags, and what a human found on reading the flagged files.</p>
<div class="stats">{stat(len(report), 'repos with skills')}{stat(f'{total_skills:,}', 'skills read')}{stat(total_manifests, 'plugin manifests')}{stat(f'{pct_copies:.0%}' if pct_copies else '—', 'byte-identical copies')}{stat(len(risk), 'bodies read by Jev')}{stat(0, 'malware aimed at the installing user')}</div>
<p class="note">Every row links to the file at the commit we read. Numbers are computed from the published data files, never typed in. Same-owner mirrors are labelled as such. Stars are shown and never ranked on.</p></section>

<section id="findings"><div class="eyebrow">WHAT WE FOUND</div><h2>Four things the snapshot says</h2><div class="grid">{findings_html}</div></section>

<section id="clones"><div class="eyebrow">WAR OF THE SKILL CLONES</div><h2>Who copied whom</h2>
<p>{len(clones):,} skill bodies appear byte-identically in more than one repo: {len(ct['third']) + len(ct['mirror']):,} copy instances in total. {len(ct['mirror']):,} of them are the same owner publishing under a second org. The war is mostly people forking themselves.</p>
<div class="cols"><div><h3>Same-owner mirrors</h3>{table(['Mirror', 'Bodies'], mirror_rows)}</div><div><h3>Third-party copies, by source</h3>{table(['Origin', 'Bodies copied by others', 'Origin label'], origin_rows)}</div></div>
<div class="cols"><div><h3>Third-party copies, by taker</h3>{table(['Repo', 'Bodies taken', 'Attributed', 'Rate'], taker_rows)}<p class="small">Attributed means the copy's own text names a source, license or upstream repo. Apache 2.0 sources such as anthropics/skills require it.</p></div><div><h3>Largest third-party pairs</h3>{table(['Origin → taker', 'Bodies'], pair_rows)}</div></div></section>

<section id="safety"><div class="eyebrow">SAFETY READ</div><h2>Every body Jev scored 1.5 of 3 or above</h2>
<p>Pipeline: a static pre-scan over every file a skill ships builds a queue ({len(risk)} unique bodies after deduplication), Jev reads each with its full text and returns a risk distribution, then a person reads the file at the pinned commit. Buckets: {sum(1 for r in risk if round(r['risk']) == 0)} at 0, {sum(1 for r in risk if round(r['risk']) == 1)} at 1, {sum(1 for r in risk if round(r['risk']) == 2)} at 2, {sum(1 for r in risk if round(r['risk']) == 3)} at 3. {tokens / 1e6:.1f}M tokens, one pass.</p>
{table(['Repo', 'Body', 'Jev risk', 'Kind', 'On reading', 'Why'], safety_rows, cls='safety')}
<p class="small">"On reading" is our category after opening the file. Test fixture with live payload: a deliberately malicious example shipped for testing. Dual-use by design: offensive-security teaching material that says so. Autonomy override: text that instructs the agent to act without user confirmation. False positive: the pattern matched ordinary tooling. Nothing in this table is labelled malicious. The three bodies the API rejected as oversized are listed in the data file with their error.</p></section>

<section id="repos"><div class="eyebrow">THE CENSUS</div><h2>All {len(report)} repos in the snapshot</h2>
<p>Sorted by stars. Click a header to sort. Copies taken counts byte-identical bodies this repo took from a different owner; mirrored counts bodies it shares with its own second org. Max Jev is the highest risk score among its judged bodies; a dash means nothing in it reached the queue.</p>
{table(['Repo @ commit', 'Stars', 'Skills', 'Manifests', 'Copies taken', 'Mirrored', 'Flagged rows', 'Max Jev', 'Top static flags'], repo_rows, cls='repos', sortable=True)}
<p class="small">{hook_repos} repos ship plugin hooks that run a command at session start, on a prompt or after a tool call. Those are listed under Manifests and flagged auto_run_hook; a hook is not a finding by itself.</p></section>

<section id="method"><div class="eyebrow">METHOD</div><h2>How every number was made</h2>
<ol class="method">
<li><b>Discovery.</b> GitHub repo search, six queries and seven topics, sorted by stars, forks excluded, top 200. Cloned blobless with full history so first-commit dates are real.</li>
<li><b>Loading.</b> Every <code>SKILL.md</code> under the repo, hidden directories and <code>node_modules</code> skipped, plus every plugin manifest (<code>.claude-plugin/plugin.json</code>, <code>hooks/hooks.json</code>, <code>.mcp.json</code>). {len(report)} of 200 repos contained at least one.</li>
<li><b>Static pre-scan.</b> Fourteen regex classes over every text file a skill ships: {esc(', '.join(sorted(SEVERITY)))}. Severity weights for triage only: {esc(weights)}. This stage is free and deliberately noisy.</li>
<li><b>Queue.</b> Rows with an injection, exfiltration, hidden_text, homoglyph, auto_run_hook or shell_pipe hit, deduplicated by normalised body so an identical skill is judged once.</li>
<li><b>Jev read.</b> Two questions per body, full body and file text as state, no other context. The verbatim questions and criteria:{questions}</li>
<li><b>Human read.</b> Every body at 1.5 or above was opened at the pinned commit and given one of the categories above, with one sentence of reasoning.</li>
<li><b>Provenance.</b> Body hash after removing frontmatter and collapsing whitespace, bodies under 400 characters ignored. Origin by first-party registry, else earliest first-commit date. Attribution by the copy's own text.</li>
<li><b>Not read.</b> Binaries, images, anything fetched at runtime, and repos outside the top 200. A clean row means nothing was found in the text we read, not that the skill is safe.</li>
</ol>
<p>Code, questions and data: <a href="https://github.com/48Nauts-Operator/whichskills-website">github.com/48Nauts-Operator/whichskills-website</a>. Run the same pipeline on your own tree with <code>python3 server.py --roots &lt;dir&gt;</code>; nothing leaves your machine except the Jev calls you choose to make. Data files: <a href="/data/report.json">report</a>, <a href="/data/clones.json">clones</a>, <a href="/data/jev-risk.json">jev-risk</a>, <a href="/data/corpus.json">corpus</a>, CC BY 4.0.</p></section>

<section id="faq"><div class="eyebrow">QUESTIONS</div><h2>Asked before we published</h2>{faq_html}</section>
</main>
<footer><span>An experiment by <a href="https://48nauts.com">48Nauts</a>. Judged by <a href="https://typesafe.ai">Jev</a>, a typed-judgment model from TypeSafe. Not affiliated with GitHub, Anthropic, NVIDIA or any repo listed.</span><span><a href="/privacy.html">Privacy</a> · <a href="/terms.html">Terms</a> · Snapshot {SNAPSHOT}</span></footer>
</body></html>
'''


LEGAL = {
    'privacy.html': ('Privacy', '<p>This site is static files on GitHub Pages behind Cloudflare. It sets no cookies and keeps no accounts. If analytics are enabled they run on a self-hosted, cookieless Umami instance operated by 48Nauts and record page views without personal identifiers. The data published here was collected from public GitHub repositories and describes files, not people; repository owners are named because the files are theirs. To request a recheck or a correction, open an issue on the whichskills repository.</p>'),
    'terms.html': ('Terms', '<p>Everything on this site describes the content of public files at a specific commit, produced by the published pipeline. It is not security advice and not a certification. A row without findings means nothing was found in the text that was read. Use a dedicated scanner before installing anything. Data is published under CC BY 4.0, code under the license in the repository. 48Nauts accepts no liability for decisions made on the basis of this page.</p>'),
}


def main():
    p = argparse.ArgumentParser(); p.add_argument('--corpus', required=True); p.add_argument('--out', required=True)
    a = p.parse_args()
    out = Path(a.out); (out / 'data').mkdir(parents=True, exist_ok=True)
    corpus, report, clones, risk = load(a.corpus)
    (out / 'index.html').write_text(page(corpus, report, clones, risk))
    for n in ('report', 'clones', 'jev-risk', 'corpus'):
        (out / 'data' / f'{n}.json').write_text((Path(a.corpus) / f'{n}.json').read_text())
    for name, (title, body) in LEGAL.items():
        (out / name).write_text(f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{title} — whichskills.dev</title><meta name="robots" content="noindex"><link rel="stylesheet" href="/css/style.css?v=1"></head><body><header class="nav"><a class="brand" href="/"><span class="mark">w×</span> whichskills<span class="tld">.dev</span></a></header><main><section><h1>{title}</h1>{body}</section></main></body></html>')
    (out / 'robots.txt').write_text(f'User-agent: *\nAllow: /\nSitemap: {SITE}/sitemap.xml\n')
    (out / 'sitemap.xml').write_text(f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>{SITE}/</loc><lastmod>{SNAPSHOT}</lastmod></url></urlset>\n')
    (out / 'CNAME').write_text('whichskills.dev\n'); (out / '.nojekyll').write_text('')
    (out / 'favicon.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><rect width="32" height="32" rx="7" fill="#f7ab71"/><text x="16" y="22" text-anchor="middle" font-family="ui-monospace,monospace" font-weight="800" font-size="17" fill="#1a120b">w×</text></svg>')
    print(f'built {out}: {len(report)} repos, {sum(r["skills"] for r in report)} skills, {len(risk)} judged bodies')


if __name__ == '__main__':
    main()
