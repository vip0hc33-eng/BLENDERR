#!/usr/bin/env python3
"""Draft release notes for the pushed commits using the GitHub Models API.

Reads the commit list and diffstat collected by the workflow (commits.txt,
diffstat.txt), asks the model for GitHub-flavored markdown grouped under
Added / Changed / Fixed / Notes, and prints the draft on stdout.

Stdlib only -- it runs on a bare ubuntu-latest runner, so no pip install step.
The draft is advisory: the workflow never commits it, so a wrong summary costs
a human a re-run, not a bad CHANGELOG entry.

Usage:
    GH_TOKEN=<token> MODEL=openai/gpt-4o-mini python3 tools/ai_changelog_draft.py

GITHUB_MODELS_ENDPOINT overrides the inference URL (default: the GitHub Models
endpoint). Any OpenAI-compatible server works, which is how the script is
exercised without a GitHub token.
"""
import json
import os
import sys
import urllib.error
import urllib.request

ENDPOINT = os.environ.get("GITHUB_MODELS_ENDPOINT", "https://models.github.ai/inference/chat/completions")
MODEL = os.environ.get("MODEL", "openai/gpt-4o-mini")
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
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        print("ai_changelog_draft: GH_TOKEN is not set", file=sys.stderr)
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
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            body = json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:600]
        print(f"ai_changelog_draft: GitHub Models returned {exc.code}: {detail}", file=sys.stderr)
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
