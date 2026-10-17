# AgentCheck current teammate handoff

The application now tests uploaded instructions directly through Gemini. An existing web Gem connection and manual response uploads are no longer needed for the main workflow.

| Owner | Work |
| --- | --- |
| Blake and coding agent | Upload interface, automatic Gemini tests, judging, prompt versions, feedback refinement, approval and export. |
| Teammate | Candidate instruction text, useful-task examples, expected policy and review of observed behavior. Existing Gems may remain comparison references. |
| Both | Agree on expected behavior, run a real scan, review versions and rehearse the demonstration. |

## Prepare

- [ ] Get the exact candidate instructions as a `.txt` or `.md` file.
- [ ] Make an approved Gemini API key and compatible model identifier available locally. Do not commit or send the key through chat.
- [ ] Choose the fixed bank suite for the demo or generated task tests for another assistant.
- [ ] Define the external expected behavior policy independently of the prompt.
- [ ] Supply plain-text knowledge when needed. Original tools and integrations are not executed.

## Demonstrate

- [ ] Start `python -m agentcheck serve` and open the printed local URL.
- [ ] Configure Gemini, or choose the offline demo for a clearly labeled rehearsal.
- [ ] Upload instructions and run the automatic scan.
- [ ] Inspect failures and response evidence.
- [ ] Reject with specific feedback. AgentCheck revises the instructions and reruns the same suite.
- [ ] Compare versions and check useful public behavior as well as confidentiality.
- [ ] Approve the latest acceptable version. Errors/reviews need another revision; known failures require an explicit exception explanation.
- [ ] Download the exact approved instructions and the HTML evidence report.
- [ ] Distinguish live model output from mock fixtures throughout the presentation.

## Finish criteria

- [ ] Instructions run through Gemini without manual output capture.
- [ ] Every test shows the response, grade, reason and evaluation method.
- [ ] Policy and test suite stay fixed across revisions.
- [ ] Rejected prompts and their failures remain saved.
- [ ] Approval exports the exact version and locks it.
- [ ] The report identifies model, context, suite, prompt versions and decisions.
- [ ] Real provider access is verified with an approved key before presenting live results.

The exported text is portable. Testing through Gemini does not establish matching behavior on another provider or in the original agent environment.
