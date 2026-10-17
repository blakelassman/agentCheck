"""Loopback-only workbench. No authentication service or deployment required."""
import json
import re
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from .adapters import api_status, call_api
from .dataset import ROOT, load_cases, load_dataset
from .runner import AGENTS, build_run, demo_capture, empty_capture, now, persist_run

WEB = Path(__file__).parent / "web"
RUN_ID = r"\d{8}T\d{6}Z-[a-f0-9]{8}"


def make_server(port=8765, dataset=None):
    dataset = dataset or load_dataset()
    cases = load_cases()
    token = secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def send(self, content, content_type="application/json", status=200):
            if not isinstance(content, bytes):
                content = (json.dumps(content, ensure_ascii=False, allow_nan=False) if content_type == "application/json" else content).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type + "; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            self.wfile.write(content)

        def trusted_host(self):
            return self.headers.get("Host") in (f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}")

        def do_GET(self):
            if not self.trusted_host():
                return self.send({"error": "Use the loopback URL printed in the terminal."}, status=403)
            path = urlsplit(self.path).path
            if path == "/api/bootstrap":
                return self.send({"token": token, "agents": AGENTS, "cases": cases,
                                  "dataset": {"version": dataset["version"], "sha256": dataset["sha256"], "counts": {k: len(v) for k, v in dataset["sheets"].items()}},
                                  "api": api_status(), "capture": empty_capture(dataset)})
            if path == "/api/history":
                entries = []
                for file in sorted((ROOT / "results").glob("*.json"), reverse=True)[:30]:
                    if not re.fullmatch(RUN_ID + r"\.json", file.name):
                        continue
                    try:
                        run = json.loads(file.read_text(encoding="utf-8"))
                        entries.append({k: run[k] for k in ("run_id", "created_at", "source_mode", "summary", "complete")})
                    except (OSError, ValueError, KeyError):
                        continue
                return self.send(entries)
            if path in ("/", "/app.js", "/styles.css"):
                filename = {"/": "index.html", "/app.js": "app.js", "/styles.css": "styles.css"}[path]
                content = (WEB / filename).read_bytes()
                mime = {"index.html": "text/html", "app.js": "text/javascript", "styles.css": "text/css"}[filename]
                return self.send(content, mime)
            match = re.fullmatch(r"/(reports|results)/(" + RUN_ID + r")\.(html|json)", path)
            if match and ((match[1], match[3]) in (("reports", "html"), ("results", "json"))):
                file = ROOT / match[1] / (match[2] + "." + match[3])
                if file.is_file():
                    return self.send(file.read_bytes(), "text/html" if match[3] == "html" else "application/json")
            return self.send({"error": "Not found."}, status=404)

        def do_POST(self):
            if not self.trusted_host() or self.headers.get("X-AgentCheck-Token") != token:
                return self.send({"error": "Request rejected. Reload the local workbench."}, status=403)
            origin = self.headers.get("Origin")
            if origin and origin not in (f"http://127.0.0.1:{self.server.server_port}", f"http://localhost:{self.server.server_port}"):
                return self.send({"error": "Untrusted origin."}, status=403)
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length < 0 or length > 1_000_000:
                    return self.send({"error": "Request is too large."}, status=413)
                payload = json.loads(self.rfile.read(length))
                path = urlsplit(self.path).path
                if path == "/api/evaluate":
                    run = persist_run(build_run(payload, dataset, cases))
                    return self.send(run)
                if path == "/api/demo":
                    capture = demo_capture(dataset)
                    return self.send({"capture": capture, "run": persist_run(build_run(capture, dataset, cases))})
                if path == "/api/run-case":
                    if not isinstance(payload, dict):
                        raise ValueError("Expected an agent_id and test_id.")
                    agent = payload.get("agent_id")
                    case = next((c for c in cases if c["id"] == payload.get("test_id")), None)
                    if agent not in {a["id"] for a in AGENTS} or not case:
                        raise ValueError("Unknown agent or test.")
                    capture = {"agent_id": agent, "test_id": case["id"], "captured_at": now()}
                    try:
                        capture.update(call_api(agent, case["prompt"], dataset))
                    except ValueError as error:
                        capture.update(raw_response="", error=str(error), model=api_status()["model"], response_format="json")
                    return self.send(capture)
                return self.send({"error": "Not found."}, status=404)
            except (ValueError, TypeError, KeyError, OverflowError) as error:
                return self.send({"error": str(error)}, status=400)
            except OSError:
                return self.send({"error": "Could not save the run. Check write access and available disk space."}, status=500)

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def serve(port=8765):
    with make_server(port) as server:
        print(f"AgentCheck is ready: http://127.0.0.1:{server.server_port}", flush=True)
        print("Local workbench. Ctrl+C stops the server. No API key needed for pasted Gem responses.", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nAgentCheck stopped.")
