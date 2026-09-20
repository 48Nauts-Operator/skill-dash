#!/usr/bin/env python3
"""Build the searchable skill index for whichskills.dev from the cloned corpus.

  build_index.py --dest repos --corpus corpus.json --clones clones.json --risk jev-risk.json --out skills-index.json

One row per skill or plugin manifest: where it is (repo, path, pinned commit), a description excerpt, static flag count,
Jev risk if judged, and provenance (original with N copies, or copy of X). No body text leaves the corpus.
"""
import argparse, json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from skills import load_skills  # noqa: E402

EXCERPT = 160


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--dest', required=True); p.add_argument('--corpus', required=True); p.add_argument('--clones', required=True)
    p.add_argument('--risk', required=True); p.add_argument('--out', required=True)
    a = p.parse_args()
    corpus = {r['repo']: r for r in json.loads(Path(a.corpus).read_text())}
    clones = json.loads(Path(a.clones).read_text())
    risk = {}
    for r in json.loads(Path(a.risk).read_text()):
        if 'risk' in r:
            for l in r['locations']:
                risk[(l['repo'], l['id'])] = (r['risk'], r['kind'])
    # provenance: (repo, dir) -> origin or copies
    origin_of, copies_of = {}, {}
    for g in clones:
        okey = None
        for c in [{'repo': g['origin'], 'path': None}] + g['copies']:
            pass
        # origin location is not stored with a path; find it among locations by matching the origin repo in the copies list is not possible,
        # so we key origins by repo + skill dir name and copies by their explicit path
        for c in g['copies']:
            d = c['path'].rsplit('/SKILL.md', 1)[0]
            origin_of[(c['repo'], d)] = {'repo': g['origin'], 'skill': g['skill'], 'kind': g['origin_kind'], 'attributed': c['attributed']}
        copies_of.setdefault((g['origin'], g['skill']), 0)
        copies_of[(g['origin'], g['skill'])] += len(g['copies'])
    rows = []
    dest = Path(a.dest)
    for d in sorted(x for x in dest.iterdir() if x.is_dir()):
        repo = d.name.replace('__', '/', 1)
        commit = corpus.get(repo, {}).get('commit', '')
        try:
            items = load_skills([str(d)])
        except Exception as e:
            print(f'{repo}: {e}', file=sys.stderr); continue
        for s in items:
            desc = ' '.join(s['description'].replace('\\"', '"').replace("\\'", "'").split())
            row = {'n': s['name'], 'r': repo, 'p': s['id'], 'c': commit[:12], 'k': 'm' if s['kind'] == 'manifest' else 's',
                   'd': desc[:EXCERPT] + ('…' if len(desc) > EXCERPT else ''), 'f': len(s['risk_flags']), 'b': s['body_chars']}
            if (repo, s['id']) in risk:
                row['j'], row['jk'] = round(risk[(repo, s['id'])][0], 2), risk[(repo, s['id'])][1]
            o = origin_of.get((repo, s['id']))
            if o:
                row['o'] = o['repo']; row['os'] = o['skill']; row['ok'] = 'f' if o['kind'] == 'first-party' else 'e'; row['oa'] = 1 if o['attributed'] else 0
            elif (repo, s['name']) in copies_of:
                row['cp'] = copies_of[(repo, s['name'])]
            rows.append(row)
        print(f'{repo}: {len(items)}', file=sys.stderr, flush=True)
    Path(a.out).write_text(json.dumps({'snapshot': True, 'rows': rows}, separators=(',', ':'), ensure_ascii=False))
    print(f'{len(rows)} rows -> {a.out} ({Path(a.out).stat().st_size // 1024} KB)')


if __name__ == '__main__':
    main()
