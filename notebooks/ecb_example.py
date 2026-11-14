"""Live ECB request validation and charts; data work stays in visible SQL."""

from __future__ import annotations

import os
import re
from datetime import date, timedelta

import certifi
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from vgi_notebooks import finish

API_URL = "https://data-api.ecb.europa.eu/service"
COLORS = {"USD": "#266B53", "GBP": "#526EAF", "JPY": "#B16D34"}


def sql_text(value: object) -> str:
    """Quote one literal for visible JupySQL interpolation."""
    return "'" + str(value).replace("'", "''") + "'"


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
    os.environ.pop("ECB_ALLOW_INSECURE_HTTP", None)
    os.environ["ECB_API_BASE_URL"] = API_URL
    # Respect an operator's custom trust bundle; otherwise use the notebook's CA bundle.
    os.environ.setdefault("SSL_CERT_FILE", certifi.where())
    return start_date, end_date


def plot_raw(raw_plot, currencies, palette, start_date, end_date, source):
    """Keep raw quotes on separate, explicitly labeled currency axes."""
    fig, axes = plt.subplots(len(currencies), 1, figsize=(11.5, 3.0 * len(currencies)), sharex=True)
    for ax, currency in zip(axes, currencies, strict=True):
        frame = raw_plot[raw_plot.currency == currency]
        ax.plot(frame.obs_date, frame.units_per_eur, color=palette[currency], marker=".", markersize=3, linewidth=1.5)
        last = frame.dropna().iloc[-1]
        ax.set_ylabel(f"{currency} per EUR")
        ax.set_title(
            f"{currency} · latest available {last.units_per_eur:,.5g} on {last.obs_date:%d %b}", loc="left", fontsize=11
        )
        ax.ticklabel_format(axis="y", style="plain", useOffset=False)
    axes[-1].xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    axes[-1].set_xlabel("ECB observation date")
    finish(
        fig,
        "The original quotes use different currency units",
        f"{start_date} → {end_date}, inclusive · independent vertical scales · missing dates stay blank",
        source,
        name="01_original_units",
    )


def plot_indexed(indexed, currencies, palette, first_common, last_common, common_count, source):
    """Compare common-date index paths using one vertical scale."""
    fig, ax = plt.subplots(figsize=(11.5, 6.6))
    for currency in currencies:
        frame = indexed[indexed.currency == currency]
        ax.plot(frame.obs_date, frame.quote_index, color=palette[currency], linewidth=2, label=currency)
        ax.scatter(frame.obs_date.iloc[-1], frame.quote_index.iloc[-1], color=palette[currency], s=35)
    ax.axhline(100, color="#8A918B", linewidth=1, linestyle="--")
    ax.set(xlabel="Common ECB observation date", ylabel="Currency units per EUR · first common date = 100")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    ax.legend(title="Currency numerator", loc="best", frameon=True)
    finish(
        fig,
        "A common base makes the exchange-rate paths comparable",
        f"{first_common:%d %b %Y} = 100 · {common_count} shared dates through {last_common:%d %b %Y} "
        "· shared vertical scale",
        source,
        name="02_rebased_paths",
    )


def plot_endpoints(summary, first_common, last_common, source):
    """Show signed endpoint changes with their exact date window."""
    fig, ax = plt.subplots(figsize=(11.5, 5.6))
    ordered = summary.sort_values("quote_change_pct")
    bar_colors = ["#267253" if value >= 0 else "#B66347" for value in ordered.quote_change_pct]
    bars = ax.barh(ordered.currency, ordered.quote_change_pct, color=bar_colors, height=0.58)
    ax.axvline(0, color="#555E57", linewidth=1)
    ax.bar_label(bars, labels=[f"{value:+.2f}%" for value in ordered.quote_change_pct], padding=6)
    lo, hi = min(0, ordered.quote_change_pct.min()), max(0, ordered.quote_change_pct.max())
    pad = max(0.3, (hi - lo) * 0.25)
    ax.set_xlim(lo - pad, hi + pad)
    ax.set(xlabel="Change in currency units per EUR (%)", ylabel="Currency numerator")
    finish(
        fig,
        "Window endpoints summarize one chosen interval",
        f"Common dates: {first_common:%d %b %Y} → {last_common:%d %b %Y} · positive means more currency units per euro",
        source,
        name="03_endpoint_changes",
    )
