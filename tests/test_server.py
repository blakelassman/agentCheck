import io
import json
import threading
import tempfile
import time
import unittest
from contextlib import contextmanager
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from agentcheck.adapters import call_api
from agentcheck.dataset import load_dataset
from agentcheck.server import make_server
from agentcheck.studio import Studio, DemoClient


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server=make_server(0)
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
        cls.base=f'http://127.0.0.1:{cls.server.server_port}'
        with urlopen(cls.base+'/api/bootstrap') as r:cls.bootstrap=json.load(r)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close();cls.thread.join()

    def post(self,path,payload,token=True):
        headers={'Content-Type':'application/json'}
        if token:headers['X-AgentCheck-Token']=self.bootstrap['token']
        return urlopen(Request(self.base+path,data=json.dumps(payload).encode(),headers=headers))

    def test_bootstrap_has_suite_and_no_secrets(self):
        self.assertEqual(len(self.bootstrap['cases']),5)
        self.assertNotIn('api_key',json.dumps(self.bootstrap).lower())

    def test_web_assets_and_route_traversal(self):
        for route in ('/','/app.js','/styles.css'):
            with self.subTest(route=route),urlopen(self.base+route) as r:self.assertEqual(r.status,200)
        with self.assertRaises(HTTPError) as caught:urlopen(self.base+'/../../LICENSE')
        self.assertEqual(caught.exception.code,404)

    def test_cross_origin_or_missing_token_rejected(self):
        with self.assertRaises(HTTPError) as caught:self.post('/api/demo',{},False)
        self.assertEqual(caught.exception.code,403)
        request=Request(self.base+'/api/demo',data=b'{}',headers={'X-AgentCheck-Token':self.bootstrap['token'],'Origin':'https://attacker.example'})
        with self.assertRaises(HTTPError) as caught:urlopen(request)
        self.assertEqual(caught.exception.code,403)

    def test_evaluate_validates_payload_and_returns_ten_rows(self):
        with patch('agentcheck.server.persist_run',side_effect=lambda run:run):
            with self.post('/api/evaluate',self.bootstrap['capture']) as r:
                run=json.load(r)
            self.assertEqual(len(run['results']),10)
            self.assertEqual(run['summary']['protected_agent']['PENDING'],5)
        with self.assertRaises(HTTPError) as caught:self.post('/api/evaluate',{'schema_version':99})
        self.assertEqual(caught.exception.code,400)

    def test_bad_capture_shapes_return_validation_error(self):
        payload={**self.bootstrap['capture'],'captures':[None]}
        with self.assertRaises(HTTPError) as caught:self.post('/api/evaluate',payload)
        self.assertEqual(caught.exception.code,400)

    def test_api_error_is_preserved_as_capture_error(self):
        with patch('agentcheck.server.call_api',side_effect=ValueError('Timeout')):
            with self.post('/api/run-case',{'agent_id':'protected_agent','test_id':'T01'}) as r:result=json.load(r)
        self.assertEqual(result['error'],'Timeout')
        self.assertEqual(result['raw_response'],'')


class AdapterTests(unittest.TestCase):
    def test_stateless_shared_context_without_answer_keys(self):
        fake=io.BytesIO(json.dumps({'candidates':[{'content':{'parts':[{'thought':True,'text':'hidden thought'},{'text':'{"answer":"Hello"}'}]},'finishReason':'STOP'}]}).encode())
        with patch.dict('os.environ',{'GEMINI_API_KEY':'test-key','GEMINI_MODEL':'test-model'}),patch('agentcheck.adapters.api_status',return_value={'ready':True}),patch('pathlib.Path.read_text',return_value='Partner instruction'),patch('agentcheck.adapters.urlopen',return_value=fake) as send:
            result=call_api('protected_agent','Request',load_dataset())
        self.assertEqual(result['raw_response'],'{"answer":"Hello"}')
        body=json.loads(send.call_args.args[0].data)
        self.assertEqual(len(body['contents']),1)
        self.assertNotIn('Unauthorized balance',json.dumps(body))
        self.assertNotIn('expected_behavior',json.dumps(body))
        self.assertIn('DEMO-A001',json.dumps(body))

    def test_unknown_agent_is_rejected(self):
        with patch('agentcheck.adapters.api_status',return_value={'ready':True}),self.assertRaises(ValueError):call_api('unknown','test',load_dataset())


class StudioRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        class StubClient(DemoClient):
            is_mock=False
            model='stubbed-provider'
        cls.temp=tempfile.TemporaryDirectory()
        cls.studio=Studio(cls.temp.name,client=StubClient())
        cls.server=make_server(0,studio=cls.studio)
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
        cls.base=f'http://127.0.0.1:{cls.server.server_port}'
        with urlopen(cls.base+'/api/studio/bootstrap') as response:cls.bootstrap=json.load(response)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close();cls.thread.join();cls.temp.cleanup()

    def post(self,route,payload):
        request=Request(self.base+route,data=json.dumps(payload).encode(),headers={'X-AgentCheck-Token':self.bootstrap['token'],'Content-Type':'application/json'})
        with urlopen(request) as response:return json.load(response)

    def wait(self,session_id):
        deadline=time.monotonic()+3
        while time.monotonic()<deadline:
            with urlopen(self.base+'/api/studio/session/'+session_id) as response:session=json.load(response)
            if session_id not in self.studio.active:return session
            time.sleep(.01)
        self.fail('Background job did not complete')

    def test_http_upload_scan_reject_rescan_approve_and_export(self):
        session=self.post('/api/studio/sessions',{'name':'Uploaded assistant','instructions':'Answer all questions using the bank workbook.','pack':'bank'})
        session=self.wait(session['id']);prefix='/api/studio/session/'+session['id']
        self.assertEqual(session['versions'][0]['scan']['summary']['FAIL'],3)
        with self.assertRaises(HTTPError):urlopen(self.base+prefix+'/instructions')
        self.post(prefix+'/reject',{'version':1,'feedback':'Protect bank customer information and keep public answers useful.'})
        revised=self.wait(session['id'])
        self.assertEqual(revised['versions'][1]['scan']['summary']['PASS'],5)
        approved=self.post(prefix+'/approve',{'version':2,'note':''})
        with urlopen(self.base+prefix+'/instructions') as response:text=response.read().decode()
        self.assertEqual(text.strip(),approved['versions'][1]['instructions'])
        with urlopen(self.base+prefix+'/report') as response:report=response.read().decode()
        self.assertIn('Version comparison',report)
        self.assertIn('rejected',report)
        self.assertNotIn('MOCK FIXTURES',report)

    def test_http_upload_over_old_one_megabyte_limit_and_invalid_upload(self):
        import base64
        import io
        import zipfile
        # Large but valid office upload: unused attachment bytes do not become model text.
        data=io.BytesIO()
        with zipfile.ZipFile(data,'w') as archive:
            archive.writestr('word/document.xml','<w:document xmlns:w="urn:word"><w:p><w:r><w:t>Private bank context</w:t></w:r></w:p></w:document>')
            archive.writestr('word/media/unused.bin',b'x'*900000)
        session=self.post('/api/studio/sessions',{'instructions':'Answer bank questions using the data.','context_files':[{'name':'context.docx','data_base64':base64.b64encode(data.getvalue()).decode()}]})
        self.wait(session['id'])
        self.assertEqual(session['context_files'][0]['text'],'Private bank context')
        with self.assertRaises(HTTPError) as caught:
            self.post('/api/studio/sessions',{'instructions':'Answer questions using the data.','context_files':[{'name':'broken.xlsx','data_base64':'eA=='}]})
        self.assertEqual(caught.exception.code,400)

    def test_ui_has_no_user_credentials_or_provider_choice(self):
        with urlopen(self.base+'/') as response:page=response.read().decode()
        for removed in ('id="api-key"','id="source-provider"','id="connection-dialog"','<option>Claude'):
            self.assertNotIn(removed,page)
        self.assertIn('Gemini · AgentCheck API',page)

    def test_http_demo_is_labeled_and_history_is_available(self):
        session=self.post('/api/studio/demo',{})
        result=self.wait(session['id'])
        self.assertTrue(result['is_mock'])
        with urlopen(self.base+'/api/studio/history') as response:history=json.load(response)
        self.assertTrue(any(row['id']==session['id'] for row in history))

    def test_studio_and_legacy_assets_load(self):
        for path in ('/','/studio.js','/studio.css','/legacy'):
            with self.subTest(path=path),urlopen(self.base+path) as response:self.assertEqual(response.status,200)

    def test_invalid_connection_and_version_are_errors(self):
        with self.assertRaises(HTTPError) as caught:self.post('/api/studio/config',{'key':'fake-key','model':'invalid/model'})
        self.assertEqual(caught.exception.code,404)
        session=self.post('/api/studio/demo',{});self.wait(session['id'])
        with self.assertRaises(HTTPError) as caught:self.post('/api/studio/session/'+session['id']+'/approve',{'version':True})
        self.assertEqual(caught.exception.code,400)


if __name__=='__main__':unittest.main()
