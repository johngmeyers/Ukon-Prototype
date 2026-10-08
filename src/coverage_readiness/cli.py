"""coverage-readiness check <business_dir> --carrier <carrier_a|carrier_b>"""

from datetime import date, datetime
from pathlib import Path
from typing import Annotated

import anthropic
import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.markdown import Markdown

from coverage_readiness import config
from coverage_readiness.llm.client import AnthropicClient, LLMClient, LLMOutputError, RunLog
from coverage_readiness.parsers import EvidenceParseError
from coverage_readiness.pipeline import assess
from coverage_readiness.report import render_markdown

app = typer.Typer(add_completion=False, help="Check application answers against MSP evidence.")
console = Console()


def make_client(model: str) -> LLMClient:
    """Separate so tests can swap in a fake."""
    return AnthropicClient(model)


@app.callback()
def main() -> None:
    load_dotenv()


@app.command()
def check(
    business_dir: Annotated[Path, typer.Argument(help="Folder with application + evidence.")],
    carrier: Annotated[str, typer.Option(help="Carrier question set, e.g. carrier_a.")],
    carriers_dir: Annotated[Path, typer.Option(help="Where carrier YAML files live.")] = Path(
        "fixtures/carriers"
    ),
    as_of: Annotated[
        datetime | None, typer.Option(formats=["%Y-%m-%d"], help="Assessment date (default today).")
    ] = None,
    output: Annotated[Path | None, typer.Option(help="Also write the markdown here.")] = None,
    runs_dir: Annotated[Path, typer.Option(help="Where the JSONL run log goes.")] = Path("runs"),
    model: Annotated[str, typer.Option(help="Claude model ID.")] = config.MODEL,
) -> None:
    """Produce a readiness report for one business and one carrier application."""
    day = as_of.date() if as_of else date.today()
    log = RunLog(runs_dir / f"{date.today().isoformat()}.jsonl")
    try:
        with console.status(f"Assessing {business_dir.name} for {carrier}..."):
            assessment = assess(
                business_dir, carriers_dir / f"{carrier}.yaml", make_client(model), log, day
            )
    except (FileNotFoundError, EvidenceParseError, LLMOutputError) as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(2) from e
    except anthropic.AuthenticationError as e:
        console.print("[red]Error:[/red] API key rejected. Set ANTHROPIC_API_KEY in .env.")
        raise typer.Exit(2) from e

    markdown = render_markdown(assessment)
    console.print(Markdown(markdown))
    if output:
        output.write_text(markdown, encoding="utf-8")
        console.print(f"Report written to {output}")
