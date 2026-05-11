"""Minimal stdio MCP server for Vinod. JSON-RPC 2.0 over stdin/stdout."""
from __future__ import annotations

import json
import sys

from vinod.memory import read_recent, append_episode, read_beliefs, search_episodes, update_belief

TOOLS = [
    {
        "name": "read_memory",
        "description": "Return the last N episodic memory entries.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "n": {"type": "integer", "default": 15, "description": "Number of entries to return"},
            },
        },
    },
    {
        "name": "write_episode",
        "description": "Append one episodic memory entry.",
        "inputSchema": {
            "type": "object",
            "required": ["source", "project", "event_type", "summary"],
            "properties": {
                "source": {"type": "string"},
                "project": {"type": "string"},
                "event_type": {"type": "string"},
                "summary": {"type": "string"},
                "detail": {"type": "string", "default": ""},
                "files_touched": {"type": "array", "items": {"type": "string"}, "default": []},
                "tags": {"type": "array", "items": {"type": "string"}, "default": []},
            },
        },
    },
    {
        "name": "get_beliefs",
        "description": "Return the current beliefs.json contents.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "search_episodes",
        "description": "Search episodic memory by project name and/or tags.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project": {"type": "string", "description": "Filter by project name (partial match)"},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "Filter by tags (any match)"},
                "limit": {"type": "integer", "default": 20, "description": "Max entries to return"},
            },
        },
    },
    {
        "name": "consolidate",
        "description": "Promote episodic patterns into semantic beliefs via Claude API. Requires an API key configured via `vinod config set-api-key`.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "default": 30, "description": "How many days of history to read"},
                "dry_run": {"type": "boolean", "default": False, "description": "Preview without writing"},
            },
        },
    },
    {
        "name": "update_belief",
        "description": "Update a belief's confidence or retire it (set confidence to 0).",
        "inputSchema": {
            "type": "object",
            "required": ["belief_id"],
            "properties": {
                "belief_id": {"type": "string", "description": "The id field of the belief to update"},
                "confidence": {"type": "number", "description": "New confidence value (0.0–1.0)"},
                "retire": {"type": "boolean", "default": False, "description": "Set confidence to 0 to retire the belief"},
            },
        },
    },
]


def handle(req: dict) -> dict:
    rid = req.get("id")
    method = req.get("method", "")
    params = req.get("params", {})

    if method == "initialize":
        return {
            "jsonrpc": "2.0", "id": rid,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "vinod", "version": "0.5.0"},
            },
        }

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": rid, "result": {"tools": TOOLS}}

    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments", {})

        if name == "read_memory":
            entries = read_recent(args.get("n", 15))
            return {
                "jsonrpc": "2.0", "id": rid,
                "result": {"content": [{"type": "text", "text": json.dumps(entries, indent=2)}]},
            }

        if name == "write_episode":
            try:
                eid = append_episode(**{k: v for k, v in args.items()})
                return {
                    "jsonrpc": "2.0", "id": rid,
                    "result": {"content": [{"type": "text", "text": f"OK — entry written: {eid}"}]},
                }
            except ValueError as e:
                return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32602, "message": str(e)}}

        if name == "get_beliefs":
            beliefs = read_beliefs()
            return {
                "jsonrpc": "2.0", "id": rid,
                "result": {"content": [{"type": "text", "text": json.dumps(beliefs, indent=2)}]},
            }

        if name == "search_episodes":
            entries = search_episodes(
                project=args.get("project"),
                tags=args.get("tags"),
                limit=args.get("limit", 20),
            )
            return {
                "jsonrpc": "2.0", "id": rid,
                "result": {"content": [{"type": "text", "text": json.dumps(entries, indent=2)}]},
            }

        if name == "consolidate":
            from vinod.consolidation import run as consolidate_run
            result = consolidate_run(days=args.get("days", 30), dry_run=args.get("dry_run", False))
            return {
                "jsonrpc": "2.0", "id": rid,
                "result": {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]},
            }

        if name == "update_belief":
            belief_id = args.get("belief_id", "")
            found = update_belief(
                belief_id=belief_id,
                confidence=args.get("confidence"),
                retire=args.get("retire", False),
            )
            msg = f"Belief {belief_id} updated." if found else f"Belief {belief_id} not found."
            return {
                "jsonrpc": "2.0", "id": rid,
                "result": {"content": [{"type": "text", "text": msg}]},
            }

        return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": f"Unknown tool: {name}"}}

    return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": f"Unknown method: {method}"}}


def run() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            if "id" not in req:
                continue
            resp = handle(req)
        except json.JSONDecodeError as e:
            resp = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": f"Parse error: {e}"}}
        sys.stdout.write(json.dumps(resp) + "\n")
        sys.stdout.flush()
