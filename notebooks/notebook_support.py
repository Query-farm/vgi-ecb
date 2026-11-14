"""Small presentation and live-source helpers for the ECB walkthrough."""

from __future__ import annotations

import os
import re
from datetime import date, timedelta
from pathlib import Path

import certifi
import matplotlib.pyplot as plt
import seaborn as sns
from IPython.display import Markdown, display

API_URL = "https://data-api.ecb.europa.eu/service"
COLORS = {"USD": "#266B53", "GBP": "#526EAF", "JPY": "#B16D34"}


def sql_text(value: object) -> str:
    """Quote one literal for visible JupySQL interpolation."""
    return "'" + str(value).replace("'", "''") + "'"


def prose(text: str) -> None:
    """Display result-derived Markdown while keeping its source folded."""
    display(Markdown(text))


def configure(currencies: list[str], lookback: int, end: str | None, today: date):
    """Validate a modest live request and isolate it from inherited test endpoints."""
    if not isinstance(currencies, list) or not 2 <= len(currencies) <= 5:
        raise ValueError("CURRENCIES must be a list of 2-5 distinct three-letter codes.")
    if len(set(currencies)) != len(currencies) or any(
        not isinstance(c, str) or not re.fullmatch(r"[A-Z]{3}", c) or c == "EUR" for c in currencies
    ):
        raise ValueError("Use distinct uppercase currency codes other than EUR, such as USD, GBP and JPY.")
    if type(lookback) is not int or not 14 <= lookback <= 366:
        raise ValueError("LOOKBACK_DAYS must be an integer from 14 to 366 calendar days.")
    if end is not None and (not isinstance(end, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", end)):
        raise ValueError("END_DATE must be None or an ISO date YYYY-MM-DD.")
    end_date = date.fromisoformat(end) if end else today - timedelta(days=1)
    if end_date >= today:
        raise ValueError("END_DATE must precede the current UTC date; use a completed day.")
    start_date = end_date - timedelta(days=lookback - 1)
    # Respect an operator's custom trust bundle; otherwise use the notebook's CA bundle.
    os.environ.setdefault("SSL_CERT_FILE", certifi.where())
    return start_date, end_date


def set_theme() -> None:
    """Use one readable palette and preserve literal currency notation."""
    sns.set_theme(style="whitegrid", context="notebook", font_scale=1.05)
    plt.rcParams.update({"figure.dpi": 120, "savefig.dpi": 160, "text.parse_math": False})


def chart(fig, name: str, title: str, subtitle: str, source: str, artifact_dir: Path) -> None:
    """Display and save a chart with a provenance footer and generous margins."""
    fig.suptitle(title, x=0.08, y=0.98, ha="left", fontsize=17, fontweight="bold", color="#243D32")
    fig.text(0.08, 0.925, subtitle, ha="left", fontsize=10, color="#4D5650")
    fig.text(0.08, 0.025, source, ha="left", fontsize=8, color="#626B64")
    fig.tight_layout(rect=(0.025, 0.07, 0.99, 0.89), h_pad=1.7)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    fig.savefig(artifact_dir / f"{name}.png", facecolor="white")
    plt.show()
