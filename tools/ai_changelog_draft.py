#!/usr/bin/env python3
"""Draft release notes for the pushed commits against an OpenAI-compatible API.

Reads the commit list and diffstat (commits.txt, diffstat.txt), asks the model
for GitHub-flavored markdown grouped under Added / Changed / Fixed / Notes,
and prints the draft on stdout.

Stdlib only -- no pip install step. The draft is advisory: nothing commits it
automatically, so a wrong summary costs a human a re-run, not a bad CHANGELOG
entry.

CI does not use this script: the workflow runs the Copilot CLI instead, because
GitHub Models was retired on 2026-07-30 and the Copilot CLI is the supported
way to make an AI request from Actions (see .github/workflows/ai-changelog.yml).
This script is the path for any OpenAI-compatible server -- Azure AI Foundry
(the successor GitHub points to), a self-hosted model, or a local one.

Usage:
    INFERENCE_ENDPOINT=https://<host>/chat/completions \\
    INFERENCE_KEY=<key> MODEL=<model> python3 tools/ai_changelog_draft.py
"""
import json
import os
import sys
import urllib.error
import urllib.request

ENDPOINT = os.environ.get("INFERENCE_ENDPOINT") or os.environ.get("GITHUB_MODELS_ENDPOINT", "")
MODEL = os.environ.get("MODEL", "gpt-4o-mini")
NO_CHANGES = "NO_USER_FACING_CHANGES"

SYSTEM_PROMPT = """\
You write release notes for BLENDERR, a Blender add-on for designing, simulating,
aligning and rendering optical setups.

Rules:
- Reply with GitHub-flavored markdown only. No preamble, no closing remarks.
- Group the notes under these headings, and omit a heading with nothing in it:
  ### Added
  ### Changed
  ### Fixed
  ### Notes
- Write for users of the add-on, not for developers reading the diff.
- Describe behaviour, not implementation: "auto-align now handles mounts with
  a 2 mm offset" rather than "refactored solve_mount_offsets".
- One bullet per user-visible change. Omit refactors, test-only commits,
  formatting, and CI changes.
- If the commits contain nothing a user would notice, reply with exactly:
  {no_changes}
"""


def read(name):
    try:
        with open(name, encoding="utf-8", errors="replace") as handle:
            return handle.read().strip()
    except FileNotFoundError:
        return ""


def main():
    if not ENDPOINT:
        print(
            "ai_changelog_draft: INFERENCE_ENDPOINT is not set -- point it at an "
            "OpenAI-compatible chat-completions URL (Azure AI Foundry, a "
            "self-hosted model, ...). GitHub Models was retired on 2026-07-30.",
            file=sys.stderr,
        )
        return 1

    token = os.environ.get("INFERENCE_KEY") or os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        print("ai_changelog_draft: INFERENCE_KEY is not set", file=sys.stderr)
        return 1

    commits = read("commits.txt")
    diffstat = read("diffstat.txt")
    if not commits:
        print("No commits in this range -- nothing to summarize.")
        return 0

    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT.format(no_changes=NO_CHANGES)},
            {
                "role": "user",
                "content": f"Commits:\n{commits}\n\nDiffstat:\n```\n{diffstat}\n```",
            },
        ],
        "temperature": 0.2,
        "max_tokens": 1200,
    }
    request = urllib.request.Request(
        ENDPOINT,
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            body = json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:600]
        print(f"ai_changelog_draft: the endpoint returned {exc.code}: {detail}", file=sys.stderr)
        return 1
    except Exception as exc:  # network, DNS, timeout
        print(f"ai_changelog_draft: request failed: {exc}", file=sys.stderr)
        return 1

    try:
        text = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        print(f"ai_changelog_draft: unexpected response shape: {json.dumps(body)[:600]}", file=sys.stderr)
        return 1

    text = (text or "").strip()
    if not text:
        print("ai_changelog_draft: model returned an empty completion", file=sys.stderr)
        return 1
    if NO_CHANGES in text:
        print("No user-facing changes in this push.")
        return 0

    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
