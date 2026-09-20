"""Find skills for this tree: profile the user locally, cut the corpus to candidates, let Jev judge fit on full text."""
import hashlib
import json
import math
import re
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from engine import POLICY, judge
from skills import PROJECTS, risk_flags
HIGH = ('injection', 'exfiltration', 'hidden_text', 'homoglyph', 'shell_pipe', 'obfuscation')

INDEX_URL = 'https://whichskills.dev/data/skills-index.json'
UA = {'User-Agent': 'skill-dash/1.0 (+https://whichskills.dev)'}  # Cloudflare rejects the default Python agent
FIT_QUESTIONS = {
    'fit': {'type': 'score', 'instructions': POLICY +
            'Would this candidate skill fill a gap this user actually has? Judge from profile (their CLAUDE.md, the skills they already have and use, and any recent requests) against the candidate\'s description and body. A skill for a stack or task the profile never mentions is a 0 even if it is well written.',
            'criteria': ['No connection to what this user does or the stack they run.',
                         'Plausibly relevant, but nothing in the profile shows the need.',
                         'Matches a task or stack the profile shows, and does something the user\'s own skills do not.',
                         'Matches a repeated task or a stated rule in the profile, with a concrete procedure the user would run often.']},
    'covered': {'type': 'noul', 'instructions': POLICY + 'Does one of the user\'s own skills (profile.own_skills) already do the same job as this candidate? Yes means installing it would add a twin.'},
}
TOKEN = re.compile(r'[a-z][a-z0-9+#.-]{2,}')
STOP = set('the and for with that this from your you are use when user skill skills use using into over about into can will not any all one two what how run runs file files code'.split())


def toks(text):
    return [t for t in TOKEN.findall(text.lower()) if t not in STOP]


def recent_prompts(limit=60, chars=300):
    """The first user message of the most recent sessions. Local only; sent to Jev only when the user opts in."""
    out = []
    files = sorted((f for f in PROJECTS.rglob('*.jsonl')), key=lambda f: f.stat().st_mtime, reverse=True)[:limit]
    for f in files:
        try:
            with open(f, errors='replace') as fh:
                for line in fh:
                    if '"type":"user"' in line and '"content":"' in line:
                        m = re.search(r'"content":"((?:[^"\\]|\\.){10,})"', line)
                        if m and not m.group(1).startswith('<'):
                            out.append(m.group(1).encode().decode('unicode_escape', errors='ignore')[:chars]); break
        except OSError:
            continue
    return out


def profile(claude_md, own_skills, evidence, with_prompts=False):
    own = [{'name': s['id'], 'description': s['description'][:300], 'invocations': (evidence.get(s['id']) or {}).get('invocations', 0)} for s in own_skills]
    p = {'claude_md_excerpt': claude_md[:7000], 'own_skills': own, 'most_used': [o['name'] for o in sorted(own, key=lambda o: -o['invocations'])[:10] if o['invocations']]}
    if with_prompts:
        p['recent_requests'] = recent_prompts()
    return p


def load_index(data_dir):
    p = Path(data_dir) / 'skills-index.json'
    if not p.exists():
        with urllib.request.urlopen(urllib.request.Request(INDEX_URL, headers=UA), timeout=60) as r:
            p.write_bytes(r.read())
    return json.loads(p.read_text())['rows']


def candidates(rows, own_skills, prof, k=200):
    own_names = {s['name'].lower() for s in own_skills} | {s['id'].lower() for s in own_skills}
    own_hashes = {hashlib.sha256(re.sub(r'\s+', ' ', s.get('body_full', '')).strip().lower().encode()).hexdigest()[:16] for s in own_skills}
    pool = [r for r in rows if r['k'] == 's' and 'o' not in r and r['n'].lower() not in own_names and r.get('j', 0) < 1.5 and r.get('b', 0) >= 400]
    docs = [toks(r['n'].replace('-', ' ') + ' ' + r['d']) for r in pool]
    df = Counter(t for d in docs for t in set(d)); n = len(pool)
    ptext = prof['claude_md_excerpt'] + ' ' + ' '.join(o['description'] for o in prof['own_skills']) + ' ' + ' '.join(prof.get('recent_requests', []))
    q = Counter(toks(ptext))
    def score(d):
        c = Counter(d); s = 0.0
        for t, w in q.items():
            if t in c:
                s += math.log1p(w) * c[t] * math.log((n + 1) / (df[t] + 1))
        return s / math.sqrt(len(d) + 1)
    ranked = sorted(zip(pool, docs), key=lambda x: -score(x[1]))
    own_docs = [(o['name'], set(toks(o['name'].replace('-', ' ').replace(':', ' ') + ' ' + o['description']))) for o in prof['own_skills']]
    out, per_repo, seen_names = [], Counter(), set()
    for r, d in ranked:  # ponytail: cap per repo so one 7,000-skill aggregator cannot fill the whole list; one row per repo+name
        if per_repo[r['r']] >= 8 or (r['r'], r['n']) in seen_names: continue
        per_repo[r['r']] += 1; seen_names.add((r['r'], r['n']))
        c = Counter(d)
        r = dict(r, matched=[t for t, _ in sorted(((t, math.log1p(q[t]) * c[t] * math.log((n + 1) / (df[t] + 1))) for t in c if t in q), key=lambda x: -x[1])[:6]])
        ds = set(d); best = max(own_docs, key=lambda od: len(ds & od[1]) / (len(ds | od[1]) or 1), default=None)
        if best: r['closest_own'] = best[0]
        out.append(r)
        if len(out) >= k: break
    return out, len(pool), own_hashes


def fetch_body(r, cap=8000):
    url = f"https://raw.githubusercontent.com/{r['r']}/{r['c']}/{r['p']}/SKILL.md"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20) as resp:
            text = resp.read().decode('utf-8', errors='replace')
        m = re.match(r'---\n.*?\n---\n?', text, re.S)
        return (text[m.end():] if m else text).strip()[:cap]
    except Exception:
        return ''


def run(app, with_prompts=False, k=200, workers=4, progress=None, include_flagged=False):
    """Full pass. progress(done, total, stage) is called as it goes. Returns the result rows sorted by fit."""
    from engine import environment
    skills = app.store.skills()
    own = [s for s in skills if s['kind'] != 'manifest']
    env = environment(skills)
    prof = profile(env['claude_md_excerpt'], own, app.evidence, with_prompts)
    rows = load_index(app.data_dir)
    cands, pool_size, own_hashes = candidates(rows, own, prof, k)
    if progress: progress(0, len(cands), 'fetching')
    with ThreadPoolExecutor(max_workers=8) as pool:
        bodies = list(pool.map(fetch_body, cands))
    seen, deduped = {}, []
    for r, b in zip(cands, bodies):
        if not b: continue
        h = hashlib.sha256(re.sub(r'\s+', ' ', b).strip().lower().encode()).hexdigest()[:16]
        if h in own_hashes: continue
        if h in seen: seen[h]['dupes'] += 1; continue  # same body again, inside a repo or across the cut
        flags, _ = risk_flags({'SKILL.md': b})  # the same static pre-scan, on the file we are about to recommend
        classes = sorted({f['flag'] for f in flags})
        if any(c in HIGH for c in classes): continue
        if classes and not include_flagged: continue
        seen[h] = dict(r, body=b, dupes=0, flags=classes); deduped.append(seen[h])
    cands = deduped
    results, done = [], 0
    def one(r):
        skill = {'id': r['n'], 'kind': 'candidate', 'plugin': None, 'description': r['d'], 'body_excerpt': r['body'][:2500], 'scripts': [],
                 'imported_from': r['r'], 'disable_model_invocation': False, 'installed_at': ''}
        try:
            res = judge(skill, {}, {'claude_md_excerpt': '', 'session_hooks': '', 'other_skill_names': []}, app.key, FIT_QUESTIONS, [], extra={'profile': prof})
        except Exception as e:
            return dict(r, error=str(e)[:160])
        a = res['answers']
        return dict(r, fit=round(a['fit']['score'], 2), fit_conf=round(a['fit']['confidence'], 2), fit_legend=a['fit']['legend'], covered=round(a['covered']['noul'], 2), usage=res['usage'])
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for res in pool.map(one, cands):
            results.append(res); done += 1
            if progress: progress(done, len(cands), 'judging')
    for r in results:
        if r.get('fit') is not None: r['gap'] = round(r['fit'] * (1 - r['covered']), 2)  # fit discounted by the chance you already have it
    results.sort(key=lambda r: (-(r.get('gap') or -1), -(r.get('fit') or 0)))
    tokens = sum(v for r in results for kk, v in (r.get('usage') or {}).items() if kk.endswith('tokens') and isinstance(v, int))
    return {'results': [{kk: v for kk, v in r.items() if kk not in ('body', 'usage')} for r in results], 'pool': pool_size, 'candidates': len(cands),
            'with_prompts': with_prompts, 'include_flagged': include_flagged, 'tokens': tokens, 'profile_summary': {'own_skills': len(own), 'most_used': prof['most_used'], 'requests': len(prof.get('recent_requests', []))}}


def cluster(results, threshold=0.35):
    """Group scored candidates that do the same job. Head-based: a row joins a cluster only if its description resembles the
    cluster's best row directly (cosine over name and description tokens), so chains cannot pull unrelated jobs together."""
    scored = sorted((r for r in results if r.get('fit') is not None), key=lambda r: (-(r.get('gap') or 0), -(r.get('fit') or 0)))
    def vec(r):
        c = Counter(toks(r['n'].replace('-', ' ').replace('_', ' ') + ' ' + r['d']))
        norm = math.sqrt(sum(v * v for v in c.values())) or 1
        return {t: v / norm for t, v in c.items()}
    cos = lambda a, b: sum(v * b.get(t, 0) for t, v in a.items())
    heads = []
    for r in scored:
        v = vec(r)
        for h in heads:
            if cos(v, h['_vec']) >= threshold:
                h['alternatives'].append({'n': r['n'], 'r': r['r'], 'p': r['p'], 'c': r['c'], 'gap': r.get('gap'), 'fit': r.get('fit'), 'covered': r.get('covered')}); break
        else:
            heads.append(dict(r, _vec=v, alternatives=[]))
    for h in heads: del h['_vec']
    return heads
