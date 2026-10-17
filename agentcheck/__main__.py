import argparse
import json
from pathlib import Path

from .adapters import call_api
from .dataset import load_cases, load_dataset
from .report import write_report
from .runner import AGENTS, atomic_json, build_run, demo_capture, empty_capture, now, persist_run


def main():
    parser = argparse.ArgumentParser(description="AgentCheck bank agent evaluation workbench")
    commands = parser.add_subparsers(dest="command")
    server = commands.add_parser("serve", help="Open the local capture and evaluation workbench")
    server.add_argument("--port", type=int, default=8765)
    demo = commands.add_parser("demo", help="Generate explicitly labeled mock results and a report")
    demo.add_argument("--output", default=None, help="Optional path for the mock capture JSON")
    evaluate = commands.add_parser("evaluate", help="Evaluate a captured response JSON file")
    evaluate.add_argument("capture", type=Path)
    report = commands.add_parser("report", help="Render an existing results JSON as standalone HTML")
    report.add_argument("results", type=Path)
    report.add_argument("--output", type=Path, default=Path("dashboard.html"))
    commands.add_parser("run", help="Run all cases using API recreations of the partner's instructions")
    args = parser.parse_args()
    try:
        if args.command in (None, "serve"):
            from .server import serve
            return serve(getattr(args, "port", 8765))
        if args.command == "report":
            run = json.loads(args.results.read_text(encoding="utf-8"))
            print(write_report(run, args.output).resolve())
            return
        dataset = load_dataset()
        if args.command == "demo":
            capture = demo_capture(dataset)
            if args.output:
                atomic_json(args.output, capture)
        elif args.command == "evaluate":
            capture = json.loads(args.capture.read_text(encoding="utf-8"))
        else:
            capture = empty_capture(dataset)
            capture["source_mode"] = "api"
            for agent in AGENTS:
                for case in load_cases():
                    item = {"agent_id": agent["id"], "test_id": case["id"], "captured_at": now()}
                    try:
                        item.update(call_api(agent["id"], case["prompt"], dataset))
                    except ValueError as error:
                        item.update(raw_response="", error=str(error), response_format="json")
                    capture["captures"].append(item)
                    print(f"Captured {agent['id']} / {case['id']}")
        run = persist_run(build_run(capture, dataset))
        print(json.dumps(run["summary"], indent=2))
        print(f"Report: reports/{run['run_id']}.html")
        print(f"Results: results/{run['run_id']}.json")
    except (ValueError, KeyError, OSError) as error:
        parser.exit(1, f"AgentCheck: {error}\n")


if __name__ == "__main__":
    main()
