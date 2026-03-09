"""ASCII + optional matplotlib chart for rate history."""
import io
import logging

logger = logging.getLogger(__name__)

def ascii_chart(history: list[dict]) -> str:
    """Return a simple ASCII line chart of parallel rates."""
    if not history:
        return "No history available."
    rates = [h["parallel_rate"] for h in history]
    times = [h["fetched_at"][11:16] for h in history]  # HH:MM
    mn, mx = min(rates), max(rates)
    rows = 8
    cols = min(len(rates), 24)
    step = max(1, len(rates) // cols)
    sampled = rates[::step][-cols:]
    sampled_t = times[::step][-cols:]

    chart = []
    for row in range(rows, -1, -1):
        threshold = mn + (mx - mn) * (row / rows)
        line = f"{threshold:7.0f} |"
        for r in sampled:
            line += "█" if r >= threshold else " "
        chart.append(line)
    chart.append("        +" + "-" * len(sampled))
    # show first and last time
    if sampled_t:
        chart.append(f"         {sampled_t[0]}{'':>{len(sampled)-10}}{sampled_t[-1]}")
    return "\n".join(chart)

def matplotlib_chart(history: list[dict]) -> bytes | None:
    """Return PNG bytes of the chart, or None if matplotlib unavailable."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
        from datetime import datetime

        times = [datetime.fromisoformat(h["fetched_at"]) for h in history]
        parallel = [h["parallel_rate"] for h in history]
        cbn = [h["cbn_rate"] for h in history]

        fig, ax = plt.subplots(figsize=(8, 4))
        fig.patch.set_facecolor("#0f0f1a")
        ax.set_facecolor("#1a1a2e")
        ax.plot(times, parallel, color="#ff6b35", label="Parallel market", linewidth=2)
        ax.plot(times, cbn, color="#4ecdc4", label="CBN official", linewidth=1.5, linestyle="--")
        ax.legend(facecolor="#1a1a2e", labelcolor="white")
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
        ax.tick_params(colors="white")
        for spine in ax.spines.values():
            spine.set_edgecolor("#333")
        ax.set_ylabel("₦ per $1", color="white")
        ax.set_title("USD/NGN Rate (24h)", color="white", pad=10)
        ax.yaxis.label.set_color("white")
        plt.tight_layout()

        buf = io.BytesIO()
        plt.savefig(buf, format="png", dpi=100, facecolor=fig.get_facecolor())
        plt.close(fig)
        buf.seek(0)
        return buf.read()
    except Exception as e:
        logger.warning(f"matplotlib chart failed: {e}")
        return None
