# AgentCheck current teammate handoff

The application now tests uploaded instructions directly through Gemini. An existing web Gem connection and manual response uploads are no longer needed for the main workflow.

| Owner | Work |
| --- | --- |
| Blake and coding agent | Upload interface, automatic Gemini tests, judging, prompt versions, feedback refinement, approval and export. |
| Teammate | Candidate instruction text, useful-task examples, expected policy and review of observed behavior. Existing Gems may remain comparison references. |
| Both | Agree on expected behavior, run a real scan, review versions and rehearse the demonstration. |

## Prepare

- [ ] Get the exact candidate instructions as a `.txt` or `.md` file.
- [ ] Operator: set the shared `GEMINI_API_KEY` on the server. The model defaults to `gemini-3.8-flash`; override with `GEMINI_MODEL` if needed. The GitHub secret already powers Actions, but a separate runtime needs explicit environment injection.
- [ ] Choose the fixed bank suite for the demo or generated task tests for another assistant.
- [ ] Define the external expected behavior policy independently of the prompt.
- [ ] Upload the bank `.xlsx` workbook and any Markdown, Word `.docx`, CSV, JSON or text context. Optional PDF/legacy `.doc` extraction needs the server tools listed in README.

## Demonstrate

- [ ] Start `python -m agentcheck serve` and open the printed local URL.
- [ ] Confirm the managed Gemini status is available, or choose the offline demo for a clearly labeled rehearsal. No end-user API key is requested.
- [ ] Upload instructions and context files, then run the automatic scan.
- [ ] Inspect failures and response evidence.
- [ ] Reject with specific feedback. AgentCheck revises the instructions and reruns the same suite.
- [ ] Compare versions and check useful public behavior as well as confidentiality.
- [ ] Approve the latest acceptable version. Errors/reviews need another revision; known failures require an explicit exception explanation.
- [ ] Download the exact approved instructions and the HTML evidence report.
- [ ] Distinguish live model output from mock fixtures throughout the presentation.

## Finish criteria

- [ ] Instructions run through Gemini without manual output capture.
- [ ] Every test shows the response, grade, reason and evaluation method.
- [ ] Policy, test suite and uploaded context stay fixed across revisions.
- [ ] Rejected prompts and their failures remain saved.
- [ ] Approval exports the exact version and locks it.
- [ ] The report identifies model, context, suite, prompt versions and decisions.
- [ ] Real provider access is verified with an approved key before presenting live results.

The exported text is portable. Testing through Gemini does not establish matching behavior on another provider or in the original agent environment.
