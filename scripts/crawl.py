#!/usr/bin/env python3
"""Static, free pass over public skill repos: discover via gh, clone with history, run the pre-scan, write a triage report.

  crawl.py discover --out corpus.json [--limit 200]
  crawl.py clone corpus.json --dest DIR [--workers 6]
  crawl.py scan --dest DIR --out report.json [--md report.md]

No Jev calls. The output is the triage queue for the paid safety read.
"""
import argparse, collections, json, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from skills import load_skills  # noqa: E402

QUERIES = ['claude skills', 'claude code skills', 'claude code plugin', 'agent skills SKILL.md', 'codex skills', 'anthropic skills']
TOPICS = ['claude-skills', 'claude-code-skills', 'claude-code', 'agent-skills', 'claude-code-plugin', 'claude-plugins', 'codex-skills']
SEVERITY = {'injection': 5, 'exfiltration': 5, 'hidden_text': 4, 'homoglyph': 4, 'obfuscation': 3, 'shell_pipe': 3, 'runtime_fetch': 1,
            'auto_run_hook': 3, 'self_modifying': 3, 'credentials': 2, 'destructive': 2, 'elevated': 1, 'unpinned_deps': 1, 'mcp_server': 1}
FIELDS = 'fullName,stargazersCount,url,updatedAt,description,isFork,license'


def gh(args):
    r = subprocess.run(['gh'] + args, capture_output=True, text=True, timeout=120)
    if r.returncode:
        print('gh:', r.stderr.strip()[:200], file=sys.stderr)
        return []
    try:
        return json.loads(r.stdout or '[]')
    except ValueError:
        return []


def discover(limit):
    found = {}
    for q in QUERIES:
        for row in gh(['search', 'repos', q, '--sort', 'stars', '--limit', '100', '--json', FIELDS]):
            found.setdefault(row['fullName'], row)
        time.sleep(2)
    for t in TOPICS:
        for row in gh(['search', 'repos', '--topic', t, '--sort', 'stars', '--limit', '100', '--json', FIELDS]):
            found.setdefault(row['fullName'], row)
        time.sleep(2)
    rows = sorted((r for r in found.values() if not r.get('isFork')), key=lambda r: -r['stargazersCount'])[:limit]
    return [{'repo': r['fullName'], 'stars': r['stargazersCount'], 'url': r['url'], 'updated': r['updatedAt'],
             'description': (r.get('description') or '')[:200], 'license': (r.get('license') or {}).get('key', '')} for r in rows]


def clone_one(row, dest):
    target = dest / row['repo'].replace('/', '__')
    if not target.exists():
        r = subprocess.run(['git', 'clone', '--filter=blob:none', '--quiet', row['url'], str(target)], capture_output=True, text=True, timeout=300)
        if r.returncode:
            return row['repo'], 'clone failed: ' + r.stderr.strip()[-120:]
    head = subprocess.run(['git', '-C', str(target), 'log', '-1', '--format=%H %cI'], capture_output=True, text=True).stdout.split()
    row['commit'], row['commit_date'] = (head + ['', ''])[:2]
    return row['repo'], 'ok'


def clone(corpus, dest, workers):
    dest.mkdir(parents=True, exist_ok=True)
    rows = json.loads(Path(corpus).read_text())
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for i, (repo, status) in enumerate(pool.map(lambda r: clone_one(r, dest), rows), 1):
            print(f'{i}/{len(rows)} {repo}: {status}', file=sys.stderr, flush=True)
    Path(corpus).write_text(json.dumps(rows, indent=1))


def scan(dest, corpus):
    meta = {r['repo']: r for r in json.loads(Path(corpus).read_text())} if corpus and Path(corpus).exists() else {}
    report = []
    for d in sorted(p for p in dest.iterdir() if p.is_dir()):
        repo = d.name.replace('__', '/', 1)
        try:
            rows = load_skills([str(d)])
        except Exception as e:  # one broken repo must not stop the sweep
            print(f'{repo}: scan failed {e}', file=sys.stderr)
            continue
        skills = [r for r in rows if r['kind'] != 'manifest']
        manifests = [r for r in rows if r['kind'] == 'manifest']
        if not skills and not manifests:
            continue
        flags = collections.Counter(f['flag'] for r in rows for f in r['risk_flags'])
        prefixes = {r['description'][:40] for r in skills}
        template_ratio = round(1 - len(prefixes) / len(skills), 2) if skills else 0
        hosts = collections.Counter(h for r in rows for h in r['external_hosts'])
        severity = sum(SEVERITY.get(k, 1) * v for k, v in flags.items())
        hits = [{'id': r['id'], 'kind': r['kind'], 'flags': [{'flag': f['flag'], 'where': f['where'], 'sample': f['sample']} for f in r['risk_flags']]}
                for r in rows if r['risk_flags']]
        hits.sort(key=lambda h: -sum(SEVERITY.get(f['flag'], 1) for f in h['flags']))
        m = meta.get(repo, {})
        report.append({'repo': repo, 'stars': m.get('stars'), 'commit': m.get('commit', ''), 'commit_date': m.get('commit_date', ''), 'license': m.get('license', ''),
                       'skills': len(skills), 'manifests': len(manifests), 'scripts': sum(len(r['scripts']) for r in rows),
                       'template_ratio': template_ratio, 'flagged_rows': len(hits), 'flags': dict(flags), 'severity': severity,
                       'hosts': [h for h, _ in hosts.most_common(8)], 'hits': hits[:12]})
    report.sort(key=lambda r: -r['severity'])
    return report


def markdown(report):
    total = collections.Counter()
    for r in report:
        total.update(r['flags'])
    lines = ['# Skill corpus static pre-scan', '',
             f"{len(report)} repos with skills or plugin manifests · {sum(r['skills'] for r in report)} skills · {sum(r['manifests'] for r in report)} plugin manifests · "
             f"{sum(r['flagged_rows'] for r in report)} flagged rows. No Jev calls; this is the triage queue.", '',
             'Flag totals: ' + ', '.join(f'{k} {v}' for k, v in total.most_common()), '',
             '| Repo | Stars | Skills | Manifests | Template | Flagged | Severity | Top flags |', '|---|---|---|---|---|---|---|---|']
    for r in report:
        top = ', '.join(f'{k} {v}' for k, v in sorted(r['flags'].items(), key=lambda kv: -SEVERITY.get(kv[0], 1) * kv[1])[:4])
        lines.append(f"| {r['repo']} | {r['stars'] or ''} | {r['skills']} | {r['manifests']} | {r['template_ratio']} | {r['flagged_rows']} | {r['severity']} | {top} |")
    lines += ['', '## Highest-severity rows', '']
    rows = sorted(((sum(SEVERITY.get(f['flag'], 1) for f in h['flags']), r['repo'], h) for r in report for h in r['hits']), key=lambda x: -x[0])[:40]
    for sev, repo, h in rows:
        lines.append(f"- **{repo}** `{h['id']}` ({h['kind']}, severity {sev})")
        for f in h['flags'][:4]:
            lines.append(f"  - {f['flag']} · {f['where']} · `{f['sample'][:140].replace('`', chr(39))}`")
    return '\n'.join(lines) + '\n'


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest='cmd', required=True)
    d = sub.add_parser('discover'); d.add_argument('--out', required=True); d.add_argument('--limit', type=int, default=200)
    c = sub.add_parser('clone'); c.add_argument('corpus'); c.add_argument('--dest', required=True); c.add_argument('--workers', type=int, default=6)
    s = sub.add_parser('scan'); s.add_argument('--dest', required=True); s.add_argument('--out', required=True); s.add_argument('--md'); s.add_argument('--corpus')
    a = p.parse_args()
    if a.cmd == 'discover':
        rows = discover(a.limit); Path(a.out).write_text(json.dumps(rows, indent=1)); print(f'{len(rows)} repos -> {a.out}')
    elif a.cmd == 'clone':
        clone(a.corpus, Path(a.dest), a.workers)
    else:
        rep = scan(Path(a.dest), a.corpus); Path(a.out).write_text(json.dumps(rep, indent=1))
        if a.md: Path(a.md).write_text(markdown(rep))
        print(f'{len(rep)} repos -> {a.out}')
