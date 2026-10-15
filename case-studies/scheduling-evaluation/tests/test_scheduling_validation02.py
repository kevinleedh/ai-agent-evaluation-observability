"""Offline regression tests; no network/model calls or Langfuse score writes."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('schedule_eval', ROOT.parent / 'evaluators/scheduling_validation02.py')
evaluator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evaluator)
archive = ROOT.parent.parent / 'project-scheduling'
question = json.loads((archive / 'datasets/validation-02.json').read_text())['input']['question']
answer = (archive / 'responses/validation-02-v4.txt').read_text()

def run(text, q=question):
    ctx = SimpleNamespace(observation=SimpleNamespace(input=[{'role':'user','content':q}], output={'text':text}))
    return {s.name:s for s in evaluator.evaluate(ctx).scores}

def expect(text, score, value, q=question):
    scores = run(text, q)
    assert score in scores, (score, list(scores))
    assert scores[score].value == value, (score, scores[score])
    return scores

passed = 0
for version in ('v3','v4'):
    text = (archive / f'responses/validation-02-{version}.txt').read_text()
    expect(text, 'sched_all_deterministic_checks', True)
    passed += 1
cases = [
    ('missing', '- N: October 20, 09:30–10:00', '', 'coverage'),
    ('duplicate', '- N: October 20, 09:30–10:00', '- N: October 20, 09:30–10:00\n- N: October 20, 09:30–10:00', 'coverage'),
    ('duration', '- A: October 19, 09:00–10:00', '- A: October 19, 09:00–09:30', 'durations'),
    ('dependency', '- B: October 19, 10:00–11:00', '- B: October 19, 09:00–10:00', 'dependencies'),
    ('person overlap', '- E: October 19, 10:00–11:00', '- E: October 19, 09:00–10:00', 'resource_exclusivity'),
    ('GPU overlap', '- L: October 19, 16:00–16:30', '- L: October 19, 14:00–14:30', 'resource_exclusivity'),
    ('lunch', '- F: October 19, 13:00–14:00', '- F: October 19, 11:30–12:30', 'availability_lunch_continuity'),
    ('outside dates', '- A: October 19, 09:00–10:00', '- A: October 18, 09:00–10:00', 'availability_lunch_continuity'),
    ('boundary', '- A: October 19, 09:00–10:00', '- A: October 19, 09:15–10:15', 'start_boundaries'),
    ('approved M', '- M: October 20, 09:00–09:30', '- M: October 19, 16:30–17:00', 'approved_m_constraint'),
    ('deadline', '- N: October 20, 09:30–10:00', '- N: October 20, 10:00–10:30', 'deadline'),
    ('cost', 'Additional cost: 5', 'Additional cost: 6', 'budget_cost'),
    ('completion', 'Project completion: October 20, 2026 at 10:00', 'Project completion: October 20, 2026 at 09:30', 'completion_consistency'),
    ('method', 'Testing method: Accelerated', 'Testing method: Standard', 'durations'),
    ('missing cost', 'Additional cost: 5', '', 'required_fields'),
    ('malformed row', '- A: October 19, 09:00–10:00', '- A: October 19, nine to ten', 'coverage'),
]
for label, old, new, score in cases:
    assert old in answer, label
    altered = answer.replace(old, new, 1)
    scores = expect(altered, 'sched_s1_' + score, False)
    assert not scores['sched_all_deterministic_checks'].value, label
    passed += 1
# Guard against accidental use on another dataset or modified constraints.
for name in ('development','validation-01'):
    wrong_q = json.loads((archive / f'datasets/{name}.json').read_text())['input']['question']
    scores = expect(answer, 'sched_input_status','unsupported_input', wrong_q)
    assert 'sched_all_deterministic_checks' not in scores
    passed += 1
expect(answer, 'sched_input_status','unsupported_input', question.replace('budget is 5','budget is 6'))
passed += 1
# Table and bold Markdown presentation support.
import re
bullet = re.compile(r'^- ([A-N]): (October \d+), (\d+:\d+)–(\d+:\d+)$',re.M)
table = bullet.sub(lambda m: '| ' + ' | '.join(m.groups()) + ' |',answer)
expect(table,'sched_all_deterministic_checks',True)
passed += 1
bold = answer.replace('Verdict:', '**Verdict:**').replace('Testing method:', '**Testing method:**')
expect(bold,'sched_all_deterministic_checks',True)
passed += 1
# Missing scenario -> unscored parse status, never a schedule pass.
truncated = answer[:answer.rfind('Verdict: INFEASIBLE')]
scores=expect(truncated,'sched_parse_status','unsupported_scenarios')
assert 'sched_all_deterministic_checks' not in scores
passed += 1
bad_s2=answer.replace('Verdict: INFEASIBLE','Verdict: FEASIBLE')
expect(bad_s2,'sched_s2_verdict_reference',False)
passed += 1
# A false prose claim does not silently become an explanation-accuracy pass.
prose=answer + '\nAll task durations are seven hours.'
expect(prose,'sched_explanation_accuracy_status','requires_human_or_llm_judge')
passed += 1
print(f'{passed} checks passed. Explanation semantics remain explicitly unscored.')
