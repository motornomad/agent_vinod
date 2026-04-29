"""Minimal stdio MCP server for Vinod. JSON-RPC 2.0 over stdin/stdout."""
from __future__ import annotations

import json
import sys

from vinod.memory import read_recent, append_episode, read_beliefs

TOOLS = [
    {
        "name": "read_memory",
        "description": "Return the last N episodic memory entries.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "n": {"type": "integer", "default": 15, "description": "Number of entries to return"}
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
                "serverInfo": {"name": "vinod", "version": "0.1.0"},
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
