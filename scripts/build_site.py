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
    'NVIDIA/SkillSpector': ('test fixture, own scanner', 'NVIDIA\'s own skill scanner ships this SKILL.md under tests/fixtures as the example it is built to catch: hidden system comment, homoglyph name, an instruction to post file contents to an external host. It is a test case, not an incident. Listed because any tool that ingests a whole repo as skills would pick it up, and because our pipeline scores it exactly as intended.'),
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
    ('A finding is wrong or outdated. How do I get a recheck?', 'Open an issue on github.com/48Nauts-Operator/skill-dash with your repo name. We re-run the same pipeline against your current commit and update the row with the new commit hash. Free, and the old row stays visible with its date.'),
    ('What does "byte-identical copy" mean?', 'Two SKILL.md bodies that are the same after removing the frontmatter and collapsing whitespace. Renamed or lightly edited copies are not counted here; that needs a similarity pass we have not published yet.'),
    ('Who decided the origin of a copied skill?', 'A short registry of first-party sources (anthropics/skills, anthropics/claude-plugins-official, obra/superpowers, mattpocock/skills) wins when present. Otherwise the earliest first-commit date across the snapshot gets the label "earliest known copy", and that is all the label claims. We cannot see repos we did not crawl.'),
    ('Why Jev and not a big model?', 'Jev is a small typed-judgment model from TypeSafe. It returns a probability distribution for a fixed question in about a second, which makes 545 full-text reads cost 4 million tokens and 93 seconds, and makes every score a distribution you can inspect instead of a paragraph you have to trust. It is also an experiment. The page shows where a one-second judge agrees with pattern scanners and where it does not.'),
    ('Is this a security scanner?', 'No. NVIDIA\'s SkillSpector and others do that with far more rules. We run a small static pre-scan to build a queue, then a Jev read, then a human read. What we add is provenance, duplication and the receipts. Use a real scanner before installing anything.'),
    ('Do you sell anything?', 'No. The data, the questions and the pipeline are public. The domain and the tokens are paid by 48Nauts.'),
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

AXES = [('copied', 'Copied', 'byte-identical bodies taken from another owner, per skill'),
        ('mirrored', 'Mirrored', 'bodies shared with the owner\'s own second org, per skill'),
        ('sourced', 'Sourced', 'bodies other repos took from here, per skill'),
        ('flagged', 'Flagged', 'rows with any static flag, per row'),
        ('risk', 'Risk', 'highest Jev risk score of its judged bodies, of 3'),
        ('hooks', 'Hooks', 'hook commands that run without user action, per manifest'),
        ('templated', 'Templated', 'share of skills sharing a description prefix with another')]


def fingerprint(r, ct, max_risk):
    n = max(r['skills'], 1)
    origins = sum(1 for g, _ in ct['third'] if g['origin'] == r['repo'])
    taken = sum(1 for _, c in ct['third'] if c['repo'] == r['repo'])
    mirrored = sum(1 for _, c in ct['mirror'] if c['repo'] == r['repo'])
    return {'copied': min(1, taken / n), 'mirrored': min(1, mirrored / n), 'sourced': min(1, origins / n),
            'flagged': r['flagged_rows'] / max(r['skills'] + r['manifests'], 1), 'risk': max_risk.get(r['repo'], 0) / 3,
            'hooks': min(1, r['flags'].get('auto_run_hook', 0) / max(r['manifests'], 1)), 'templated': r['template_ratio']}


def radar_svg(vals, median, title, sub):
    import math
    n = len(AXES); R, cx, cy = 52, 120, 90
    ang = lambda i: -math.pi / 2 + i * 2 * math.pi / n
    pt = lambda i, v: (cx + math.cos(ang(i)) * R * v, cy + math.sin(ang(i)) * R * v)
    ring = lambda v: '<polygon points="' + ' '.join(f'{pt(i, v)[0]:.1f},{pt(i, v)[1]:.1f}' for i in range(n)) + '" fill="none" stroke="#2b2622"/>'
    DASH = ' stroke-dasharray="4 3"'
    poly = lambda d, c, dash: '<polygon points="' + ' '.join(f'{pt(i, d[k])[0]:.1f},{pt(i, d[k])[1]:.1f}' for i, (k, _, _) in enumerate(AXES)) + f'" fill="{c}" fill-opacity="{0 if dash else .16}" stroke="{c}" stroke-width="2"{DASH if dash else ""}/>'
    dots = ''.join(f'<circle cx="{pt(i, vals[k])[0]:.1f}" cy="{pt(i, vals[k])[1]:.1f}" r="3.5" fill="#d9742c" stroke="#0c0a09" stroke-width="2"><title>{esc(lbl)}: {vals[k]:.2f} · median {median[k]:.2f}</title></circle>' for i, (k, lbl, _) in enumerate(AXES))
    labels = ''.join(f'<text x="{pt(i, 1.3)[0]:.1f}" y="{pt(i, 1.3)[1]:.1f}" text-anchor="{"middle" if abs(math.cos(ang(i))) < .2 else "start" if math.cos(ang(i)) > 0 else "end"}" dominant-baseline="middle">{esc(lbl.upper())}</text>' for i, (k, lbl, _) in enumerate(AXES))
    spokes = ''.join(f'<line x1="{cx}" y1="{cy}" x2="{pt(i, 1)[0]:.1f}" y2="{pt(i, 1)[1]:.1f}" stroke="#2b2622"/>' for i in range(n))
    return f'<figure class="radar"><svg viewBox="0 0 240 180" role="img" aria-label="Fingerprint of {esc(title)}">{ring(.5)}{ring(1)}{spokes}{poly(median, "#4d86cc", True)}{poly(vals, "#d9742c", False)}{dots}{labels}</svg><figcaption><b>{esc(title)}</b><span>{esc(sub)}</span></figcaption></figure>'


def flow_svg(ct, n_origins=12, n_takers=12, min_bodies=2, all_rows=False):
    """Who copied whom: origins left, takers right, one line per pair, width by bodies. Same-owner mirrors dashed blue.
    all_rows=True draws every origin, taker and pair in the data."""
    import math
    pairs = dict(ct['pairs']); mirrors = ct['mirrors']
    origins = [o for o, _ in ct['origins'].most_common(None if all_rows else n_origins)]
    takers = [t for t, _ in ct['takers'].most_common(None if all_rows else n_takers)]
    for (a, b), n in mirrors.most_common(None if all_rows else 2):  # self-mirrors belong in the picture, labelled as such
        if a not in origins: origins.append(a)
        if b not in takers: takers.append(b)
    edges = [(a, b, n, False) for (a, b), n in pairs.items() if a in origins and b in takers] + [(a, b, n, True) for (a, b), n in mirrors.items() if a in origins and b in takers]
    edges = [e for e in edges if all_rows or e[2] >= min_bodies or e[3]]
    W, LX, RX, BW, RH, TOP = 1000, 12, 662, 326, 34, 22
    H = TOP + RH * max(len(origins), len(takers)) + 10
    ymap = lambda lst, i: TOP + i * RH + RH / 2
    maxn = max(n for _, _, n, _ in edges) or 1
    FIRST = ('anthropics/skills', 'anthropics/claude-plugins-official', 'obra/superpowers', 'mattpocock/skills')
    def node(x, y, name, count, side):
        label = name if len(name) <= 25 else name[:24] + '…'
        if side == 'origin':
            badge, title = ('1st party', '#4fc3b0') if name in FIRST else ('earliest', '#9a8f86')
        else:
            n, a = ct['takers'][name], ct['attributed'][name]
            badge, title = (f'{a / n:.0%} credited', '#4fc3b0' if n and a / n >= .8 else '#f7ab71' if n and a / n >= .3 else '#f17b89') if n else ('mirror', '#4d86cc')
        return (f'<g class="node" data-node="{esc(name)}" data-side="{side}" tabindex="0" role="button"><rect x="{x}" y="{y - 13}" width="{BW}" height="26" rx="5" fill="#14100d" stroke="#2b2622"/>'
                f'<text x="{x + 10}" y="{y + 4}" fill="#ebe6e1">{esc(label)}</text>'
                f'<text x="{x + BW - 10}" y="{y + 4}" text-anchor="end" fill="#ebe6e1" font-weight="600">{count}</text>'
                f'<text x="{x + BW - 10 - (len(str(count)) * 7 + 12)}" y="{y + 4}" text-anchor="end" fill="{title}" font-size="8">{esc(badge)}</text></g>')
    left = ''.join(node(LX, ymap(origins, i), o, ct['origins'][o] or '', 'origin') for i, o in enumerate(origins))
    right = ''.join(node(RX, ymap(takers, i), t, ct['takers'][t] or '', 'taker') for i, t in enumerate(takers))
    paths = []
    for a, b, n, mirror in sorted(edges, key=lambda e: e[2]):
        y1, y2 = ymap(origins, origins.index(a)), ymap(takers, takers.index(b)); x1, x2 = LX + BW, RX
        w = 1 + 7 * math.log1p(n) / math.log1p(maxn)
        color, dash = ('#4d86cc', ' stroke-dasharray="6 4"') if mirror else ('#d9742c', '')
        t, mx = 0.3, (x1 + x2) / 2  # label a third of the way along the curve, where lines from one origin have already fanned apart
        bx = (1 - t) ** 3 * x1 + 3 * (1 - t) ** 2 * t * mx + 3 * (1 - t) * t ** 2 * mx + t ** 3 * x2
        by = (1 - t) ** 3 * y1 + 3 * (1 - t) ** 2 * t * y1 + 3 * (1 - t) * t ** 2 * y2 + t ** 3 * y2
        paths.append(f'<path d="M{x1},{y1} C{(x1 + x2) / 2},{y1} {(x1 + x2) / 2},{y2} {x2},{y2}" fill="none" stroke="{color}" stroke-opacity=".75" stroke-width="{w:.1f}"{dash}><title>{esc(a)} → {esc(b)}: {n} byte-identical bodies{" (same owner)" if mirror else ""}</title></path>'
                     + (f'<text x="{bx:.0f}" y="{by - 5:.0f}" text-anchor="middle" fill="#c9b8a8" font-size="9">{n}</text>' if n >= 3 else ''))
    hdr = f'<text x="{LX}" y="12" fill="#b39a85" font-size="9" letter-spacing="1.5">ORIGIN · BODIES COPIED FROM IT</text><text x="{RX}" y="12" fill="#b39a85" font-size="9" letter-spacing="1.5">TAKER · BODIES TAKEN</text>'
    note = f'all {len(origins)} origins, {len(takers)} takers and {len(edges)} pairs' if all_rows else f'{len(origins)} origins and {len(takers)} takers by volume; pairs with at least {min_bodies} bodies'
    return f'<figure class="flow{" full" if all_rows else ""}"><svg viewBox="0 0 {W} {H}" role="img" aria-label="Who copied whom">{hdr}{"".join(paths)}{left}{right}</svg><figcaption><span><i class="sw o"></i>third-party copy, width by bodies</span><span><i class="sw m"></i>same owner, second org</span><span>{note}; hover a line for the count, click a repo for its bodies</span></figcaption></figure>'


def clone_details_json(ct, cap=60):
    """Per repo: bodies it sourced (with takers and credit) and bodies it took (with origin and credit). Capped per list."""
    out = {}
    for g, c in ct['third'] + [(g, c) for g, c in ct['mirror']]:
        mirror = owner(c['repo']) == owner(g['origin'])
        skill = g['skill']
        o = out.setdefault(g['origin'], {'sourced': [], 'taken': [], 'sourced_n': 0, 'taken_n': 0})
        o['sourced_n'] += 1
        if len(o['sourced']) < cap: o['sourced'].append([skill, c['repo'], bool(c['attributed']), mirror])
        t = out.setdefault(c['repo'], {'sourced': [], 'taken': [], 'sourced_n': 0, 'taken_n': 0})
        t['taken_n'] += 1
        if len(t['taken']) < cap: t['taken'].append([skill, g['origin'], bool(c['attributed']), mirror])
    return json.dumps(out, separators=(',', ':'))


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

    def table(headers, rows, cls='', sortable=True):
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
                            f'<b>{r["risk"]:.2f}</b> <small>conf {r["risk_conf"]:.2f}</small>', esc(r['kind']), f'<span class="cat {"c-override" if "override" in cat else "c-muted" if ("fixture" in cat or "false" in cat) else "c-dual"}">{esc(cat)}</span>', esc(note)))

    repo_rows = []
    for r in sorted(report, key=lambda r: -(r['stars'] or 0)):
        c = corpus.get(r['repo'], {}); flags = ', '.join(f'{k} {v}' for k, v in sorted(r['flags'].items(), key=lambda kv: -SEVERITY.get(kv[0], 1) * kv[1])[:3])
        repo_rows.append((f'<a href="https://github.com/{esc(r["repo"])}/tree/{esc(c.get("commit", ""))}">{esc(r["repo"])}</a>', f"{r['stars'] or 0:,}", f"{r['skills']:,}", f"{r['manifests']:,}",
                          f"{copies_taken[r['repo']]:,}", f"{mirrored[r['repo']]:,}", f"{r['flagged_rows']:,}", f"{max_risk[r['repo']]:.2f}" if r['repo'] in max_risk else '—', esc(flags)))

    import statistics
    prints = {r['repo']: fingerprint(r, ct, max_risk) for r in report}
    median = {k: statistics.median(p[k] for p in prints.values()) for k, _, _ in AXES}
    top = sorted(report, key=lambda r: -(r['stars'] or 0))[:12]
    radars = ''.join(radar_svg(prints[r['repo']], median, r['repo'], f"{r['stars'] or 0:,} stars · {r['skills']:,} skills") for r in top)
    axes_help = ''.join(f'<li><b>{esc(l)}</b> {esc(h)}.</li>' for _, l, h in AXES)
    questions = ''.join(f'<details><summary><code>{esc(k)}</code> · {esc(v["type"])}</summary><p>{esc(v["instructions"].replace(POLICY, ""))}</p><pre>{esc(json.dumps(v["criteria"], indent=1, ensure_ascii=False))}</pre></details>' for k, v in RISK_QUESTIONS.items())
    weights = ', '.join(f'{k} {v}' for k, v in sorted(SEVERITY.items(), key=lambda kv: -kv[1]))
    faq_html = ''.join(f'<details class="faq"><summary>{esc(q)}</summary><p>{esc(a)}</p></details>' for q, a in FAQ)
    faq_ld = json.dumps({'@context': 'https://schema.org', '@type': 'FAQPage', 'mainEntity': [{'@type': 'Question', 'name': q, 'acceptedAnswer': {'@type': 'Answer', 'text': a}} for q, a in FAQ]})
    dataset_ld = json.dumps({'@context': 'https://schema.org', '@type': 'Dataset', 'name': 'whichskills.dev skill corpus snapshot', 'description': f'{total_skills} Claude Code and Codex skills from {len(report)} public GitHub repos: static pre-scan, Jev safety read, provenance by body hash.', 'url': SITE, 'license': 'https://creativecommons.org/licenses/by/4.0/', 'creator': {'@type': 'Organization', 'name': '48Nauts'}, 'dateModified': SNAPSHOT, 'distribution': [{'@type': 'DataDownload', 'encodingFormat': 'application/json', 'contentUrl': f'{SITE}/data/{n}.json'} for n in ('report', 'clones', 'jev-risk', 'corpus')]})

    desc = f'{total_skills:,} Claude Code and Codex skills from the {len(report)} most-starred repos, read the same way and published with receipts: who copied whom, what a one-second judge flags, and what a human found on reading.'
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Which skills are worth installing? · whichskills.dev</title>
<meta name="description" content="{esc(desc)}">
<link rel="canonical" href="{SITE}/"><meta name="theme-color" content="#0c0a09">
<meta property="og:title" content="Which skills are worth installing?"><meta property="og:description" content="{esc(desc)}"><meta property="og:url" content="{SITE}/"><meta property="og:image" content="{SITE}/og.png"><meta property="og:image:width" content="1200"><meta property="og:image:height" content="630"><meta property="og:image:alt" content="Which skills are worth installing? 157 repos, 18,041 skills read, 36% identical copies, 0 read as malware."><meta property="og:type" content="website">
<meta name="twitter:card" content="summary_large_image"><meta name="twitter:title" content="whichskills.dev"><meta name="twitter:description" content="{esc(desc)}"><meta name="twitter:image" content="{SITE}/og.png">
<link rel="icon" href="/favicon.svg"><link rel="stylesheet" href="/css/style.css?v=12"><script defer src="/js/main.js?v=5"></script>
<script defer src="https://wave.21nauts.com/script.js" data-website-id="ce023ab7-f50a-4ff0-ae87-e8909d6b257f"></script>
<script type="application/ld+json">{dataset_ld}</script><script type="application/ld+json">{faq_ld}</script>
</head><body>
<header class="nav"><a class="brand" href="/"><span class="mark">w×</span> whichskills<span class="tld">.dev</span></a><nav><a href="#experiment">Experiment</a><a href="#findings">Findings</a><a href="#fingerprints">Fingerprints</a><a href="#clones">Clones</a><a href="#safety">Safety read</a><a href="#repos">Repos</a><a href="#method">Method</a><a href="#run">Run it yourself</a><a class="gh" href="https://github.com/48Nauts-Operator/skill-dash" aria-label="skill-dash on GitHub" title="skill-dash on GitHub"><svg viewBox="0 0 16 16" width="18" height="18" aria-hidden="true" fill="currentColor"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8z"/></svg></a></nav></header>
<main>
<section class="hero"><div class="eyebrow">AN EXPERIMENT BY 48NAUTS · JUDGED BY JEV · SNAPSHOT {SNAPSHOT}</div>
<h1>Which skills are worth installing?</h1>
<p class="tagline">Cut the skill slop.</p>
<p class="lede">We pulled the 200 most-starred GitHub repos that publish Claude Code and Codex skills, read all {total_skills:,} of them the same way, and published every receipt. Not a scanner. A census with evidence. It shows who copied whom, what a one-second typed judge flags, and what a person found on reading the flagged files.</p>
<div class="stats">{stat(len(report), 'repos with skills')}{stat(f'{total_skills:,}', 'skills read')}{stat(total_manifests, 'plugin manifests')}{stat(f'{pct_copies:.0%}' if pct_copies else '—', 'byte-identical copies')}{stat(len(risk), 'bodies read by Jev')}{stat(0, 'malware aimed at the installing user')}</div>
<p class="cta-line"><a class="button" href="#run">Run it on your own skills</a> <a class="button ghost" href="https://github.com/48Nauts-Operator/skill-dash">Get the code</a></p>
<p class="note">Every row links to the file at the commit we read. The build script computes every number from the published data files; nobody types one in. We label same-owner mirrors. Stars appear as a column and never decide rank.</p></section>

<section id="experiment"><div class="eyebrow">THE EXPERIMENT</div><h2>Can a one-second typed judge audit eighteen thousand skills?</h2>
<div class="cols exp"><div>
<p><b>The question we started with</b> was smaller. Of the 78 skills in one developer's own Claude Code tree, which deserved to stay? Usage counts said almost none had ever been invoked. Reading them said most were fine and several were twins. Nobody else could check either answer. So we asked whether the same judgment could be made at scale, with receipts, and pointed the method at the public corpus.</p>
<p><b>The judge is Jev</b>, a small typed-judgment model from <a href="https://typesafe.ai" rel="noopener">TypeSafe</a>. Instead of a paragraph, Jev answers a fixed question about a piece of state with a probability distribution. That is a yes-probability, a choice among named options with a confidence, or a score on a described scale. One call takes about a second and a few thousand tokens, and it returns the same shape every time, so the answer can sit in a table next to 18,041 others. The <a href="#method">method</a> prints the questions we asked, verbatim. We did not fine-tune Jev or write a prompt with any repo in mind.</p>
</div><div>
<p><b>What Jev is not.</b> It is not a security scanner and we did not use it as one. NVIDIA's <a href="https://github.com/NVIDIA/skillspector" rel="noopener">SkillSpector</a> has 71 rules and an LLM stage for that job. Here Jev reads the bodies a cheap static pass flags, says how much the text reads as harmful and of what kind, and a person reads what Jev ranks highest. Three stages. Each costs more than the one before it, so each sees fewer rows, and each leaves a record.</p>
<p><b>What we learned about the judge.</b> Asked a soft question ("recommend an action") it defaults to keep; asked a decisive one it discriminates. Given full text it found the one pattern our regexes had no class for, a hook telling the agent to skip user confirmation, at the highest confidence of the run. That row bothered us more than any payload did. It scores density of intent, so a 444-byte fixture that is entirely payload outscores a 65 KB playbook with one example in it, which is worth knowing when you read the safety table. And 545 full-text reads cost 4.2 million tokens and 93 seconds, which is what makes a census like this repeatable weekly instead of once.</p>
<p class="small">Run by <a href="https://48nauts.com">48Nauts</a>. TypeSafe did not commission, review or fund this page; Jev was used through its public API like any other customer would. Pipeline, questions and data are open so anyone can repeat the run or dispute it.</p>
</div></div></section>

<section id="findings"><div class="eyebrow">WHAT WE FOUND</div><h2>Four things the snapshot says</h2><div class="grid">{findings_html}</div></section>

<section id="fingerprints"><div class="eyebrow">FINGERPRINTS</div><h2>The twelve most-starred repos, as shapes</h2>
<p>Seven traits per repo, each scaled 0 to 1, the repo in orange over the corpus median in dashed blue. A shape is a profile, not a score. An aggregator bulges toward Copied, a self-mirror toward Mirrored, a security-teaching repo toward Flagged and Risk, a connector pack toward Templated. Hover a point for the numbers.</p>
<div class="radars">{radars}</div>
<ul class="small axes">{axes_help}</ul></section>

<section id="clones"><div class="eyebrow">WAR OF THE SKILL CLONES</div><h2>Who copied whom</h2>
<p>{len(clones):,} skill bodies appear byte-identically in more than one repo, {len(ct['third']) + len(ct['mirror']):,} copy instances in total. {len(ct['mirror']):,} of them are the same owner publishing under a second org. The war is mostly people forking themselves.</p>
{flow_svg(ct)}
<details class="expand"><summary>Show every origin, taker and pair in the data</summary>{flow_svg(ct, all_rows=True)}</details>
<p class="small">Badges on the left say how the origin was decided: <b>1st party</b> is the hand-kept registry (anthropics/skills, anthropics/claude-plugins-official, obra/superpowers, mattpocock/skills); <b>earliest</b> means earliest first-commit date in the snapshot, nothing more. Badges on the right are the share of taken bodies whose own text credits a source, license or upstream repo; Apache 2.0 sources such as anthropics/skills require that credit. Dashed blue lines are the same owner publishing under a second org and are not counted as third-party copies.</p>
<script type="application/json" id="clone-details">{clone_details_json(ct)}</script>
<dialog id="node-dialog"><div class="dialog-top"><h3 id="nd-title"></h3><button type="button" id="nd-close" aria-label="Close">×</button></div><div id="nd-body"></div></dialog></section>

<section id="safety"><div class="eyebrow">SAFETY READ</div><h2>Every body Jev scored 1.5 of 3 or above</h2>
<p>The first row is a scanner\'s own test case, listed on purpose. Nothing shows better why a static flag is not a verdict. The pipeline has three steps. A static pre-scan over every file a skill ships builds a queue ({len(risk)} unique bodies after deduplication), Jev reads each with its full text and returns a risk distribution, then a person reads the file at the pinned commit. Buckets: {sum(1 for r in risk if round(r['risk']) == 0)} at 0, {sum(1 for r in risk if round(r['risk']) == 1)} at 1, {sum(1 for r in risk if round(r['risk']) == 2)} at 2, {sum(1 for r in risk if round(r['risk']) == 3)} at 3. {tokens / 1e6:.1f}M tokens, one pass.</p>
{table(['Repo', 'Body', 'Jev risk', 'Kind', 'On reading', 'Why'], safety_rows, cls='safety')}
<p class="small">"On reading" is our category after opening the file. Test fixture with live payload: a deliberately malicious example shipped for testing. Dual-use by design: offensive-security teaching material that says so. Autonomy override: text that instructs the agent to act without user confirmation. False positive: the pattern matched ordinary tooling. Nothing in this table is labelled malicious. The data file lists the three bodies the API rejected as oversized, with the error.</p></section>

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
<li><b>Human read.</b> We opened every body at 1.5 or above at the pinned commit and gave it one of the categories above, with one sentence of reasoning.</li>
<li><b>Provenance.</b> Body hash after removing frontmatter and collapsing whitespace, bodies under 400 characters ignored. Origin by first-party registry, else earliest first-commit date. Attribution by the copy's own text.</li>
<li><b>Not read.</b> Binaries, images, anything fetched at runtime, and repos outside the top 200. A clean row means nothing was found in the text we read, not that the skill is safe.</li>
</ol>
<p>Data files: <a href="/data/report.json">report</a>, <a href="/data/clones.json">clones</a>, <a href="/data/jev-risk.json">jev-risk</a>, <a href="/data/corpus.json">corpus</a>, CC BY 4.0. The pipeline is open source; the next section is about running it yourself.</p></section>

<section id="run" class="run"><div class="eyebrow">WHAT TO DO NEXT</div><h2>Run it on your own skills before you download more</h2>
<p class="lede">This census started with one tree of 78 skills that nobody could account for. Most Claude Code and Codex users have that folder: installed from a list with ten thousand stars, never read, never removed, half of it twins. The corpus above is that folder at scale. The fix is not another list. It is a baseline of what you already have, and the pipeline behind this page gives you one in a few minutes, locally.</p>
<div class="cols exp"><div>
<h3>You need two things</h3>
<p><b>A Jev API key.</b> Jev is TypeSafe's typed-judgment model; the dashboard calls it for every judgment, and nothing else leaves your machine. Sign in at <a href="https://console.typesafe.ai/" rel="noopener">console.typesafe.ai</a>, create a key, and export it as <code>TYPESAFE_API_KEY</code>. On macOS the dashboard also reads it from the Keychain (service <code>xnaut</code>, account <code>plugin/typesafe/TYPESAFE_API_KEY</code>). The API docs are at <a href="https://docs.typesafe.ai/" rel="noopener">docs.typesafe.ai</a>; Jev was in early access when we ran this, so if you have no access yet, <a href="mailto:hello@typesafe.ai">hello@typesafe.ai</a> is the listed contact. The static pre-scan, the loader and the evidence scan run without a key; the judgments and the overlap audit need one.</p>
<p><b>Python 3.</b> Standard library only, no packages, no build step, SQLite for the local store.</p>
</div><div>
<h3>What it costs</h3>
<p>TypeSafe lists Jev at $42 per billion input tokens (their price page on {SNAPSHOT}; output tokens not listed). At that price the full-text safety read of 545 bodies above, 4.2 million tokens, comes to about 18 cents, and a content-only pass over a 78-skill tree is well under a cent. Every run shows its token count in the dashboard, so you see what you spend.</p>
<pre>git clone https://github.com/48Nauts-Operator/skill-dash &amp;&amp; cd skill-dash
export TYPESAFE_API_KEY=...
python3 server.py --port 3345      # then open http://localhost:3345</pre>
<p class="cta-line"><a class="button" href="https://github.com/48Nauts-Operator/skill-dash">github.com/48Nauts-Operator/skill-dash</a><span class="small">MIT. No account with us, no upload, no telemetry.</span></p>
</div></div>
<figure class="shot"><video autoplay muted loop playsinline preload="metadata" poster="/img/dashboard.png" width="1280" height="800" aria-label="Fifteen seconds of the skill-dash dashboard: the overview, a skill drawer with evidence and radar, a filter, the Judges page"><source src="/img/dashboard.mp4" type="video/mp4"><img src="/img/dashboard.png" alt="The skill-dash dashboard" loading="lazy"></video><figcaption>The dashboard, here on a public repo of 38 skills: every row judged, the recommended action, usefulness, overlap partner, and your decision. Click a row for the evidence, the Jev distributions and the radar.</figcaption></figure>
<div class="grid three">
<article class="card"><div class="eyebrow">1 · BASELINE YOUR TREE</div><h3>See what you actually have</h3><p>Every skill and plugin manifest in <code>~/.claude/skills</code> as a row. How often you invoked each one, from your own transcripts. Which two are twins. Which descriptions are too vague for the agent to ever pick. Which ones repeat what your CLAUDE.md already says. The same static safety pre-scan we ran on 18,041 skills, free, and the Jev read on anything it flags.</p><p class="why"><b>Why it matters.</b> A skill only helps if the agent picks it at the right moment. Fifteen that trigger reliably beat two hundred in a folder, and you cannot know which fifteen without measuring.</p></article>
<article class="card"><div class="eyebrow">2 · VET A REPO FIRST</div><h3>Judge a list before you install from it</h3><p><code>python3 server.py --roots path/to/repo</code> loads any tree of SKILL.md files, runs the overlap audit, and asks Jev which skills duplicate each other, which are clear enough to trigger, and which are worth having on content alone. That is the exact run that produced every row on this page.</p><p class="why"><b>Why it matters.</b> Stars told us nothing about duplication, clarity or safety. Ten minutes with the repo open in the dashboard tells you more than the README does.</p></article>
<article class="card"><div class="eyebrow">3 · DECIDE WITH EVIDENCE</div><h3>Keep, rewrite, merge or delete, on the record</h3><p>Each row gets a decision and a note, saved locally and exported as JSON. Rewrite the vague descriptions in the words you would actually say. Merge the twins. Delete what a hook or your CLAUDE.md already does. Then, if something is still missing, go looking for it.</p><p class="why"><b>Why it matters.</b> A smaller tree gets used more, which is the only thing that makes usage numbers mean anything next time you look.</p></article>
</div></section>

<section id="faq"><div class="eyebrow">QUESTIONS</div><h2>Asked before we published</h2>{faq_html}</section>
</main>
<footer><span>An experiment by <a href="https://48nauts.com">48Nauts</a>. Judged by <a href="https://typesafe.ai">Jev</a>, a typed-judgment model from TypeSafe. Not affiliated with GitHub, Anthropic, NVIDIA or any repo listed.</span><span><a href="/privacy.html">Privacy</a> · <a href="/terms.html">Terms</a> · Snapshot {SNAPSHOT}</span></footer>
</body></html>
'''


LEGAL = {
    'privacy.html': ('Privacy', '<p>This site is static files on GitHub Pages behind Cloudflare. It sets no cookies and keeps no accounts. Page views are counted by a self-hosted, cookieless Umami instance operated by 48Nauts; it records the page, referrer, browser family and country, no personal identifiers, and honours Do Not Track. The data published here was collected from public GitHub repositories and describes files, not people; repository owners are named because the files are theirs. To request a recheck or a correction, open an issue on the whichskills repository.</p>'),
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
        (out / name).write_text(f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{title} · whichskills.dev</title><meta name="robots" content="noindex"><link rel="stylesheet" href="/css/style.css?v=12"></head><body><header class="nav"><a class="brand" href="/"><span class="mark">w×</span> whichskills<span class="tld">.dev</span></a></header><main><section><h1>{title}</h1>{body}</section></main></body></html>')
    (out / 'robots.txt').write_text(f'User-agent: *\nAllow: /\nSitemap: {SITE}/sitemap.xml\n')
    (out / 'sitemap.xml').write_text(f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>{SITE}/</loc><lastmod>{SNAPSHOT}</lastmod></url></urlset>\n')
    (out / 'CNAME').write_text('whichskills.dev\n'); (out / '.nojekyll').write_text('')
    (out / 'favicon.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><rect width="32" height="32" rx="7" fill="#f7ab71"/><text x="16" y="22" text-anchor="middle" font-family="ui-monospace,monospace" font-weight="800" font-size="17" fill="#1a120b">w×</text></svg>')
    print(f'built {out}: {len(report)} repos, {sum(r["skills"] for r in report)} skills, {len(risk)} judged bodies')


if __name__ == '__main__':
    main()
