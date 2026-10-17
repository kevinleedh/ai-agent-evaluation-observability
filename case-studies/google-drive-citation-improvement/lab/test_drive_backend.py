from hashlib import md5
import json
from pathlib import Path
import unittest
from contextlib import redirect_stdout
from io import StringIO

from drive_backend import decode_body, download_reference, parse_listing
from terminal_drive import Session, display_answer


def payload(value):
    return {'content': [{'type': 'text', 'text': '```json\n' + json.dumps(value) + '\n```'}], 'isError': False}


class ParsingTests(unittest.TestCase):
    def test_abstention_limitations_are_printed_once(self):
        output = {'answer': 'Limitations: Required document could not be read.',
                  'limitations': 'Required document could not be read.', 'status': 'abstained'}
        stream = StringIO()
        with redirect_stdout(stream):
            display_answer(output)
        self.assertEqual(stream.getvalue().count('Required document could not be read.'), 1)

    def setUp(self):
        self.data = 'Complete body. \u03a9.\n'.encode()
        self.file = {'id': 'one', 'name': 'fixture.txt', 'size': str(len(self.data)),
                     'mimeType': 'text/plain', 'md5Checksum': md5(self.data).hexdigest()}

    def test_buffer_decode_preserves_utf8(self):
        result = payload({'fileId': 'one', 'content': {'type': 'Buffer', 'data': list(self.data)}})
        text, integrity = decode_body(result, self.file)
        self.assertEqual(text.encode(), self.data)
        self.assertTrue(integrity['md5_matches_drive_metadata'])

    def test_observed_prose_buffer_format(self):
        result = {'content': [{'type': 'text', 'text': 'File ID: one\nFile Content (Buffer Data): ' + json.dumps(list(self.data))}]}
        self.assertEqual(decode_body(result, self.file)[0].encode(), self.data)

    def test_bad_buffers_are_not_evidence(self):
        variants = [list(self.data[:-1]), [0] * len(self.data), [True] * len(self.data), [256], ['...']]
        for data in variants:
            with self.subTest(data=data[:2]):
                with self.assertRaises(ValueError):
                    decode_body(payload({'fileId': 'one', 'content': {'type': 'Buffer', 'data': data}}), self.file)

    def test_wrong_file_or_download_reference_rejected(self):
        for result in (payload({'fileId': 'other', 'content': list(self.data)}),
                       payload({'fileId': 'one', 'filePath': '/tmp/fixture.txt'}),
                       payload({'fileId': 'one', 'url': 'https://example.com/download'})):
            with self.assertRaises(ValueError):
                decode_body(result, self.file)

    def test_failed_tool_is_not_evidence(self):
        result = payload({'fileId': 'one', 'content': list(self.data)})
        result['isError'] = True
        with self.assertRaises(ValueError):
            decode_body(result, self.file)

    def test_folder_scope_and_listing_completeness(self):
        valid = {'files': [{'id': 'one', 'name': 'fixture.txt', 'parents': ['folder']}],
                 'nextPageToken': None, 'isComplete': True}
        self.assertEqual(len(parse_listing(payload(valid), 'folder')['files']), 1)
        with self.assertRaises(ValueError):
            parse_listing(payload(valid), 'other-folder')
        for extra in ({'incompleteSearch': True}, {'isComplete': False}):
            with self.assertRaises(ValueError):
                parse_listing(payload({**valid, **extra}), 'folder')

    def test_ambiguous_listings_rejected(self):
        one = {'files': [], 'isComplete': True}
        two = {'files': [], 'isComplete': False, 'nextPageToken': 'two'}
        result = {'content': [{'type': 'text', 'text': f'```json\n{json.dumps(one)}\n```\n```json\n{json.dumps(two)}\n```'}]}
        with self.assertRaises(ValueError):
            parse_listing(result, 'folder')

    def test_only_expected_file_stash_resource_can_be_downloaded(self):
        url = 'https://pipedream-file-stash-production.s3.us-east-1.amazonaws.com/fixture.txt?signature=test'
        valid = {'content': [{'type': 'resource', 'resource': {'uri': url, 'text': '/tmp/fixture.txt'}}]}
        self.assertEqual(download_reference(valid), url)
        for bad in ('https://drive.google.com/file/d/one/view', 'http://127.0.0.1/file',
                    'https://pipedream-file-stash-production.s3.us-east-1.amazonaws.com.evil.example/file'):
            with self.assertRaises(ValueError):
                download_reference({'content': [{'type': 'resource', 'resource': {'uri': bad}}]})


class SessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_unknown_file_cannot_be_read(self):
        state = Session(None)
        state.list_attempted = True
        state.listing = {'status': 'listed', 'files': [{'id': 'allowed'}]}
        state.review = {'decisions': [{'document_id': 'allowed', 'decision': 'select'}]}
        with self.assertRaises(ValueError):
            await state.execute('read_drive_file', {'document_id': 'outside', 'selection_reason': 'test', 'information_needed': 'test'}, [])

    async def test_same_turn_unseen_read_cannot_support_claim(self):
        state = Session(None)
        state.list_attempted = True
        state.listing = {'status': 'listed', 'files': []}
        state.review = {'decisions': []}
        state.reads = [{'document_id': 'one', 'status': 'read', 'source_url': 'https://example.com', 'text': 'This text was not seen before the model request.'}]
        args = {'claims': [{'claim_id': 'c1', 'claim': 'A claim', 'evidence': [{'document_id': 'one', 'quote': state.reads[0]['text']}]}], 'limitations': ''}
        with self.assertRaises(ValueError):
            await state.execute('submit_answer', args, [])


if __name__ == '__main__':
    unittest.main()
