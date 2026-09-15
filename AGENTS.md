# Project instructions

## Scope and sources
- This is the IdentifAI Genetics intern take-home pipeline.
- Convert, Process, Aggregate, Docker/Compose, and the `run_pipeline.ps1`
  launcher are all implemented; README.md is the current source of truth
  for architecture, contracts, and run instructions - this file reflects
  early Convert-only working conventions and is kept for git history, not
  as a current description.
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
- Real pipeline runs use `output/<RUN_ID>/{convert,process,aggregate,logs}/`
  (see README.md), not the `data/converted`/`data/processed` defaults
  below - those remain only as this module's own argparse fallbacks for
  running a stage standalone, outside Docker.
- data/converted/: default generated conversion outputs (standalone use only).
- data/processed/ and output/summary.json: same, standalone use only.

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
