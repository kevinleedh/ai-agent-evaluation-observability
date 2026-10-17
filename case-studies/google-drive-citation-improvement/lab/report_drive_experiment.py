"""Write an evidence-based summary after the metadata-aware rescoring completes."""
from collections import Counter
import json
from pathlib import Path
from statistics import median

from drive_experiment import RESULTS, STUDY, digest, read_json, write_asset


def main():
    report = read_json(RESULTS / 'latest.json')
    if report.get('status') != 'completed' or not report.get('all_cases_recorded'):
        raise ValueError('Complete every expected experiment item before reporting.')
    if report['study'].get('judge_version') != '2-metadata-context':
        raise ValueError('The original judge omitted metadata; report only corrected scores.')
    records = report['records']
    summary = []
    for variant in ('baseline', 'candidate'):
        rows = [r for r in records if r['variant'] == variant]
        summary.append({'variant': variant, 'trials': len(rows),
                        'code_passes': sum(r['code_pass'] for r in rows),
                        'grounding_passes': sum(bool(r['judge'] and r['judge']['grounded']) for r in rows),
                        'task_successes': sum(bool(r['judge'] and r['judge']['task_success']) for r in rows),
                        'combined_passes': sum(r['study_pass'] for r in rows),
                        'evaluator_errors': sum(r['judge'] is None for r in rows),
                        'median_answer_latency_seconds': median(r['output']['latency_seconds'] for r in rows)})
    pairs = Counter()
    for r in records:
        if r['variant'] != 'baseline':
            continue
        other = next(x for x in records if x['case_id'] == r['case_id'] and x['trial'] == r['trial'] and x['variant'] == 'candidate')
        pairs[f'{"pass" if r["study_pass"] else "fail"}->{"pass" if other["study_pass"] else "fail"}'] += 1
    original = read_json(Path(report['source_report'])) if report.get('source_report') else report
    changed = []
    for r in records:
        old = next(x for x in original['records'] if (x['case_id'], x['variant'], x['trial']) == (r['case_id'], r['variant'], r['trial']))
        if r['output'] != old['output']:
            raise ValueError('Rescoring changed a generated answer.')
        if old['study_pass'] != r['study_pass']:
            changed.append({'case_id': r['case_id'], 'variant': r['variant'], 'trial': r['trial'],
                            'old_pass': old['study_pass'], 'corrected_pass': r['study_pass']})
    failures = [{'case_id': r['case_id'], 'variant': r['variant'], 'trial': r['trial'],
                 'trace_id': r.get('trace_id'), 'original_answer_trace_id': r.get('original_trace_id'),
                 'code_reason': r['code_reason'], 'judge': r['judge'], 'submission': r['output'].get('submission')}
                for r in records if not r['study_pass']]
    recovery = [r for r in records if r['case_id'] == 'approval_read_failed']
    recovery_all_pass = all(r['judge'] and r['judge']['task_success'] for r in recovery)
    conclusion = ('No demonstrated improvement in partial-answer recovery: both prompts completed all recorded recovery trials. '
                  'The historical over-abstention is real but did not recur at this reconstructed final-answer checkpoint.'
                  if recovery_all_pass else
                  'Recovery results differ; inspect the per-case counts and outputs before judging the prompt change.')
    output = {'model': report['study']['answer_model'], 'answer_trials': len(records),
              'dataset_sha256': report['study']['dataset_sha256'], 'judge_sha256': report['study']['judge_sha256'],
              'variant_summary': summary, 'case_summary': report['summary'],
              'matched_case_trial_transitions': dict(pairs), 'changed_judgments_after_context_fix': changed,
              'remaining_flagged_outputs': failures, 'conclusion': conclusion,
              'experiment_links': report['experiments'],
              'review_status': 'Assistant reviewed source evidence and evaluator disagreements. Not independent human review.'}
    write_asset(STUDY / 'results-summary.json', output)
    repetitions = len({r['trial'] for r in records})
    lines = ['DRIVE FAILURE ANALYSIS: FIRST CONTROLLED EXPERIMENT', '',
             'DECISION', conclusion,
             'Do not claim that the prompt fix is proven effective or that live Drive reliability improved.', '',
             'WHAT WAS DONE',
             'Collected eight saved Drive runs and classified recorded listing/read failures.',
             'Re-evaluated the actual over-abstaining answer and an actual successful answer.',
             'Compared the historical prompt with the updated per-fact partial-answer prompt.',
             f'Five frozen evidence cases x two prompt variants x {repetitions} trials = {len(records)} generated answers.',
             'The only answer-generation difference was the registered prompt rule. No live Drive calls.', '',
             'CORRECTED RESULTS', 'Variant | trials | code | semantic grounding | task success | all checks']
    for row in summary:
        lines.append(f"{row['variant']} | {row['trials']} | {row['code_passes']} | {row['grounding_passes']} | {row['task_successes']} | {row['combined_passes']}")
    lines += ['', 'BY CASE (combined pass count / trials)']
    for row in report['summary']:
        lines.append(f"{row['case_id']} / {row['variant']}: {row['passed']}/{row['trials']}")
    lines += ['', 'EVALUATOR ERROR FOUND AND CORRECTED',
              'The first judge input omitted file-list metadata and selection records. It falsely rejected',
              'known file names and recorded exclusions. The metadata-aware v2 judge receives those records',
              'while still forbidding file names as proof of unread contents. BOTH variants were rescored.',
              f'{len(changed)} combined judgments changed. All {len(records)} saved answer outputs remained identical.',
              'Original scores and reports are retained. Use judge-v2 experiments for the final comparison.', '',
              'REMAINING FLAGS FOR REVIEW']
    if not failures:
        lines.append('No remaining flags under the corrected rubric; this does not establish general reliability.')
    for row in failures:
        lines.append(f"{row['variant']} r{row['trial']} {row['case_id']}: {row['judge']['reason'] if row['judge'] else row['code_reason']}")
    lines += ['', 'INTERPRETATION AND NEXT EXPERIMENT',
              'The historical failure omitted a supported owner from claims despite a successful read.',
              'Reconstructing the final-answer checkpoint did not reproduce that omission in either prompt.',
              'Do not infer a unique cause: model variability and the reconstructed earlier context remain possible factors.',
              'Investigate remaining claim/quote coverage flags by reading each full claim and its attached quote.',
              'For recovery, the next stronger test should replay the full agent loop with a frozen backend.',
              'Preserve this suite as regression coverage, add new independent cases, and validate live MCP separately.', '',
              'LIMITS',
              f'Five hand-selected cases, {repetitions} trials per variant, no held-out set, and a same-model judge.',
              'Sanity checks are hand-authored references, not independent human calibration.',
              'Reconstructed history does not preserve every historical token, hidden state, or tool-call batch.',
              'Rescore experiment durations measure replay/scoring. Answer latency is retained in the original outputs.',
              'Full model alias, hashes, original trace IDs, outputs and judge reasons are retained for review.', '',
              'CORRECTED LANGFUSE EXPERIMENTS']
    lines += [f"{e['variant']} r{e['trial']}: {e['url']}" for e in report['experiments']]
    lines += ['', 'REPRODUCE',
              f'cd {STUDY.parent.parent}',
              '.venv/bin/python drive_experiment.py --trials 3',
              '.venv/bin/python report_drive_experiment.py']
    (STUDY / 'RESULTS.txt').write_text('\n'.join(lines) + '\n')
    print(json.dumps({'summary': summary, 'conclusion': conclusion, 'remaining_flags': len(failures),
                      'judge_corrections': len(changed), 'report': str(STUDY / 'RESULTS.txt')}, indent=2))


if __name__ == '__main__':
    main()
