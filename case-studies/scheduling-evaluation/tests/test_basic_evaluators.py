"""Replay basic/self-test evaluators on archived final answers, without APIs."""
import json
from pathlib import Path
from types import SimpleNamespace

BASE = Path(__file__).resolve().parent.parent
ARCHIVE = BASE.parent / 'project-scheduling'

def load(name):
    namespace = {}
    exec(compile((BASE / 'evaluators' / (name + '.py')).read_text(), name, 'exec'), namespace)
    return namespace

coverage = load('task_coverage')
duration = load('task_duration')
coverage_test = load('task_coverage_self_test')
duration_test = load('task_duration_self_test')

def run(module, answer):
    result = module['evaluate'](SimpleNamespace(observation=SimpleNamespace(output=answer)))
    return {s.name: s.value for s in result.scores}

count = 0
for version in ('v3', 'v4'):
    answer = (ARCHIVE / f'responses/validation-02-{version}.txt').read_text()
    # Both raw text and Langfuse-style serialized output wrappers.
    for output in (answer, {'text': answer, 'reasoningText': 'ignored'}, json.dumps({'text': answer})):
        assert run(coverage, output)['code_task_coverage'] is True
        assert run(duration, output)['code_task_duration'] is True
        count += 2
    scores = run(coverage_test, answer)
    assert scores == {'coverage_test_original': True, 'coverage_test_missing_n': False,
                      'coverage_test_duplicate_n': False, 'coverage_self_test_passed': True}
    count += 1
    scores = run(duration_test, answer)
    assert scores == {'duration_test_original': True, 'duration_test_wrong_a': False,
                      'duration_self_test_passed': True}
    count += 1
assert run(coverage, '')['code_task_coverage_status'] == 'unscored_no_output'
assert run(duration, '')['code_task_duration_status'] == 'no_output'
count += 2
print(f'{count} basic evaluator checks passed; no model/network calls.')
