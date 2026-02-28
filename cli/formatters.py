"""Rich-based output formatters for the CLI."""

import json
import sys

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()
err_console = Console(stderr=True)


def _is_json_output(output: str | None) -> bool:
    if output == "json":
        return True
    if output == "table":
        return False
    # Auto-detect: json if piped, table if TTY
    return not sys.stdout.isatty()


def format_tools(tools: list[dict], output: str | None = None):
    if _is_json_output(output):
        console.print_json(json.dumps(tools))
        return

    if not tools:
        console.print("[dim]No tools found.[/dim]")
        return

    table = Table(title=f"Tools ({len(tools)})")
    table.add_column("Name", style="cyan", no_wrap=True)
    table.add_column("Description", max_width=60)
    table.add_column("Server", style="dim")

    for t in tools:
        name = t.get("name", "")
        desc = t.get("description", "")
        # Extract server from tool name prefix (before __)
        server = name.split("__")[0] if "__" in name else ""
        if len(desc) > 60:
            desc = desc[:57] + "..."
        table.add_row(name, desc, server)

    console.print(table)


def format_servers(servers: list[dict], output: str | None = None):
    if _is_json_output(output):
        console.print_json(json.dumps(servers))
        return

    if not servers:
        console.print("[dim]No servers found.[/dim]")
        return

    table = Table(title=f"MCP Servers ({len(servers)})")
    table.add_column("Name", style="cyan", no_wrap=True)
    table.add_column("Transport", style="dim")
    table.add_column("Category", style="dim")
    table.add_column("Status", justify="center")
    table.add_column("CB", justify="center")
    table.add_column("User-Aware", justify="center")

    for s in servers:
        connected = s.get("connected", False)
        cb = s.get("circuit_breaker", "closed")
        status_str = "[green]connected[/green]" if connected else "[dim]idle[/dim]"
        cb_str = {
            "closed": "[green]ok[/green]",
            "open": "[red]OPEN[/red]",
            "half_open": "[yellow]half[/yellow]",
        }.get(cb, cb)
        ua = "[cyan]yes[/cyan]" if s.get("user_aware") else ""

        table.add_row(
            s.get("name", ""),
            s.get("transport", ""),
            s.get("category", ""),
            status_str,
            cb_str,
            ua,
        )

    console.print(table)


def format_server_detail(detail: dict, output: str | None = None):
    if _is_json_output(output):
        console.print_json(json.dumps(detail))
        return

    name = detail.get("name", "unknown")
    lines = [
        f"[bold]Transport:[/bold] {detail.get('transport', '')}",
        f"[bold]Category:[/bold] {detail.get('category', '')}",
        f"[bold]Plugin:[/bold] {detail.get('plugin', '')}",
        f"[bold]User-Aware:[/bold] {detail.get('user_aware', False)}",
        f"[bold]Connected:[/bold] {detail.get('connected', False)}",
        f"[bold]Circuit Breaker:[/bold] {detail.get('circuit_breaker', 'closed')}",
        f"[bold]Connection ID:[/bold] {detail.get('service_connection_id', '')}",
    ]

    config = detail.get("config", {})
    if config:
        lines.append("")
        lines.append("[bold]Config:[/bold]")
        for k, v in config.items():
            lines.append(f"  {k}: {v}")

    tools = detail.get("tools", [])
    if tools:
        lines.append("")
        lines.append(f"[bold]Tools ({len(tools)}):[/bold]")
        for t in tools:
            desc = t.get("description", "")
            if len(desc) > 50:
                desc = desc[:47] + "..."
            lines.append(f"  [cyan]{t.get('name', '')}[/cyan]  {desc}")

    console.print(Panel("\n".join(lines), title=name, border_style="blue"))


def format_creds(result: dict, output: str | None = None):
    if _is_json_output(output):
        console.print_json(json.dumps(result))
        return

    status = result.get("status", "unknown")
    color = "green" if status == "connected" else "red"
    ctype = result.get("type", "")
    is_global = result.get("is_global", False)
    source = " (global)" if is_global else " (per-user)"

    console.print(
        f"[bold]{result.get('connection_id', '')}[/bold] "
        f"user=[cyan]{result.get('user', '')}[/cyan] "
        f"[{color}]{status}[/{color}]" + (f"  type={ctype}{source}" if ctype else "")
    )


def print_error(message: str):
    err_console.print(f"[red]Error:[/red] {message}")


def print_success(message: str):
    console.print(f"[green]{message}[/green]")


def format_whoami(info: dict, output: str | None = None):
    if _is_json_output(output):
        console.print_json(json.dumps(info))
        return

    if not info.get("logged_in"):
        console.print("[dim]Not logged in.[/dim]")
        return

    import datetime

    expires = info.get("expires_at", 0)
    exp_str = datetime.datetime.fromtimestamp(expires).isoformat() if expires else "?"
    valid = info.get("token_valid", False)
    valid_str = "[green]valid[/green]" if valid else "[red]expired[/red]"

    console.print(f"[bold]Client ID:[/bold]  {info.get('client_id', '')}")
    console.print(f"[bold]Agent:[/bold]      {info.get('agent_name', '')}")
    console.print(f"[bold]Gateway:[/bold]    {info.get('gateway_url', '')}")
    console.print(f"[bold]Token:[/bold]      {valid_str}")
    console.print(f"[bold]Expires:[/bold]    {exp_str}")
    console.print(f"[bold]Scope:[/bold]      {info.get('scope', '')}")
