#!/usr/bin/env python3
"""Local dashboard: Jev judgments over the Claude skill tree. Stdlib only."""
import argparse
import json
import mimetypes
import hashlib
import secrets
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from engine import QUESTIONS, CONTENT_QUESTIONS, PRESETS, POLICY, prepare_questions, judge, credential, environment
from skills import load_skills, evidence
from store import Store, DECISIONS, stamp

ROOT = Path(__file__).resolve().parent
AUDIT = Path.home() / '.claude/skills/skill-audit/scripts/audit.py'
ACTIVE = ('running', 'paused', 'stopping')


class Application:
    def __init__(self, path, key=None, roots=None):
        self.roots = [str(Path(r).expanduser().resolve()) for r in (roots or [])]
        self.store = Store(path)
        self.data_dir = Path(path).parent
        self.key = credential() if key is None else key
        self.lock = threading.RLock()
        self.job = None
        self.paused = self.cancelled = False
        self.evidence, self.scan = {}, {'status': 'idle'}
        self.overlap = {'status': 'idle'}
        self.rescan()

    # --- skills + evidence -------------------------------------------------
    def rescan(self):
        with self.lock:
            if self.scan.get('status') == 'running':
                raise ValueError('A scan is already running')
            self.scan = {'status': 'running', 'started_at': stamp()}
        skills = load_skills(self.roots)
        self.store.sync(skills)
        if self.roots:
            with self.lock:
                self.scan = {'status': 'skipped', 'reason': 'custom roots: transcripts are not evidence for another tree'}
            return
        threading.Thread(target=self._scan, args=(skills,), daemon=True).start()

    def _scan(self, skills):
        try:
            per_skill, meta = evidence(self.store, skills)
            with self.lock:
                self.evidence, self.scan = per_skill, {'status': 'done', **meta}
        except Exception as e:
            with self.lock:
                self.scan = {'status': 'error', 'error': str(e)[:240]}

    def overlap_pairs(self):
        p = self.data_dir / 'overlap.json'
        try:
            return json.loads(p.read_text()) if p.exists() else {}
        except ValueError:
            return {}

    def top_overlap(self, pairs, n=3):
        """name -> up to n partners, strongest first."""
        partners = {}
        for k, score in pairs.items():
            a, b = k.split('|', 1)
            partners.setdefault(a, []).append({'with': b, 'score': round(score, 3)})
            partners.setdefault(b, []).append({'with': a, 'score': round(score, 3)})
        return {k: sorted(v, key=lambda o: -o['score'])[:n] for k, v in partners.items()}

    def run_overlap(self):
        with self.lock:
            if self.overlap.get('status') == 'running':
                raise ValueError('Overlap audit already running')
            if not AUDIT.exists():
                raise ValueError('skill-audit script not found')
            self.overlap = {'status': 'running', 'started_at': stamp()}
        threading.Thread(target=self._overlap, daemon=True).start()

    def _overlap(self):
        # ponytail: audit.py pairs one directory at a time; several roots are audited separately and merged, cross-root pairs are not scored
        merged, errors = {}, []
        for i, root in enumerate(self.roots or [None]):
            out = self.data_dir / f'overlap-{i}.md'
            cmd = [sys.executable, str(AUDIT)] + (['--dir', root, '--recursive'] if root else []) + ['overlap', '--out', str(out)]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=7200)
            j = out.with_suffix('.json')
            if r.returncode == 0 and j.exists():
                merged.update(json.loads(j.read_text()))
            else:
                errors.append((r.stderr or 'audit failed')[-200:])
        if merged:
            (self.data_dir / 'overlap.json').write_text(json.dumps(merged, indent=1))
        with self.lock:
            self.overlap = {'status': 'done', 'finished_at': stamp()} if merged and not errors else {'status': 'error', 'error': ' | '.join(errors)[-240:] or 'no pairs'}

    def state(self):
        with self.lock:
            pairs = self.overlap_pairs()
            top = self.top_overlap(pairs)
            okey = (lambda s: s['id']) if self.roots else (lambda s: s['name'])
            skills = [{**s, 'evidence': self.evidence.get(s['id'], None), 'overlap': (top.get(okey(s)) or [None])[0],
                       'overlaps': top.get(okey(s), [])} for s in self.store.skills()]
            return {'skills': skills, 'runs': self.store.runs(), 'job': dict(self.job) if self.job else None,
                    'scan': dict(self.scan), 'overlap': {**self.overlap, 'pairs': len(pairs)}, 'roots': self.roots,
                    'config': {'jev_available': bool(self.key), 'questions': CONTENT_QUESTIONS if self.roots else QUESTIONS,
                               'usage_questions': QUESTIONS, 'content_questions': CONTENT_QUESTIONS, 'presets': PRESETS,
                               'policy': POLICY, 'max_workers': 6, 'decisions': list(DECISIONS)}}

    # --- judgments -------------------------------------------------------------
    def start(self, payload):
        if not self.key:
            raise ValueError('Jev credential is not configured on the server')
        questions = prepare_questions(payload.get('questions', CONTENT_QUESTIONS if self.roots else QUESTIONS))
        workers, limit = payload.get('workers', 3), payload.get('limit', 200)
        if isinstance(workers, bool) or not isinstance(workers, int) or not 1 <= workers <= 6: raise ValueError('Workers must be 1–6')
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500: raise ValueError('Batch limit must be 1–500')
        ids = payload.get('ids', [])
        if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids): raise ValueError('Invalid selection')
        with self.lock:
            if self.job and self.job['status'] in ACTIVE: raise ValueError('A batch is already running')
            if self.scan.get('status') == 'running': raise ValueError('Evidence scan still running; wait a moment')
            if not (self.data_dir / 'overlap.json').exists() and any(q.get('criteria', {}).get('partner_1') for q in questions.values() if isinstance(q.get('criteria'), dict)):
                raise ValueError('The duplicate judgment needs overlap pairs. Run the overlap audit in Settings first.')
            skills = self.store.skills()
            selected = [s for s in skills if s['id'] in ids] if ids else [s for s in skills if not s['result'] or payload.get('reprocess') is True]
            selected = selected[:limit]
            if not selected: raise ValueError('Nothing pending. Select rows to judge them again.')
            self.paused = self.cancelled = False
            self.job = {'id': secrets.token_hex(6), 'provider': 'jev', 'status': 'running', 'total': len(selected),
                        'completed': 0, 'succeeded': 0, 'failed': 0, 'started_at': stamp(), 'elapsed_s': 0, 'workers': workers,
                        'questions': questions, 'latencies': [], 'input_tokens': 0, 'output_tokens': 0}
            env = environment(skills)
            top = self.top_overlap(self.overlap_pairs())
            threading.Thread(target=self._run, args=(selected, workers, questions, env, top), daemon=True).start()
            return dict(self.job)

    def _run(self, skills, workers, questions, env, top):
        started = time.monotonic(); next_index = 0
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {}
            while next_index < len(skills) or futures:
                with self.lock:
                    stopped, paused = self.cancelled, self.paused
                    self.job['elapsed_s'] = round(time.monotonic() - started, 3)
                if stopped and not futures: break
                while not stopped and not paused and next_index < len(skills) and len(futures) < workers:
                    s = skills[next_index]; next_index += 1
                    ev = self.evidence.get(s['id']) or {}
                    futures[pool.submit(judge, s, ev, env, self.key, questions, top.get(s['id'] if self.roots else s['name'], []))] = s
                if not futures:
                    time.sleep(0.05); continue
                done, _ = wait(futures, timeout=0.2, return_when=FIRST_COMPLETED)
                for f in done:
                    s = futures.pop(f)
                    try:
                        result = f.result()
                        self.store.save_result(s['id'], result=result)
                        with self.lock:
                            self.job['succeeded'] += 1
                            self.job['latencies'].append(result['elapsed_ms'])
                            for field in ('input_tokens', 'output_tokens'):
                                v = result.get('usage', {}).get(field, 0)
                                if isinstance(v, int) and v >= 0: self.job[field] += v
                    except Exception as e:
                        error = str(e) if isinstance(e, ValueError) else 'Processing failed; inspect configuration and retry'
                        self.store.save_result(s['id'], error=error[:240])
                        with self.lock: self.job['failed'] += 1
                    with self.lock: self.job['completed'] += 1
        with self.lock:
            self.job.update(status='cancelled' if self.cancelled else 'complete', finished_at=stamp(), elapsed_s=round(time.monotonic() - started, 3))
            self.store.save_run(dict(self.job))

    def control(self, action):
        with self.lock:
            if not self.job or self.job['status'] not in ACTIVE: raise ValueError('No active batch')
            if action == 'pause': self.paused = True; self.job['status'] = 'paused'
            elif action == 'resume': self.paused = False; self.job['status'] = 'running'
            elif action == 'stop': self.cancelled = True; self.paused = False; self.job['status'] = 'stopping'
            else: raise ValueError('Invalid batch action')


def handler(app, port):
    allowed = {f'localhost:{port}', f'127.0.0.1:{port}'}
    files = {'/': 'index.html', '/app.js': 'app.js', '/builder.js': 'builder.js', '/style.css': 'style.css', '/favicon.svg': 'favicon.svg'}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args): pass

        def send(self, code, data, content_type='application/json'):
            raw = json.dumps(data, allow_nan=False).encode() if content_type == 'application/json' else data
            self.send_response(code)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(raw)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            self.end_headers()
            try: self.wfile.write(raw)
            except (BrokenPipeError, ConnectionResetError): pass

        def authorized(self):
            if self.headers.get('Host', '') not in allowed: return False
            origin = self.headers.get('Origin')
            if origin and origin not in {f'http://{h}' for h in allowed}: return False
            return self.headers.get('Sec-Fetch-Site') != 'cross-site'

        def do_GET(self):
            if not self.authorized(): return self.send(403, {'error': 'Local same-origin access required'})
            path = urlparse(self.path).path
            qid = parse_qs(urlparse(self.path).query).get('id', [''])[0]
            if path == '/api/state': return self.send(200, app.state())
            if path == '/api/export':
                skills = app.state()['skills']
                return self.send(200, {'exported_at': stamp(), 'decisions': [{'id': s['id'], **s['decision']} for s in skills if s['decision']],
                                       'skills': [{k: s.get(k) for k in ('id', 'kind', 'path', 'description', 'evidence', 'overlap', 'result', 'decision', 'error')} for s in skills]})
            if path == '/api/predictions': return self.send(200, app.store.predictions(qid))
            if path == '/api/decisions': return self.send(200, app.store.decisions(qid))
            if path == '/health': return self.send(200, {'ok': True})
            if path not in files: return self.send(404, {'error': 'Not found'})
            p = ROOT / 'public' / files[path]
            return self.send(200, p.read_bytes(), (mimetypes.guess_type(str(p))[0] or 'text/plain') + '; charset=utf-8')

        def do_POST(self):
            if not self.authorized(): return self.send(403, {'error': 'Local same-origin access required'})
            if self.headers.get('Content-Type', '').split(';')[0] != 'application/json': return self.send(415, {'error': 'JSON required'})
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 1_000_000: return self.send(413, {'error': 'Request limit is 1 MB'})
                data = json.loads(self.rfile.read(size))
                if not isinstance(data, dict): raise ValueError('Request must be an object')
                if self.path == '/api/run': return self.send(200, app.start(data))
                if self.path == '/api/control': app.control(data.get('action'))
                elif self.path == '/api/decide': app.store.decide(data.get('id', ''), data.get('decision', ''), data.get('note', ''))
                elif self.path == '/api/rescan': app.rescan()
                elif self.path == '/api/overlap': app.run_overlap()
                else: return self.send(404, {'error': 'Not found'})
                self.send(200, {'ok': True})
            except (ValueError, TypeError, KeyError) as e:
                self.send(400, {'error': str(e)[:250]})
            except Exception:
                self.send(500, {'error': 'Server could not complete this operation'})
    return Handler


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=3345)
    parser.add_argument('--data', help='SQLite path; defaults per root set under .data/')
    parser.add_argument('--roots', help='comma-separated directories of SKILL.md files to review instead of the live tree')
    args = parser.parse_args()
    roots = [r for r in (args.roots or '').split(',') if r.strip()]
    data = args.data or str(ROOT / '.data' / (('roots-' + hashlib.sha256(','.join(sorted(roots)).encode()).hexdigest()[:8]) if roots else '') / 'skills.sqlite').replace('/.data//', '/.data/')
    app = Application(data, roots=roots)
    print(f'Skills × Jev listening on http://localhost:{args.port} (Jev credential: {"available" if app.key else "not configured"})', flush=True)
    ThreadingHTTPServer(('127.0.0.1', args.port), handler(app, args.port)).serve_forever()
