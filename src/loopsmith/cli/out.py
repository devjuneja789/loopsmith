"""Minimal terminal output helpers (no rich dependency)."""

import typer

MAX_CELL = 72


def print_table(headers: list[str], rows: list[list[object]]) -> None:
    if not rows:
        typer.echo("(none)")
        return
    truncated: list[list[str]] = []
    widths = [len(h) for h in headers]
    for row in rows:
        cells = []
        for i, cell in enumerate(row):
            s = str(cell)
            if len(s) > MAX_CELL:
                s = s[: MAX_CELL - 3] + "..."
            cells.append(s)
            widths[i] = max(widths[i], len(s))
        truncated.append(cells)

    def line(cells: list[str]) -> str:
        return "  ".join(c.ljust(w) for c, w in zip(cells, widths)).rstrip()

    typer.echo(line(headers))
    typer.echo("  ".join("-" * w for w in widths))
    for row in truncated:
        typer.echo(line(row))


def kv(label: str, value: object) -> None:
    typer.echo(f"  {label + ':':<18} {value}")


def err(message: str) -> None:
    typer.echo(f"error: {message}", err=True)
