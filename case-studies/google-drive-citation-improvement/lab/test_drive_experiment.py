import json
import unittest
from copy import deepcopy
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock

from drive_experiment import Runner, STUDY, code_check, messages_at_checkpoint, read_json, summarize


class FrozenExperimentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = {d['metadata']['case_id']: d for d in read_json(STUDY / 'dataset.json')}

    def test_expected_answers_and_download_credentials_are_not_in_model_context(self):
        case = self.data['approval_read_failed']
        messages = messages_at_checkpoint('system', case['input'])
        encoded = json.dumps(messages)
        for forbidden in ('expected_output', 'required_claims', 'X-Amz-', 'raw_mcp_result', 'reference_criteria'):
            self.assertNotIn(forbidden, encoded)
        reads = [json.loads(m['output']) for m in messages if m.get('type') == 'function_call_output']
        self.assertEqual(reads[2:], case['input']['read_documents'])

    def test_failed_read_cannot_support_a_claim(self):
        case = self.data['approval_read_failed']['input']
        failed = next(r for r in case['read_documents'] if r['status'] == 'failed')
        output = {'execution_status': 'completed', 'submission': {'claims': [
            {'claim_id': 'c1', 'claim': 'The final date is November 20, 2026.',
             'evidence': [{'document_id': failed['document_id'],
                           'quote': 'The final approved launch date for Project Aurora is November 20, 2026.'}]}], 'limitations': ''}}
        self.assertFalse(code_check(output, case)[0])

    def test_quote_check_does_not_measure_completeness(self):
        case = self.data['approval_read_failed']['input']
        output = {'execution_status': 'completed', 'submission': {'claims': [], 'limitations': 'I cannot answer.'}}
        self.assertTrue(code_check(output, case)[0])

    def test_counterfactual_failed_reads_contain_no_hidden_body(self):
        for case in self.data.values():
            for read in case['input']['read_documents']:
                if read['status'] == 'failed':
                    self.assertNotIn('text', read)
                    self.assertNotIn('integrity', read)

    def test_missing_evaluation_is_not_counted_as_success(self):
        record = {'case_id': 'a', 'variant': 'baseline', 'study_pass': False,
                  'code_pass': True, 'judge': None}
        summary = summarize([record])[0]
        self.assertEqual(summary['passed'], 0)
        self.assertEqual(summary['judge_errors'], 1)

    def test_judge_can_verify_known_filenames_without_unread_bodies(self):
        case = self.data['approval_read_failed']
        observation = Mock()
        lf = Mock()
        lf.start_as_current_observation.return_value = nullcontext(observation)
        client = Mock()
        client.responses.create.return_value = SimpleNamespace(status='completed', id='test', usage=None,
            output=[SimpleNamespace(type='function_call', name='record_judgment',
                arguments=json.dumps({'grounded': True, 'task_success': True,
                                      'reason': 'Metadata establishes the filename.', 'failure_types': []}))])
        Runner(lf, client).judge(case['input'], {'submission': {'claims': [], 'limitations': 'test'}}, case['expected_output'])
        sent = json.loads(client.responses.create.call_args.kwargs['input'][1]['content'])
        self.assertEqual(sent['candidates'], case['input']['candidates'])
        failed = next(r for r in sent['read_documents'] if r['status'] == 'failed')
        self.assertNotIn('text', failed)


if __name__ == '__main__':
    unittest.main()
