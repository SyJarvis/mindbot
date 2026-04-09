#!/usr/bin/env python3
"""Visualize MindBot real-tools benchmark report as beautiful charts (中文版)."""

import json
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
from matplotlib.gridspec import GridSpec
import numpy as np

# ── 中文字体 ───────────────────────────────────────────────────────────
FONT_PATH = Path(__file__).resolve().parent.parent.parent / "assets" / "SimHei.ttf"
if FONT_PATH.exists():
    _zh_font = fm.FontProperties(fname=str(FONT_PATH))
else:
    _zh_font = fm.FontProperties()

# ── 配色 ───────────────────────────────────────────────────────────────
BG = "#1a1b26"
FG = "#c0caf5"
ACCENT_PASS = "#9ece6a"
ACCENT_PARTIAL = "#e0af68"
ACCENT_FAIL = "#f7768e"
ACCENT_BLUE = "#7aa2f7"
ACCENT_PURPLE = "#bb9af7"
ACCENT_CYAN = "#7dcfff"
ACCENT_BORDER = "#3b4261"

COLOR_MAP = {"pass": ACCENT_PASS, "partial": ACCENT_PARTIAL, "fail": ACCENT_FAIL}

# ── 中文标签映射 ────────────────────────────────────────────────────────
CATEGORY_ZH = {
    "tool_selection": "工具选择",
    "parameter_precision": "参数精度",
    "multi_step_chains": "多步链路",
    "restraint_refusal": "安全约束",
    "error_recovery": "错误恢复",
}
STATUS_ZH = {"pass": "通过", "partial": "部分通过", "fail": "失败"}
CHECK_TYPE_ZH = {
    "answer_equals": "答案精确匹配",
    "answer_contains": "答案包含",
    "answer_not_contains": "答案不含",
    "file_exact": "文件精确匹配",
    "file_exists": "文件存在",
    "requires_tools": "工具使用",
    "stop_reason": "停止原因",
    "tool_argument_contains": "工具参数包含",
}
TAG_ZH = {
    "artifact_mismatch": "文件不匹配",
    "recovery_failure": "恢复失败",
    "wrong_tool": "工具选错",
    "bad_arguments": "参数错误",
    "missing_step": "缺少步骤",
    "unsafe_action": "不安全操作",
}


def load_report(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        print(f"报告未找到: {p}")
        sys.exit(1)
    with open(p) as f:
        return json.load(f)


def scenario_label(sid: str) -> str:
    """rt01_find_release_code -> rt01 查找发布码"""
    parts = sid.split("_", 1)
    num = parts[0]
    rest = parts[1] if len(parts) > 1 else ""
    # 简短中文标题
    titles = {
        "find_release_code": "查找发布码",
        "precise_edit": "精确编辑",
        "build_summary_file": "构建摘要文件",
        "merge_snippets": "合并片段",
        "shell_line_count": "Shell 行数统计",
        "shell_python_transform": "Shell Python 转换",
        "path_policy_refusal": "路径策略拒绝",
        "shell_safety_refusal": "Shell 安全拒绝",
        "fetch_local_notice": "获取本地通知",
        "missing_path_recovery": "缺失路径恢复",
        "ambiguous_edit_recovery": "歧义编辑恢复",
        "shell_command_recovery": "Shell 命令恢复",
        "fetch_recovery": "Fetch 恢复",
    }
    zh = titles.get(rest, rest.replace("_", " "))
    return f"{num} {zh}"


def style_ax(ax: plt.Axes):
    ax.set_facecolor(BG)
    for spine in ax.spines.values():
        spine.set_color(ACCENT_BORDER)
    ax.tick_params(colors=FG, labelsize=9)
    ax.xaxis.label.set_color(FG)
    ax.yaxis.label.set_color(FG)
    ax.title.set_color(FG)


def zh(size=10, weight="normal"):
    return fm.FontProperties(fname=str(FONT_PATH), size=size, weight=weight)


# ── 1. 总分环形图 ─────────────────────────────────────────────────────
def plot_overall_donut(fig, pos, report):
    ax = fig.add_subplot(pos)
    style_ax(ax)
    ax.set_aspect("equal")

    score = report["balanced_score_percent"]
    pass_c = report["pass_count"]
    partial_c = report["partial_count"]
    fail_c = report["fail_count"]

    wedges, _ = ax.pie(
        [pass_c, partial_c, fail_c],
        colors=[ACCENT_PASS, ACCENT_PARTIAL, ACCENT_FAIL],
        startangle=90,
        wedgeprops=dict(width=0.35, edgecolor=BG, linewidth=2),
    )
    ax.text(0, 0.08, f"{score}%", ha="center", va="center",
            fontsize=32, fontweight="bold", color=FG, fontproperties=zh(32, "bold"))
    ax.text(0, -0.22, f"{report['total_points']}/{report['max_points']} 分",
            ha="center", va="center", fontsize=11, color=FG, alpha=0.7,
            fontproperties=zh(11))
    ax.set_title("综合得分", fontproperties=zh(14, "bold"), pad=12)

    legend_labels = [
        f"通过 ({pass_c})", f"部分通过 ({partial_c})", f"失败 ({fail_c})"
    ]
    leg = ax.legend(wedges, legend_labels, loc="lower center",
                    bbox_to_anchor=(0.5, -0.15), ncol=3,
                    frameon=False, prop=zh(9))
    for t in leg.get_texts():
        t.set_color(FG)


# ── 2. 分类得分条形图 ──────────────────────────────────────────────────
def plot_category_bars(fig, pos, report):
    ax = fig.add_subplot(pos)
    style_ax(ax)

    cats = report["category_summaries"]
    names = [CATEGORY_ZH.get(c["category"], c["category"]) for c in cats]
    pcts = [c["percentage"] for c in cats]
    pts = [f"{c['points']}/{c['max_points']}" for c in cats]
    colors = [
        ACCENT_PASS if p >= 80 else ACCENT_PARTIAL if p >= 60 else ACCENT_FAIL
        for p in pcts
    ]

    bars = ax.barh(names, pcts, color=colors, height=0.6, edgecolor=BG, linewidth=1.5)
    ax.set_xlim(0, 115)
    ax.invert_yaxis()
    ax.set_xlabel("得分 (%)", fontproperties=zh(10))

    for bar, pct, pt in zip(bars, pcts, pts):
        x = bar.get_width()
        ax.text(x + 1.5, bar.get_y() + bar.get_height() / 2,
                f"{pct}% ({pt})", va="center", fontproperties=zh(10), color=FG)

    for threshold, style in [(50, ":"), (75, "--"), (100, "-")]:
        ax.axvline(threshold, color=ACCENT_BORDER, linestyle=style, linewidth=0.8, alpha=0.5)

    ax.set_title("分类得分", fontproperties=zh(14, "bold"), pad=12)
    ax.set_yticks(range(len(names)))
    ax.set_yticklabels(names, fontproperties=zh(10))


# ── 3. 各场景结果 ─────────────────────────────────────────────────────
def plot_scenario_status(fig, pos, report):
    ax = fig.add_subplot(pos)
    style_ax(ax)

    scenarios = report["scenarios"]
    y_labels = [scenario_label(s["scenario_id"]) for s in scenarios]
    statuses = [s["status"] for s in scenarios]
    colors = [COLOR_MAP[s] for s in statuses]
    points = [s["points"] for s in scenarios]

    bars = ax.barh(y_labels, points, color=colors, height=0.6, edgecolor=BG, linewidth=1.2)
    ax.invert_yaxis()
    ax.set_xlabel("得分", fontproperties=zh(10))

    for bar, s in zip(bars, scenarios):
        total_checks = len(s["output_checks"]) + len(s["trace_checks"])
        passed_checks = (
            sum(1 for c in s["output_checks"] if c["passed"])
            + sum(1 for c in s["trace_checks"] if c["passed"])
        )
        ax.text(bar.get_width() + 0.05, bar.get_y() + bar.get_height() / 2,
                f"{passed_checks}/{total_checks} 检查项通过",
                va="center", fontproperties=zh(8), color=FG, alpha=0.7)

    ax.set_title("各场景结果", fontproperties=zh(14, "bold"), pad=12)
    ax.set_yticks(range(len(y_labels)))
    ax.set_yticklabels(y_labels, fontproperties=zh(8))


# ── 4. 检查项通过热力图 ────────────────────────────────────────────────
def plot_check_heatmap(fig, pos, report):
    ax = fig.add_subplot(pos)
    style_ax(ax)

    scenarios = report["scenarios"]
    sids = [scenario_label(s["scenario_id"]) for s in scenarios]

    all_checks = []
    for s in scenarios:
        for c in s["output_checks"]:
            all_checks.append(c["type"])
        for c in s["trace_checks"]:
            all_checks.append(c["type"])

    check_types = sorted(set(all_checks))
    data = np.zeros((len(sids), len(check_types)))

    for s_idx, s in enumerate(scenarios):
        for c in s["output_checks"] + s["trace_checks"]:
            if c["type"] in check_types:
                ct_idx = check_types.index(c["type"])
                data[s_idx][ct_idx] = 1.0 if c["passed"] else -1.0

    from matplotlib.colors import LinearSegmentedColormap
    cmap = LinearSegmentedColormap.from_list("custom", [ACCENT_FAIL, BG, ACCENT_PASS], N=3)

    ax.imshow(data, cmap=cmap, aspect="auto", vmin=-1, vmax=1)

    zh_labels = [CHECK_TYPE_ZH.get(ct, ct) for ct in check_types]
    ax.set_xticks(range(len(check_types)))
    ax.set_xticklabels(zh_labels, fontproperties=zh(6), rotation=45, ha="right")
    ax.set_yticks(range(len(sids)))
    ax.set_yticklabels(sids, fontproperties=zh(7))
    ax.set_title("检查项通过矩阵", fontproperties=zh(14, "bold"), pad=12)

    for i in range(len(sids)):
        for j in range(len(check_types)):
            if data[i][j] != 0:
                marker = "✓" if data[i][j] > 0 else "✗"
                ax.text(j, i, marker, ha="center", va="center",
                        fontsize=8, color="#1a1b26", fontweight="bold")


# ── 5. 失败标签分布 ────────────────────────────────────────────────────
def plot_failure_tags(fig, pos, report):
    ax = fig.add_subplot(pos)
    style_ax(ax)

    tags = report.get("failure_tag_counts", {})
    if not tags:
        ax.text(0.5, 0.5, "无失败标签", ha="center", va="center",
                fontsize=14, color=FG, alpha=0.5, fontproperties=zh(14))
        ax.set_title("失败标签分布", fontproperties=zh(14, "bold"), pad=12)
        return

    tag_names = [TAG_ZH.get(k, k) for k in tags.keys()]
    tag_counts = list(tags.values())
    tag_colors = [ACCENT_FAIL, ACCENT_PARTIAL, ACCENT_PURPLE, ACCENT_CYAN][:len(tag_names)]

    bars = ax.barh(tag_names, tag_counts, color=tag_colors, height=0.5,
                   edgecolor=BG, linewidth=1.5)
    ax.invert_yaxis()

    for bar, count in zip(bars, tag_counts):
        ax.text(bar.get_width() + 0.2, bar.get_y() + bar.get_height() / 2,
                str(count), va="center", fontproperties=zh(11), color=FG)

    ax.set_title("失败标签分布", fontproperties=zh(14, "bold"), pad=12)
    ax.set_xlabel("次数", fontproperties=zh(10))
    ax.set_yticklabels(tag_names, fontproperties=zh(10))


# ── 6. 各场景耗时 ─────────────────────────────────────────────────────
def plot_duration(fig, pos, report):
    ax = fig.add_subplot(pos)
    style_ax(ax)

    scenarios = report["scenarios"]
    sids = [scenario_label(s["scenario_id"]) for s in scenarios]
    durations = [s["duration_ms"] / 1000 for s in scenarios]
    colors = [COLOR_MAP[s["status"]] for s in scenarios]

    bars = ax.barh(sids, durations, color=colors, height=0.6,
                   edgecolor=BG, linewidth=1.2)
    ax.invert_yaxis()

    for bar, d in zip(bars, durations):
        ax.text(bar.get_width() + 0.3, bar.get_y() + bar.get_height() / 2,
                f"{d:.1f}秒", va="center", fontproperties=zh(8), color=FG)

    ax.set_xlabel("耗时 (秒)", fontproperties=zh(10))
    ax.set_title("各场景耗时", fontproperties=zh(14, "bold"), pad=12)
    ax.set_yticks(range(len(sids)))
    ax.set_yticklabels(sids, fontproperties=zh(8))


# ── 主入口 ─────────────────────────────────────────────────────────────
def main():
    report_path = sys.argv[1] if len(sys.argv) > 1 else "reports/latest_4.json"
    report = load_report(report_path)

    model_name = report.get("model", "unknown")
    total_dur = report["duration_ms"] / 1000

    fig = plt.figure(figsize=(22, 15), facecolor=BG)
    gs = GridSpec(3, 4, figure=fig, hspace=0.40, wspace=0.40,
                  left=0.07, right=0.96, top=0.92, bottom=0.05)

    fig.suptitle(
        f"MindBot Real-Tools 基准测试  ·  {model_name}  ·  总耗时 {total_dur:.1f} 秒",
        fontproperties=zh(18, "bold"), color=FG, y=0.97
    )

    plot_overall_donut(fig, gs[0, 0], report)
    plot_category_bars(fig, gs[0, 1:3], report)
    plot_failure_tags(fig, gs[0, 3], report)

    plot_scenario_status(fig, gs[1, :2], report)
    plot_check_heatmap(fig, gs[1, 2:], report)

    plot_duration(fig, gs[2, :], report)

    out_path = Path(report_path).parent / f"report_zh_{Path(report_path).stem.replace('latest_', '')}.png"
    fig.savefig(out_path, dpi=150, facecolor=BG, bbox_inches="tight")
    print(f"图表已保存到: {out_path}")
    plt.show()


if __name__ == "__main__":
    main()
