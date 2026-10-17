"""Read the shared synthetic workbook using Python's standard library."""
import hashlib
import json
import math
import re
from datetime import datetime, timedelta
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_WORKBOOK = ROOT / "data" / "AgentCheck_Bank_Data.xlsx"
NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
HEADERS = {
    "Public_Info": ["record_id", "topic", "label", "text_value", "numeric_value", "unit", "classification"],
    "Customers": ["customer_id", "full_name", "email", "phone", "identity_reference", "classification"],
    "Accounts": ["account_id", "customer_id", "product", "available_balance_usd", "status", "classification"],
    "Transactions": ["transaction_id", "account_id", "posted_date", "merchant", "amount_usd", "currency", "classification"],
}


def _sheet_rows(archive, target, strings):
    root = ET.fromstring(archive.read(target))
    rows = []
    for row in root.findall("s:sheetData/s:row", NS):
        values = {}
        for cell in row.findall("s:c", NS):
            letters = re.match(r"[A-Z]+", cell.attrib["r"]).group()
            col = 0
            for char in letters:
                col = col * 26 + ord(char) - 64
            kind = cell.attrib.get("t")
            raw = cell.findtext("s:v", default="", namespaces=NS)
            if kind == "s":
                value = strings[int(raw)]
            elif kind == "inlineStr":
                value = "".join(cell.itertext())
            elif kind in ("str", "e", "d"):
                value = raw
            elif not raw:
                value = None
            elif kind == "b":
                value = raw == "1"
            else:
                value = float(raw)
                if value.is_integer():
                    value = int(value)
            values[col - 1] = value
        if values:
            rows.append([values.get(i) for i in range(max(values) + 1)])
    return rows


def load_dataset(path=DEFAULT_WORKBOOK):
    path = Path(path)
    with ZipFile(path) as archive:
        if sum(item.file_size for item in archive.infolist()) > 10_000_000:
            raise ValueError("Workbook exceeds the demo dataset size limit.")
        strings = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            strings = ["".join(x.itertext()) for x in root]
        relroot = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        targets = {r.attrib["Id"]: r.attrib["Target"] for r in relroot}
        book = ET.fromstring(archive.read("xl/workbook.xml"))
        sheets = {}
        for sheet in book.findall("s:sheets/s:sheet", NS):
            rel = sheet.attrib["{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"]
            target = targets[rel]
            target = target.lstrip("/") if target.startswith("/") else "xl/" + target
            sheets[sheet.attrib["name"]] = _sheet_rows(archive, target, strings)
    if any(name not in sheets for name in ["Readme", *HEADERS]):
        raise ValueError("Workbook is missing required dataset sheets.")
    metadata = {r[0]: r[1] for r in sheets["Readme"] if len(r) > 1 and r[0]}
    if metadata.get("Dataset version") != "agentcheck-bank-v1.0":
        raise ValueError("Unknown dataset version. Update the suite before using this workbook.")
    result = {"version": metadata["Dataset version"], "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "sheets": {}}
    for name, expected in HEADERS.items():
        rows = sheets[name]
        if rows[0] != expected:
            raise ValueError(f"Unexpected headers in {name}.")
        records = []
        for row in rows[1:]:
            row = row + [None] * (len(expected) - len(row))
            if len(row) != len(expected):
                raise ValueError(f"Unexpected columns in {name}.")
            item = dict(zip(expected, row))
            level = "PUBLIC" if name == "Public_Info" else "CONFIDENTIAL"
            if item["classification"] != level:
                raise ValueError(f"Invalid classification in {name}.")
            if name == "Transactions" and isinstance(item["posted_date"], (int, float)):
                item["posted_date"] = (datetime(1899, 12, 30) + timedelta(days=item["posted_date"])).date().isoformat()
            for key in ("available_balance_usd", "amount_usd", "numeric_value"):
                if key in item and item[key] is not None:
                    if isinstance(item[key], bool) or not isinstance(item[key], (int, float)) or not math.isfinite(item[key]):
                        raise ValueError(f"Invalid numeric field {key}.")
            records.append(item)
        if not records:
            raise ValueError(f"Empty dataset sheet {name}.")
        ids = [r[expected[0]] for r in records]
        if any(not isinstance(i, str) or not i for i in ids) or len(ids) != len(set(ids)):
            raise ValueError(f"Missing or duplicate identifiers in {name}.")
        result["sheets"][name] = records
    customers = {r["customer_id"] for r in result["sheets"]["Customers"]}
    accounts = {r["account_id"] for r in result["sheets"]["Accounts"]}
    if any(r["customer_id"] not in customers for r in result["sheets"]["Accounts"]):
        raise ValueError("Account references a missing customer.")
    if any(r["account_id"] not in accounts for r in result["sheets"]["Transactions"]):
        raise ValueError("Transaction references a missing account.")
    return result


def load_cases():
    return json.loads((ROOT / "data" / "test_cases.json").read_text(encoding="utf-8"))


def agent_context(dataset):
    """No test cases, answer keys or evaluator logic are included in agent input."""
    return json.dumps({"dataset_version": dataset["version"], "data": dataset["sheets"]}, ensure_ascii=False)
