"""Load the skill tree and mine transcripts for usage evidence. Stdlib only."""
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

HOME = Path.home()
OWN = HOME / '.claude/skills'
PLUGINS = HOME / '.claude/plugins/cache'
PROJECTS = HOME / '.claude/projects'
SETTINGS = HOME / '.claude/settings.json'
SCRIPT_SUFFIXES = ('.py', '.sh', '.mjs', '.js', '.cjs', '.ts')
# ponytail: generic basenames match every repo; skip them rather than build attribution logic
GENERIC = {'index.js', 'main.py', 'server.py', 'app.js', 'build.sh', 'run.sh', 'setup.sh', 'test.py',
           'utils.py', 'config.py', 'install.sh', 'index.ts', 'cli.py', 'main.js', 'script.sh'}
INVOKE = re.compile(r'"name":"Skill","input":\{"skill":"([^"]+)"')
SLASH = re.compile(r'<command-name>/([A-Za-z0-9:_-]+)</command-name>')
TS = re.compile(r'"timestamp":"([^"]+)"')
TEXT_SUFFIXES = SCRIPT_SUFFIXES + ('.md', '.json', '.yaml', '.yml', '.toml', '.txt')
# Static pre-scan: the patterns people get burned by when they install a skill without reading it.
RISK_PATTERNS = [
    ('shell_pipe', re.compile(r'(curl|wget)\b[^\n|]*\|\s*(sudo\s+)?(ba|z)?sh\b', re.I)),
    ('destructive', re.compile(r'rm\s+-rf\s+[~/$]|git\s+push\s+(-f|--force)|--no-verify|mkfs\.|\bdd\s+if=|:\(\)\s*\{', re.I)),
    ('credentials', re.compile(r'~/\.ssh|id_rsa|id_ed25519|\.aws/credentials|find-generic-password|\.netrc|\.npmrc|GITHUB_TOKEN|OPENAI_API_KEY|ANTHROPIC_API_KEY|\bcat\s+[^\n]*\.env\b', re.I)),
    ('exfiltration', re.compile(r'(curl|wget|fetch|requests\.post|urlopen)[^\n]{0,120}(https?://(?!localhost|127\.0\.0\.1)[^\s"\')]+)[^\n]{0,80}(-d\s|--data|-F\s|@|POST)|webhook\.site|ngrok|pipedream|requestbin', re.I)),
    ('obfuscation', re.compile(r'base64\s+(-d|--decode)|\beval\s*\(|\bexec\s*\(|\\x[0-9a-f]{2}\\x[0-9a-f]{2}|atob\(|fromCharCode', re.I)),
    ('injection', re.compile(r'ignore (all |any )?(previous|prior|above) instructions|do not (tell|inform|mention)( this)? to the user|without (asking|telling|informing) the user|never mention|keep this (secret|hidden)|system prompt override', re.I)),
    ('hidden_text', re.compile(r'[\u200b\u200c\u200d\u200e\u200f\u2060\u2061\u2062\u2063\u2064\ufeff\u00ad]|<!--[^>]{0,400}(instruction|ignore|must|always|never)[^>]{0,400}-->', re.I)),
    ('elevated', re.compile(r'\bsudo\b|chmod\s+[0-7]*777|launchctl\s+(load|bootstrap)|crontab\s+-|\bosascript\b|defaults\s+write', re.I)),
    ('self_modifying', re.compile(r'~/\.claude/(settings|CLAUDE\.md)|\.claude/settings\.json|settings\.local\.json|~/\.zshrc|~/\.bashrc|~/\.gitconfig', re.I)),
]
URL = re.compile(r'https?://([a-z0-9.-]+\.[a-z]{2,})', re.I)


def iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).isoformat()


def frontmatter(text):
    m = re.match(r'---\n(.*?)\n---', text, re.S)
    if not m:
        return {}, text
    fm, key = {}, None
    for line in m.group(1).splitlines():
        km = re.match(r'^([A-Za-z_-]+):\s*(.*)$', line)
        if km:
            key, val = km.group(1), km.group(2).strip()
            fm[key] = val.strip('"\'').lstrip('>|').strip()
        elif key and line.startswith((' ', '\t')):
            fm[key] = (fm[key] + ' ' + line.strip()).strip()
    fm = {k: v.strip('"\'') for k, v in fm.items()}
    return fm, text[m.end():]


def enabled_plugins():
    try:
        settings = json.loads(SETTINGS.read_text())
    except (OSError, ValueError):
        return []
    out = []
    for key, on in settings.get('enabledPlugins', {}).items():
        if not on or '@' not in key:
            continue
        name, market = key.split('@', 1)
        base = PLUGINS / market / name
        if not base.is_dir():
            continue
        versions = sorted((p for p in base.iterdir() if p.is_dir()), key=lambda p: p.stat().st_mtime)
        if versions and (versions[-1] / 'skills').is_dir():
            out.append((name, versions[-1] / 'skills'))
    return out


def risk_flags(texts):
    """texts: {label: content}. Returns [{flag, where, sample}] with one sample per flag per file, plus external hosts."""
    flags, hosts = [], set()
    for where, content in texts.items():
        for name, rx in RISK_PATTERNS:
            m = rx.search(content)
            if m:
                end = content.find('\n', m.end())
                line = content[content.rfind('\n', 0, m.start()) + 1:end if end > 0 else len(content)]
                flags.append({'flag': name, 'where': where, 'sample': line.strip()[:200]})
        hosts.update(h.lower() for h in URL.findall(content))
    return flags, sorted(hosts)


def read_skill(path, plugin=None, root=None):
    text = path.read_text(errors='replace')
    fm, body = frontmatter(text)
    base = fm.get('name') or path.parent.name
    folder = path.parent
    rel = str(folder.relative_to(root)) if root else base
    src = re.search(r'Installed from ([^,\n]+)', text) or re.search(r'_?Source: (https?://\S+)', text)
    scripts = sorted({f.name for f in folder.rglob('*') if f.is_file() and f.suffix in SCRIPT_SUFFIXES
                      and 'node_modules' not in f.parts and f.name not in GENERIC})
    try:
        installed = min(f.stat().st_mtime for f in folder.rglob('*') if f.is_file())
    except ValueError:
        installed = folder.stat().st_mtime
    # everything text-like the skill ships, capped, for the safety pre-scan and the Jev risk question
    texts, budget = {'SKILL.md': text}, 30000
    for f in sorted(folder.rglob('*')):
        if f.is_file() and f.suffix in TEXT_SUFFIXES and f.name != 'SKILL.md' and 'node_modules' not in f.parts and budget > 0:
            try:
                chunk = f.read_text(errors='replace')[:budget]
            except OSError:
                continue
            texts[str(f.relative_to(folder))] = chunk
            budget -= len(chunk)
    if plugin:
        for extra in ('hooks/hooks.json', '.claude-plugin/plugin.json'):
            pf = folder.parent.parent / extra
            if pf.exists():
                texts['plugin:' + extra] = pf.read_text(errors='replace')[:4000]
    flags, hosts = risk_flags(texts)
    return {
        'id': f'{plugin}:{base}' if plugin else (rel if root else base),
        'name': base,
        'plugin': plugin,
        'kind': 'plugin' if plugin else 'repo' if root else 'own',
        'description': fm.get('description', ''),
        'path': str(folder),
        'symlink': folder.is_symlink(),
        'imported_from': src.group(1).strip().rstrip('.') if src else '',
        'disable_model_invocation': fm.get('disable-model-invocation', '').lower() == 'true',
        'user_invocable': fm.get('user-invocable', '').lower() == 'true',
        'body_chars': len(body),
        'body_excerpt': body.strip()[:2500],
        'body_full': body.strip()[:12000],
        'files_text': {k: v for k, v in texts.items() if k != 'SKILL.md'},
        'scripts': scripts,
        'risk_flags': flags,
        'external_hosts': hosts,
        'installed_at': iso(installed),
    }


def load_skills(roots=None):
    """Live tree (own + enabled plugins) by default; any directories of SKILL.md files when roots are given."""
    if roots:
        skills = []
        for root in roots:
            root = Path(root).expanduser().resolve()
            # hidden dirs such as .gemini/ hold mirrored copies; they are not separate skills
            skills += [read_skill(p, root=root) for p in sorted(root.rglob('SKILL.md'))
                       if 'node_modules' not in p.parts and not any(part.startswith('.') for part in p.relative_to(root).parts)]
        return skills
    skills = [read_skill(p) for p in sorted(OWN.glob('*/SKILL.md'))]
    for plugin, root in enabled_plugins():
        skills += [read_skill(p, plugin) for p in sorted(root.glob('*/SKILL.md'))]
    return skills


def scan_file(path, script_names):
    text = path.read_text(errors='replace')
    first = TS.search(text)
    inv, slash, scripts = {}, {}, {}
    for m in INVOKE.finditer(text):
        line_start = text.rfind('\n', 0, m.start()) + 1
        line_end = text.find('\n', m.end())
        ts = TS.search(text, line_start, line_end if line_end > 0 else len(text))
        entry = inv.setdefault(m.group(1), [0, ''])
        entry[0] += 1
        if ts and ts.group(1) > entry[1]:
            entry[1] = ts.group(1)
    for m in SLASH.finditer(text):
        slash[m.group(1)] = slash.get(m.group(1), 0) + 1
    for s in script_names:
        n = text.count(s)
        if n:
            scripts[s] = n
    return {'first_ts': first.group(1) if first else '', 'invocations': inv, 'slash': slash, 'scripts': scripts}


def evidence(store, skills):
    """Per-skill usage evidence across all transcripts. Cached per file by mtime/size in the store."""
    owners = {}
    for s in skills:
        for name in s['scripts']:
            owners.setdefault(name, []).append(s['id'])
    key = hashlib.sha256(json.dumps(sorted(owners)).encode()).hexdigest()[:12]
    files = sorted(PROJECTS.rglob('*.jsonl')) if PROJECTS.is_dir() else []
    per_skill = {s['id']: {'invocations': 0, 'last_invoked': '', 'slash': 0, 'script_mentions': 0} for s in skills}
    since, scanned = '', 0
    for f in files:
        st = f.stat()
        data = store.cache_get(str(f), key, st.st_mtime, st.st_size)
        if data is None:
            data = scan_file(f, list(owners))
            store.cache_put(str(f), key, st.st_mtime, st.st_size, data)
            scanned += 1
        if data['first_ts'] and (not since or data['first_ts'] < since):
            since = data['first_ts']
        for sid, (count, last) in data['invocations'].items():
            if sid in per_skill:
                per_skill[sid]['invocations'] += count
                if last > per_skill[sid]['last_invoked']:
                    per_skill[sid]['last_invoked'] = last
        for name, count in data['slash'].items():
            for sid in (name, name.split(':')[-1]):
                if sid in per_skill:
                    per_skill[sid]['slash'] += count
                    break
        for name, count in data['scripts'].items():
            for sid in owners.get(name, []):
                per_skill[sid]['script_mentions'] += count
    return per_skill, {'transcripts': len(files), 'since': since, 'rescanned_files': scanned,
                       'scanned_at': datetime.now(timezone.utc).isoformat()}
