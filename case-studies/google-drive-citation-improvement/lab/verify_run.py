"""Read back Langfuse observations and compare their full outputs to a local run."""
import argparse
import json
from pathlib import Path

from langfuse import Langfuse

from connect_drive import credentials
from mcp_connection import ROOT, payload_fingerprint, private_json


def decode(value):
    return json.loads(value) if isinstance(value, str) else value


def verify(path):
    run = json.loads(Path(path).read_text())
    keys = credentials()
    lf = Langfuse(public_key=keys['LANGFUSE_PUBLIC_KEY'], secret_key=keys['LANGFUSE_SECRET_KEY'],
                  base_url=keys['LANGFUSE_BASE_URL'] or 'https://us.cloud.langfuse.com')
    try:
        trace_id = run['trace_url'].rsplit('/', 1)[-1]
        result = lf.api.observations.get_many(trace_id=trace_id, fields='basic,io,metadata,model,usage', limit=100)
        observations = [item.model_dump(mode='json') for item in result.data]
        roots = [item for item in observations if item['name'] == 'terminal-drive-mcp-review']
        root_matches = (len(roots) == 1 and decode(roots[0].get('input')) == run['input']
                        and decode(roots[0].get('output')) == run['output'])
        output = run['output']
        listing = output.get('file_listing') or {}
        raw_expected = [('mcp.google_drive-list-files', page) for page in listing.get('raw_mcp_pages', [])]
        raw_expected.extend(('mcp.google_drive-download-file', read['raw_mcp_result'])
                            for read in output.get('read_documents', []) if 'raw_mcp_result' in read)
        raw_checks = []
        for name, expected in raw_expected:
            matches = [o for o in observations if o['name'] == name and decode(o.get('output')) == expected]
            raw_checks.append({'name': name, 'full_payload_matches': len(matches) == 1,
                               **payload_fingerprint(expected)})
        actual_raw_count = sum(o['name'] in ('mcp.google_drive-list-files', 'mcp.google_drive-download-file')
                               for o in observations)
        body_checks = []
        for read in output.get('read_documents', []):
            if read.get('status') != 'read':
                continue
            matches = [o for o in observations if o['name'] == 'read_drive_file'
                       and decode(o.get('output')) == read]
            original = ROOT.parent / 'fixtures/upload-to-drive' / read['title']
            body_checks.append({'title': read['title'], 'full_text_visible_in_langfuse': len(matches) == 1,
                                'character_count': len(read['text']), 'byte_count': len(read['text'].encode()),
                                'matches_original_fixture': read['text'].encode() == original.read_bytes() if original.exists() else None})
        generations = sorted((o for o in observations if o['name'].startswith('grok-drive-agent / ')),
                             key=lambda o: int(o['name'].rsplit(' ', 1)[-1]))
        model_reads = {}
        for generation in generations:
            for message in decode(generation.get('input')) or []:
                if message.get('type') != 'function_call_output':
                    continue
                value = decode(message.get('output'))
                if isinstance(value, dict) and value.get('status') == 'read':
                    model_reads[value['document_id']] = value
        for check, read in zip(body_checks, (d for d in output.get('read_documents', []) if d.get('status') == 'read')):
            check['full_text_in_subsequent_grok_input'] = model_reads.get(read['document_id'], {}).get('text') == read['text']
        chain_ok = True
        previous = None
        for item in generations:
            metadata = item.get('metadata') or {}
            if metadata.get('previous_response_id') != previous or not metadata.get('provider_response_id'):
                chain_ok = False
            previous = metadata.get('provider_response_id')
        checks_passed = (root_matches and bool(raw_checks) and actual_raw_count == len(raw_expected)
                         and all(c['full_payload_matches'] for c in raw_checks)
                         and all(c['full_text_visible_in_langfuse'] and c['full_text_in_subsequent_grok_input'] for c in body_checks)
                         and bool(generations) and chain_ok)
        report = {'trace_id': trace_id, 'status': output.get('status'),
                  'root_input_and_output_match_local_run': root_matches,
                  'raw_mcp_outputs': raw_checks, 'read_bodies': body_checks,
                  'actual_raw_mcp_observations': actual_raw_count,
                  'model_calls': len(generations), 'continuation_chain_verified': chain_ok,
                  'recording_checks_passed': checks_passed,
                  'semantic_answer_accuracy_evaluated_by_this_script': False}
        private_json(ROOT / 'runs' / f'verification-{trace_id}.json', report)
        print(json.dumps(report, indent=2))
        return 0 if checks_passed else 1
    finally:
        lf.shutdown()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', nargs='?', default=str(ROOT / 'runs/latest-run.json'))
    args = parser.parse_args()
    raise SystemExit(verify(args.run))
