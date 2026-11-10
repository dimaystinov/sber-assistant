"""Построить научную иллюстрацию из сохранённых результатов симуляции."""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    simulation = json.loads(
        (root / "evals/results/large-deployment-simulation.json").read_text()
    )
    rag = json.loads((root / "evals/results/rag-benchmark.json").read_text())
    output = root / "docs/figures"
    output.mkdir(parents=True, exist_ok=True)

    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11})
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.3), constrained_layout=True)
    fig.patch.set_facecolor("#f6fbf7")
    for ax in axes:
        ax.set_facecolor("#f6fbf7")
        ax.spines[["top", "right"]].set_visible(False)
        ax.grid(axis="y", alpha=.16, zorder=0)

    roles = ("retail", "business", "employee")
    labels = ("Клиент", "Бизнес", "Сотрудник")
    counts = [simulation["by_role"][role]["passed"] for role in roles]
    axes[0].bar(labels, counts, color=("#0aad67", "#087c62", "#2450a4"), zorder=3)
    axes[0].set_ylim(0, 1350)
    axes[0].set_ylabel("Эпизоды с выполненным инвариантом")
    axes[0].set_title("Симуляция: 1 200 эпизодов на роль", loc="left", weight="bold")
    for i, count in enumerate(counts):
        axes[0].text(i, count + 32, f"{count}/1 200", ha="center", weight="bold")
    axes[0].text(.0, -.27, "23 шаблона; повторения не являются независимыми случаями",
                 transform=axes[0].transAxes, fontsize=9, color="#566a60")

    x = [0, 1]
    lexical = [rag["lexical"]["exact"]["hit_at_1"],
               rag["lexical"]["paraphrase"]["hit_at_1"]]
    router = [None, rag["GigaChat-3-Lightning-router"]["paraphrase"]["hit_at_1"]]
    axes[1].bar([v - .18 for v in x], lexical, width=.34, color="#0aad67",
                label="Ключевые слова", zorder=3)
    axes[1].bar([x[1] + .18], [router[1]], width=.34, color="#9367f5",
                label="GigaChat-3-Lightning", zorder=3)
    axes[1].set_xticks(x, ("Точный запрос", "Перефразировка"))
    axes[1].set_ylim(0, 11.6)
    axes[1].set_ylabel("Верный документ на 1-м месте из 10")
    axes[1].set_title("Поиск по 10 учебным документам", loc="left", weight="bold")
    axes[1].legend(frameon=False, loc="lower left")
    for x_pos, value in ((-.18, lexical[0]), (.82, lexical[1]), (1.18, router[1])):
        axes[1].text(x_pos, value + .25, f"{value}/10", ha="center", weight="bold")
    axes[1].text(.0, -.27, "Роутер проверен только на перефразировках; n=10",
                 transform=axes[1].transAxes, fontsize=9, color="#566a60")

    fig.savefig(output / "research-results.png", dpi=200, facecolor=fig.get_facecolor())
    fig.savefig(output / "research-results.svg", facecolor=fig.get_facecolor())
    plt.close(fig)
    print(output / "research-results.png")


if __name__ == "__main__":
    main()
