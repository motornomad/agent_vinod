"""Parse a Claude Code session transcript and write an episodic memory entry."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from vinod.memory import upsert_episode_by_session_id

_SUMMARIZE_SYSTEM = """\
You summarize Claude Code sessions into structured memory entries for a personal agent called Vinod.

Given a session transcript, extract:
- project: the primary project worked on (short name, e.g. "my-project", "api-server", "paper")
- summary: one sentence — what was asked and what was built or decided
- detail: 2-4 sentences — key files touched, decisions made, what's next
- tags: 2-5 short lowercase tags

Respond ONLY with valid JSON: {"project": "...", "summary": "...", "detail": "...", "tags": [...]}
"""


def parse_transcript(path: str) -> dict:
    """Extract user messages, assistant texts, files touched, and session_id."""
    p = Path(path)
    if not p.exists():
        return {}

    lines = [json.loads(l) for l in p.read_text().splitlines() if l.strip()]

    session_id: str | None = None
    project_dir: str = ""
    user_messages: list[str] = []
    assistant_texts: list[str] = []
    files_touched: set[str] = set()

    for rec in lines:
        rtype = rec.get("type")

        if not session_id:
            session_id = rec.get("sessionId") or rec.get("session_id")

        if rtype == "system":
            project_dir = rec.get("cwd", "") or rec.get("projectDir", "")

        elif rtype == "user":
            content = rec.get("message", {}).get("content", "")
            if isinstance(content, list):
                text = " ".join(
                    c.get("text", "") for c in content
                    if isinstance(c, dict) and c.get("type") == "text"
                )
            else:
                text = str(content)
            text = text.strip()
            if len(text) > 3:
                user_messages.append(text[:500])

        elif rtype == "assistant":
            content = rec.get("message", {}).get("content", [])
            if isinstance(content, list):
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "text":
                        t = block.get("text", "").strip()
                        if len(t) > 10:
                            assistant_texts.append(t[:300])
                    elif block.get("type") == "tool_use":
                        inp = block.get("input", {})
                        for key in ("file_path", "path"):
                            if key in inp and isinstance(inp[key], str):
                                files_touched.add(inp[key])

    return {
        "session_id": session_id,
        "project_dir": project_dir,
        "user_messages": user_messages,
        "assistant_texts": assistant_texts[:20],
        "files_touched": sorted(files_touched),
    }


def _rule_based_summary(parsed: dict) -> dict:
    from collections import Counter
    msgs = parsed.get("user_messages", [])
    files = parsed.get("files_touched", [])
    project_dir = parsed.get("project_dir", "")

    # Infer project from files touched (most common /root/<project>/)
    if files:
        candidates = []
        for f in files:
            parts = Path(f).parts
            if len(parts) >= 3 and parts[1] == "root":
                candidates.append(parts[2])
        project = Counter(candidates).most_common(1)[0][0] if candidates else Path(project_dir).name or "unknown"
    else:
        project = Path(project_dir).name or "unknown"

    substantive = [m for m in msgs if len(m) > 20]
    if substantive:
        first = substantive[0][:120]
        last = substantive[-1][:120] if len(substantive) > 1 else ""
        summary = (
            f"{project}: '{first}' → '{last}'" if last and last != first
            else f"{project}: {first}"
        )
    else:
        summary = f"Session in {project}: {len(msgs)} exchanges"

    detail = f"{len(msgs)} exchanges. Files touched: {', '.join(files[:8]) or 'none'}."
    return {"project": project, "summary": summary, "detail": detail, "tags": [project]}


def _get_api_key() -> str | None:
    import os
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        return key
    # fallback: ~/.vinod/config.json (set via `vinod config set-api-key <key>`)
    config_path = Path.home() / ".vinod" / "config.json"
    if config_path.exists():
        try:
            cfg = json.loads(config_path.read_text())
            return cfg.get("api_key") or None
        except Exception:
            pass
    return None


def summarize_with_claude(parsed: dict) -> dict:
    """Call Claude API (haiku, cached system) to summarise the session. Falls back gracefully."""
    try:
        import anthropic
    except ImportError:
        return _rule_based_summary(parsed)

    api_key = _get_api_key()
    if not api_key:
        return _rule_based_summary(parsed)

    msgs = parsed.get("user_messages", [])
    asst = parsed.get("assistant_texts", [])
    files = parsed.get("files_touched", [])

    if not msgs:
        return _rule_based_summary(parsed)

    parts: list[str] = []
    for i, m in enumerate(msgs[:15]):
        parts.append(f"User: {m}")
        if i < len(asst):
            parts.append(f"Assistant: {asst[i]}")
    if files:
        parts.append(f"Files touched: {', '.join(files[:10])}")

    try:
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=400,
            system=[{
                "type": "text",
                "text": _SUMMARIZE_SYSTEM,
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{"role": "user", "content": "<transcript>\n" + "\n".join(parts) + "\n</transcript>"}],
        )
        raw = resp.content[0].text.strip()
        # strip markdown code fences if present
        if raw.startswith("```"):
            raw = "\n".join(raw.splitlines()[1:])
            raw = raw.rstrip("`").strip()
        return json.loads(raw)
    except Exception as e:
        print(f"vinod session-end: Claude API error: {e}", file=sys.stderr)
        return _rule_based_summary(parsed)


def handle_start_hook(payload: dict) -> str | None:
    """Entry point for the Claude Code UserPromptSubmit hook.
    Returns memory briefing text to inject as context, or None if not first turn.
    """
    transcript_path = payload.get("transcript_path", "")
    if transcript_path:
        parsed = parse_transcript(transcript_path)
        if parsed.get("assistant_texts"):
            return None

    vinod_dir = Path.home() / ".vinod"
    episodic_file = vinod_dir / "memory" / "episodic.jsonl"
    beliefs_file = vinod_dir / "memory" / "semantic" / "beliefs.json"
    system_prompt_file = vinod_dir / "agent" / "system_prompt.md"
    guardrails_file = vinod_dir / "agent" / "guardrails.md"

    episodes: list[dict] = []
    if episodic_file.exists():
        for line in episodic_file.read_text().splitlines():
            if line.strip():
                try:
                    episodes.append(json.loads(line))
                except Exception:
                    pass
        episodes = episodes[-15:]

    beliefs: list[dict] = []
    if beliefs_file.exists():
        try:
            beliefs = json.loads(beliefs_file.read_text()).get("beliefs", [])
        except Exception:
            pass

    if not episodes and not beliefs:
        return None

    out = ["[Vinod memory loaded]", ""]

    if system_prompt_file.exists():
        content = system_prompt_file.read_text().strip()
        if content:
            out.extend(["## Agent Identity", content, ""])

    if guardrails_file.exists():
        content = guardrails_file.read_text().strip()
        if content:
            out.extend(["## Guardrails", content, ""])

    out.append("## Recent Sessions (oldest first)")
    for ep in episodes:
        ts = ep.get("timestamp", "")[:16]
        summary = ep.get("summary", "")
        detail = ep.get("detail", "")
        out.append(f"[{ts}] {summary}")
        if detail:
            out.append(f"  {detail}")

    if beliefs:
        out.extend(["", "## Active Beliefs (hard invariants — override episodic)"])
        for b in beliefs:
            out.append(f"[{b.get('domain', '?')}] {b.get('summary', '')}")
            if b.get("detail"):
                out.append(f"  {b['detail'][:300]}")

    out.extend([
        "",
        'Brief the user in 2-3 sentences on what was last worked on and what\'s next.',
        'Then ask: "Want to continue there, or work on something else?"',
        "Do this before answering anything else.",
    ])
    return "\n".join(out)


def handle_stop_hook(payload: dict) -> str | None:
    """Entry point for the Claude Code Stop hook. Returns episode ID or None."""
    transcript_path = payload.get("transcript_path")
    if not transcript_path:
        return None

    parsed = parse_transcript(transcript_path)
    if not parsed.get("user_messages"):
        return None

    session_id = payload.get("session_id") or parsed.get("session_id") or ""

    digest = summarize_with_claude(parsed)
    project = digest.get("project") or Path(parsed.get("project_dir", "")).name or "unknown"

    return upsert_episode_by_session_id(
        session_id=session_id,
        source="claude_code_hook",
        project=project,
        event_type="coding_session",
        summary=digest.get("summary", ""),
        detail=digest.get("detail", ""),
        files_touched=parsed.get("files_touched", []),
        tags=digest.get("tags", []),
    )
