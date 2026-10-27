"""`loopsmith benchmark` -- inspect and smoke-test the scenario pack."""

from typing import Optional

import typer

from loopsmith.cli.out import print_table

app = typer.Typer(no_args_is_help=True, add_completion=False)


def _load(benchmark: Optional[str]):
    from loopsmith.eval.scenarios import PackError, load_pack, resolve_pack_root

    try:
        return load_pack(resolve_pack_root(benchmark))
    except PackError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(1)


@app.command("list")
def list_(
    benchmark: Optional[str] = typer.Option(
        None, "--benchmark", "-b", help="Benchmark pack directory"),
) -> None:
    """List scenarios in the benchmark pack."""
    pack = _load(benchmark)
    typer.echo(f"Pack {pack.id} (hash {pack.hash}) at {pack.root}")
    print_table(
        ["scenario", "title", "max turns"],
        [[s.id, s.title, s.max_turns] for s in pack.scenarios],
    )


@app.command()
def smoke(
    benchmark: Optional[str] = typer.Option(
        None, "--benchmark", "-b", help="Benchmark pack directory"),
) -> None:
    """Run hidden checkers on pristine fixtures: they should NOT pass yet."""
    from loopsmith.eval.runner import grade

    pack = _load(benchmark)
    failed = False
    for scenario in pack.scenarios:
        success, output = grade(scenario, scenario.workspace)
        state = "UNSOLVED (expected)" if not success else "ALREADY GREEN (fix the fixture)"
        typer.echo(f"{scenario.id:<26} {state}")
        if success:
            failed = True
            typer.echo(output)
    if failed:
        raise typer.Exit(1)
    typer.echo("All fixtures start unsolved; the benchmark can measure a delta.")