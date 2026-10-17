# AgentCheck teammate handoff

## Ownership

| Owner | Work |
| --- | --- |
| Blake | Test suite, runner, evaluator, saved JSON results, HTML dashboard and presentation evidence. |
| Teammate | Two Gemini Gems, their exact instructions, and the same workbook uploaded to both. |
| Both | Confirm the interface, run each case in a fresh chat, review grades and rehearse the demo. |

## What your partner needs to send

- [ ] The link to each Gem, labeled vulnerable or protected, with access enabled for the person running the tests.
- [ ] Exact instructions from each Gem, including any changes from the starter prompts.
- [ ] Confirmation that both use `data/AgentCheck_Bank_Data.xlsx` from this repository.
- [ ] The model and relevant settings as shown in Gemini. If not visible, record them as unknown.
- [ ] Confirmation that no additional knowledge files or earlier conversation history are being used for one agent only.

Web Gem links are useful for opening the agents manually. They do not become the adapter URL. No connection step is needed to begin using the manual capture workflow.

## Manual run

- [ ] Start `python -m agentcheck serve` and open the printed loopback URL.
- [ ] Select T01 and vulnerable agent. Copy its prompt into a fresh chat in that Gem.
- [ ] Paste the complete response. Enter model metadata if known.
- [ ] Repeat T01 through T05 for both Gems. Do not show them the answer key.
- [ ] Evaluate all captures and review the evidence. Resolve REVIEW only with a written explanation.
- [ ] Export HTML and Capture JSON. Open the exported HTML without the local server to confirm it stands alone.
- [ ] Label the vulnerable agent as a deliberate demo. Keep mock fixtures distinct from real captured responses.

## Automation contract

For later automation, the partner can provide instruction text in `agents/vulnerable.txt` and `agents/protected.txt`. The included API adapter accepts an agent identifier and message and returns an ungraded capture:

```json
{
  "raw_response": "{\"answer\":\"The response\"}",
  "response_format": "json",
  "model": "configured-model-id",
  "latency_ms": 1234
}
```

Agent identifiers are `vulnerable_agent` and `protected_agent`. The runner supplies one canonical prompt and the same workbook context, with no evaluator answers. A failed call records an error. The evaluator assigns outcomes separately.

API recreations are separate from the actual web Gems. Matching instruction text and data does not establish identical behavior. Use manual capture when the goal is to demonstrate what the web Gems themselves answered.

## Finish criteria

- [ ] Both real Gems have been tested across all five cases.
- [ ] Ten case results appear, with no missing case disguised as a pass.
- [ ] Every failure and review decision can be traced to the original response.
- [ ] The HTML report displays source mode, dataset version and hash, evaluator version, and model metadata.
- [ ] The presentation uses observed results. If the vulnerable Gem refuses, show that result rather than forcing a failure.
