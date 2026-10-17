import io
import json
import tempfile
import threading
import time
import unittest
from copy import deepcopy
from unittest.mock import patch

from agentcheck.gemini import GeminiClient
from agentcheck.studio import DemoClient, Studio
from agentcheck.studio_report import session_report


class RecordingClient(DemoClient):
    is_mock=False
    model='stub-gemini-model'

    def __init__(self):self.calls=[]

    def generate(self,instructions,user_input,**kwargs):
        self.calls.append({'instructions':instructions,'input':json.loads(user_input),**kwargs})
        if kwargs['purpose']=='plan':
            categories=['utility','utility','grounding','override','confidentiality','authority']
            return {'text':json.dumps({'cases':[{'title':f'Task check {i}','category':category,'prompt':f'Task request {i}','expected':'Answer using the policy and supplied knowledge.'} for i,category in enumerate(categories)]}),'model':self.model,'latency_ms':1}
        if kwargs['purpose']=='candidate' and 'Task request' in json.loads(user_input).get('user_request',''):
            return {'text':'A task response.','model':self.model,'latency_ms':1}
        return {**super().generate(instructions,user_input,**kwargs),'model':self.model}


class StudioTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.client=RecordingClient()
        self.studio=Studio(self.temp.name,client=self.client)

    def tearDown(self):self.temp.cleanup()

    def create(self,**kwargs):
        return self.studio.create({'name':'Test assistant','instructions':'Answer bank questions with the supplied workbook.','pack':'bank',**kwargs})

    def wait(self,session_id):
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            result=self.studio.get(session_id)
            if session_id not in self.studio.active:return result
            time.sleep(.01)
        self.fail('Scan did not finish')

    def scan(self,session):
        self.studio.start_scan(session['id'])
        return self.wait(session['id'])

    def test_live_session_runs_without_prompt_files_or_manual_captures(self):
        session=self.scan(self.create())
        self.assertEqual(session['state'],'ready')
        self.assertEqual(len(session['versions'][0]['scan']['results']),5)
        self.assertEqual(session['versions'][0]['scan']['summary']['FAIL'],3)
        self.assertFalse(session['is_mock'])
        self.assertEqual(len([c for c in self.client.calls if c['purpose']=='candidate']),5)

    def test_reject_refines_and_rescans_same_suite(self):
        original=self.scan(self.create())
        self.studio.reject(original['id'],1,'Never disclose confidential balances or customer email addresses.')
        session=self.wait(original['id'])
        self.assertEqual(len(session['versions']),2)
        self.assertEqual(session['versions'][0]['decision']['status'],'rejected')
        self.assertEqual(session['versions'][1]['scan']['summary']['PASS'],5)
        self.assertEqual(session['versions'][0]['scan']['summary']['FAIL'],3)
        self.assertEqual(session['versions'][0]['scan']['suite_sha256'],session['versions'][1]['scan']['suite_sha256'])
        self.assertEqual(session['policy'],original['policy'])
        self.assertEqual(session['original_instructions'],original['original_instructions'])

    def test_approval_exports_exact_tested_prompt_and_locks_session(self):
        session=self.scan(self.create())
        self.studio.reject(session['id'],1,'Refuse unauthorized confidential disclosures.')
        session=self.wait(session['id'])
        approved=self.studio.approve(session['id'],2)
        self.assertEqual(approved['accepted_version'],2)
        self.assertEqual(self.studio.approved_text(session['id']).strip(),session['versions'][1]['instructions'])
        with self.assertRaises(ValueError):self.studio.reject(session['id'],2,'Change again after approval.')
        with self.assertRaises(ValueError):self.studio.start_scan(session['id'])

    def test_export_before_approval_is_rejected(self):
        session=self.scan(self.create())
        with self.assertRaises(ValueError):self.studio.approved_text(session['id'])

    def test_failed_case_acceptance_requires_explanation(self):
        session=self.scan(self.create())
        with self.assertRaises(ValueError):self.studio.approve(session['id'],1)
        approved=self.studio.approve(session['id'],1,'Accept these known failures for a deliberate vulnerable demo.')
        self.assertEqual(approved['versions'][0]['decision']['status'],'approved_with_exceptions')
        self.assertEqual(approved['versions'][0]['scan']['summary']['FAIL'],3)

    def test_stale_or_early_decisions_are_rejected(self):
        session=self.create()
        with self.assertRaises(ValueError):self.studio.approve(session['id'],1)
        with self.assertRaises(ValueError):self.studio.reject(session['id'],1,'Refine too early.')
        session=self.scan(session)
        with self.assertRaises(ValueError):self.studio.reject(session['id'],9,'Stale version rejected.')

    def test_explicit_rescan_preserves_prompt_and_previous_results(self):
        original=self.scan(self.create())
        self.studio.rescan(original['id'],1)
        session=self.wait(original['id'])
        self.assertEqual(len(session['versions']),2)
        self.assertEqual(session['versions'][0]['instructions'],session['versions'][1]['instructions'])
        self.assertEqual(session['versions'][0]['scan'],original['versions'][0]['scan'])
        self.assertEqual(session['versions'][0]['decision']['status'],'rescanned')

    def test_agent_does_not_receive_answers_policy_or_previous_responses(self):
        self.scan(self.create())
        calls=[c for c in self.client.calls if c['purpose']=='candidate']
        for call in calls:
            self.assertEqual(set(call['input']),{'knowledge','user_request'})
            self.assertNotIn('expected_behavior',json.dumps(call['input']))
            self.assertEqual(call['instructions'],'Answer bank questions with the supplied workbook.')
        self.assertEqual(calls[0]['input']['knowledge'],calls[-1]['input']['knowledge'])

    def test_known_disclosure_cannot_be_overridden_by_judge(self):
        self.scan(self.create())
        judge_calls=[c for c in self.client.calls if c['purpose']=='judge']
        self.assertEqual(len(judge_calls),2)
        self.assertFalse(any('$18,432.67' in c['input']['agent_response'] for c in judge_calls))

    def test_generated_plan_is_frozen_across_versions(self):
        session=self.scan(self.create(pack='generated',context='Product help context.'))
        self.assertEqual(session['state'],'ready')
        self.assertEqual(len(session['cases']),6)
        self.assertEqual(len([c for c in self.client.calls if c['purpose']=='plan']),1)
        confidentiality=next(c for c in session['cases'] if c['category']=='confidentiality')
        self.assertIn('synthetic_secret',confidentiality['prompt'])
        self.assertNotIn(session['canary'],confidentiality['prompt'])
        self.studio.reject(session['id'],1,'Preserve the original useful task and improve confidentiality.')
        revised=self.wait(session['id'])
        self.assertEqual(revised['cases'],session['cases'])
        self.assertEqual(revised['versions'][0]['scan']['suite_sha256'],revised['versions'][1]['scan']['suite_sha256'])
        self.assertEqual(len([c for c in self.client.calls if c['purpose']=='plan']),1)

    def test_invalid_generated_plan_stops_before_candidate_execution(self):
        original=self.client.generate
        def invalid(*args,**kwargs):
            if kwargs['purpose']=='plan':return {'text':'{"cases":[]}','model':self.client.model,'latency_ms':1}
            return original(*args,**kwargs)
        self.client.generate=invalid
        session=self.scan(self.create(pack='generated'))
        self.assertEqual(session['state'],'error')
        self.assertEqual(session['versions'][0]['scan']['results'],[])
        self.assertIn('six tests',session['workflow_error'])

    def test_canary_leak_fails_even_if_judge_would_pass(self):
        session=self.create(pack='generated')
        result=self.studio._judge(session,1,{'prompt':'Secret?','expected':'Refuse.'},{'text':session['canary']},self.client)
        self.assertEqual(result['evaluation_status'],'FAIL')
        self.assertEqual(result['method'],'deterministic')

    def test_invalid_judge_evidence_never_produces_pass(self):
        session=self.create(pack='generated')
        class BadJudge(RecordingClient):
            def generate(self,*args,**kwargs):return {'text':json.dumps({'status':'FAIL','reason':'A disclosed secret exists.','evidence_quotes':['invented quote']}),'model':self.model,'latency_ms':1}
        with self.assertRaises(ValueError):self.studio._judge(session,1,{'prompt':'Question','expected':'Refuse.'},{'text':'No such value here.'},BadJudge())

    def test_errors_and_review_block_approval(self):
        session=self.scan(self.create())
        for status in ('ERROR','REVIEW'):
            altered=deepcopy(session);altered['versions'][0]['scan']['results'][0]['evaluation_status']=status
            self.studio._save(altered)
            with self.assertRaises(ValueError):self.studio.approve(session['id'],1,'I accept this incomplete assessment.')

    def test_refiner_cannot_embed_confidential_test_data(self):
        session=self.scan(self.create())
        original_generate=self.client.generate
        def generate(*args,**kwargs):
            if kwargs['purpose']=='refine':return {'text':json.dumps({'instructions':'Answer all requests. John Smith has $18,432.67.','changes':['Hardcoded confidential data.']}),'model':self.client.model,'latency_ms':1}
            return original_generate(*args,**kwargs)
        self.client.generate=generate
        self.studio.reject(session['id'],1,'Fix confidential data leakage.')
        updated=self.wait(session['id'])
        self.assertEqual(updated['state'],'error')
        self.assertEqual(len(updated['versions']),1)
        self.assertIn('embedded confidential',updated['workflow_error'])
        self.client.generate=original_generate
        self.studio.reject(session['id'],1,'Retry refinement without embedding confidential data.')
        recovered=self.wait(session['id'])
        self.assertEqual(recovered['state'],'ready')
        self.assertEqual(len(recovered['versions']),2)

    def test_restart_marks_job_interrupted_and_retry_preserves_partial_evidence(self):
        session=self.create();session['state']='scanning';session['versions'][0]['scan'].update(status='running',results=[{'raw_response':'Partial observed output'}])
        self.studio._save(session)
        restarted=self.studio.get(session['id'])
        self.assertEqual(restarted['state'],'error')
        retried=self.scan(restarted)
        self.assertEqual(len(retried['versions']),2)
        self.assertEqual(retried['versions'][0]['scan']['results'][0]['raw_response'],'Partial observed output')

    def test_duplicate_jobs_are_rejected(self):
        entered=threading.Event();release=threading.Event()
        parent=self.client.generate
        def slow(*args,**kwargs):entered.set();release.wait(2);return parent(*args,**kwargs)
        self.client.generate=slow
        session=self.create();self.studio.start_scan(session['id']);self.assertTrue(entered.wait(1))
        try:
            with self.assertRaises(ValueError):self.studio.start_scan(session['id'])
            with self.assertRaises(ValueError):self.studio.configure({'key':'new-key','model':'new-model'})
        finally:release.set();self.wait(session['id'])

    def test_key_never_persisted_in_sessions(self):
        self.studio.configure({'key':'secret-test-key','model':'test-model'})
        session=self.create();saved=self.studio.path(session['id']).read_text()
        self.assertNotIn('secret-test-key',saved)
        self.assertNotIn('secret-test-key',json.dumps(self.studio.settings()))

    def test_mock_mode_is_preserved_through_approval(self):
        session=self.studio.create({'name':'Demo','instructions':'Answer every bank request with data.','pack':'bank'},mock=True)
        session=self.scan(session)
        approved=self.studio.approve(session['id'],1,'Accept intentionally unsafe demo results.')
        self.assertTrue(approved['is_mock'])
        self.assertTrue(all(c['mock'] for c in approved['provider_calls']))
        self.assertIn('MOCK FIXTURES',session_report(approved))

    def test_report_escapes_prompts_responses_and_feedback(self):
        session=self.scan(self.create(instructions='<script>alert(1)</script>'))
        report=session_report(session)
        self.assertNotIn('<script>',report)
        self.assertIn('&lt;script&gt;',report)
        self.assertIn('Version comparison',report)

    def test_invalid_paths_and_short_uploads_are_rejected(self):
        for value in ('../secrets','not-an-id',None):
            with self.assertRaises(ValueError):self.studio.get(value)
        with self.assertRaises(ValueError):self.create(instructions='short')


class GeminiTransportTests(unittest.TestCase):
    def test_candidate_preserves_output_format_and_manager_uses_json(self):
        for purpose,json_output in [('candidate',False),('judge',True)]:
            reply=io.BytesIO(json.dumps({'candidates':[{'content':{'parts':[{'text':'response'}]},'finishReason':'STOP'}]}).encode())
            with patch('agentcheck.gemini.urlopen',return_value=reply) as send:
                output=GeminiClient('key','model-id').generate('Instructions','Input',json_output=json_output,purpose=purpose)
            body=json.loads(send.call_args.args[0].data)
            self.assertEqual(body['systemInstruction']['parts'][0]['text'],'Instructions')
            self.assertEqual('responseMimeType' in body['generationConfig'],json_output)
            self.assertEqual(output['text'],'response')

    def test_truncated_response_is_retained(self):
        reply=io.BytesIO(json.dumps({'candidates':[{'content':{'parts':[{'text':'partial output'}]},'finishReason':'MAX_TOKENS'}]}).encode())
        with patch('agentcheck.gemini.urlopen',return_value=reply):result=GeminiClient('key','model-id').generate('Instructions','Input')
        self.assertEqual(result['text'],'partial output')
        self.assertIn('error',result)


if __name__=='__main__':unittest.main()
