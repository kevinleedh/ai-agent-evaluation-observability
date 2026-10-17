"""Summarize citation experiments and optionally apply a fully passing pilot prompt."""
import argparse
from datetime import datetime, timezone
import json
from statistics import median

from citation_experiment import RESULTS, STUDY, TARGETS
from drive_experiment import digest, read_json, write_asset
from mcp_connection import ROOT


def report(promote=False):
    source = RESULTS / 'latest.json'
    run = read_json(source)
    if run['status'] != 'completed' or not run['all_cases_recorded']:
        raise ValueError('Complete and record every planned trial before reporting.')
    rows = run['records']
    summaries = []
    for variant in ('baseline', 'candidate'):
        group = [r for r in rows if r['variant'] == variant]
        targets = [r for r in group if r['case_id'] in TARGETS]
        summaries.append({'variant': variant, 'trials': len(group),
            'code_passes': sum(r['code_pass'] for r in group),
            'citation_passes': sum(r['citation_pass'] for r in group),
            'task_passes': sum(bool(r['judge'] and r['judge']['task_success']) for r in group),
            'grounding_passes': sum(bool(r['judge'] and r['judge']['grounded']) for r in group),
            'combined_passes': sum(r['study_pass'] for r in group),
            'judge_errors': sum(r['judge'] is None for r in group),
            'relationship_targets': len(targets),
            'relationship_target_passes': sum(r['study_pass'] for r in targets),
            'median_answer_latency_seconds': median(r['output']['latency_seconds'] for r in group)})
    baseline, candidate = summaries
    eligible = candidate['combined_passes'] == candidate['trials'] and not any(s['judge_errors'] for s in summaries)
    lift = candidate['combined_passes'] > baseline['combined_passes']
    flags = [{'variant': r['variant'], 'trial': r['trial'], 'case_id': r['case_id'],
              'trace_id': r.get('trace_id'), 'submission': r['output'].get('submission'),
              'judge': r['judge'], 'code_reason': r['code_reason']} for r in rows if not r['study_pass']]
    summary = {'source_report': str(source), 'scope': run['study']['scope'], 'summary': summaries,
               'case_summary': run['summary'], 'flagged_answers': flags, 'pilot_eligible': eligible,
               'observed_suite_lift': lift, 'experiments': run['experiments'],
               'conclusion': ('The revised prompt has a higher observed combined pass count in this exploratory suite.' if lift
                              else 'No higher combined pass count was demonstrated in this exploratory suite.'),
               'limits': run['study']['limits']}
    write_asset(STUDY / 'results-summary.json', summary)
    lines = ['DRIVE CLAIM / QUOTE COVERAGE: RESULTS', '', 'QUESTION', run['study']['hypothesis'], '',
             'METHOD', run['study']['scope'],
             f"{run['study']['case_count']} cases; {len(rows)} freshly generated answers; one prompt block differs.",
             'Both variants used the same frozen evidence, model settings, code checks and per-claim judge.',
             'Baseline source: ' + run['study']['baseline_source'],
             'Changed variable: ' + run['study']['changed_variable'],
             'These are new trials, independently generated for both variants.', '',
             'RAW EVALUATOR RESULTS',
             'Variant | answers | code | attached quote support | requested facts | grounding | combined']
    for s in summaries:
        lines.append(f"{s['variant']} | {s['trials']} | {s['code_passes']} | {s['citation_passes']} | {s['task_passes']} | {s['grounding_passes']} | {s['combined_passes']}")
    lines += ['', 'RELATIONSHIP QUESTIONS (required distinctions cannot be skipped)']
    for s in summaries:
        lines.append(f"{s['variant']}: {s['relationship_target_passes']}/{s['relationship_targets']}")
    lines += ['', 'BY CASE']
    for s in run['summary']:
        lines.append(f"{s['case_id']} / {s['variant']}: {s['combined_passes']}/{s['trials']} combined; {s['citation_passes']}/{s['trials']} citation; {s['task_passes']}/{s['trials']} task")
    lines += ['', 'INTERPRETATION', summary['conclusion'],
              'Counts are judge decisions, not independently confirmed production accuracy.',
              'Inspect every flagged claim and its attached quotes. Quote support and factual completion are separate.',
              'An empty answer cannot win by avoiding citations when requested supported facts are missing.', '',
              'FLAGGED ANSWERS']
    for f in flags:
        lines.append(f"{f['variant']} r{f['trial']} {f['case_id']}: {f['judge']['reason'] if f['judge'] else f['code_reason']}")
    if not flags:
        lines.append('None under this frozen evaluator.')
    lines += ['', 'REFERENCE CHECKS',
              'The actual role-citation defect was isolated from a separate disputed precedence clause.',
              'Seven reference checks passed before any A/B answers were generated. Earlier disagreements',
              'and the evaluator clarification are retained in the audit files. Neither answer prompt nor',
              'the study evidence dataset was changed by those evaluator preflight repairs.', '',
              'LIMITS', run['study']['limits'],
              'No model training, live Drive integration test, or independent human adjudication was performed.', '',
              'LANGFUSE EXPERIMENTS']
    lines += [f"{e['variant']} r{e['trial']}: {e['url']}" for e in run['experiments']]
    if promote:
        if not eligible:
            raise ValueError('Candidate has failures or missing judgments; review instead of promoting.')
        live = ROOT / 'drive_prompt.txt'
        current, old, new = live.read_text(), (STUDY / 'baseline.txt').read_text(), (STUDY / 'candidate.txt').read_text()
        ancestor = (ROOT / 'experiments' / 'citation-coverage-v1' / 'baseline.txt').read_text()
        allowed = (old, new, ancestor) if STUDY.name == 'citation-coverage-v2' else (old, new)
        if current not in allowed:
            raise ValueError('Live prompt changed independently; preserve it and review the difference.')
        terminal = ROOT / 'terminal_drive.py'
        script = terminal.read_text()
        before = "PROMPT_VERSION = '2-partial-supported-answers'"
        after = "PROMPT_VERSION = '3-claim-quote-coverage'"
        if before not in script and after not in script:
            raise ValueError('Unexpected live prompt version; preserve it.')
        live.write_text(new)
        terminal.write_text(script.replace(before, after, 1))
        write_asset(STUDY / 'promotion.json', {'timestamp': datetime.now(timezone.utc).isoformat(),
            'baseline_sha256': digest(old), 'candidate_sha256': digest(new), 'source_report': str(source),
            'live_before_sha256': digest(current),
            'live_prompt_version': '3-claim-quote-coverage', 'observed_suite_lift': lift,
            'basis': 'All candidate cases passed the exploratory pilot; no required-fact loss or observed critical regression.',
            'scope': 'Local prompt update; production-wide improvement is not established.'})
        lines += ['', 'APPLIED CHANGE', 'Local drive_prompt.txt now uses the tested candidate.',
                  'terminal_drive.py records prompt version 3-claim-quote-coverage.',
                  'Existing open terminal processes must restart to load the new version.']
    elif (STUDY / 'promotion.json').exists():
        lines += ['', 'APPLIED CHANGE', 'See promotion.json for the recorded local prompt update.']
    else:
        lines += ['', 'APPLIED CHANGE', 'The tested candidate is saved separately; no live prompt update is recorded.']
    (STUDY / 'RESULTS.txt').write_text('\n'.join(lines) + '\n')
    # Keep a directly inspectable example from the explicit relationship question.
    example = next(r for r in rows if r['variant'] == 'candidate' and r['trial'] == 1
                   and r['case_id'] == 'approver_owner_distinction')
    write_asset(STUDY / 'example-corrected-answer.json', example)
    print(json.dumps({'summary': summaries, 'pilot_eligible': eligible, 'observed_suite_lift': lift,
                      'flagged_answers': len(flags), 'report': str(STUDY / 'RESULTS.txt')}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--promote', action='store_true')
    parser.add_argument('--study-version', choices=['1', '2'], default='1')
    args = parser.parse_args()
    if args.study_version == '2':
        STUDY = ROOT / 'experiments' / 'citation-coverage-v2'
        RESULTS = ROOT / 'runs' / 'citation-experiments-v2'
    report(args.promote)
