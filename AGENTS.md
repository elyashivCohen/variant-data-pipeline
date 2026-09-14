# Project instructions

## Scope and sources
- This is the IdentifAI Genetics intern take-home pipeline.
- Current work covers simplifying conversion and testing it; Process,
  Aggregate, Docker, and orchestration require separately approved work.
- The assignment PDF is external. Never copy it into the repository or Git.
  If unavailable, attribute requirements to the user-provided PDF summary.
- Keep detailed requirements, contracts, and design decisions in README.md.
  Distinguish assignment requirements from project choices.

## Relevant paths
- src/convert.py: single-file conversion, directory batches, and CLI.
- tests/test_convert.py: standard-library unittest tests.
- tests/fixtures/: proposed location for small authored CSV fixtures.
- input/variants_1.csv through input/variants_5.csv: original samples;
  preserve them unchanged.
- data/converted/: default generated conversion outputs.
- data/processed/ and output/summary.json: planned downstream outputs.

## Code and testing
- Use English for communication, names, comments, docstrings, and logs.
- Prefer descriptive names, focused functions, straightforward control flow,
  and the standard library; avoid unnecessary abstractions.
- Preserve public interfaces, JSON metadata, record order, and safe reruns
  unless a change is explicitly approved.
- Follow the approved error policy; do not invent biological validation
  or treat unexpected programming errors as invalid records.
- Keep logging configuration and process exit behavior at the CLI boundary.
- Use unittest, temporary directories, and mocks for deterministic I/O errors.
  Test observable outputs, warnings, failures, and reruns.
- Preserve existing user changes and original samples.

## Commands
From the repository root:
- python -m src.convert --input-dir input --output-dir data/converted
- python -m unittest discover -s tests -v

These commands are documented and match the current interfaces, but have
not been execution-verified in this session. README.md specifies Python 3.9+.

## Approval workflow
- Explain each stage, summarize its findings or changes, propose the next
  stage, and stop for explicit approval.
- Approval applies only to the proposed next stage.
- After questions or revisions, respond and wait again.
- Ask before materially changing the approved design.
- Do not commit, push, install dependencies, or implement unrelated stages.
- Keep implementation and test implementation in separately approved stages.
- Report only checks actually performed; never claim unrun tests passed.
