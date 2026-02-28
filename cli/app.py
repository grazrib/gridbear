"""GridBear CLI — Typer application with all commands."""

import fnmatch
from typing import Annotated, Optional

import typer

from cli import __version__
from cli.config import load_config
from cli.formatters import (
    console,
    format_creds,
    format_server_detail,
    format_servers,
    format_tools,
    format_whoami,
    print_error,
    print_success,
)

app = typer.Typer(
    name="gridbear",
    help="GridBear CLI — interact with the MCP gateway and runtime.",
    no_args_is_help=True,
)

# ── Global options ──────────────────────────────────────────────────

OutputOption = Annotated[
    Optional[str],
    typer.Option("--output", "-o", help="Output format: table or json"),
]
GatewayOption = Annotated[
    Optional[str],
    typer.Option("--gateway-url", "-g", help="Gateway URL override"),
]
UserOption = Annotated[
    Optional[str],
    typer.Option("--user", "-u", help="Username (e.g. Telegram username)"),
]
IdentityOption = Annotated[
    Optional[str],
    typer.Option(
        "--identity", "-i", help="Unified ID for credential/permission resolution"
    ),
]


def _version_callback(value: bool):
    if value:
        console.print(f"gridbear {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool, typer.Option("--version", "-V", callback=_version_callback, is_eager=True)
    ] = False,
):
    """GridBear CLI."""


# ── Helpers ─────────────────────────────────────────────────────────


def _resolve_user(user_flag: str | None, cfg) -> str | None:
    return user_flag or cfg.default_user


def _resolve_identity(
    identity_flag: str | None, user_flag: str | None, cfg
) -> str | None:
    """Resolve unified_id: --identity > --user > config default."""
    return identity_flag or user_flag or cfg.default_user


def _get_token(cfg):
    from cli.auth import AuthError, get_token

    try:
        return get_token(cfg.gateway_url)
    except AuthError as e:
        print_error(str(e))
        raise typer.Exit(2)


# ── Auth commands ───────────────────────────────────────────────────


@app.command()
def login(
    session_name: Annotated[
        Optional[str],
        typer.Option("--session-name", "-s", help="Isolated session name"),
    ] = None,
    gateway_url: GatewayOption = None,
):
    """Register OAuth2 client and obtain access token."""
    from cli.auth import AuthError
    from cli.auth import login as do_login

    cfg = load_config(gateway_url=gateway_url)
    try:
        result = do_login(cfg.gateway_url, session_name)
        print_success(
            f"Logged in as {result['agent_name']} "
            f"(client: {result['client_id'][:8]}...)"
        )
    except AuthError as e:
        print_error(str(e))
        raise typer.Exit(2)


@app.command()
def logout(gateway_url: GatewayOption = None):
    """Revoke token and delete stored credentials."""
    from cli.auth import logout as do_logout

    cfg = load_config(gateway_url=gateway_url)
    do_logout(cfg.gateway_url)
    print_success("Logged out.")


@app.command()
def whoami(
    output: OutputOption = None,
    gateway_url: GatewayOption = None,
):
    """Show current authentication info."""
    from cli.auth import whoami as do_whoami

    load_config(gateway_url=gateway_url)
    info = do_whoami()
    format_whoami(info, output)


@app.command()
def status(
    output: OutputOption = None,
    gateway_url: GatewayOption = None,
):
    """Show gateway connection status and server summary."""
    cfg = load_config(gateway_url=gateway_url)
    token = _get_token(cfg)

    from cli.api import APIClient, APIError

    client = APIClient(cfg.gateway_url, token)
    try:
        servers = client.list_servers()
    except APIError as e:
        print_error(str(e))
        raise typer.Exit(1)
    finally:
        client.close()

    connected = sum(1 for s in servers if s.get("connected"))
    cb_open = sum(1 for s in servers if s.get("circuit_breaker") == "open")

    console.print(f"[bold]Gateway:[/bold]    {cfg.gateway_url}")
    console.print(
        f"[bold]Servers:[/bold]    {len(servers)} total, {connected} connected"
    )
    if cb_open:
        console.print(f"[bold]CB Open:[/bold]    [red]{cb_open}[/red]")
    console.print()
    format_servers(servers, output)


# ── Tool commands ───────────────────────────────────────────────────


@app.command()
def tools(
    user: UserOption = None,
    identity: IdentityOption = None,
    grep: Annotated[
        Optional[str], typer.Option("--grep", help="Filter by name/description")
    ] = None,
    server: Annotated[
        Optional[str], typer.Option("--server", help="Filter by server name pattern")
    ] = None,
    category: Annotated[
        Optional[str], typer.Option("--category", help="Filter by MCP category")
    ] = None,
    output: OutputOption = None,
    gateway_url: GatewayOption = None,
):
    """List available MCP tools."""
    cfg = load_config(gateway_url=gateway_url)
    token = _get_token(cfg)
    uid = _resolve_identity(identity, user, cfg)

    from cli.gateway import GatewayClient, GatewayError

    gw = GatewayClient(cfg.gateway_url, token)
    try:
        if uid:
            gw.set_user_context(cfg.gateway_url, uid)
        gw.initialize()
        tool_list = gw.list_tools(user_identity=uid)
    except GatewayError as e:
        print_error(str(e))
        raise typer.Exit(1)
    finally:
        gw.close()

    # Client-side filtering
    if grep:
        gl = grep.lower()
        tool_list = [
            t
            for t in tool_list
            if gl in t.get("name", "").lower() or gl in t.get("description", "").lower()
        ]
    if server:
        tool_list = [
            t
            for t in tool_list
            if fnmatch.fnmatch(t.get("name", "").split("__")[0], server)
        ]
    if category:
        # Category filtering requires server info — filter by name prefix
        # For now, match tools whose server name prefix matches category pattern
        from cli.api import APIClient

        api = APIClient(cfg.gateway_url, token)
        try:
            servers_list = api.list_servers()
        finally:
            api.close()
        cat_servers = {s["name"] for s in servers_list if s.get("category") == category}
        tool_list = [
            t
            for t in tool_list
            if any(
                t.get("name", "").startswith(sn.replace(".", "-").replace("@", "-"))
                for sn in cat_servers
            )
        ]

    format_tools(tool_list, output)


@app.command()
def search(
    query: Annotated[str, typer.Argument(help="Search query for tools")],
    user: UserOption = None,
    identity: IdentityOption = None,
    output: OutputOption = None,
    gateway_url: GatewayOption = None,
):
    """Search tools by keyword (semantic search)."""
    cfg = load_config(gateway_url=gateway_url)
    token = _get_token(cfg)
    uid = _resolve_identity(identity, user, cfg)

    from cli.gateway import GatewayClient, GatewayError

    gw = GatewayClient(cfg.gateway_url, token)
    try:
        if uid:
            gw.set_user_context(cfg.gateway_url, uid)
        gw.initialize()
        results = gw.call_tool("search_tools", {"query": query}, user_identity=uid)
    except GatewayError as e:
        print_error(str(e))
        raise typer.Exit(1)
    finally:
        gw.close()

    # search_tools returns text content blocks
    for block in results:
        if block.get("type") == "text":
            console.print(block.get("text", ""))


# ── Server inspection commands ──────────────────────────────────────


@app.command()
def servers(
    status_filter: Annotated[
        Optional[str],
        typer.Option("--status", help="Filter: connected, idle, open"),
    ] = None,
    output: OutputOption = None,
    gateway_url: GatewayOption = None,
):
    """List all known MCP servers."""
    cfg = load_config(gateway_url=gateway_url)
    token = _get_token(cfg)

    from cli.api import APIClient, APIError

    client = APIClient(cfg.gateway_url, token)
    try:
        srv_list = client.list_servers()
    except APIError as e:
        print_error(str(e))
        raise typer.Exit(1)
    finally:
        client.close()

    if status_filter:
        if status_filter == "connected":
            srv_list = [s for s in srv_list if s.get("connected")]
        elif status_filter == "idle":
            srv_list = [s for s in srv_list if not s.get("connected")]
        elif status_filter == "open":
            srv_list = [s for s in srv_list if s.get("circuit_breaker") == "open"]

    format_servers(srv_list, output)


@app.command("server")
def server_detail(
    name: Annotated[str, typer.Argument(help="Server name")],
    output: OutputOption = None,
    gateway_url: GatewayOption = None,
):
    """Show detail for a single MCP server."""
    cfg = load_config(gateway_url=gateway_url)
    token = _get_token(cfg)

    from cli.api import APIClient, APIError

    client = APIClient(cfg.gateway_url, token)
    try:
        detail = client.get_server(name)
    except APIError as e:
        print_error(str(e))
        raise typer.Exit(1)
    finally:
        client.close()

    format_server_detail(detail, output)


@app.command()
def creds(
    connection_id: Annotated[str, typer.Argument(help="Service connection ID")],
    user: UserOption = None,
    identity: IdentityOption = None,
    output: OutputOption = None,
    gateway_url: GatewayOption = None,
):
    """Check credential status for a user + connection."""
    cfg = load_config(gateway_url=gateway_url)
    uid = _resolve_identity(identity, user, cfg)
    if not uid:
        print_error("--user is required (or set GRIDBEAR_CLI_USER / config.toml)")
        raise typer.Exit(1)

    token = _get_token(cfg)

    from cli.api import APIClient, APIError

    client = APIClient(cfg.gateway_url, token)
    try:
        result = client.check_creds(connection_id, uid)
    except APIError as e:
        print_error(str(e))
        raise typer.Exit(1)
    finally:
        client.close()

    format_creds(result, output)


# ── Chat command ────────────────────────────────────────────────────


def _get_chat_token(cfg) -> str:
    """Get auth token for chat — INTERNAL_API_SECRET or OAuth2.

    Precedence: INTERNAL_API_SECRET env var > OAuth2 token.
    """
    import os

    secret = os.environ.get("INTERNAL_API_SECRET")
    if secret:
        return secret

    # Fall back to OAuth2 token
    return _get_token(cfg)


@app.command()
def chat(
    text: Annotated[str, typer.Argument(help="Message to send to the agent")],
    user: UserOption = None,
    identity: IdentityOption = None,
    agent: Annotated[
        Optional[str],
        typer.Option("--agent", "-a", help="Agent name"),
    ] = None,
    portal_user: Annotated[
        Optional[str],
        typer.Option("--portal-user", "-p", help="Portal username (e.g. admin)"),
    ] = None,
    output: OutputOption = None,
    gateway_url: GatewayOption = None,
):
    """Send a message to an agent and print the response.

    --user: username visible to the agent (e.g. Telegram username)
    --identity: unified_id for credential/permission resolution
    --portal-user: portal username for display_name lookup

    Examples:
        gridbear chat "What's my next meeting?" --user johndoe --agent myagent
        gridbear chat "Hello" -i johndoe -a myagent -p admin
    """
    cfg = load_config(gateway_url=gateway_url)
    uid = _resolve_identity(identity, user, cfg)
    username = user or uid
    agent_name = agent or cfg.default_agent

    if not uid:
        print_error(
            "--user or --identity is required (or set GRIDBEAR_CLI_USER / config.toml)"
        )
        raise typer.Exit(1)
    if not agent_name:
        print_error("--agent is required (or set default_agent in config.toml)")
        raise typer.Exit(1)

    token = _get_chat_token(cfg)

    from cli.api import APIClient, APIError

    client = APIClient(cfg.gateway_url, token)
    try:
        with console.status(f"[bold]Waiting for {agent_name}...[/bold]"):
            result = client.chat(
                text,
                user_id=uid,
                agent_name=agent_name,
                username=portal_user or username,
                display_name=portal_user,
            )
    except APIError as e:
        print_error(str(e))
        raise typer.Exit(1)
    finally:
        client.close()

    from cli.formatters import _is_json_output

    if _is_json_output(output):
        import json

        console.print_json(json.dumps(result))
    else:
        response_text = result.get("text", "")
        if response_text:
            console.print()
            console.print(f"[bold cyan]{agent_name}:[/bold cyan]")
            console.print(response_text)
            console.print()
        else:
            console.print("[dim]No response.[/dim]")


# ── Server-side shell ───────────────────────────────────────────────


@app.command()
def shell(
    command: Annotated[
        Optional[str],
        typer.Option("-c", help="Execute a single command and exit"),
    ] = None,
    script: Annotated[
        Optional[str],
        typer.Argument(help="Python script to execute with runtime loaded"),
    ] = None,
):
    """Interactive shell with runtime access (run inside container).

    Starts a Python REPL with database, plugin_manager, agent_manager,
    ORM, and MCP tools pre-loaded. Like 'odoo shell'.

    Examples:
        gridbear shell                    # Interactive REPL
        gridbear shell -c "print(pm)"     # One-shot command
        gridbear shell script.py          # Run script with runtime
    """
    from cli.shell import run_shell

    exit_code = run_shell(command=command, script=script)
    raise typer.Exit(exit_code)


# ── i18n commands ──────────────────────────────────────────────────

i18n_app = typer.Typer(help="Translation management")
app.add_typer(i18n_app, name="i18n")


@i18n_app.command()
def extract(
    domain: Annotated[
        Optional[str],
        typer.Option(help="Domain to extract: ui, plugin name, or all"),
    ] = "all",
):
    """Extract translatable strings from source code."""
    import subprocess
    from pathlib import Path

    script = Path(__file__).resolve().parent.parent / "scripts" / "i18n_extract.sh"
    if not script.exists():
        print_error(f"Extraction script not found: {script}")
        raise typer.Exit(1)

    result = subprocess.run(["bash", str(script), domain or "all"], check=False)
    if result.returncode != 0:
        print_error("Extraction failed.")
        raise typer.Exit(result.returncode)
    print_success("Extraction complete.")


@i18n_app.command()
def update(
    lang: Annotated[str, typer.Option(help="Language code to update")],
    domain: Annotated[
        Optional[str],
        typer.Option(help="Domain to update (ui or plugin name)"),
    ] = "ui",
):
    """Merge .pot template into existing .po file for a language."""
    import subprocess
    from pathlib import Path

    base_dir = Path(__file__).resolve().parent.parent

    if domain == "ui":
        pot_file = base_dir / "ui" / "i18n" / "ui.pot"
        po_file = base_dir / "ui" / "i18n" / f"{lang}.po"
    else:
        pot_file = base_dir / "plugins" / domain / "i18n" / f"{domain}.pot"
        po_file = base_dir / "plugins" / domain / "i18n" / f"{lang}.po"

    if not pot_file.exists():
        print_error(
            f"Template not found: {pot_file}  (run 'gridbear i18n extract' first)"
        )
        raise typer.Exit(1)

    if po_file.exists():
        # Merge into existing .po
        result = subprocess.run(
            ["pybabel", "update", "-i", str(pot_file), "-o", str(po_file), "-l", lang],
            check=False,
        )
    else:
        # Create new .po from template
        result = subprocess.run(
            ["pybabel", "init", "-i", str(pot_file), "-o", str(po_file), "-l", lang],
            check=False,
        )

    if result.returncode != 0:
        print_error("Update failed.")
        raise typer.Exit(result.returncode)
    print_success(f"Updated {po_file.relative_to(base_dir)}")


@i18n_app.command("status")
def i18n_status(
    lang: Annotated[
        Optional[str],
        typer.Option(help="Filter by language code"),
    ] = None,
):
    """Show translation statistics per domain/language."""
    from pathlib import Path

    from rich.table import Table

    base_dir = Path(__file__).resolve().parent.parent

    # Collect all .po files
    po_files: list[tuple[str, str, Path]] = []  # (domain, lang, path)

    # UI domain
    ui_i18n = base_dir / "ui" / "i18n"
    if ui_i18n.is_dir():
        for po in ui_i18n.glob("*.po"):
            po_files.append(("ui", po.stem, po))

    # Plugin domains
    plugins_dir = base_dir / "plugins"
    if plugins_dir.is_dir():
        for i18n_dir in plugins_dir.glob("*/i18n"):
            plugin_name = i18n_dir.parent.name
            for po in i18n_dir.glob("*.po"):
                po_files.append((plugin_name, po.stem, po))

    if lang:
        po_files = [(d, lc, p) for d, lc, p in po_files if lc == lang]

    if not po_files:
        console.print("[dim]No .po files found.[/dim]")
        raise typer.Exit(0)

    table = Table(title="Translation Status")
    table.add_column("Domain", style="cyan")
    table.add_column("Language", style="green")
    table.add_column("Translated", justify="right")
    table.add_column("Untranslated", justify="right")
    table.add_column("Coverage", justify="right")

    for domain, po_lang, po_path in sorted(po_files):
        translated, untranslated = _count_po_stats(po_path)
        total = translated + untranslated
        pct = f"{translated * 100 // total}%" if total > 0 else "-"
        table.add_row(
            domain,
            po_lang,
            str(translated),
            str(untranslated) if untranslated else "[green]0[/green]",
            pct,
        )

    console.print(table)


def _count_po_stats(po_path) -> tuple[int, int]:
    """Count translated and untranslated entries in a .po file."""
    translated = 0
    untranslated = 0
    current_msgid = None
    current_msgstr: list[str] = []
    in_msgstr = False

    with open(po_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line.startswith("msgid "):
                # Save previous
                if current_msgid is not None and current_msgid != "":
                    msgstr = "".join(current_msgstr)
                    if msgstr:
                        translated += 1
                    else:
                        untranslated += 1
                current_msgid = line[6:].strip().strip('"')
                current_msgstr = []
                in_msgstr = False
            elif line.startswith("msgstr "):
                in_msgstr = True
                current_msgstr.append(line[7:].strip().strip('"'))
            elif line.startswith('"') and line.endswith('"') and in_msgstr:
                current_msgstr.append(line.strip('"'))

    # Last entry
    if current_msgid is not None and current_msgid != "":
        msgstr = "".join(current_msgstr)
        if msgstr:
            translated += 1
        else:
            untranslated += 1

    return translated, untranslated


if __name__ == "__main__":
    app()
