"""Verify published evidence, deterministic checks and recorded totals without APIs."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys

PACKAGE = Path(__file__).resolve().parents[1]
LAB = PACKAGE / 'lab'
sys.path.insert(0, str(LAB))

from citation_experiment import JUDGE_PROMPT, RELEVANCE_RULE, RULE, aggregate
from drive_experiment import code_check, digest, messages_at_checkpoint
from document_audit import validate_answer


def load(path):
    return json.loads(path.read_text())


def require(condition, message):
    if not condition:
        raise ValueError(message)


def verify():
    publication = load(PACKAGE / 'PUBLICATION.json')
    for filename, hashes in publication['adapted_code'].items():
        require(hashlib.sha256((LAB / filename).read_bytes()).hexdigest() == hashes['published_sha256'],
                f'{filename}: published code hash changed')
    datasets = {}
    body_count = 0
    for study in ('partial-answer-v1', 'citation-coverage-v1', 'citation-coverage-v2'):
        directory = LAB / 'experiments' / study
        data = load(directory / 'dataset.json')
        datasets[study] = {item['metadata']['case_id']: item for item in data}
        require(len(datasets[study]) == len(data), f'{study}: duplicate case ID')
        manifest = load(directory / ('manifest-v2.json' if study == 'partial-answer-v1' else 'manifest.json'))
        require(digest(data) == manifest['dataset_sha256'], f'{study}: dataset hash')
        for variant in ('baseline', 'candidate'):
            require(digest((directory / f'{variant}.txt').read_text()) == manifest[f'{variant}_sha256'],
                    f'{study}: {variant} prompt hash')
        judge_file = 'judge-v2.txt' if study == 'partial-answer-v1' else 'judge.txt'
        require(digest((directory / judge_file).read_text()) == manifest['judge_sha256'],
                f'{study}: judge file hash')
        if study != 'partial-answer-v1':
            require(digest(JUDGE_PROMPT) == manifest['judge_sha256'], f'{study}: executable judge hash')
        for item in data:
            inp = item['input']
            require(digest(inp) == item['metadata']['input_sha256'], f'{study}: input hash')
            candidates = {candidate['id'] for candidate in inp['candidates']}
            decisions = item['input']['candidate_review']['decisions']
            require(Counter(d['document_id'] for d in decisions) == Counter(candidates),
                    f'{study}: candidate decision coverage')
            selected = {d['document_id'] for d in decisions if d['decision'] == 'select'}
            for read in inp['read_documents']:
                require(read['document_id'] in selected, f'{study}: unread selection')
                if read['status'] != 'read':
                    require('text' not in read and 'integrity' not in read, f'{study}: body leaked into failed read')
                    continue
                expected = (PACKAGE / 'fixtures/upload-to-drive' / read['title']).read_bytes()
                require(read['text'].encode() == expected, f'{study}: full original body mismatch')
                require(hashlib.sha256(expected).hexdigest() == read['integrity']['sha256'],
                        f'{study}: body checksum')
                body_count += 1
            encoded = json.dumps(messages_at_checkpoint('test prompt', inp))
            for forbidden in ('expected_output', 'required_claims', 'reference_criteria', 'X-Amz-', 'raw_mcp_result'):
                require(forbidden not in encoded, f'{study}: model-input leakage: {forbidden}')

    v1 = LAB / 'experiments/citation-coverage-v1'
    v2 = LAB / 'experiments/citation-coverage-v2'
    require((v1 / 'candidate.txt').read_text().replace(RULE, '') == (v1 / 'baseline.txt').read_text(),
            'Revision 1 changes more than the citation block')
    require((v2 / 'baseline.txt').read_text() == (v1 / 'candidate.txt').read_text(),
            'Revision 2 baseline is not revision 1 candidate')
    require((v2 / 'candidate.txt').read_text() == (v2 / 'baseline.txt').read_text() + '\n' + RELEVANCE_RULE,
            'Revision 2 changes more than the relevance block')
    require((LAB / 'drive_prompt.txt').read_text() == (v2 / 'candidate.txt').read_text(),
            'Published live prompt differs from final candidate')

    totals = {}
    saved = {}
    plan = [
        ('partial-answer-initial-judge.json', 'partial-answer-v1', 5),
        ('partial-answer-corrected-judge.json', 'partial-answer-v1', 5),
        ('citation-coverage-v1.json', 'citation-coverage-v1', 7),
        ('citation-coverage-v2.json', 'citation-coverage-v2', 7),
    ]
    for filename, study, case_count in plan:
        report = load(PACKAGE / 'results' / filename)
        saved[filename] = report
        rows = report['records']
        expected = {(case_id, variant, trial) for case_id in datasets[study]
                    for variant in ('baseline', 'candidate') for trial in range(1, 4)}
        observed = [(r['case_id'], r['variant'], r['trial']) for r in rows]
        require(len(rows) == case_count * 6 and len(set(observed)) == len(rows)
                and set(observed) == expected, f'{filename}: incomplete trial coverage')
        require(report['status'] == 'completed' and report['all_cases_recorded'], f'{filename}: incomplete report')
        for row in rows:
            inp = datasets[study][row['case_id']]['input']
            require(digest(inp) == row['input_sha256'], f'{filename}: record input hash')
            passed, _ = code_check(row['output'], inp)
            require(passed == row['code_pass'], f'{filename}: deterministic result changed')
            judgment = row['judge']
            require(judgment is not None and row['judge_error'] is None, f'{filename}: evaluator error')
            require(row['study_pass'] == bool(passed and judgment['grounded'] and judgment['task_success']),
                    f'{filename}: combined score mismatch')
            if 'claim_checks' in judgment:
                require(Counter(c['claim_id'] for c in judgment['claim_checks'])
                        == Counter(c['claim_id'] for c in row['output']['submission']['claims']),
                        f'{filename}: per-claim judge coverage')
                citation_pass = all(c['quote_supports_full_claim'] for c in judgment['claim_checks'])
                require(citation_pass == row['citation_pass'] == judgment['citation_pass'],
                        f'{filename}: citation aggregation')
                require(not judgment['grounded'] or citation_pass, f'{filename}: contradictory judgment')
        if study.startswith('citation-'):
            require(aggregate(rows) == report['summary'], f'{filename}: per-case summary mismatch')
        groups = {}
        for variant in ('baseline', 'candidate'):
            group = [r for r in rows if r['variant'] == variant]
            groups[variant] = {
                'answers': len(group), 'code': sum(r['code_pass'] for r in group),
                'grounding': sum(r['judge']['grounded'] for r in group),
                'task': sum(r['judge']['task_success'] for r in group),
                'combined': sum(r['study_pass'] for r in group),
            }
            if study.startswith('citation-'):
                groups[variant]['citation'] = sum(r['citation_pass'] for r in group)
        totals[filename] = groups

    initial = {(r['case_id'], r['variant'], r['trial']): r
               for r in saved['partial-answer-initial-judge.json']['records']}
    corrected = saved['partial-answer-corrected-judge.json']['records']
    require(all(initial[(r['case_id'], r['variant'], r['trial'])]['output'] == r['output'] for r in corrected),
            'Partial-answer re-scoring changed an answer')
    changed = sum(initial[(r['case_id'], r['variant'], r['trial'])]['study_pass'] != r['study_pass'] for r in corrected)
    require(changed == 6, 'Unexpected partial-answer judgment change count')
    for groups in [totals['partial-answer-corrected-judge.json']]:
        require(all(g == {'answers': 15, 'code': 15, 'grounding': 14, 'task': 15, 'combined': 14}
                    for g in groups.values()), 'Partial-answer corrected totals changed')
    for filename, before, after in [('citation-coverage-v1.json', 15, 19), ('citation-coverage-v2.json', 19, 21)]:
        require(totals[filename]['baseline']['citation'] == before and totals[filename]['candidate']['citation'] == after,
                f'{filename}: documented citation totals changed')
        require(all(g['code'] == g['task'] == 21 for g in totals[filename].values()), f'{filename}: code/task totals')

    final = saved['citation-coverage-v2.json']
    require(len(final['calibration']) == 7 and all(c['matched'] for c in final['calibration']), 'Final reference checks')
    for control in final['calibration']:
        require(all(control['expected'][key] == control['actual'][key] for key in control['expected']),
                'Reference expected/actual mismatch')
    for name in ('citation-preflight-01.json', 'citation-preflight-02.json'):
        report = load(PACKAGE / 'results' / name)
        require(report['status'] == 'reference_disagreement' and not report['records'], 'Preflight history altered')
    failures = {(r['case_id'], r['trial']) for r in final['records'] if not r['study_pass']}
    require(failures == {('venue_not_in_documents', 2), ('owner_read_failed', 3)}, 'Final failures changed')
    examples = load(PACKAGE / 'results/final-failure-examples.json')
    require(len(examples) == 2, 'Final failure examples missing')
    index = {(r['case_id'], r['variant'], r['trial']): r for r in final['records']}
    for pair in examples:
        for field, variant in [('before', 'baseline'), ('after', 'candidate')]:
            require(pair[field] == index[(pair['case_id'], variant, pair['trial_index'])], 'Example not from recorded run')
        require(not pair['before']['study_pass'] and pair['after']['study_pass'], 'Unexpected example transition')

    for name in ('historical-over-abstention', 'live-success'):
        snapshot = load(PACKAGE / 'fixtures' / f'{name}.json')['output']
        regenerated = validate_answer({'claims': snapshot['claim_evidence'], 'limitations': snapshot['limitations']},
                                     snapshot['read_documents'])
        require(all(regenerated[key] == snapshot[key] for key in regenerated), f'{name}: live snapshot mismatch')
    inventory = load(PACKAGE / 'results/live-run-inventory.json')
    require(len(inventory) == 8, 'Live run inventory changed')
    for path in PACKAGE.rglob('*.json'):
        text = path.read_text()
        require(not re.search(r'[?&](?:X-Amz-(?:Signature|Credential|Security-Token)|access_token)=', text, re.I),
                f'Signed credential material in {path.name}')
        require(not re.search(r'/(?:Users|home)/[^\s"\']+/', text)
                and 'us.cloud.langfuse.com/project/' not in text, f'Private path/link in {path.name}')
        require(not re.search(r'[\uac00-\ud7a3]', text), f'Unexpected non-English text in {path.name}')

    return {'status': 'passed', 'api_calls': 0, 'semantic_judgments_repeated': False,
            'saved_record_checks': 144, 'unique_generated_answers': 114,
            'successful_frozen_body_checks': body_count, 'partial_answer_rescore_changes': changed,
            'live_runs': len(inventory), 'totals': totals,
            'scope': 'Public hashes, complete original evidence bodies, prompt differences, deterministic replay, saved-score aggregation, example provenance and basic publication checks.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write', action='store_true', help='Save results/offline-validation.json')
    args = parser.parse_args()
    report = verify()
    if args.write:
        (PACKAGE / 'results/offline-validation.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
