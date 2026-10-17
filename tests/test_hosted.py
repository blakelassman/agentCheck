"""Hosted boundary and durable-stage tests; transport/storage are injected."""
import base64
from copy import deepcopy
import json
import os
import unittest
from unittest.mock import patch

try:
    from fastapi.testclient import TestClient
    from agentcheck.hosted import create_app
    from agentcheck.hosted_jobs import execute_stage
    from agentcheck.hosted_store import HostedStudio, BlobStore
    from test_studio import RecordingClient
    HOSTED_AVAILABLE=True
except ImportError:
    HOSTED_AVAILABLE=False


class MemoryStore:
    def __init__(self):self.rows={};self.locks=set();self.runs={}
    def save(self,owner,session):self.rows[(owner,session['id'])]=deepcopy(session)
    def load(self,owner,session_id):
        if (owner,session_id) not in self.rows:raise ValueError('Session not found in this browser.')
        return deepcopy(self.rows[(owner,session_id)])
    def history(self,owner):return [deepcopy(s) for (o,_),s in self.rows.items() if o==owner]
    def claim(self,owner,session_id):
        if (owner,session_id) in self.locks:raise ValueError('This session already has an operation in progress.')
        self.locks.add((owner,session_id))
    def release(self,owner,session_id):self.locks.discard((owner,session_id))
    def set_run(self,owner,session_id,job_id,run_id):self.runs[(owner,session_id,job_id)]=run_id
    def get_run(self,owner,session_id,job_id):return self.runs.get((owner,session_id,job_id))


@unittest.skipUnless(HOSTED_AVAILABLE,'Install hosted dependencies to run hosting tests.')
class HostedTests(unittest.TestCase):
    def setUp(self):
        self.env=patch.dict(os.environ,{'AGENTCHECK_SESSION_SECRET':'test-session-secret'});self.env.start()
        self.store=MemoryStore();self.transport=RecordingClient()
        async def start(fn,owner,session_id,job_id,operation):
            for stage in (['refine'] if operation=='refine' else [])+['prepare']+[f'case:{i}' for i in range(6)]+['complete']:
                if not execute_stage(owner,session_id,job_id,stage,store=self.store,client=self.transport):break
            return type('Run',(),{'run_id':'test-run'})()
        self.app=create_app(store=self.store,start_workflow=start,client=self.transport)
        self.browser=TestClient(self.app)
        self.bootstrap=self.browser.get('/api/studio/bootstrap').json()
        self.headers={'X-AgentCheck-Token':self.bootstrap['token']}

    def tearDown(self):self.browser.close();self.env.stop()

    def post(self,route,payload):return self.browser.post('/api/studio/'+route,json=payload,headers=self.headers)

    def test_hosted_upload_scan_refine_approve_export(self):
        response=self.post('sessions',{'instructions':'Answer bank questions using the supplied workbook.','context_files':[{'name':'notes.md','data_base64':base64.b64encode(b'Private records are confidential.').decode()}]})
        self.assertEqual(response.status_code,200,response.text)
        session=response.json();session_id=session['id']
        self.assertEqual(session['state'],'ready')
        self.assertEqual(session['versions'][0]['scan']['summary']['FAIL'],3)
        self.assertFalse(self.store.locks)
        revised=self.post(f'session/{session_id}/reject',{'version':1,'feedback':'Require verified authorization before disclosing customer records.'}).json()
        self.assertEqual(revised['versions'][-1]['scan']['summary']['PASS'],5)
        self.assertEqual(revised['context_files'],session['context_files'])
        approved=self.post(f'session/{session_id}/approve',{'version':2}).json()
        self.assertEqual(approved['state'],'approved')
        self.assertIn('verified authorization',self.browser.get(f'/api/studio/session/{session_id}/instructions').text)
        report=self.browser.get(f'/api/studio/session/{session_id}/report').text
        self.assertIn('notes.md',report)
        self.assertIn('Version 2',report)

    def test_sessions_are_isolated_between_browsers(self):
        session=self.post('demo',{}).json()
        other=TestClient(self.app)
        self.assertEqual(other.get('/api/studio/history').json(),[])
        self.assertEqual(other.get('/api/studio/session/'+session['id']).status_code,400)
        other.close()
        self.assertEqual(self.browser.get('/api/studio/session/'+session['id']).status_code,200)

    def test_missing_or_foreign_csrf_and_origin_are_rejected(self):
        self.assertEqual(self.browser.post('/api/studio/demo',json={}).status_code,403)
        self.assertEqual(self.browser.post('/api/studio/demo',json={},headers={**self.headers,'Origin':'https://attacker.example'}).status_code,403)
        self.assertEqual(self.browser.post('/api/studio/demo',json={},headers={'X-AgentCheck-Token':'incorrect'}).status_code,403)

    def test_upload_limit_and_no_user_configuration(self):
        too_large=base64.b64encode(b'x'*(2*1024*1024+1)).decode()
        response=self.post('sessions',{'instructions':'Answer questions using context.','context_files':[{'name':'large.docx','data_base64':too_large}]})
        self.assertIn(response.status_code,(400,413))
        self.assertEqual(self.post('config',{'key':'user-key','model':'other'}).status_code,404)
        self.assertNotIn('user-key',json.dumps(self.store.rows,default=str))

    def test_duplicate_jobs_and_stage_replay_do_not_repeat_model_calls(self):
        owner='a'*64;studio=HostedStudio(owner,store=self.store,client=self.transport)
        session=studio.create({'instructions':'Answer bank requests using the workbook.'})
        session['host_job']={'id':'test-job','completed_stages':[]};studio._save(session)
        self.store.claim(owner,session['id'])
        with self.assertRaises(ValueError):self.store.claim(owner,session['id'])
        execute_stage(owner,session['id'],'test-job','prepare',store=self.store,client=self.transport)
        execute_stage(owner,session['id'],'test-job','case:0',store=self.store,client=self.transport)
        count=len(self.transport.calls)
        execute_stage(owner,session['id'],'test-job','case:0',store=self.store,client=self.transport)
        self.assertEqual(len(self.transport.calls),count)
        with self.assertRaises(ValueError):execute_stage(owner,session['id'],'stale-job','case:1',store=self.store,client=self.transport)

    def test_workflow_module_imports_inside_the_real_sdk_sandbox(self):
        import importlib
        from agentcheck.hosted_jobs import wf
        with wf._get_sandbox() as sandbox:
            with sandbox.enter():
                module=importlib.import_module('agentcheck.hosted_jobs')
                self.assertTrue(hasattr(module,'scan_workflow'))

    def test_missing_signing_configuration_blocks_operations(self):
        with patch.dict(os.environ,{'AGENTCHECK_SESSION_SECRET':''}):
            self.assertFalse(self.browser.get('/api/studio/bootstrap').json()['config']['ready'])
            self.assertEqual(self.post('demo',{}).status_code,503)

    def test_immutable_blob_reader_ignores_operation_lock(self):
        from types import SimpleNamespace
        from agentcheck import hosted_store
        entries=[SimpleNamespace(pathname='sessions/'+'a'*64+'/deadbeef/'+'0001.json'),SimpleNamespace(pathname='sessions/'+'a'*64+'/deadbeef/operation.lock')]
        with patch.object(hosted_store.blob,'query_blobs',return_value=iter(entries)),patch.object(hosted_store.blob,'get_blob',return_value=SimpleNamespace(body=b'{"name":"saved"}')) as read:
            value=BlobStore().load('a'*64,'b'*32)
        self.assertEqual(value['name'],'saved')
        self.assertTrue(read.call_args.args[0].endswith('0001.json'))


if __name__=='__main__':unittest.main()
