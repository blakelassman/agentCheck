import base64
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from agentcheck.context import parse_uploads
from agentcheck.gemini import GeminiClient
from agentcheck.studio import Studio
from test_studio import RecordingClient


def upload(name, data):
    return {'name': name, 'data_base64': base64.b64encode(data).decode()}


def docx(text):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as archive:
        archive.writestr('word/document.xml', '<w:document xmlns:w="urn:word"><w:body><w:p><w:r><w:t>' + text + '</w:t></w:r></w:p></w:body></w:document>')
    return stream.getvalue()


class ContextTests(unittest.TestCase):
    def test_excel_all_sheets_and_confidential_rows_are_extracted(self):
        data = (Path(__file__).parents[1] / 'data/AgentCheck_Bank_Data.xlsx').read_bytes()
        file = parse_uploads([upload('bank.xlsx', data)])[0]
        self.assertIn('Sheet: Customers', file['text'])
        self.assertIn('Sheet: Public_Info', file['text'])
        self.assertIn('maya.chen@example.com', file['text'])
        self.assertEqual(file['size_bytes'], len(data))
        self.assertEqual(len(file['sha256']), 64)

    def test_word_paragraphs(self):
        file = parse_uploads([upload('policy.docx', docx('Project ORION is confidential.'))])[0]
        self.assertEqual(file['text'], 'Project ORION is confidential.')

    def test_text_and_structured_formats(self):
        for name, data in [('notes.md', b'# Facts\nFee: $5'), ('data.csv', b'customer,balance\nDemo,42'), ('data.json', b'{"fee":5}'), ('data.tsv', b'a\tb'), ('notes.txt', b'Hello')]:
            with self.subTest(name=name):
                self.assertIn(data.decode(), parse_uploads([upload(name, data)])[0]['text'])

    def test_rejects_bad_binary_paths_formats_and_encoding(self):
        for item in [upload('../bad.md', b'x'), upload('run.exe', b'x'), upload('broken.xlsx', b'broken'), upload('bad.txt', b'\xff'), upload('bad.txt', b'a\x00b'), upload('bad.json', b'{'), {'name':'bad.md','data_base64':'!'}, upload('empty.md', b'  ')]:
            with self.subTest(name=item['name']), self.assertRaises(ValueError):
                parse_uploads([item])

    def test_limits_file_count_size_and_extracted_characters(self):
        for files in [[upload('a.txt', b'x')]*11, [upload('a.txt', b'x'*(5*1024*1024+1))], [upload('a.txt', b'x'*100001), upload('b.txt', b'y'*100000)]]:
            with self.assertRaises(ValueError):parse_uploads(files)

    def test_rejects_xml_entities_and_zip_expansion(self):
        stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w',compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('word/document.xml', b'<!DOCTYPE x [<!ENTITY a "secret">]><x>&a;</x>')
        with self.assertRaises(ValueError):parse_uploads([upload('entities.docx',stream.getvalue())])
        stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w',compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('word/document.xml', b'x'*(21*1024*1024))
        with self.assertRaises(ValueError):parse_uploads([upload('expanded.docx',stream.getvalue())])

    def test_legacy_formats_explain_missing_server_extractor(self):
        with patch('agentcheck.context.shutil.which', return_value=None):
            for suffix in ('.doc','.pdf'):
                with self.subTest(suffix=suffix),self.assertRaisesRegex(ValueError,'unavailable on this server'):
                    parse_uploads([upload('context'+suffix,b'data')])

    def test_owner_key_is_loaded_without_user_configuration(self):
        with patch.dict('os.environ', {'GEMINI_API_KEY':'owner-test-key'}, clear=True):
            studio=Studio()
        self.assertTrue(studio.settings()['ready'])
        self.assertEqual(studio.client.model,'gemini-3.8-flash')
        self.assertNotIn('owner-test-key',json.dumps(studio.settings()))
        self.assertFalse(hasattr(studio,'configure'))

    def test_files_reach_candidate_planner_and_judge_and_survive_reload(self):
        with tempfile.TemporaryDirectory() as directory:
            client=RecordingClient();studio=Studio(directory,client=client)
            session=studio.create({'instructions':'Answer questions using the provided facts.','pack':'generated','context_files':[upload('notes.docx',docx('Project ORION is confidential.'))]})
            studio._worker(session['id'],'scan',None,client)
            self.assertEqual(studio.get(session['id'])['state'],'ready')
            for purpose in ('candidate','plan','judge'):
                calls=[c for c in client.calls if c['purpose']==purpose]
                self.assertTrue(calls)
                self.assertTrue(all('Project ORION is confidential.' in json.dumps(c['input']) for c in calls))
            restarted=Studio(directory,client=client)
            self.assertEqual(restarted._knowledge(restarted.get(session['id']))['context_files'][0]['text'],'Project ORION is confidential.')
            studio._worker(session['id'],'refine','Protect confidential project details.',client)
            revised=studio.get(session['id'])
            self.assertEqual(len(revised['versions']),2)
            self.assertIn('Project ORION',json.dumps(client.calls[-1]['input']))
            self.assertEqual(revised['context_files'],session['context_files'])

    def test_bank_suite_also_receives_uploaded_workbook_and_notes(self):
        with tempfile.TemporaryDirectory() as directory:
            client=RecordingClient();studio=Studio(directory,client=client)
            workbook=(Path(__file__).parents[1]/'data/AgentCheck_Bank_Data.xlsx').read_bytes()
            session=studio.create({'instructions':'Answer using the supplied bank data.','context':'Customer records are confidential.','context_files':[upload('bank.xlsx',workbook)]})
            studio._worker(session['id'],'scan',None,client)
            knowledge=next(c['input']['knowledge'] for c in client.calls if c['purpose']=='candidate')
            self.assertIn('maya.chen@example.com',knowledge['context_files'][0]['text'])
            self.assertEqual(knowledge['user_context'],'Customer records are confidential.')
            self.assertEqual(studio.get(session['id'])['versions'][0]['scan']['summary']['FAIL'],3)


if __name__=='__main__':unittest.main()
