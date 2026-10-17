"""Single-file report, with no CDN, network calls or executable response content."""
import html
from pathlib import Path

from .runner import AGENTS


def write_report(run, destination):
    esc = lambda v: html.escape(str(v if v is not None else "Not recorded"))
    sections = []
    for agent in AGENTS:
        counts = run["summary"][agent["id"]]
        cards = []
        for r in run["results"]:
            if r["agent_id"] != agent["id"]:
                continue
            status = r["evaluation_status"]
            items = [f'<li>{esc(e.get("field", "evidence"))}: <code>{esc(e.get("excerpt", ""))}</code></li>' for e in r["evidence"]]
            evidence = '<ul>' + ''.join(items[:5]) + '</ul>' if items else ''
            if len(items) > 5:
                evidence += f'<details class="additional-evidence"><summary>{len(items)-5} additional matches</summary><ul>{"".join(items[5:])}</ul></details>'
            review = f'<p><b>Human review:</b> {esc(r["review"]["note"])} (automated grade: {esc(r["automated_status"])})</p>' if r.get("review") else ""
            cards.append(f'''<details data-status="{esc(status)}" open><summary><span class="pill {esc(status)}">{esc(status)}</span> {esc(r['test_id'])} · {esc(r['title'])}</summary>
                <p class="prompt">{esc(r['user_prompt'])}</p><pre>{esc(r['raw_response'] or 'No response captured.')}</pre>
                <p><b>Reason:</b> {esc(r['reason'])}</p>{review}{evidence}
                <small>Model: {esc(r['model'])} · Latency: {esc(r['latency_ms'])} ms · Captured: {esc(r['captured_at'])}</small></details>''')
        metrics = "".join(f'<span><b>{n}</b> {esc(status.lower())}</span>' for status, n in counts.items())
        sections.append(f'<section><h2>{esc(agent["name"])}</h2><p class="muted">{esc(agent["description"])}</p><div class="metrics">{metrics}</div>{"".join(cards)}</section>')
    banner = 'MOCK FIXTURES · No model was called' if run["is_mock"] else ('MANUAL GEM CAPTURE · Responses supplied by operator' if run["source_mode"] == 'manual' else 'API RECREATION · Separate from web Gems')
    content = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>AgentCheck report {esc(run['run_id'])}</title>
    <style>{(Path(__file__).parent / 'web' / 'report.css').read_text()}</style></head><body>
    <header><div class="brand">AgentCheck<span> / EVALUATION REPORT</span></div><div class="banner">{esc(banner)}</div>
    <h1>Same tests. Visible evidence.</h1><p>Run {esc(run['run_id'])} · {esc(run['created_at'])} · {'All cases recorded' if run['complete'] else 'INCOMPLETE RUN'}</p>
    <p class="muted">{esc(run['dataset_version'])} · {esc(run['evaluator_version'])} · SHA256 {esc(run['dataset_sha256'])}</p></header>
    <main>{''.join(sections)}</main><footer>Five cases per agent. Pending, errors and reviews count toward the scheduled total. Rule-based checks can miss novel or paraphrased disclosures. A pass is limited to this test and rubric.</footer></body></html>'''
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(content, encoding="utf-8")
    return destination
