from contextlib import nullcontext
from copy import deepcopy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from citation_experiment import CitationRunner, RULE, STUDY, read_json, reference_checks
from drive_experiment import code_check, messages_at_checkpoint


class CitationStudyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = read_json(STUDY / 'dataset.json')
        cls.full = next(d for d in cls.data if d['metadata']['case_id'] == 'all_required_reads_succeeded')

    def test_only_added_instruction_block_changes(self):
        before = (STUDY / 'baseline.txt').read_text()
        after = (STUDY / 'candidate.txt').read_text()
        self.assertEqual(after.replace(RULE, ''), before)

    def test_model_receives_no_reference_or_variant_label(self):
        messages = messages_at_checkpoint((STUDY / 'candidate.txt').read_text(), self.full['input'])
        encoded = json.dumps(messages)
        for forbidden in ['required_claims', 'expected_output', 'reference_criteria', 'X-Amz-']:
            self.assertNotIn(forbidden, encoded)

    def test_existing_quote_presence_check_accepts_known_semantic_failure(self):
        name, case, bad, *_ = reference_checks(self.data)[0]
        self.assertEqual(name, 'isolated_actual_role_quote_failure')
        self.assertTrue(code_check({'execution_status': 'completed', 'submission': bad}, case['input'])[0])

    def runner(self, result):
        lf, client = Mock(), Mock()
        lf.start_as_current_observation.return_value = nullcontext(Mock())
        client.responses.create.return_value = SimpleNamespace(status='completed', id='test', usage=None,
            output=[SimpleNamespace(type='function_call', name='record_citation_judgment', arguments=json.dumps(result))])
        return CitationRunner(lf, client)

    def test_judge_cannot_skip_a_claim(self):
        submission = reference_checks(self.data)[0][2]
        runner = self.runner({'grounded': True, 'task_success': True, 'claim_checks': [], 'reason': '', 'failure_types': []})
        with self.assertRaises(ValueError):
            runner.judge(self.full['input'], {'submission': submission}, self.full['expected_output'])

    def test_judge_cannot_pass_overall_while_rejecting_a_quote(self):
        submission = reference_checks(self.data)[2][2]
        runner = self.runner({'grounded': True, 'task_success': False,
            'claim_checks': [{'claim_id': submission['claims'][0]['claim_id'], 'quote_supports_full_claim': False, 'reason': 'unsupported'}],
            'reason': 'contradiction', 'failure_types': []})
        with self.assertRaises(ValueError):
            runner.judge(self.full['input'], {'submission': submission}, self.full['expected_output'])

    def test_judge_errors_are_recorded_as_incomplete_evaluation(self):
        runner = CitationRunner(Mock(), Mock())
        runner.judge = Mock(side_effect=ValueError('bad output'))
        runner.variant, runner.trial = 'baseline', 1
        submission = reference_checks(self.data)[2][2]
        scores = runner.evaluate(input=self.full['input'], output={'execution_status': 'completed', 'submission': submission},
            expected_output=self.full['expected_output'], metadata=self.full['metadata'])
        self.assertFalse(runner.records[0]['study_pass'])
        self.assertEqual(runner.records[0]['judge_error'], 'ValueError')
        self.assertFalse(next(s.value for s in scores if s.name == 'evaluation_completed'))


if __name__ == '__main__':
    unittest.main()
