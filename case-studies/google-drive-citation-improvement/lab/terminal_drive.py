"""Grok requests listing and reading; an MCP client captures actual returned data."""
import argparse
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import json
import logging
import os

from langfuse import Langfuse
from openai import AsyncOpenAI

from connect_drive import credentials, settings
from document_audit import REVIEW_TOOL, SUBMIT_TOOL, function, nonempty, validate_review, validate_answer
from drive_backend import DriveBackend, LIST_TOOL, READ_TOOL
from mcp_connection import ROOT, connect, private_json

LIST = function('list_drive_files', 'List the complete file metadata in the authorized test folder.',
                {'selection_reason': {'type': 'string'}, 'information_needed': {'type': 'string'}},
                ['selection_reason', 'information_needed'])
READ = function('read_drive_file', 'Read the full text of a selected file using existing Drive MCP.',
                {'document_id': {'type': 'string'}, 'selection_reason': {'type': 'string'},
                 'information_needed': {'type': 'string'}},
                ['document_id', 'selection_reason', 'information_needed'])
FIRST_QUESTION = ('What are the final approved launch date and launch owner for Project Aurora? '
                  'Support each fact with an exact quote from the documents.')
PROMPT_VERSION = '3-claim-quote-coverage'


def display_answer(output):
    print('\n' + output['answer'], flush=True)
    # validate_answer already renders limitations as the answer on abstention.
    if output['limitations'] and output['status'] != 'abstained':
        print('Limitations:', output['limitations'], flush=True)


class Session:
    def __init__(self, backend):
        self.backend = backend
        self.listing = None
        self.list_attempted = False
        self.review = None
        self.reads = []

    def tools(self):
        if not self.list_attempted:
            return [LIST]
        if not self.listing or self.listing.get('status') != 'listed':
            return [SUBMIT_TOOL]
        if self.review is None:
            return [REVIEW_TOOL]
        selected = {d['document_id'] for d in self.review['decisions'] if d['decision'] == 'select'}
        remaining = selected - {d['document_id'] for d in self.reads}
        return [READ, SUBMIT_TOOL] if remaining and len(self.reads) < 5 else [SUBMIT_TOOL]

    def snapshot(self):
        return {'backend': 'pipedream-drive-mcp-client', 'file_listing': self.listing,
                'candidates': self.listing.get('candidates', []) if self.listing else [],
                'candidate_review': self.review, 'read_documents': self.reads,
                'list_attempts': int(self.list_attempted), 'read_attempts': len(self.reads)}

    async def execute(self, name, args, evidence):
        if not isinstance(args, dict) or name not in {t['name'] for t in self.tools()}:
            raise ValueError('Tool unavailable in this phase')
        if name in ('list_drive_files', 'read_drive_file'):
            if not all(nonempty(args.get(k)) for k in ('selection_reason', 'information_needed')):
                raise ValueError('Declare the action purpose and intended information')
        if name == 'list_drive_files':
            self.list_attempted = True
            try:
                self.listing = {**args, **await self.backend.list_files()}
            except Exception as error:
                self.listing = {'status': 'failed', 'error_type': type(error).__name__,
                                'validation_error': str(error) if type(error) is ValueError else None}
            return self.listing
        if name == 'review_candidates':
            self.review = validate_review(args, self.listing['candidates'])
            self.review['basis'] = 'question_and_file_metadata_only'
            return self.review
        if name == 'read_drive_file':
            doc_id = args.get('document_id')
            selected = {d['document_id'] for d in self.review['decisions'] if d['decision'] == 'select'}
            candidate = next((f for f in self.listing['files'] if f['id'] == doc_id), None)
            if candidate is None or doc_id not in selected:
                raise ValueError('Read only an ID selected from this authorized folder listing')
            if any(d['document_id'] == doc_id for d in self.reads):
                raise ValueError('File already attempted; no hidden retry')
            try:
                result = {**args, **await self.backend.read_file(candidate)}
            except Exception as error:
                result = {**args, 'status': 'failed', 'error_type': type(error).__name__,
                          'validation_error': str(error) if type(error) is ValueError else None,
                          'source_url': f'https://drive.google.com/file/d/{doc_id}/view'}
            self.reads.append(result)
            return result
        return validate_answer(args, evidence)


async def ask(question, config, lf, client, mcp_session):
    state = Session(DriveBackend(mcp_session, lf, config['folder_id']))
    messages = [{'role': 'system', 'content': (ROOT / 'drive_prompt.txt').read_text()},
                {'role': 'user', 'content': question}]
    previous = None
    root_input = {'question': question, 'folder_id': config['folder_id'],
                  'budgets': {'max_model_calls': 12, 'max_read_attempts': 5, 'max_list_pages': 3}}
    with lf.start_as_current_observation(name='terminal-drive-mcp-review', as_type='span', input=root_input,
        metadata={'backend': 'pipedream-drive-mcp-client', 'output_language': 'English',
                  'prompt_version': PROMPT_VERSION, 'mcp_server_built_by_us': False,
                  'reader_version': '3-execute-synced-download',
                  'model_receives_full_text_without_presigned_download_urls': True}) as root:
        trace_url = lf.get_trace_url()
        print('\nTrace:', trace_url, flush=True)
        try:
            for turn in range(12):
                offered = state.tools()
                evidence = deepcopy(state.reads)
                print(f'Grok call {turn + 1}/12', flush=True)
                with lf.start_as_current_observation(name=f'grok-drive-agent / {turn + 1}', as_type='generation',
                    model='grok-4.7', input=messages, version=PROMPT_VERSION,
                    metadata={'previous_response_id': previous, 'available_tools': [t['name'] for t in offered]},
                    model_parameters={'reasoning_effort': 'low', 'max_output_tokens': 6000}) as generation:
                    params = {'model': 'grok-4.7', 'input': messages, 'tools': offered,
                              'tool_choice': 'required', 'store': True,
                              'reasoning': {'effort': 'low'}, 'max_output_tokens': 6000}
                    if previous:
                        params['previous_response_id'] = previous
                    try:
                        response = await client.responses.create(**params)
                        calls = [item for item in response.output if item.type == 'function_call']
                        generation.update(output={'text': response.output_text,
                                                  'tool_calls': [c.model_dump(mode='json') for c in calls]},
                            metadata={'provider_response_id': response.id},
                            usage_details={'input': response.usage.input_tokens, 'output': response.usage.output_tokens,
                                           'total': response.usage.total_tokens} if response.usage else None)
                        if response.status != 'completed' or not calls:
                            raise RuntimeError('No completed required tool request')
                    except BaseException as error:
                        generation.update(level='ERROR', status_message=type(error).__name__)
                        raise
                previous, messages = response.id, []
                for call in calls:
                    with lf.start_as_current_observation(name=call.name, as_type='tool',
                        metadata={'provider_call_id': call.call_id, 'execution_source': 'client_orchestration'}) as tool:
                        try:
                            if call.name not in {t['name'] for t in offered}:
                                raise ValueError('Tool was not offered to this model call')
                            args = json.loads(call.arguments)
                            tool.update(input=args)
                            result = await state.execute(call.name, args, evidence)
                            tool.update(output=result)
                            if result.get('status') == 'failed':
                                tool.update(level='ERROR', status_message=result['error_type'])
                            if call.name == 'submit_answer':
                                output = {**result, **state.snapshot()}
                                root.update(output=output)
                                run = {'input': root_input, 'output': output, 'trace_url': trace_url}
                                save_run(run)
                                display_answer(output)
                                return run
                            print(f"{call.name}: {result.get('status', 'reviewed')}", flush=True)
                        except Exception as error:
                            result = {'status': 'failed', 'error_type': type(error).__name__,
                                      'validation_error': str(error) if type(error) is ValueError else None}
                            tool.update(output=result, level='ERROR', status_message=type(error).__name__)
                            print(call.name + ': rejected (' + type(error).__name__ + ')', flush=True)
                        # Full text is forwarded unchanged; presigned download references
                        # remain in the tool trace instead of the model context.
                        model_result = {k: v for k, v in result.items() if k != 'raw_mcp_result'}
                        messages.append({'type': 'function_call_output', 'call_id': call.call_id,
                                         'output': json.dumps(model_result, ensure_ascii=False)})
            raise RuntimeError('Model-call budget exhausted')
        except BaseException as error:
            output = {'status': 'failed', 'error_type': type(error).__name__, **state.snapshot()}
            root.update(output=output, level='ERROR', status_message=type(error).__name__)
            save_run({'input': root_input, 'output': output, 'trace_url': trace_url})
            raise


def save_run(run):
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    private_json(ROOT / 'runs' / f'drive-{stamp}.json', run)
    private_json(ROOT / 'runs' / 'latest-run.json', run)


async def run(question, check=False):
    cfg, keys = settings(), credentials()
    if check:
        ready = all(keys[k] for k in ('LANGFUSE_PUBLIC_KEY', 'LANGFUSE_SECRET_KEY')) and bool(os.environ.get('XAI_API_KEY'))
        print('Credential configuration:', 'ready' if ready else 'missing')
        print('No API calls. Existing Google/Pipedream login will be used at runtime.')
        return 0 if ready else 1
    lf = Langfuse(public_key=keys['LANGFUSE_PUBLIC_KEY'], secret_key=keys['LANGFUSE_SECRET_KEY'],
                  base_url=keys['LANGFUSE_BASE_URL'] or 'https://us.cloud.langfuse.com', environment=cfg['environment'])
    try:
        if not lf.auth_check():
            raise RuntimeError('Langfuse authentication failed')
        async with connect(cfg) as (mcp_session, _):
            catalog = await mcp_session.list_tools()
            names = {t.name for t in catalog.tools}
            if not {LIST_TOOL, READ_TOOL} <= names:
                raise RuntimeError('Required existing Drive MCP tools are unavailable')
            async with AsyncOpenAI(api_key=os.environ['XAI_API_KEY'], base_url='https://api.x.ai/v1',
                                   timeout=180, max_retries=0) as client:
                if question is not None:
                    await ask(question, cfg, lf, client, mcp_session)
                else:
                    print('Grok + existing Drive MCP | English claims and quotes | /exit to stop')
                    while True:
                        try:
                            value = await asyncio.to_thread(input, '\nQuestion > ')
                        except EOFError:
                            break
                        if value.strip().lower() in ('/exit', '/quit'):
                            break
                        if value.strip():
                            await ask(value.strip(), cfg, lf, client, mcp_session)
                            lf.flush()
        return 0
    finally:
        lf.shutdown()


if __name__ == '__main__':
    for namespace in ('httpx', 'httpcore', 'mcp'):
        logging.getLogger(namespace).setLevel(logging.CRITICAL)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--question')
    parser.add_argument('--first-question', action='store_true')
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    question = FIRST_QUESTION if args.first_question else args.question
    if question is not None and not question.strip():
        parser.error('Question must not be empty')
    try:
        raise SystemExit(asyncio.run(run(question, args.check)))
    except KeyboardInterrupt:
        print('\nStopped.')
        raise SystemExit(130)
    except Exception as error:
        print('Execution failed:', type(error).__name__, '— inspect the trace and local run.')
        raise SystemExit(1)
