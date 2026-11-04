# Documentation claim auditor

An offline, deterministic checker that compares exact documentation claims about scene descriptions with static Python call patterns. It uses only the standard library at runtime, sends nothing over the network, collects no telemetry, and writes no files.

## Install and use

Requires Python 3.9 or newer.

```sh
python3 -m pip install image-captioning-claim-audit
image-captioning-claim-audit --version
image-captioning-claim-audit audit .
python3 -m image_captioning_claim_audit audit . --json
image-captioning-claim-audit audit . --verbose --ignore vendor/ build/ --ignore scratch/ --fail-on medium
```

The repository defaults to the current directory. Root documentation and Markdown under the documentation directory are checked. Triple-backtick fenced blocks are excluded; inline code still counts. Test fixtures receive MEDIUM severity. Python sources are searched recursively, excluding version control, caches and virtual environments. Prefix exclusions apply to both prose and sources.

```text
README.md
docs/**/*.md
tests/**/*.md and tests/**/*.py
*.py
```

JSON output is a list of finding objects, each with rule, verdict, message, path and phrase fields. Verbose decisions go to standard error. Exit status is 0 when nothing meets the threshold, 2 when findings meet it, and 1 for usage or input errors. The default threshold is HIGH; selecting medium also fails on MEDIUM findings.

```text
documented-image-captioning-claim-false   HIGH (MEDIUM for test fixtures)
documented-no-image-captioning-claim-false   HIGH
```

## Detection

The checker removes exact denial spans before checking positive phrases, with longer phrases taking precedence. Matching ignores case, preserves hyphens, and does not stem words. Evidence must occur within one Python module. Imports and aliases resolve to calls, and local function or class definitions shadow route names throughout that module.

```python
from transformers import pipeline as make
model = make(task="image-to-text")
```

Other recognized routes pair a supported model construction with an instance generation call, or use one of the fixed generic call names. Imports, comments, strings, uncalled references and model construction alone do not suffice.

## Differentiation

These neighboring tools cover different directions or output types:

```text
image-generation-claim-audit: text to image
ocr-claim-audit: embedded text transcript
classification-claim-audit: single label
image-captioning-claim-audit: image to text, scene description sentence
```

This checker distinguishes scene description sentences from embedded text transcripts and single labels. Producing a picture from a prompt reverses the direction it checks. Detection, segmentation and answers to visual questions alone do not establish the required route.

## Limitations

Static pattern matching does not establish runtime behavior, output quality or semantic correctness. Exact phrases miss paraphrases. Generic method names can produce false positives. Dynamic imports, wrappers, cross-module construction and execution through external commands may be missed. Local definitions conservatively shadow names across the module, regardless of execution order. Malformed or unreadable scanned Python files report an input error. No dependency is imported or executed during inspection.

## Development

```sh
python3 -m unittest discover
python3 -m build
```

The source distribution includes the behavioral suite. The project is distributed under the MIT license.
