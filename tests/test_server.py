import io
import json
import threading
import unittest
from contextlib import contextmanager
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from agentcheck.adapters import call_api
from agentcheck.dataset import load_dataset
from agentcheck.server import make_server


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


if __name__=='__main__':unittest.main()
