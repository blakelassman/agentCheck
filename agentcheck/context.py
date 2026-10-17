"""Bounded, text-only context extraction. Uploaded files are never executed."""
import base64
import binascii
import csv
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile
from xml.etree import ElementTree as ET

MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_TOTAL_BYTES = 10 * 1024 * 1024
MAX_TEXT = 200_000
SUPPORTED = {'.txt', '.md', '.markdown', '.csv', '.tsv', '.json', '.xlsx', '.docx', '.doc', '.pdf'}


def xml(data):
    if b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():
        raise ValueError('Document XML declarations are unsupported.')
    return ET.fromstring(data)


def office_text(data, suffix):
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        if len(archive.infolist()) > 2000 or sum(i.file_size for i in archive.infolist()) > 20 * 1024 * 1024:
            raise ValueError('Office document expands beyond the extraction limit.')
        if suffix == '.docx':
            root = xml(archive.read('word/document.xml'))
            return '\n'.join(''.join(n.itertext()) for n in root.iter() if n.tag.endswith('}p'))
        ns = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
        strings = []
        if 'xl/sharedStrings.xml' in archive.namelist():
            strings = [''.join(n.itertext()) for n in xml(archive.read('xl/sharedStrings.xml')).findall('s:si', ns)]
        relationships = {n.get('Id'): n.get('Target') for n in xml(archive.read('xl/_rels/workbook.xml.rels')) if n.get('TargetMode') != 'External'}
        result = []
        for sheet in xml(archive.read('xl/workbook.xml')).findall('s:sheets/s:sheet', ns):
            target = relationships.get(sheet.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id'), '')
            member = target.lstrip('/') if target.startswith('/') else 'xl/' + target
            result.append('Sheet: ' + sheet.get('name', 'Unnamed'))
            for row in xml(archive.read(member)).findall('.//s:sheetData/s:row', ns):
                cells = []
                for cell in row.findall('s:c', ns):
                    value = cell.findtext('s:v', '', ns)
                    kind = cell.get('t')
                    if kind == 's':
                        value = strings[int(value)]
                    elif kind == 'inlineStr':
                        value = ''.join(cell.find('s:is', ns).itertext())
                    formula = cell.findtext('s:f', None, ns)
                    if formula is not None and not value:
                        value = '[Formula has no cached result: ' + formula + ']'
                    cells.append(cell.get('r', '') + '=' + value)
                result.append('\t'.join(cells))
            if sum(map(len, result)) > MAX_TEXT:
                raise ValueError('Extracted spreadsheet exceeds the context limit.')
        return '\n'.join(result)


def extract(data, suffix):
    if suffix in ('.xlsx', '.docx'):
        return office_text(data, suffix)
    if suffix in ('.doc', '.pdf'):
        executable = 'antiword' if suffix == '.doc' else 'pdftotext'
        if not shutil.which(executable):
            raise ValueError(f'{suffix} extraction is unavailable on this server. Convert to .docx or .txt, or ask the operator to install {executable}.')
        with tempfile.TemporaryDirectory(prefix='agentcheck-context-') as directory:
            source = Path(directory) / ('context' + suffix)
            source.write_bytes(data)
            command = [executable, str(source)] if suffix == '.doc' else [executable, '-enc', 'UTF-8', str(source), '-']
            # Bound output on disk, with a timeout, rather than accumulating arbitrary stdout in memory.
            output = Path(directory) / 'text'
            with output.open('wb') as stream:
                process = subprocess.run(command, stdout=stream, stderr=subprocess.DEVNULL, timeout=15, check=False)
            if process.returncode or output.stat().st_size > MAX_TEXT * 4:
                raise ValueError('Document extraction failed or exceeded the text limit. Use .docx or .txt.')
            return output.read_text(encoding='utf-8', errors='replace')
    text = data.decode('utf-8-sig')
    if '\x00' in text:
        raise ValueError('Text context must be UTF-8, not a binary document.')
    if suffix == '.json':
        json.loads(text)
    if suffix in ('.csv', '.tsv'):
        # Validate the text without evaluating spreadsheet formulas.
        list(csv.reader(io.StringIO(text), delimiter='\t' if suffix == '.tsv' else ','))
    return text


def parse_uploads(files):
    if not isinstance(files, list) or len(files) > 10:
        raise ValueError('Upload at most 10 context files.')
    parsed, total, characters = [], 0, 0
    for item in files:
        if not isinstance(item, dict) or not isinstance(item.get('name'), str):
            raise ValueError('Each context file needs a filename and base64 content.')
        name = item['name']
        if not name or len(name) > 200 or '/' in name or '\\' in name or any(ord(c) < 32 for c in name):
            raise ValueError('Invalid context filename.')
        suffix = Path(name).suffix.lower()
        if suffix not in SUPPORTED:
            raise ValueError(f'Unsupported context format: {suffix or "no extension"}. Use Excel .xlsx, Word .docx, text, Markdown, CSV, JSON, PDF or legacy .doc.')
        encoded = item.get('data_base64')
        if not isinstance(encoded, str) or len(encoded) > ((MAX_FILE_BYTES + 2) // 3) * 4:
            raise ValueError('Each context file must be at most 5 MB.')
        try:
            data = base64.b64decode(encoded, validate=True)
            total += len(data)
            if len(data) > MAX_FILE_BYTES or total > MAX_TOTAL_BYTES:
                raise ValueError('Context files must total at most 10 MB, with at most 5 MB per file.')
            text = extract(data, suffix).strip()
        except (binascii.Error, UnicodeError, zipfile.BadZipFile, ET.ParseError, KeyError, IndexError, TypeError, RuntimeError, NotImplementedError, subprocess.TimeoutExpired) as error:
            raise ValueError(f'Cannot extract {name}. Supply a valid, unencrypted document.') from error
        if not text:
            raise ValueError(f'{name} contains no extractable text. Scanned images need OCR before upload.')
        characters += len(text)
        if characters > MAX_TEXT:
            raise ValueError('Combined extracted context must be at most 200000 characters.')
        parsed.append({'name': name, 'size_bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
                       'text': text, 'characters': len(text), 'format': suffix})
    return parsed
