"""Render the README figures from the reviewed pilot summary.

Install matplotlib and run python3 -m runner.plot_results from the repo root.
"""

import csv
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
from matplotlib import pyplot as plt
from matplotlib.patches import Patch, Rectangle


ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results/pilot-runs.csv"
OUTPUT = ROOT / "docs/figures"
MODELS = ("Qwen3 14B", "Ministral 3 14B", "Gemini 3.5 Flash Lite", "Claude Sonnet 4.6")
MODES = {"blind": "Blind", "hinted": "Hinted", "answer_provided": "Answer provided"}
REASONING = {"Thinking off": "Off", "Thinking on": "On", "Default": "Default"}
ORDER = {"Thinking off": 0, "Thinking on": 1, "MINIMAL": 0, "HIGH": 1, "Default": 0}
INK = "#172941"
MUTED = "#52647A"
LINE = "#D8E2EB"
LOCAL = "#536FA2"
HOSTED = "#177B78"
CONTINUATION = "#B6592E"


def figure(title, description, size):
    fig = plt.figure(figsize=size, facecolor="#FFFFFF")
    fig.text(0.04, 0.94, title, fontsize=19, weight="bold", color=INK)
    fig.text(0.04, 0.89, description, fontsize=10.5, color=MUTED)
    return fig


def write(fig, filename):
    fig.savefig(OUTPUT / filename, format="svg", metadata={"Date": None})
    plt.close(fig)


def reproduction_matrix(rows):
    fig = figure(
        "Which runs produced executable evidence?",
        "Each tile is one run condition. Values count the two known audit findings.",
        (10.8, 5.25),
    )
    ax = fig.add_axes([0.235, 0.18, 0.725, 0.64])
    ax.set_xlim(0, 3)
    ax.set_ylim(4, -0.38)
    ax.axis("off")

    for column, mode in enumerate(MODES):
        ax.text(column + 0.5, -0.16, MODES[mode], ha="center", va="center",
                fontsize=11, weight="bold", color=INK)
    for row_index, model in enumerate(MODELS):
        deployment = next(row["deployment"] for row in rows if row["model"] == model)
        ax.text(-0.78, row_index + 0.38, model, fontsize=11, weight="bold", color=INK)
        ax.text(-0.78, row_index + 0.63, deployment.capitalize(), fontsize=9, color=MUTED)
        for column, mode in enumerate(MODES):
            matches = sorted(
                (row for row in rows if row["model"] == model and row["mode"] == mode),
                key=lambda row: ORDER[row["reasoning"]],
            )
            if not matches:
                ax.add_patch(Rectangle((column + 0.04, row_index + 0.07), 0.92, 0.83,
                                       facecolor="#FFFFFF", edgecolor=LINE,
                                       linestyle="dashed"))
                ax.text(column + 0.5, row_index + 0.49, "Unrun", ha="center",
                        va="center", fontsize=10, color=MUTED)
                continue
            width = (0.92 - 0.03 * (len(matches) - 1)) / len(matches)
            for index, row in enumerate(matches):
                count = int(row["reproduced_v_aha_vul_001"]) + int(row["reproduced_v_aha_vul_002"])
                x = column + 0.04 + index * (width + 0.03)
                ax.add_patch(Rectangle((x, row_index + 0.07), width, 0.83,
                                       facecolor="#D7EEE9" if count else "#EFF3F8"))
                ax.text(x + width / 2, row_index + 0.34, f"{count}/2", ha="center",
                        va="center", fontsize=15, weight="bold", color=INK)
                label = REASONING.get(row["reasoning"], row["reasoning"])
                if int(row["continuation_turns"]):
                    label += " · 50 turns"
                ax.text(x + width / 2, row_index + 0.67, label, ha="center",
                        va="center", fontsize=8.5, color=MUTED)

    fig.text(0.04, 0.09, "Evidence comes from executed tests in the saved logs. Independent replay is pending.",
             fontsize=9.5, color=MUTED)
    fig.text(0.04, 0.045, "Zero means no demonstration in that run. The budgets differ across runners.",
             fontsize=9.5, color=MUTED)
    write(fig, "reproduction-by-condition.svg")


def turns_by_run(rows):
    fig = figure(
        "How many turns did each run use?",
        "Each bar is one condition, with its final stop recorded at the right.",
        (10.8, 8.6),
    )
    ax = fig.add_axes([0.22, 0.145, 0.735, 0.69])
    y = 0
    for model in MODELS:
        ax.text(-16, y, model, va="center", fontsize=11, weight="bold", color=INK)
        y += 1.1
        model_rows = sorted(
            (row for row in rows if row["model"] == model),
            key=lambda row: (list(MODES).index(row["mode"]), ORDER[row["reasoning"]]),
        )
        for row in model_rows:
            reason = REASONING.get(row["reasoning"], row["reasoning"])
            label = f"{MODES[row['mode']]} · {reason}"
            ax.text(-0.85, y, label, ha="right", va="center", fontsize=8.3, color=MUTED)
            initial = int(row["initial_turns"])
            extra = int(row["continuation_turns"])
            color = LOCAL if row["deployment"] == "local" else HOSTED
            ax.barh(y, initial, height=0.59, color=color, zorder=3)
            if extra:
                ax.barh(y, extra, left=initial, height=0.59, color=CONTINUATION, zorder=3)
            total = initial + extra
            ax.text(total + 0.7, y, f"{total} · {row['stop']}", va="center",
                    fontsize=8.6, color=INK,
                    bbox={"facecolor": "white", "edgecolor": "none", "pad": 0.15})
            y += 1
        y += 0.65

    ax.set_xlim(0, 67)
    ax.set_ylim(y - 0.85, -0.85)
    ax.set_yticks([])
    ax.set_xticks(range(0, 51, 10), labels=[str(tick) for tick in range(0, 51, 10)])
    ax.tick_params(axis="x", labelsize=9, colors=MUTED, length=0)
    ax.set_xlabel("Turns used", fontsize=10, color=MUTED, labelpad=6)
    ax.grid(axis="x", color=LINE, linewidth=0.65, zorder=0)
    ax.axvline(20, color="#627991", linestyle=(0, (3, 3)), linewidth=1.15, zorder=2)
    ax.text(20, -1.06, "Standard cap", ha="center", va="bottom", fontsize=8.7, color=MUTED)
    for spine in ax.spines.values():
        spine.set_visible(False)

    fig.legend(handles=[
        Patch(facecolor=LOCAL, label="Local"),
        Patch(facecolor=HOSTED, label="Hosted"),
        Patch(facecolor=CONTINUATION, label="Resumed segment"),
    ], loc="lower left", bbox_to_anchor=(0.033, 0.04), ncol=3, frameon=False,
       labelcolor=MUTED, fontsize=9.5)
    write(fig, "turns-and-stop-reasons.svg")


def main():
    plt.rcParams.update({"font.family": "DejaVu Sans", "svg.fonttype": "none",
                         "svg.hashsalt": "soro-scone-pilot"})
    with RESULTS.open(newline="") as file:
        rows = list(csv.DictReader(file))
    OUTPUT.mkdir(parents=True, exist_ok=True)
    reproduction_matrix(rows)
    turns_by_run(rows)


if __name__ == "__main__":
    main()
