import html
import random
from pathlib import Path
import statistics

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from .data import ROOT, load_json, write_json
from .evaluation import EvaluationAdapter, pairing
from .ontology import active


def build_report(base_url, root=ROOT):
    root = Path(root)
    history = load_json(root / "reports/evolution-history.json")
    selected = active(root)
    manifest = load_json(root / "evaluation/cases.json")
    benchmark_id = manifest["sha256"]
    final_marker = root / "reports/final-freeze.json"
    if final_marker.exists():
        freeze = load_json(final_marker)
        if freeze["version"] != selected or freeze["benchmark_sha256"] != benchmark_id:
            raise ValueError("Final benchmark already exposed. A changed version needs a new final benchmark.")
        comparisons = {key: load_json(root / f"reports/{key}-all.json") for key in ["plain_rag", "initial", "improved", "no_ontology", "no_skill"]}
    else:
        comparisons = {}
        for key, version, variant in [("plain_rag", "v0", "plain_rag"), ("initial", "v0", "full"), ("improved", selected, "full"), ("no_ontology", selected, "no_ontology"), ("no_skill", selected, "no_skill")]:
            comparisons[key] = EvaluationAdapter(base_url, root, variant=variant).evaluate(version, output_hint=root / f"reports/{key}-all.json")
        write_json(final_marker, {"version": selected, "benchmark_sha256": benchmark_id, "status": "final split exposed; no further tuning permitted in this experiment"})
    summary = {"metric": "offline HTTP behavioral assertion pass rate; NOT resolution rate", "benchmark": {"original_first_emails_seen": 63, "constructed_semantic_cases": 30, "split_counts": manifest["split_counts"], "sha256": benchmark_id, "independent_real_holdout": 0}, "models": {"main_live_calls": 0, "judge_live_calls": 0, "llm_judge_pass_rate": None, "real_resolution_rate": None, "reason": "User authorized offline delivery; previous competition gateway blockage retained. No fresh remote-model result claimed."}, "evolution": {k: history[k] for k in ["candidate_attempts", "accepted_versions", "active_version", "stop_reason"]}, "comparisons": {}, "limitations": ["Regression labels mostly cover integrity and routing; they do not certify a complete troubleshooting answer.", "Initial v0 intentionally represents a minimal Skill without completed-action inheritance. This controlled mechanism experiment is not evidence of production-wide autonomous improvement.", "The host authored the constructed test cases. Final split was excluded from the proposer, but this is not an independent human-authored blind benchmark.", "Only the executed candidate count is reported; the available curve cannot establish convergence.", "Schema and Tool contracts are versioned and compatibility-checked, not autonomously evolved in this run.", "Offline Chinese/English templates do not translate every full English source; true generated bilingual quality remains unevaluated."]}
    for key, result in comparisons.items():
        by_split = {}
        for split in ["development", "validation", "final", "regression"]:
            cs = [c for c in result["cases"] if c["split"] == split]
            by_split[split] = {"passed": sum(c["passed"] for c in cs), "total": len(cs), "rate": sum(c["passed"] for c in cs) / len(cs) if cs else None}
        latency = sorted(c["http_complete_ms"] for c in result["cases"])
        summary["comparisons"][key] = {"metrics": result["metrics"], "by_split": by_split, "offline_http_latency_ms": {"p50": statistics.median(latency), "p95": latency[int(.95 * (len(latency) - 1))], "boundary": "local HTTP request to completed JSON; offline path; not answer TTFT or model latency"}}
    summary["paired"] = pairing(comparisons["initial"], comparisons["improved"])
    old = {c["id"]: c for c in comparisons["initial"]["cases"]}
    new = {c["id"]: c for c in comparisons["improved"]["cases"]}
    selected_ids = summary["paired"]["improved"][:5]
    pool = [i for i in new if i not in selected_ids]
    rng = random.Random(20261028)
    selected_ids += rng.sample(pool, max(0, 10 - len(selected_ids)))
    reviews, answer_key = [], []
    for index, case_id in enumerate(selected_ids, 1):
        swap = rng.choice([False, True])
        a, b = (new[case_id], old[case_id]) if swap else (old[case_id], new[case_id])
        # Reviewers inspect replies/sources; expected answers and version labels are withheld.
        reviews.append({"review_id": f"review-{index:02}", "case_id": case_id, "A": {"zh": a["reply"]["zh"], "en": a["reply"]["en"], "citation_ids": a["citation_ids"]}, "B": {"zh": b["reply"]["zh"], "en": b["reply"]["en"], "citation_ids": b["citation_ids"]}, "human_status": "pending", "reviewer": None, "winner": None, "reasons": None})
        answer_key.append({"review_id": f"review-{index:02}", "A": "candidate" if swap else "parent", "B": "parent" if swap else "candidate"})
    if not (root / "reports/manual-review.json").exists():
        write_json(root / "reports/manual-review.json", {"status": "pending_real_human_review", "instructions": "Review with original local ticket and cited Q&A. Supply reviewer, winner and evidence-based reasons; an AI must not sign as a human.", "reviews": reviews})
    write_json(root / "local/manual-review-answer-key.json", answer_key)
    write_json(root / "reports/summary.json", summary)
    xs = list(range(len(history["rounds"]) + 1))
    ys = [history["baseline"]["offline_assertion_pass_rate"] * 100] + [r["metrics"]["offline_assertion_pass_rate"] * 100 for r in history["rounds"]]
    fig, ax = plt.subplots(figsize=(10, 4.5), layout="constrained")
    ax.plot(xs, ys, color="#267c79", marker="o", linewidth=2)
    for x, y in zip(xs, ys):
        ax.annotate(f"{y:.1f}%", (x, y), xytext=(0, 12), textcoords="offset points", ha="center")
    ax.set(ylim=(0, 105), xticks=xs, xticklabels=["Parent v0"] + [f"Candidate {r['round']}\n{'accepted' if r['decision']['accepted'] else 'rejected'}" for r in history["rounds"]], ylabel="Offline assertion pass rate (%)", title="All attempted candidates — selection cases only")
    ax.grid(axis="y", alpha=.2)
    fig.text(.1, -.025, "Not LLM scores or resolution rate. Too few rounds to infer convergence.", fontsize=9, color="#61787e")
    for extension in ["svg", "png"]:
        fig.savefig(root / f"reports/curve.{extension}", bbox_inches="tight", dpi=180)
    plt.close(fig)
    table = ["| 配置 | 已见工单 | 构造开发 | 构造验证 | 冻结最终测试 |", "|---|---:|---:|---:|---:|"]
    for key, value in summary["comparisons"].items():
        fields = [value["by_split"][s] for s in ["regression", "development", "validation", "final"]]
        table.append("| " + key + " | " + " | ".join(f"{v['passed']}/{v['total']}" for v in fields) + " |")
    text = "# OntoCare 重建：执行与事实边界\n\n本报告通过实际 localhost HTTP 客服接口产生；数字表示程序断言通过，不代表真实解决率或 LLM Judge 分数。\n\n" + "\n".join(table) + f"\n\n尝试 {history['candidate_attempts']} 个候选，采纳 {history['accepted_versions']} 个；当前版本 {selected}。真实模型和 Judge 调用均为 0，人工抽检待完成。曲线点数不足以证明收敛。\n\n## 改进案例\n\n真实首封邮件 ticket-028 报告 T2353/3212 已尝试建议、未见阻塞。初始 Skill 仍重复检查；候选继承用户报告并转入人工核查。用户陈述没有变成工具核验事实。\n\n## 限制\n\n" + "\n".join("- " + s for s in summary["limitations"]) + "\n\n逐例理由见各配置的 *-all.json；抽检包为 manual-review.json。\n"
    (root / "reports/report.md").write_text(text)
    page = '<!doctype html><meta charset="utf-8"><title>OntoCare 评测报告</title><style>body{font:16px/1.8 system-ui;max-width:1050px;margin:45px auto;color:#1d4249;background:#f6f9f9;padding:25px}pre{white-space:pre-wrap;background:white;padding:25px;border-radius:12px}img{width:100%}</style><h1>OntoCare · 评测与事实边界</h1><img src="curve.svg"><pre>' + html.escape(text) + '</pre><details><summary>完整摘要</summary><pre>' + html.escape(__import__("json").dumps(summary, ensure_ascii=False, indent=2)) + '</pre></details>'
    (root / "reports/report.html").write_text(page)
    return summary
