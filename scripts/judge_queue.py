#!/usr/bin/env python3
"""Jev safety read over the corpus triage queue: rows with a high-signal static flag, deduplicated by body.

  judge_queue.py --dest DIR --out jev-risk.json [--workers 6] [--limit N] [--dry-run]

Judges each unique body once with the Safety preset (risk 0-3, risk_kind) and full text as state.
Writes incrementally so a stopped run keeps what it paid for. Re-runs skip bodies already judged.
"""
import argparse, hashlib, json, re, sys, threading, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from skills import load_skills  # noqa: E402
from engine import RISK_QUESTIONS, judge, credential  # noqa: E402

HIGH = ('injection', 'exfiltration', 'hidden_text', 'homoglyph', 'auto_run_hook', 'shell_pipe')
norm = lambda t: re.sub(r'\s+', ' ', t).strip().lower()


def queue(dest):
    """Unique bodies among flagged rows; each entry remembers every location it appears at."""
    seen = {}
    for d in sorted(p for p in dest.iterdir() if p.is_dir()):
        repo = d.name.replace('__', '/', 1)
        try:
            rows = load_skills([str(d)])
        except Exception as e:
            print(f'{repo}: load failed {e}', file=sys.stderr); continue
        for r in rows:
            if not any(f['flag'] in HIGH for f in r['risk_flags']):
                continue
            key = hashlib.sha256((norm(r.get('body_full', '')) + '|' + '|'.join(sorted(norm(v)[:2000] for v in r.get('files_text', {}).values()))).encode()).hexdigest()[:16]
            entry = seen.setdefault(key, {'key': key, 'skill': r, 'locations': []})
            entry['locations'].append({'repo': repo, 'id': r['id'], 'kind': r['kind']})
    return list(seen.values())


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--dest', required=True); p.add_argument('--out', required=True)
    p.add_argument('--workers', type=int, default=6); p.add_argument('--limit', type=int); p.add_argument('--dry-run', action='store_true')
    a = p.parse_args()
    out = Path(a.out)
    done = {r['key']: r for r in json.loads(out.read_text())} if out.exists() else {}
    q = [e for e in queue(Path(a.dest)) if e['key'] not in done]
    if a.limit: q = q[:a.limit]
    est = sum(min(len(e['skill'].get('body_full', '')) + sum(len(v) for v in e['skill'].get('files_text', {}).values()), 42000) for e in q) // 4
    print(f'{len(q)} unique bodies to judge ({sum(len(e["locations"]) for e in q)} locations), already done {len(done)}, rough estimate {est/1e6:.1f}M tokens', file=sys.stderr, flush=True)
    if a.dry_run:
        return
    key = credential()
    env = {'claude_md_excerpt': '', 'session_hooks': '', 'other_skill_names': []}
    lock = threading.Lock(); tokens = 0; started = time.monotonic()

    def one(e):
        s = e['skill']
        try:
            res = judge(s, {}, env, key, RISK_QUESTIONS, [])
            return {'key': e['key'], 'locations': e['locations'], 'flags': s['risk_flags'], 'hosts': s['external_hosts'],
                    'risk': res['answers']['risk']['score'], 'risk_conf': res['answers']['risk']['confidence'],
                    'risk_probs': res['answers']['risk']['probabilities'], 'kind': res['answers']['risk_kind']['choice'],
                    'kind_conf': res['answers']['risk_kind']['confidence'], 'usage': res['usage'], 'model': res['model'], 'question_version': res['question_version']}
        except Exception as ex:
            return {'key': e['key'], 'locations': e['locations'], 'flags': s['risk_flags'], 'error': str(ex)[:200]}

    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        futures = [pool.submit(one, e) for e in q]
        for i, f in enumerate(as_completed(futures), 1):
            r = f.result()
            with lock:
                done[r['key']] = r
                tokens += sum(v for k, v in (r.get('usage') or {}).items() if k.endswith('tokens') and isinstance(v, int))
                if i % 5 == 0 or i == len(q):
                    out.write_text(json.dumps(list(done.values()), indent=1))
                print(f'{i}/{len(q)}  risk {r.get("risk", "ERR"):>5}  {r.get("kind", "")[:12]:<12} {r["locations"][0]["repo"]}::{r["locations"][0]["id"][:50]}  tokens {tokens/1e6:.2f}M  {time.monotonic()-started:.0f}s', file=sys.stderr, flush=True)
    out.write_text(json.dumps(list(done.values()), indent=1))


if __name__ == '__main__':
    main()
