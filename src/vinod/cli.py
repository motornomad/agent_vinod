"""Vinod CLI — vinod init / status / log / mcp"""
from __future__ import annotations

import json
from pathlib import Path

import click

VINOD_DIR = Path.home() / ".vinod"
CLAUDE_SETTINGS = Path.home() / ".claude" / "settings.json"


@click.group()
@click.version_option()
def cli() -> None:
    """Vinod: a stateful personal agent that learns how you work."""


@cli.command()
@click.option("--no-mcp", is_flag=True, help="Skip MCP registration in ~/.claude/settings.json")
def init(no_mcp: bool) -> None:
    """Initialise Vinod in ~/.vinod/ and register MCP with Claude Code."""
    from vinod.templates import CONTEXT_MD, SYSTEM_PROMPT_MD, GUARDRAILS_MD, BELIEFS_JSON, CLAUDE_MD

    # ── Onboarding questionnaire ──────────────────────────────────────────────
    click.echo("")
    click.echo("Vinod gives Claude Code a persistent memory across sessions.")
    click.echo("")
    click.echo("  • Every session is summarised and stored locally as JSONL — your data never leaves this machine")
    click.echo("  • Beliefs and long-term context survive across sessions automatically")
    click.echo("  • No more pasting a context file at the start of every conversation")
    click.echo("")
    click.echo("It works entirely through Claude Code — no separate LLM account needed.")
    click.echo("")
    click.echo("Feedback or questions? arunabh.majumdar@gmail.com")
    click.echo("")
    click.echo("How will you run it?")
    click.echo("  1  Claude Code  (recommended — no API key needed inside Vinod)")
    click.echo("  2  Something else")
    click.echo("")
    choice = click.prompt("Enter choice", type=click.Choice(["1", "2"]), default="1", show_default=True)

    if choice == "2":
        click.echo("")
        click.echo("Vinod currently only works with Claude Code.")
        click.echo("Standalone LLM support (API key / local models) is planned for a future release.")
        click.echo("Install Claude Code at https://claude.ai/code and re-run `vinod init`.")
        return

    click.echo("")
    click.echo("Great. Vinod will register itself as an MCP server inside Claude Code.")
    # ─────────────────────────────────────────────────────────────────────────

    if VINOD_DIR.exists():
        click.echo(f"Vinod already initialised at {VINOD_DIR}")
        click.echo("Run `vinod status` to check memory state.")
        return

    dirs = [
        VINOD_DIR / "memory" / "semantic",
        VINOD_DIR / "agent",
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)

    (VINOD_DIR / "CONTEXT.md").write_text(CONTEXT_MD)

    claude_md_path = CLAUDE_SETTINGS.parent / "CLAUDE.md"
    if not claude_md_path.exists():
        write_claude_md = click.confirm(
            f"Write session instructions to {claude_md_path}?", default=True
        )
        if write_claude_md:
            claude_md_path.write_text(CLAUDE_MD)
            click.echo(f"CLAUDE.md written to {claude_md_path}")
    else:
        click.echo(f"CLAUDE.md already exists at {claude_md_path} — skipping")

    (VINOD_DIR / "agent" / "system_prompt.md").write_text(SYSTEM_PROMPT_MD)
    (VINOD_DIR / "agent" / "guardrails.md").write_text(GUARDRAILS_MD)
    (VINOD_DIR / "memory" / "semantic" / "beliefs.json").write_text(BELIEFS_JSON)
    episodic = VINOD_DIR / "memory" / "episodic.jsonl"
    if not episodic.exists():
        episodic.touch()

    click.echo(f"Scaffolded {VINOD_DIR}")

    if not no_mcp:
        _register_mcp()
        _register_stop_hook()
        _register_start_hook()

    click.echo("")
    click.echo("All done. Start a new Claude Code session — Vinod will load your memory automatically.")


@cli.command()
def status() -> None:
    """Show current observer and memory status."""
    from vinod.memory import episode_count, read_recent, read_beliefs
    from vinod.consolidation import last_run_info

    if not VINOD_DIR.exists():
        click.echo("Vinod not initialised. Run `vinod init` first.")
        return

    count = episode_count()
    click.echo(f"Episodic entries : {count}")

    if count > 0:
        recent = read_recent(3)
        click.echo("Last 3 entries:")
        for e in reversed(recent):
            ts = e.get("timestamp", "")[:16]
            click.echo(f"  [{ts}] {e.get('project', '?')} -- {e.get('summary', '')[:80]}")

    beliefs = read_beliefs()
    belief_list = beliefs.get("beliefs", [])
    n_beliefs = len(belief_list)
    active = [b for b in belief_list if b.get("confidence", 1) > 0]
    click.echo(f"Beliefs          : {n_beliefs} total, {len(active)} active")
    if active:
        top = sorted(active, key=lambda b: b.get("confidence", 0), reverse=True)[:3]
        for b in top:
            fact = (b.get("fact") or b.get("summary", ""))[:70]
            conf = b.get("confidence", 0)
            click.echo(f"  [{int(conf*100)}%] {fact}")

    state = last_run_info()
    if state:
        click.echo(f"Last consolidate : {state.get('last_run', '')[:16]}  (+{state.get('promoted', 0)} beliefs from {state.get('episodes_read', 0)} episodes)")
    else:
        click.echo("Last consolidate : never  (run: vinod consolidate)")

    mcp_ok = _mcp_registered()
    click.echo(f"MCP registered   : {'yes' if mcp_ok else 'no  (run: vinod init)'}")


@cli.command()
@click.option("--project", "-p", required=True, help="Project name")
@click.option("--summary", "-s", required=True, help="One-line summary")
@click.option("--detail", "-d", default="", help="Full detail")
@click.option("--tags", "-t", multiple=True, help="Tags (repeat for multiple)")
@click.option("--files", "-f", multiple=True, help="Files touched (repeat for multiple)")
@click.option("--source", default="manual", show_default=True, help="Entry source")
@click.option("--event", "event_type", default="session", show_default=True, help="Event type")
def log(project: str, summary: str, detail: str, tags: tuple, files: tuple, source: str, event_type: str) -> None:
    """Write a manual episodic memory entry."""
    from vinod.memory import append_episode

    if not VINOD_DIR.exists():
        click.echo("Vinod not initialised. Run `vinod init` first.")
        return

    eid = append_episode(
        source=source,
        project=project,
        event_type=event_type,
        summary=summary,
        detail=detail,
        files_touched=list(files),
        tags=list(tags),
    )
    click.echo(f"episodic {eid}")


@cli.command()
@click.option("--days", default=30, show_default=True, help="How many days of episodic history to read.")
@click.option("--dry-run", is_flag=True, help="Preview what would be promoted without writing.")
def consolidate(days: int, dry_run: bool) -> None:
    """Promote episodic patterns into semantic beliefs via Claude API."""
    from vinod.consolidation import run as consolidate_run

    if not VINOD_DIR.exists():
        click.echo("Vinod not initialised. Run `vinod init` first.")
        return

    click.echo(f"Reading last {days} days of episodic memory...")
    result = consolidate_run(days=days, dry_run=dry_run)

    if "error" in result:
        click.echo(f"Error: {result['error']}", err=True)
        return

    if dry_run:
        click.echo(f"Would promote {result['would_promote']} beliefs from {result['episodes_read']} episodes (dry run — nothing written).")
        for b in result.get("beliefs", []):
            click.echo(f"  [{b.get('domain','?')}] [{int(b.get('confidence',0)*100)}%] {b.get('fact','')}")
    else:
        click.echo(f"Done. Promoted {result['promoted']} new beliefs. Total: {result['total_beliefs']} beliefs from {result['episodes_read']} episodes.")


@cli.command()
def mcp() -> None:
    """Start the Vinod MCP server (stdio transport -- used by Claude Code)."""
    from vinod.mcp_server import run
    run()


@cli.group()
def config() -> None:
    """Manage Vinod configuration."""


@config.command("set-api-key")
@click.argument("key")
def config_set_api_key(key: str) -> None:
    """Store an Anthropic API key for session summarisation."""
    config_path = VINOD_DIR / "config.json"
    cfg: dict = {}
    if config_path.exists():
        try:
            cfg = json.loads(config_path.read_text())
        except json.JSONDecodeError:
            pass
    cfg["api_key"] = key
    config_path.write_text(json.dumps(cfg, indent=2) + "\n")
    click.echo(f"API key saved to {config_path}")


@config.command("show")
def config_show() -> None:
    """Show current Vinod configuration."""
    config_path = VINOD_DIR / "config.json"
    if not config_path.exists():
        click.echo("No config file. Run `vinod config set-api-key <key>` to enable Claude summarisation.")
        return
    cfg = json.loads(config_path.read_text())
    if "api_key" in cfg:
        cfg["api_key"] = cfg["api_key"][:12] + "..."
    click.echo(json.dumps(cfg, indent=2))


@cli.command()
@click.option("--yes", is_flag=True, help="Skip confirmation prompts")
def uninstall(yes: bool) -> None:
    """Remove Vinod: delete ~/.vinod/, de-register MCP and hooks from settings.json."""
    import shutil

    if not yes:
        click.confirm("This will delete ~/.vinod/ and remove Vinod from Claude Code settings. Continue?", abort=True)

    # Remove ~/.vinod/
    if VINOD_DIR.exists():
        shutil.rmtree(VINOD_DIR)
        click.echo(f"Deleted {VINOD_DIR}")
    else:
        click.echo(f"{VINOD_DIR} not found — skipping")

    # De-register from settings.json
    if CLAUDE_SETTINGS.exists():
        try:
            settings = json.loads(CLAUDE_SETTINGS.read_text())
            changed = False

            if "vinod" in settings.get("mcpServers", {}):
                del settings["mcpServers"]["vinod"]
                changed = True
                click.echo("Removed MCP server registration")

            for hook_event in ("Stop", "UserPromptSubmit"):
                hook_list = settings.get("hooks", {}).get(hook_event, [])
                filtered = [
                    e for e in hook_list
                    if not any("vinod" in h.get("command", "") for h in e.get("hooks", []))
                ]
                if len(filtered) != len(hook_list):
                    settings["hooks"][hook_event] = filtered
                    changed = True
                    click.echo(f"Removed {hook_event} hook")

            if changed:
                CLAUDE_SETTINGS.write_text(json.dumps(settings, indent=2) + "\n")
        except (json.JSONDecodeError, KeyError) as e:
            click.echo(f"Warning: could not update {CLAUDE_SETTINGS}: {e}")

    click.echo("")
    click.echo("Vinod uninstalled. Run `pip uninstall vinod` to remove the package.")


@cli.command("session-start")
def session_start() -> None:
    """Called by the Claude Code UserPromptSubmit hook — injects memory on first prompt."""
    import sys
    try:
        raw = sys.stdin.read().strip()
        payload = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        sys.exit(0)

    try:
        from vinod.session_writer import handle_start_hook
        context = handle_start_hook(payload)
        if context:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            print(context)
    except Exception as e:
        click.echo(f"vinod session-start error: {e}", err=True)

    sys.exit(0)


@cli.command("session-end")
def session_end() -> None:
    """Called by the Claude Code Stop hook — summarise the session and write an episodic entry."""
    import sys
    try:
        raw = sys.stdin.read().strip()
        payload = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        sys.exit(0)

    try:
        from vinod.session_writer import handle_stop_hook
        eid = handle_stop_hook(payload)
        if eid:
            click.echo(f"vinod: episode upserted {eid}", err=True)
    except Exception as e:
        click.echo(f"vinod session-end error: {e}", err=True)

    sys.exit(0)  # never block Claude from stopping


def _register_stop_hook() -> None:
    CLAUDE_SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    settings: dict = {}
    if CLAUDE_SETTINGS.exists():
        try:
            settings = json.loads(CLAUDE_SETTINGS.read_text())
        except json.JSONDecodeError:
            return

    stop_hooks = settings.setdefault("hooks", {}).setdefault("Stop", [])
    for entry in stop_hooks:
        for h in entry.get("hooks", []):
            if "vinod session-end" in h.get("command", ""):
                click.echo("Stop hook already registered")
                return

    stop_hooks.append({"matcher": "", "hooks": [{"type": "command", "command": "vinod session-end"}]})
    CLAUDE_SETTINGS.write_text(json.dumps(settings, indent=2) + "\n")
    click.echo(f"Stop hook registered in {CLAUDE_SETTINGS}")


def _register_start_hook() -> None:
    CLAUDE_SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    settings: dict = {}
    if CLAUDE_SETTINGS.exists():
        try:
            settings = json.loads(CLAUDE_SETTINGS.read_text())
        except json.JSONDecodeError:
            return

    start_hooks = settings.setdefault("hooks", {}).setdefault("UserPromptSubmit", [])
    for entry in start_hooks:
        for h in entry.get("hooks", []):
            if "vinod session-start" in h.get("command", ""):
                click.echo("UserPromptSubmit hook already registered")
                return

    start_hooks.append({"matcher": "", "hooks": [{"type": "command", "command": "vinod session-start"}]})
    CLAUDE_SETTINGS.write_text(json.dumps(settings, indent=2) + "\n")
    click.echo(f"UserPromptSubmit hook registered in {CLAUDE_SETTINGS}")


def _register_mcp() -> None:
    import shutil
    import sys as _sys

    CLAUDE_SETTINGS.parent.mkdir(parents=True, exist_ok=True)

    settings: dict = {}
    if CLAUDE_SETTINGS.exists():
        try:
            settings = json.loads(CLAUDE_SETTINGS.read_text())
        except json.JSONDecodeError:
            click.echo(f"Warning: could not parse {CLAUDE_SETTINGS} -- skipping MCP registration")
            return

    servers = settings.setdefault("mcpServers", {})
    if "vinod" in servers:
        click.echo("MCP server already registered")
        return

    vinod_exe = shutil.which("vinod") or _sys.argv[0]
    servers["vinod"] = {"command": vinod_exe, "args": ["mcp"], "type": "stdio"}
    CLAUDE_SETTINGS.write_text(json.dumps(settings, indent=2) + "\n")
    click.echo(f"MCP server registered in {CLAUDE_SETTINGS}")


def _mcp_registered() -> bool:
    if not CLAUDE_SETTINGS.exists():
        return False
    try:
        settings = json.loads(CLAUDE_SETTINGS.read_text())
        return "vinod" in settings.get("mcpServers", {})
    except (json.JSONDecodeError, KeyError):
        return False
