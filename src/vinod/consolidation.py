"""Episodic → semantic consolidation for Vinod.

Reads recent episodic entries, calls Claude API, promotes stable patterns as beliefs.
Run manually with `vinod consolidate` or schedule via cron.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

VINOD_DIR = Path.home() / ".vinod"
EPISODIC_FILE = VINOD_DIR / "memory" / "episodic.jsonl"
BELIEFS_FILE = VINOD_DIR / "memory" / "semantic" / "beliefs.json"
STATE_FILE = VINOD_DIR / "memory" / "consolidation_state.json"

IST = timezone(timedelta(hours=5, minutes=30))

_SYSTEM = """\
You analyze a developer's session log and extract stable beliefs about their work patterns.

Given a list of episodic memory entries (JSON), identify patterns that appear in multiple entries \
and are likely to remain true over time — things like: which projects they work on, their workflow \
preferences, recurring goals, architectural decisions, or constraints they mention repeatedly.

For each belief output:
- fact: a single declarative sentence (no hedging, no "seems to")
- domain: the project or area it applies to (e.g. "my-api", "general", "frontend")
- confidence: 0.0–1.0 (how certain, based on how often you see it)
- obs_count: approximate number of episodes supporting it
- tags: 2–4 short lowercase tags

Respond ONLY with valid JSON: {"beliefs": [...]}
Only include beliefs with confidence >= 0.6 and obs_count >= 2.
"""


def _get_api_key() -> str | None:
    import os
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        return key
    config_path = VINOD_DIR / "config.json"
    if config_path.exists():
        try:
            return json.loads(config_path.read_text()).get("api_key")
        except Exception:
            pass
    return None


def _read_recent_episodes(days: int = 30) -> list[dict]:
    if not EPISODIC_FILE.exists():
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    entries = []
    for line in EPISODIC_FILE.read_text().splitlines():
        if not line.strip():
            continue
        try:
            e = json.loads(line)
            ts_str = e.get("timestamp", "")
            if ts_str:
                try:
                    ts = datetime.fromisoformat(ts_str)
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    if ts < cutoff:
                        continue
                except ValueError:
                    pass
            entries.append(e)
        except Exception:
            pass
    return entries


def _load_beliefs() -> dict:
    if not BELIEFS_FILE.exists():
        return {"version": 1, "beliefs": []}
    try:
        return json.loads(BELIEFS_FILE.read_text())
    except Exception:
        return {"version": 1, "beliefs": []}


def _save_beliefs(store: dict) -> None:
    BELIEFS_FILE.parent.mkdir(parents=True, exist_ok=True)
    BELIEFS_FILE.write_text(json.dumps(store, indent=2) + "\n")


def _upsert_belief(store: dict, new: dict, now: str) -> None:
    fact = new.get("fact", "").strip().lower()
    for b in store["beliefs"]:
        if b.get("fact", "").strip().lower() == fact:
            b["confidence"] = max(b.get("confidence", 0), new.get("confidence", 0.6))
            b["obs_count"] = max(b.get("obs_count", 0), new.get("obs_count", 2))
            b["last_seen"] = now
            b["tags"] = sorted(set(b.get("tags", []) + new.get("tags", [])))
            return
    store["beliefs"].append({
        "id": str(uuid.uuid4()),
        "fact": new.get("fact", ""),
        "domain": new.get("domain", "general"),
        "confidence": new.get("confidence", 0.6),
        "obs_count": new.get("obs_count", 2),
        "first_seen": now,
        "last_seen": now,
        "tags": new.get("tags", []),
    })


def last_run_info() -> dict | None:
    if not STATE_FILE.exists():
        return None
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return None


def run(days: int = 30, dry_run: bool = False) -> dict:
    """Run consolidation. Returns summary dict."""
    api_key = _get_api_key()
    if not api_key:
        return {"error": "No API key. Run: vinod config set-api-key sk-ant-..."}

    episodes = _read_recent_episodes(days)
    if not episodes:
        return {"error": "No episodic entries found.", "promoted": 0}

    try:
        import anthropic
    except ImportError:
        return {"error": "anthropic package not installed. Run: pip install anthropic"}

    slim = [
        {
            "ts": e.get("timestamp", "")[:16],
            "project": e.get("project", ""),
            "summary": e.get("summary", ""),
            "tags": e.get("tags", []),
        }
        for e in episodes
    ]

    client = anthropic.Anthropic(api_key=api_key)
    try:
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1000,
            system=[{"type": "text", "text": _SYSTEM, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": json.dumps(slim, indent=2)}],
        )
        raw = resp.content[0].text.strip()
        if raw.startswith("```"):
            raw = "\n".join(raw.splitlines()[1:]).rstrip("`").strip()
        result = json.loads(raw)
    except Exception as e:
        return {"error": f"Claude API error: {e}", "promoted": 0}

    new_beliefs = result.get("beliefs", [])

    if dry_run:
        return {"dry_run": True, "would_promote": len(new_beliefs), "beliefs": new_beliefs, "episodes_read": len(episodes)}

    now = datetime.now(IST).isoformat()
    store = _load_beliefs()
    before = len(store["beliefs"])
    for b in new_beliefs:
        if b.get("confidence", 0) >= 0.6 and b.get("obs_count", 0) >= 2:
            _upsert_belief(store, b, now)
    _save_beliefs(store)

    promoted = len(store["beliefs"]) - before
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps({
        "last_run": now,
        "episodes_read": len(episodes),
        "promoted": promoted,
        "total_beliefs": len(store["beliefs"]),
    }) + "\n")

    return {"promoted": promoted, "total_beliefs": len(store["beliefs"]), "episodes_read": len(episodes)}
