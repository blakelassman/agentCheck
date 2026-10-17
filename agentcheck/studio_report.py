"""Escaped standalone evidence report for a prompt optimization session."""
import html
from pathlib import Path


def session_report(session):
    e = lambda value: html.escape(str(value if value is not None else "Not recorded"))
    css = (Path(__file__).parent / "web" / "report.css").read_text()
    css += "main{display:block}section{margin:24px 0;min-width:0}section p,summary{overflow-wrap:anywhere}table{display:block;max-width:100%;overflow-x:auto;border-collapse:collapse;font-size:13px}td,th{padding:12px;text-align:left;border-bottom:1px solid #293449}h2{margin-top:28px}summary small{margin-left:8px}pre{max-height:500px;overflow:auto}.prompt-diff{margin-top:16px}"
    versions = []
    rows = []
    for version in session["versions"]:
        scan = version["scan"]
        summary = scan.get("summary", {})
        decision = version.get("decision") or {}
        rows.append(f'<tr><td>Version {version["number"]}</td><td>{e(scan["status"])}</td><td>{summary.get("PASS",0)}</td><td>{summary.get("FAIL",0)}</td><td>{summary.get("ERROR",0)}</td><td>{summary.get("REVIEW",0)}</td><td>{e(decision.get("status", "Undecided"))}</td></tr>')
        cases = []
        for result in scan["results"]:
            evidence = ''.join(f'<li>{e(v.get("field"))}: {e(v.get("excerpt"))}</li>' for v in result.get("evidence", [])[:5])
            cases.append(f'<details><summary><span class="pill {e(result["evaluation_status"])}">{e(result["evaluation_status"])}</span>{e(result["test_id"])} · {e(result["title"])}</summary><p>{e(result["user_prompt"])}</p><p><b>Expected:</b> {e(result["expected_behavior"])}</p><pre>{e(result["raw_response"])}</pre><p>{e(result["reason"])}</p><ul>{evidence}</ul><small>Method: {e(result["method"])} · Candidate: {e(result["model"])} · Latency: {e(result["latency_ms"])} ms</small></details>')
        changes = ''.join(f'<li>{e(change)}</li>' for change in version["changes"])
        feedback = decision.get("feedback") or decision.get("note") or ""
        versions.append(f'<section><h2>Version {version["number"]}</h2><p>{e(scan.get("model"))} · Suite SHA256 {e(scan.get("suite_sha256"))}</p><p>{e(decision.get("status", "Undecided"))}: {e(feedback)}</p><ul>{changes}</ul><details class="prompt-diff"><summary>Full instructions · SHA256 {e(version["instructions_sha256"])}</summary><pre>{e(version["instructions"])}</pre></details>{"".join(cases)}</section>')
    mode = "MOCK FIXTURES · No model was called" if session["is_mock"] else "GEMINI API SCAN · Instruction-only test environment"
    scope = "Offline demonstration. No provider was called." if session["is_mock"] else "Scanned through Gemini using the server-managed connection."
    files = ''.join(f'<li>{e(file["name"])} · {e(file["characters"])} extracted characters · SHA256 {e(file["sha256"])}</li>' for file in session.get("context_files", []))
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>AgentCheck {e(session["name"])}</title><style>{css}</style></head><body><header><div class="brand">AgentCheck<span> / PROMPT SCAN REPORT</span></div><div class="banner">{mode}</div><h1>{e(session["name"])}</h1><p>Session {e(session["id"])} · {e(session["state"])} · Approved version: {e(session["accepted_version"])}</p><p>Source platform: {e(session["source_provider"])}. {scope}</p><p>Context version {e(session["dataset_version"])} · SHA256 {e(session["dataset_sha256"])}</p></header><main><h2>Version comparison</h2><table><thead><tr><th>Version</th><th>Scan</th><th>Pass</th><th>Fail</th><th>Error</th><th>Review</th><th>Decision</th></tr></thead><tbody>{"".join(rows)}</tbody></table><h2>Uploaded context</h2><p>Context snapshot SHA256 {e(session.get("context_sha256", "Not recorded"))}</p><ul>{files or "<li>No uploaded files</li>"}</ul><h2>Expected behavior policy</h2><pre>{e(session["policy"])}</pre>{"".join(versions)}</main><footer>Approval records the operator's decision. Results apply to the displayed model, prompt, context and test suite. Model-generated tests and judgments can be wrong. Passing does not establish universal safety, production readiness or equivalent behavior on another provider. Original tools and integrations were not exercised.</footer></body></html>'''
