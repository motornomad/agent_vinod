"""Path-aware episodic memory for vinod — uses ~/.vinod/ not a hardcoded path."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

VINOD_DIR = Path.home() / ".vinod"
EPISODIC_FILE = VINOD_DIR / "memory" / "episodic.jsonl"
BELIEFS_FILE = VINOD_DIR / "memory" / "semantic" / "beliefs.json"

IST = timezone(timedelta(hours=5, minutes=30))


def now_ist() -> str:
    return datetime.now(IST).isoformat()


def append_episode(
    source: str,
    project: str,
    event_type: str,
    summary: str,
    detail: str = "",
    files_touched: list | None = None,
    tags: list | None = None,
    llm_digest: bool = False,
    raw_ref: str = "",
    timestamp: str | None = None,
) -> str:
    entry = {
        "id": str(uuid.uuid4()),
        "timestamp": timestamp or now_ist(),
        "source": source,
        "project": project,
        "event_type": event_type,
        "summary": summary,
        "detail": detail,
        "files_touched": files_touched or [],
        "tags": tags or [],
        "llm_digest": llm_digest,
        "raw_ref": raw_ref,
    }

    EPISODIC_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(EPISODIC_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")

    return entry["id"]


def read_recent(n: int = 15) -> list:
    if not EPISODIC_FILE.exists():
        return []
    lines = EPISODIC_FILE.read_text().strip().splitlines()
    return [json.loads(line) for line in lines[-n:] if line.strip()]


def read_beliefs() -> dict:
    if not BELIEFS_FILE.exists():
        return {}
    return json.loads(BELIEFS_FILE.read_text())


def upsert_episode_by_session_id(session_id: str, **kwargs) -> str:
    """Write an episode, replacing any existing entry with the same session_id."""
    entry = {
        "id": str(uuid.uuid4()),
        "timestamp": now_ist(),
        "session_id": session_id,
        "source": kwargs.get("source", "claude_code_hook"),
        "project": kwargs.get("project", "unknown"),
        "event_type": kwargs.get("event_type", "coding_session"),
        "summary": kwargs.get("summary", ""),
        "detail": kwargs.get("detail", ""),
        "files_touched": kwargs.get("files_touched") or [],
        "tags": kwargs.get("tags") or [],
        "llm_digest": True,
        "raw_ref": "",
    }

    EPISODIC_FILE.parent.mkdir(parents=True, exist_ok=True)

    if not EPISODIC_FILE.exists() or not session_id:
        with open(EPISODIC_FILE, "a") as f:
            f.write(json.dumps(entry) + "\n")
        return entry["id"]

    lines = EPISODIC_FILE.read_text().splitlines()
    replaced = False
    new_lines: list[str] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            existing = json.loads(line)
            if existing.get("session_id") == session_id:
                # keep original id and timestamp so the entry isn't re-dated on every turn
                entry["id"] = existing.get("id", entry["id"])
                entry["timestamp"] = existing.get("timestamp", entry["timestamp"])
                new_lines.append(json.dumps(entry))
                replaced = True
            else:
                new_lines.append(line)
        except json.JSONDecodeError:
            new_lines.append(line)

    if not replaced:
        new_lines.append(json.dumps(entry))

    EPISODIC_FILE.write_text("\n".join(new_lines) + "\n")
    return entry["id"]


def episode_count() -> int:
    if not EPISODIC_FILE.exists():
        return 0
    return sum(1 for line in EPISODIC_FILE.read_text().splitlines() if line.strip())


def search_episodes(project: str | None = None, tags: list | None = None, limit: int = 20) -> list:
    if not EPISODIC_FILE.exists():
        return []
    results = []
    for line in EPISODIC_FILE.read_text().splitlines():
        if not line.strip():
            continue
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        if project and project.lower() not in e.get("project", "").lower():
            continue
        if tags:
            entry_tags = [t.lower() for t in e.get("tags", [])]
            if not any(t.lower() in entry_tags for t in tags):
                continue
        results.append(e)
    return results[-limit:]


def update_belief(belief_id: str, confidence: float | None = None, retire: bool = False) -> bool:
    """Update a belief by id. Returns True if found and updated."""
    if not BELIEFS_FILE.exists():
        return False
    try:
        store = json.loads(BELIEFS_FILE.read_text())
    except Exception:
        return False
    for b in store.get("beliefs", []):
        if b.get("id") == belief_id:
            if retire:
                b["confidence"] = 0.0
            elif confidence is not None:
                b["confidence"] = max(0.0, min(1.0, confidence))
            BELIEFS_FILE.write_text(json.dumps(store, indent=2) + "\n")
            return True
    return False
