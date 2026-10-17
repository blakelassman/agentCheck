"""Private immutable Blob snapshots, isolated by a browser's opaque owner token."""
from copy import deepcopy
import json
import re
import time
from uuid import uuid4

from vercel.blob import sync as blob

from .runner import now
from .studio import Studio


class BlobStore:
    def prefix(self, owner, session_id=None):
        if not re.fullmatch(r'[a-f0-9]{64}', owner):
            raise ValueError('Invalid session owner.')
        if session_id is not None and not re.fullmatch(r'[a-f0-9]{32}', session_id):
            raise ValueError('Invalid session identifier.')
        return f'sessions/{owner}/' + (session_id + '/' if session_id else '')

    def save(self, owner, session):
        path = self.prefix(owner, session['id']) + f'{time.time_ns():020d}-{uuid4().hex}.json'
        blob.put_blob(path, json.dumps(session, ensure_ascii=False).encode(), access='private', content_type='application/json')

    def load(self, owner, session_id):
        entries = [entry for entry in blob.query_blobs(prefix=self.prefix(owner, session_id)) if entry.pathname.endswith('.json')]
        if not entries:
            raise ValueError('Session not found in this browser.')
        latest = max(entries, key=lambda entry: entry.pathname)
        # Immutable paths avoid cached reads of overwritten session documents.
        return json.loads(blob.get_blob(latest.pathname, access='private').body)

    def history(self, owner):
        latest = {}
        for entry in blob.query_blobs(prefix=self.prefix(owner)):
            parts = entry.pathname.split('/')
            if len(parts) != 4 or not parts[-1].endswith('.json'):
                continue
            if parts[2] not in latest or entry.pathname > latest[parts[2]].pathname:
                latest[parts[2]] = entry
        selected = sorted(latest.values(), key=lambda entry: entry.pathname.split('/')[-1], reverse=True)[:50]
        rows = []
        for entry in selected:
            session = json.loads(blob.get_blob(entry.pathname, access='private').body)
            rows.append({key: session[key] for key in ('id', 'name', 'updated_at', 'state', 'is_mock', 'pack', 'accepted_version')})
        return rows

    def claim(self, owner, session_id):
        path = self.prefix(owner, session_id) + 'operation.lock'
        try:
            blob.put_blob(path, b'operation in progress', access='private', allow_overwrite=False)
        except blob.BlobError as error:
            if error.status_code in (409,412) or 'already exists' in str(error).lower():
                raise ValueError('This session already has an operation in progress.') from None
            raise

    def set_run(self, owner, session_id, job_id, run_id):
        path = f'runs/{owner}/{session_id}/{job_id}.json'
        blob.put_blob(path, json.dumps({'run_id': run_id}).encode(), access='private')

    def get_run(self, owner, session_id, job_id):
        try:
            return json.loads(blob.get_blob(f'runs/{owner}/{session_id}/{job_id}.json', access='private').body)['run_id']
        except blob.BlobNotFoundError:
            return None

    def release(self, owner, session_id):
        blob.delete_blob(self.prefix(owner, session_id) + 'operation.lock')


class HostedStudio(Studio):
    def __init__(self, owner, store=None, client=None):
        super().__init__(client=client)
        self.owner = owner
        self.store = store or BlobStore()

    def _read(self, session_id):
        self.path(session_id)  # Validate identifiers using the shared rules.
        return self.store.load(self.owner, session_id)

    def _save(self, session):
        session['updated_at'] = now()
        self.store.save(self.owner, session)

    def get(self, session_id):
        return deepcopy(self._read(session_id))

    def history(self):
        return self.store.history(self.owner)

    def _launch(self, *_):
        # The HTTP route registers durable work instead of starting a daemon thread.
        pass
