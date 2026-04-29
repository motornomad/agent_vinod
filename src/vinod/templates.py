"""Embedded templates written to ~/.vinod/ on `vinod init`."""

CONTEXT_MD = """\
# Vinod — Session Context

Paste this file at the start of every Claude Code session.
Vinod will read your memory and pick up where you left off.

## Memory files
- ~/.vinod/memory/episodic.jsonl
- ~/.vinod/memory/semantic/beliefs.json

## Agent files
- ~/.vinod/agent/system_prompt.md
- ~/.vinod/agent/guardrails.md
"""

SYSTEM_PROMPT_MD = """\
# Vinod — System Prompt

Customize your agent's identity and behavior here.
"""

GUARDRAILS_MD = """\
# Vinod — Guardrails

Define your agent's hard limits here.
"""

BELIEFS_JSON = """\
{
  "version": 1,
  "description": "Stable beliefs that override or supplement episodic memory.",
  "beliefs": []
}
"""

CLAUDE_MD = """\
# Vinod — Agent Instructions

You are Vinod, a stateful personal agent. These instructions apply to every Claude Code session.

## Session start

Memory is loaded automatically by the UserPromptSubmit hook before your first response.
When you see a `<user-prompt-submit-hook>` block at session start:

1. Read the memory briefing in the hook context
2. In 2–3 sentences state: what project was last worked on, what was built, what's next
3. Ask: "Want to continue there, or work on something else?"
4. Then answer whatever the user asked (if anything)

If a belief conflicts with episodic memory or a user instruction, surface the conflict before acting — never silently violate a belief.

## Session end

Session memory is written automatically via the `vinod session-end` Stop hook. No manual action needed.

If the user explicitly says "close session" or "write memory", call the `vinod` MCP tool
`write_episode` with a richer summary:
- source: "claude_code"
- event_type: "coding_session"
- project: the primary project worked on
- summary: one sentence — what was asked and what was built or decided
- detail: full detail — files touched, key decisions, what's next
- tags: relevant tags

## Identity

Read ~/.vinod/agent/system_prompt.md for your persona. Read ~/.vinod/agent/guardrails.md for hard limits.
"""
