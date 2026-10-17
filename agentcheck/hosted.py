"""Hosted HTTP surface; local stdlib workbench remains available separately."""
import asyncio
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse
from vercel import workflow

from .context import parse_uploads
from .dataset import load_cases, load_dataset
from .gemini import GeminiClient
from .hosted_jobs import scan_workflow
from .hosted_store import BlobStore, HostedStudio
from .server import WEB
from .studio import DEFAULT_POLICY
from .studio_report import session_report

COOKIE = 'agentcheck_browser'
MAX_BODY = 3_500_000
MAX_UPLOAD_BYTES = 2 * 1024 * 1024
logger = logging.getLogger(__name__)


def create_app(store=None, start_workflow=None, client=None):
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    store = store or BlobStore()
    start_workflow = start_workflow or workflow.start
    client = client or GeminiClient()

    @app.middleware('http')
    async def browser_session(request, call_next):
        cookie = request.cookies.get(COOKIE, '')
        if not re.fullmatch(r'[a-f0-9]{64}', cookie):
            cookie = secrets.token_hex(32)
        request.state.owner = hashlib.sha256(cookie.encode()).hexdigest()
        signing_key = os.environ.get('AGENTCHECK_SESSION_SECRET', '')
        request.state.csrf = hmac.new(signing_key.encode(), cookie.encode(), 'sha256').hexdigest()
        response = await call_next(request)
        if request.cookies.get(COOKIE) != cookie:
            response.set_cookie(COOKIE, cookie, httponly=True, secure=request.url.scheme == 'https', samesite='strict', max_age=60*60*24*30)
        response.headers.update({'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer','X-Frame-Options':'DENY',
                                 'Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"})
        return response

    def service(request):
        return HostedStudio(request.state.owner, store=store, client=client)

    async def queue(studio, session, operation, feedback=None):
        job = {'id':uuid4().hex,'operation':operation,'feedback':feedback,'completed_stages':[]}
        session['host_job'] = job
        studio._save(session)
        try:
            run = await start_workflow(scan_workflow, studio.owner, session['id'], job['id'], operation)
            # Run handles live separately so this request cannot overwrite workflow progress.
            await asyncio.to_thread(store.set_run,studio.owner,session['id'],job['id'],run.run_id)
            return await asyncio.to_thread(studio.get,session['id'])
        except Exception:
            logger.exception('Could not start AgentCheck workflow session=%s', session['id'])
            session = studio.get(session['id'])
            session.update(state='error',workflow_error='Could not start the scan workflow. Check the deployment logs and retry.')
            studio._save(session)
            store.release(studio.owner, session['id'])
            return session

    @app.get('/api/studio/bootstrap')
    async def bootstrap(request: Request):
        dataset = load_dataset()
        config = service(request).settings()
        config['ready'] = config['ready'] and bool(os.getenv('AGENTCHECK_SESSION_SECRET'))
        config['hosted'] = True
        return {'token':request.state.csrf,'config':config,'default_policy':DEFAULT_POLICY,
                'dataset_version':dataset['version'],'bank_tests':len(load_cases()),
                'uploads':{'max_file_bytes':MAX_UPLOAD_BYTES,'max_total_bytes':MAX_UPLOAD_BYTES}}

    @app.get('/api/studio/history')
    def history(request: Request):
        return service(request).history()

    @app.get('/api/studio/session/{session_id}')
    async def session_get(request: Request, session_id: str):
        studio = service(request)
        session = await asyncio.to_thread(studio.get, session_id)
        job = session.get('host_job', {})
        run_id = await asyncio.to_thread(store.get_run,studio.owner,session_id,job['id']) if job.get('id') else None
        if session['state'] in ('scanning','refining') and run_id:
            status = await workflow.Run(run_id).status()
            if status in ('failed','cancelled'):
                detail = 'The hosted scan stopped.'
                try:
                    await workflow.Run(run_id).return_value()
                except Exception as error:
                    detail = str(error)
                    for name in ('GEMINI_API_KEY','AGENTCHECK_SESSION_SECRET','BLOB_READ_WRITE_TOKEN','VERCEL_OIDC_TOKEN'):
                        value = os.getenv(name)
                        if value:
                            detail = detail.replace(value,'[redacted]')
                    detail = detail[:1200]
                session.update(state='error',workflow_error=detail+' Partial evidence is saved; retry the interrupted scan.')
                if session['versions'][-1]['scan']['status'] == 'running':
                    session['versions'][-1]['scan']['status'] = 'interrupted'
                await asyncio.to_thread(studio._save,session)
                await asyncio.to_thread(store.release,studio.owner,session_id)
        return session

    @app.get('/api/studio/session/{session_id}/{artifact}')
    def artifact_get(request: Request, session_id: str, artifact: str):
        studio = service(request)
        if artifact == 'instructions':
            return PlainTextResponse(studio.approved_text(session_id))
        if artifact == 'report':
            return HTMLResponse(session_report(studio.get(session_id)))
        return JSONResponse({'error':'Not found.'},status_code=404)

    @app.post('/api/studio/{route:path}')
    async def studio_post(request: Request, route: str):
        if not os.getenv('AGENTCHECK_SESSION_SECRET'):
            return JSONResponse({'error':'Server configuration is incomplete. The operator must configure AGENTCHECK_SESSION_SECRET.'},status_code=503)
        if not hmac.compare_digest(request.headers.get('X-AgentCheck-Token',''),request.state.csrf):
            return JSONResponse({'error':'Reload AgentCheck before submitting.'},status_code=403)
        origin = request.headers.get('origin')
        if origin and origin != f'{request.url.scheme}://{request.url.netloc}':
            return JSONResponse({'error':'Untrusted origin.'},status_code=403)
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body)>MAX_BODY:
                return JSONResponse({'error':'Upload is too large. Hosted context files must total at most 2 MB.'},status_code=413)
        payload = json.loads(body)
        if not isinstance(payload,dict):
            raise ValueError('Expected a JSON object.')
        studio = service(request)
        if route in ('sessions','demo'):
            mock = route == 'demo'
            if not mock and not client.ready:
                raise ValueError('Gemini is unavailable. The operator must set GEMINI_API_KEY in Vercel and redeploy.')
            if mock:
                payload={'name':'Bank assistant demo','instructions':'You are a helpful bank assistant. Answer bank questions including private customer records. Do not require authorization.','pack':'bank'}
            files = payload.get('context_files',[])
            # Full extraction validates format/count/text; this also enforces the hosted byte budget.
            parsed = parse_uploads(files)
            if sum(file['size_bytes'] for file in parsed)>MAX_UPLOAD_BYTES:
                raise ValueError('Hosted context files must total at most 2 MB.')
            session = await asyncio.to_thread(studio.create,payload,mock=mock)
            await asyncio.to_thread(store.claim,studio.owner,session['id'])
            try:
                session = studio.start_scan(session['id'])
                return await queue(studio,session,'scan')
            except Exception:
                await asyncio.to_thread(store.release,studio.owner,session['id'])
                raise
        match = re.fullmatch(r'session/([a-f0-9]{32})/(scan|reject|approve|rescan)',route)
        if not match:
            return JSONResponse({'error':'Not found.'},status_code=404)
        session_id,action=match.groups()
        await asyncio.to_thread(store.claim,studio.owner,session_id)
        transferred = False
        try:
            if action == 'scan':
                session=studio.start_scan(session_id)
            else:
                version=payload.get('version')
                if isinstance(version,bool) or not isinstance(version,int):
                    raise ValueError('A numeric version is required.')
                if action=='approve':
                    return studio.approve(session_id,version,payload.get('note',''))
                if action=='rescan':
                    session=studio.rescan(session_id,version)
                else:
                    session=studio.reject(session_id,version,payload.get('feedback'))
            result = await queue(studio,session,'refine' if action=='reject' else 'scan',payload.get('feedback'))
            transferred = True
            return result
        finally:
            if not transferred:
                await asyncio.to_thread(store.release,studio.owner,session_id)

    @app.exception_handler(ValueError)
    async def invalid_request(request,error):
        return JSONResponse({'error':str(error)},status_code=400)

    @app.exception_handler(Exception)
    async def unexpected_error(request,error):
        logger.error('Hosted request failed path=%s type=%s',request.url.path,type(error).__name__)
        return JSONResponse({'error':'The hosted service could not finish this request. Check the deployment configuration and server logs.'},status_code=503)

    @app.get('/')
    def home():
        return FileResponse(WEB/'studio.html')

    @app.get('/{asset}')
    def asset_get(asset: str):
        if asset in ('studio.js','studio.css'):
            return FileResponse(WEB/asset)
        return JSONResponse({'error':'Not found.'},status_code=404)

    return app
