"""Three bounded provider calls; never print keys, prompts, or raw model output."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agentcheck.gemini import GeminiClient
from agentcheck.studio import JUDGE_INSTRUCTIONS, REFINE_INSTRUCTIONS, parse_object


def run_smoke(client):
    if not client.ready:
        raise ValueError("GEMINI_API_KEY secret or GEMINI_MODEL is missing. Configure the Actions repository secret and model variable.")
    candidate = client.generate("Reply to the request with exactly AGENTCHECK_OK and nothing else.", "Check the connection.", purpose="candidate")
    if candidate.get("error") or candidate.get("text", "").strip() != "AGENTCHECK_OK":
        raise ValueError("The live candidate smoke response was incomplete or did not satisfy the literal-response check.")
    judge = parse_object(client.generate(JUDGE_INSTRUCTIONS, json.dumps({
        "expected_behavior_policy": "Return the requested literal phrase without additional content.",
        "knowledge": {}, "test_prompt": "Check the connection.",
        "expected_behavior": "The full response is exactly AGENTCHECK_OK.", "agent_response": candidate["text"]
    }), json_output=True, purpose="judge"))
    if judge.get("status") != "PASS" or not isinstance(judge.get("reason"), str) or not isinstance(judge.get("evidence_quotes"), list):
        raise ValueError("The independent live judge did not return the required passing JSON contract.")
    if any(not isinstance(q, str) or q not in candidate["text"] for q in judge["evidence_quotes"]):
        raise ValueError("The live judge supplied invalid response evidence.")
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
            "candidate_response_ok": True, "judge_json_ok": True, "refinement_json_ok": True,
            "scope": "Transport and manager contracts only; not a full security evaluation."}


if __name__ == "__main__":
    try:
        print(json.dumps(run_smoke(GeminiClient()), indent=2))
    except ValueError as error:
        print("Live Gemini smoke test failed: " + str(error), file=sys.stderr)
        sys.exit(1)
