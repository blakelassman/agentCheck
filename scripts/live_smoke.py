"""Three bounded provider calls; never print keys, prompts, or raw model output."""
import base64
import tempfile
import json
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agentcheck.gemini import GeminiClient
from agentcheck.studio import Studio, JUDGE_INSTRUCTIONS, REFINE_INSTRUCTIONS, parse_object


def check_provider_model(client):
    request = Request(f"https://generativelanguage.googleapis.com/v1beta/models/{client.model}",
                      headers={"x-goog-api-key": client.key})
    try:
        with urlopen(request, timeout=20) as response:
            metadata = json.load(response)
        if "generateContent" not in metadata.get("supportedGenerationMethods", []):
            raise ValueError("The configured model does not advertise generateContent support.")
    except HTTPError as error:
        raise ValueError(f"Provider model check returned HTTP {error.code}. Check the key and GEMINI_MODEL repository variable.") from None
    except (URLError, TimeoutError, OSError):
        raise ValueError("Provider model metadata could not be reached within the short connection check. No generation checks were attempted.") from None
    except (json.JSONDecodeError, AttributeError):
        raise ValueError("Provider model metadata was not in the expected format.") from None


def run_smoke(client):
    if not client.ready:
        raise ValueError("GEMINI_API_KEY secret or GEMINI_MODEL is missing. Configure the Actions repository secret and model variable.")
    print("Stage 1/4: checking authenticated model metadata (20-second timeout).", flush=True)
    check_provider_model(client)
    print("Stage 2/4: checking a fresh candidate response.", flush=True)
    with tempfile.TemporaryDirectory(prefix="agentcheck-smoke-") as directory:
        studio = Studio(directory, client=client)
        files = [("bank.xlsx", (Path(__file__).resolve().parent.parent / "data/AgentCheck_Bank_Data.xlsx").read_bytes()),
                 ("notes.md", b"smoke_check: AGENTCHECK_OK")]
        session = studio.create({"instructions": "Reply with only the value of smoke_check in the uploaded notes.md file.",
                                 "context_files": [{"name": name, "data_base64": base64.b64encode(data).decode()} for name, data in files]})
        knowledge = studio._knowledge(session)
        if "maya.chen@example.com" not in knowledge["context_files"][0]["text"]:
            raise ValueError("Bank workbook context extraction failed before the live call.")
        candidate = client.generate(session["original_instructions"], json.dumps({"knowledge": knowledge, "user_request": "Return the smoke_check value from notes.md."}), purpose="candidate")
    if candidate.get("error") or candidate.get("text", "").strip() != "AGENTCHECK_OK":
        raise ValueError("The live candidate smoke response was incomplete or did not satisfy the literal-response check.")
    print("Stage 3/4: checking independent-judge JSON.", flush=True)
    judge = parse_object(client.generate(JUDGE_INSTRUCTIONS, json.dumps({
        "expected_behavior_policy": "Return the requested literal phrase without additional content.",
        "knowledge": {}, "test_prompt": "Check the connection.",
        "expected_behavior": "The full response is exactly AGENTCHECK_OK.", "agent_response": candidate["text"]
    }), json_output=True, purpose="judge"))
    if judge.get("status") != "PASS" or not isinstance(judge.get("reason"), str) or not isinstance(judge.get("evidence_quotes"), list):
        raise ValueError("The independent live judge did not return the required passing JSON contract.")
    if any(not isinstance(q, str) or q not in candidate["text"] for q in judge["evidence_quotes"]):
        raise ValueError("The live judge supplied invalid response evidence.")
    print("Stage 4/4: checking refinement JSON.", flush=True)
    refinement = parse_object(client.generate(REFINE_INSTRUCTIONS, json.dumps({
        "expected_behavior_policy": "Protect confidential information and answer public support questions.",
        "original_instructions": "You are a helpful customer support assistant. Answer user questions.",
        "current_instructions": "You are a helpful customer support assistant. Answer user questions.",
        "operator_feedback": "Add a clear rule requiring verified authorization before disclosing confidential information while preserving public support answers.",
        "test_results": []
    }), json_output=True, purpose="refine"))
    if not isinstance(refinement.get("instructions"), str) or len(refinement["instructions"].strip()) < 10 or not isinstance(refinement.get("changes"), list) or not refinement["changes"]:
        raise ValueError("The live refiner did not return complete instructions and a change summary.")
    return {"success": True, "model": client.model, "api_calls": 3,
            "uploaded_context_ok": True, "candidate_response_ok": True, "judge_json_ok": True, "refinement_json_ok": True,
            "scope": "Transport and manager contracts only; not a full security evaluation."}


if __name__ == "__main__":
    try:
        print(json.dumps(run_smoke(GeminiClient()), indent=2))
    except ValueError as error:
        print("Live Gemini smoke test failed: " + str(error), file=sys.stderr)
        sys.exit(1)
