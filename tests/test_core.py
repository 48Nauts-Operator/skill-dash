import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import skills  # noqa: E402
from engine import QUESTIONS, prepare_questions, validate_answers  # noqa: E402
from store import Store  # noqa: E402


class Core(unittest.TestCase):
    def test_frontmatter_and_skill_reading(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / 'demo'; d.mkdir(); (d / 'scripts').mkdir()
            (d / 'SKILL.md').write_text('---\nname: demo\ndescription: "Use when X.\n  Also Y."\ndisable-model-invocation: true\n---\n<!-- Installed from vendor/pack, 2026-01-01 -->\nbody')
            (d / 'scripts' / 'audit_thing.py').write_text('print(1)')
            s = skills.read_skill(d / 'SKILL.md')
            self.assertEqual(s['id'], 'demo'); self.assertEqual(s['description'], 'Use when X. Also Y.')
            self.assertTrue(s['disable_model_invocation']); self.assertEqual(s['imported_from'], 'vendor/pack')
            self.assertEqual(s['scripts'], ['audit_thing.py'])
            self.assertEqual(skills.read_skill(d / 'SKILL.md', 'pack')['id'], 'pack:demo')

    def test_scan_file_counts_invocations_slash_and_scripts(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 't.jsonl'
            p.write_text('\n'.join([
                '{"type":"user","timestamp":"2026-05-01T10:00:00Z","message":{"content":"<command-name>/demo</command-name>"}}',
                '{"type":"assistant","timestamp":"2026-05-02T10:00:00Z","message":{"content":[{"type":"tool_use","name":"Skill","input":{"skill":"demo","args":""}}]}}',
                '{"type":"assistant","timestamp":"2026-05-03T10:00:00Z","message":{"content":[{"type":"tool_use","name":"Skill","input":{"skill":"demo"}}]}}',
                '{"type":"assistant","timestamp":"2026-05-04T10:00:00Z","message":{"content":"ran audit_thing.py twice: audit_thing.py"}}']))
            r = skills.scan_file(p, ['audit_thing.py'])
            self.assertEqual(r['first_ts'], '2026-05-01T10:00:00Z')
            self.assertEqual(r['invocations'], {'demo': [2, '2026-05-03T10:00:00Z']})
            self.assertEqual(r['slash'], {'demo': 1}); self.assertEqual(r['scripts'], {'audit_thing.py': 2})

    def test_questions_validate_and_answers_are_checked(self):
        q = prepare_questions(QUESTIONS)
        self.assertEqual(set(q), {'useful', 'redundancy', 'clarity', 'action'})
        with self.assertRaises(ValueError):
            prepare_questions({'bad': {'type': 'choice', 'instructions': 'x', 'criteria': {'a': 'A', 'b': 'B'}}})
        good = {'answers': {
            'useful': {'type': 'score', 'score': 2.0, 'confidence': .8, 'legend': {str(i): v for i, v in enumerate(q['useful']['criteria'])}, 'probabilities': {'0': 0, '1': 0, '2': 1, '3': 0}},
            'redundancy': {'type': 'choice', 'choice': 'none', 'confidence': .9, 'probabilities': {k: (1 if k == 'none' else 0) for k in q['redundancy']['criteria']}},
            'clarity': {'type': 'score', 'score': 1.0, 'confidence': .8, 'legend': {str(i): v for i, v in enumerate(q['clarity']['criteria'])}, 'probabilities': {'0': 0, '1': 1, '2': 0, '3': 0}},
            'action': {'type': 'choice', 'choice': 'keep', 'confidence': .9, 'probabilities': {k: (1 if k == 'keep' else 0) for k in q['action']['criteria']}}}}
        self.assertEqual(validate_answers(good, q)['action']['choice'], 'keep')
        bad = json.loads(json.dumps(good)); bad['answers']['action']['choice'] = 'burn'
        with self.assertRaises(ValueError):
            validate_answers(bad, q)

    def test_store_sync_decide_and_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            st = Store(Path(tmp) / 'd' / 's.sqlite')
            st.sync([{'id': 'a', 'description': 'x'}, {'id': 'b', 'description': 'y'}])
            st.decide('a', 'delete', 'dup of b')
            st.sync([{'id': 'a', 'description': 'x2'}])
            rows = st.skills()
            self.assertEqual([r['id'] for r in rows], ['a']); self.assertEqual(rows[0]['description'], 'x2')
            self.assertEqual(rows[0]['decision']['decision'], 'delete')
            with self.assertRaises(ValueError):
                st.decide('a', 'burn', '')
            st.decide('a', '', ''); self.assertIsNone(st.skills()[0]['decision'])
            self.assertEqual(len(st.decisions('a')), 2)
            st.cache_put('/x', 'k', 1.0, 10, {'n': 1})
            self.assertEqual(st.cache_get('/x', 'k', 1.0, 10), {'n': 1}); self.assertIsNone(st.cache_get('/x', 'k', 2.0, 10))


if __name__ == '__main__':
    unittest.main()
