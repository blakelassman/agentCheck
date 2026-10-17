# Partner instruction files

For optional API recreation, save the partner's exact Gem instruction text in:

- `vulnerable.txt`
- `protected.txt`

The two files must be nonempty and distinct. They are ignored by Git. No instruction file is required for manual Gem response capture.

The API adapter reads these as system instructions and supplies the same workbook data to both agents. It does not call the Gemini web Gems by their share links. AgentCheck keeps the test answers and grading logic outside those requests.
