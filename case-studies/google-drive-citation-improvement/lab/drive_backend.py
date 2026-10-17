"""Folder-scoped calls to existing Pipedream Drive MCP tools, with full payloads."""
from hashlib import md5, sha256
import json
import re
from urllib.parse import urlsplit

import httpx

from mcp_connection import traced_request

LIST_TOOL = 'google_drive-list-files'
READ_TOOL = 'google_drive-download-file'


def text_blocks(payload):
    if payload.get('isError'):
        raise ValueError('MCP returned an error; it is not document evidence')
    return '\n'.join(block['text'] for block in payload.get('content', [])
                     if block.get('type') == 'text' and isinstance(block.get('text'), str))


def json_objects(payload):
    text = text_blocks(payload)
    objects = []
    structured = payload.get('structuredContent')
    if isinstance(structured, dict):
        objects.append(structured)
    chunks = re.findall(r'```(?:json)?\s*\n(.*?)```', text, re.DOTALL | re.IGNORECASE)
    chunks.append(text.strip())
    for chunk in chunks:
        try:
            value = json.loads(chunk)
        except (ValueError, TypeError):
            continue
        if isinstance(value, dict) and value not in objects:
            objects.append(value)
    return objects


def parse_listing(payload, folder_id):
    matches = [obj for obj in json_objects(payload) if isinstance(obj.get('files'), list)]
    if len(matches) != 1:
        raise ValueError('Expected one unambiguous JSON file list; no guessing from prose')
    result = matches[0]
    if result.get('incompleteSearch'):
        raise ValueError('Drive reported an incomplete search')
    if result.get('isComplete') is False and not result.get('nextPageToken'):
        raise ValueError('Incomplete file list has no continuation token')
    for item in result['files']:
        if (not isinstance(item, dict) or not isinstance(item.get('id'), str)
                or not item['id'] or not isinstance(item.get('name'), str)):
            raise ValueError('Invalid file record')
        if folder_id not in item.get('parents', []):
            raise ValueError('Returned file is outside the authorized folder')
    return result


def verify_bytes(data, candidate):
    """Verify original bytes before exposing them as successful read evidence."""
    if len(data) != int(candidate['size']):
        raise ValueError('Returned byte length does not match the listed file size')
    if md5(data).hexdigest() != candidate['md5Checksum']:
        raise ValueError('Returned bytes do not match the listed Drive MD5 checksum')
    decoded = data.decode('utf-8')
    if not decoded.strip():
        raise ValueError('Empty document')
    return decoded, {'byte_count': len(data), 'character_count': len(decoded),
                     'md5_matches_drive_metadata': True, 'sha256': sha256(data).hexdigest(),
                     'truncated_by_client': False}


def decode_body(payload, candidate):
    """Diagnostic decoder for Buffer responses observed during connection tests."""
    text = text_blocks(payload)
    buffers = []
    for obj in json_objects(payload):
        if obj.get('fileId') != candidate['id']:
            continue
        content = obj.get('content')
        if isinstance(content, dict) and content.get('type') == 'Buffer':
            buffers.append(content.get('data'))
        elif isinstance(content, list):
            buffers.append(content)
    # Pipedream's instruction-based tools can wrap a complete Buffer in prose.
    # Match this explicit observed format only, and verify every byte below.
    if not buffers:
        file_ids = re.findall(r'^File ID:\s*(\S+)\s*$', text, re.MULTILINE)
        values = re.findall(r'File Content \(Buffer Data\):\s*(\[[\s\S]*?\])', text)
        if file_ids == [candidate['id']] and len(values) == 1:
            try:
                buffers = [json.loads(values[0])]
            except ValueError:
                pass
    if len(buffers) != 1 or not isinstance(buffers[0], list):
        raise ValueError('No complete byte buffer returned; a URL or path is not document text')
    values = buffers[0]
    if not all(type(value) is int and 0 <= value <= 255 for value in values):
        raise ValueError('Invalid or abbreviated byte buffer')
    data = bytes(values)
    return verify_bytes(data, candidate)


def download_reference(payload):
    """Use the actual File Stash resource; never treat a Drive view URL as bytes."""
    text_blocks(payload)  # Reject MCP errors first.
    urls = {block.get('resource', {}).get('uri') for block in payload.get('content', [])
            if block.get('type') == 'resource'}
    urls.discard(None)
    allowed = []
    for url in urls:
        parsed = urlsplit(url)
        if (parsed.scheme == 'https'
                and parsed.hostname == 'pipedream-file-stash-production.s3.us-east-1.amazonaws.com'
                and not parsed.username and not parsed.password and parsed.port in (None, 443)):
            allowed.append(url)
    if len(allowed) != 1:
        raise ValueError('Expected one original-file Pipedream File Stash resource URL')
    return allowed[0]


async def fetch_original(payload, candidate, langfuse):
    url = download_reference(payload)
    parsed = urlsplit(url)
    with langfuse.start_as_current_observation(name='download-reference-read', as_type='tool',
        input={'document_id': candidate['id'], 'download_host': parsed.hostname,
               'download_path': parsed.path, 'method': 'GET'},
        metadata={'source': 'mcp_returned_file_stash_resource', 'timing_basis': 'client_request_wrapper'}) as tool:
        try:
            data = bytearray()
            async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
                async with client.stream('GET', url) as response:
                    if response.status_code != 200:
                        raise RuntimeError('Original download did not return HTTP 200')
                    async for chunk in response.aiter_bytes():
                        data.extend(chunk)
                        if len(data) > 65536:
                            raise ValueError('Download exceeds text-fixture limit; rejecting the entire read')
            text, integrity = verify_bytes(bytes(data), candidate)
            tool.update(output={'document_id': candidate['id'], 'text': text, 'integrity': integrity})
            return text, integrity
        except BaseException as error:
            tool.update(output={'status': 'failed', 'error_type': type(error).__name__},
                        level='ERROR', status_message=type(error).__name__)
            raise


class DriveBackend:
    def __init__(self, session, langfuse, folder_id):
        self.session, self.langfuse, self.folder_id = session, langfuse, folder_id

    async def list_files(self):
        pages, files, seen_ids, seen_cursors = [], [], set(), set()
        cursor = None
        for _ in range(3):
            instruction = (
                'Your final response must be a single valid JSON object, not a prose summary or bullet list. '
                f"List only direct non-trashed child files of folder ID {self.folder_id}. "
                'Set folderId to that exact ID and maxResults to 100. '
                'Request fields nextPageToken,incompleteSearch,files(id,name,mimeType,size,parents,md5Checksum,modifiedTime,webViewLink). '
                f'Use pageToken {json.dumps(cursor)}. '
                'Return one JSON object with files, nextPageToken and isComplete, without omitting file records or fields. '
                'Do not read contents, follow shortcuts, or search outside this folder. Do not modify Drive. '
                'Preserve the action result records exactly, including each parents array and md5Checksum. '
                'Output schema: {"files":[{"id":"...","name":"...","mimeType":"...",'
                '"size":"...","parents":["..."],"md5Checksum":"...","modifiedTime":"...",'
                '"webViewLink":"..."}],"nextPageToken":null,"isComplete":true}. '
                'Use the actual nextPageToken and isComplete values, never the placeholder values. '
                'Do not omit fields or translate the JSON into a human-readable list.'
            )
            args = {'instruction': instruction}
            raw = await traced_request(self.langfuse, name='mcp.google_drive-list-files', arguments=args,
                operation=lambda: self.session.call_tool(LIST_TOOL, arguments=args))
            pages.append(raw)
            page = parse_listing(raw, self.folder_id)
            for file in page['files']:
                if file['id'] in seen_ids:
                    raise ValueError('Duplicate file ID across listing pages')
                seen_ids.add(file['id'])
                files.append(file)
            cursor = page.get('nextPageToken')
            if not cursor:
                return {'status': 'listed', 'folder_id': self.folder_id, 'listing_complete': True,
                        'page_count': len(pages), 'files': files,
                        'candidates': [{'id': f['id'], 'title': f['name'],
                                        'url': f"https://drive.google.com/file/d/{f['id']}/view",
                                        'mime_type': f.get('mimeType'), 'modified_time': f.get('modifiedTime')}
                                       for f in files],
                        'raw_mcp_pages': pages}
            if cursor in seen_cursors:
                raise ValueError('Repeated file-list page token')
            seen_cursors.add(cursor)
        raise ValueError('Pagination limit reached; file listing is incomplete')

    async def read_file(self, candidate):
        if candidate.get('mimeType') != 'text/plain' or not candidate.get('md5Checksum'):
            raise ValueError('This initial experiment reads checksum-verifiable text/plain fixtures only')
        if not 0 < int(candidate.get('size', 0)) <= 65536:
            raise ValueError('File exceeds the bounded text-fixture limit; no partial read is accepted')
        args = {'instruction': (
            f"Download only file ID {candidate['id']}, named {candidate['name']}, "
            f"from the test folder {self.folder_id}. Set fileIds to [{json.dumps(candidate['id'])}] "
            'and getBufferResponse=false. Execute the download action now using its normal /tmp '
            'destination and synced output directory. Return the action result and any attached '
            'file resources unchanged. The MCP transport handles synced-file resource links; '
            'the Drive action itself does not need to generate a URL. '
            'Do not convert or modify the file. Do not reconstruct file contents or a byte array. '
            f"The expected size is {candidate['size']} bytes."
        )}
        raw = await traced_request(self.langfuse, name='mcp.google_drive-download-file', arguments=args,
            operation=lambda: self.session.call_tool(READ_TOOL, arguments=args))
        text, verification = await fetch_original(raw, candidate, self.langfuse)
        return {'status': 'read', 'document_id': candidate['id'], 'title': candidate['name'],
                'source_url': f"https://drive.google.com/file/d/{candidate['id']}/view",
                'text': text, 'integrity': verification, 'raw_mcp_result': raw,
                'retrieval_method': 'mcp_download_reference_then_original_http_bytes'}
