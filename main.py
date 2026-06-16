import asyncio
import json
import os
import time
from collections import Counter
from typing import Dict, List, Tuple

from agent.main_agent import MainAgent
from engine.llm_judge import LLMJudge
from engine.retrieval_eval import RetrievalEvaluator
from engine.runner import BenchmarkRunner


def load_dataset() -> List[Dict]:
    if not os.path.exists("data/golden_set.jsonl"):
        raise FileNotFoundError("Missing data/golden_set.jsonl. Run 'python data/synthetic_gen.py' first.")

    with open("data/golden_set.jsonl", "r", encoding="utf-8") as f:
        dataset = [json.loads(line) for line in f if line.strip()]

    if not dataset:
        raise ValueError("data/golden_set.jsonl is empty. Regenerate the dataset first.")

    return dataset


def build_summary(agent_version: str, results: List[Dict]) -> Dict:
    total = len(results)
    pass_count = sum(1 for result in results if result["status"] == "pass")
    avg_score = sum(result["judge"]["final_score"] for result in results) / total
    hit_rate = sum(result["ragas"]["retrieval"]["hit_rate"] for result in results) / total
    avg_mrr = sum(result["ragas"]["retrieval"]["mrr"] for result in results) / total
    agreement_rate = sum(result["judge"]["agreement_rate"] for result in results) / total
    avg_latency = sum(result["latency"] for result in results) / total
    avg_faithfulness = sum(result["ragas"]["faithfulness"] for result in results) / total
    avg_relevancy = sum(result["ragas"]["relevancy"] for result in results) / total

    return {
        "metadata": {
            "version": agent_version,
            "total": total,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "dataset_path": "data/golden_set.jsonl",
        },
        "metrics": {
            "avg_score": round(avg_score, 4),
            "hit_rate": round(hit_rate, 4),
            "mrr": round(avg_mrr, 4),
            "agreement_rate": round(agreement_rate, 4),
            "pass_rate": round(pass_count / total, 4),
            "avg_latency": round(avg_latency, 4),
            "faithfulness": round(avg_faithfulness, 4),
            "relevancy": round(avg_relevancy, 4),
        },
    }


def decide_release(v1_summary: Dict, v2_summary: Dict) -> Dict:
    v1_metrics = v1_summary["metrics"]
    v2_metrics = v2_summary["metrics"]

    score_delta = round(v2_metrics["avg_score"] - v1_metrics["avg_score"], 4)
    hit_rate_delta = round(v2_metrics["hit_rate"] - v1_metrics["hit_rate"], 4)
    agreement_delta = round(v2_metrics["agreement_rate"] - v1_metrics["agreement_rate"], 4)
    latency_delta = round(v2_metrics["avg_latency"] - v1_metrics["avg_latency"], 4)
    pass_rate_delta = round(v2_metrics["pass_rate"] - v1_metrics["pass_rate"], 4)

    reasons = []
    if score_delta < 0:
        reasons.append("Điểm judge trung bình bị giảm.")
    if hit_rate_delta < 0:
        reasons.append("Hit Rate retrieval bị giảm.")
    if agreement_delta < -0.05:
        reasons.append("Độ đồng thuận giữa các judge bị giảm đáng kể.")
    if latency_delta > 0.05:
        reasons.append("Độ trễ trung bình tăng vượt ngưỡng cho phép.")
    if pass_rate_delta < 0:
        reasons.append("Tỉ lệ pass bị giảm.")

    decision = "APPROVE" if not reasons else "BLOCK RELEASE"
    if not reasons:
        reasons.append("Phiên bản mới không hồi quy và cải thiện hoặc giữ ổn định các chỉ số chính.")

    return {
        "score_delta": score_delta,
        "hit_rate_delta": hit_rate_delta,
        "agreement_delta": agreement_delta,
        "latency_delta": latency_delta,
        "pass_rate_delta": pass_rate_delta,
        "decision": decision,
        "reasons": reasons,
    }


def build_failure_analysis(results: List[Dict], summary: Dict) -> str:
    total = len(results)
    pass_count = sum(1 for result in results if result["status"] == "pass")
    fail_count = total - pass_count

    clusters = Counter()
    for result in results:
        test_case = result["test_case_raw"]
        retrieval = result["ragas"]["retrieval"]
        judge = result["judge"]
        case_type = test_case.get("metadata", {}).get("type", "general")

        if retrieval["hit_rate"] == 0:
            clusters["Retrieval Miss"] += 1
        elif case_type == "ambiguous":
            clusters["Ambiguous Handling"] += 1
        elif case_type == "adversarial":
            clusters["Safety Refusal"] += 1
        elif case_type == "out-of-context":
            clusters["Out-of-Context Handling"] += 1
        elif judge["agreement_rate"] < 0.75:
            clusters["Judge Disagreement"] += 1
        elif result["status"] == "fail":
            clusters["Incomplete Answer"] += 1

    worst_cases = sorted(results, key=lambda item: (item["judge"]["final_score"], item["ragas"]["retrieval"]["hit_rate"], item["judge"]["agreement_rate"]))[:3]

    cluster_lines = ["| Nhóm lỗi | Số lượng | Nguyên nhân dự kiến |", "|----------|----------|---------------------|"]
    cluster_reasons = {
        "Retrieval Miss": "Agent không lấy đúng tài liệu mong đợi hoặc bỏ sót multi-doc context.",
        "Ambiguous Handling": "Câu trả lời chưa chủ động hỏi lại hoặc khoanh vùng yêu cầu mơ hồ.",
        "Safety Refusal": "Phản hồi từ chối chưa bám sát chính sách hoặc còn chung chung.",
        "Out-of-Context Handling": "Agent chưa nêu rõ giới hạn tài liệu khi câu hỏi nằm ngoài phạm vi.",
        "Judge Disagreement": "Câu trả lời có dấu hiệu đúng một phần nhưng chưa đủ rõ ràng/đầy đủ.",
        "Incomplete Answer": "Agent trả lời thiếu ý hoặc lược bớt chi tiết quan trọng.",
    }
    for cluster, count in clusters.most_common():
        cluster_lines.append(f"| {cluster} | {count} | {cluster_reasons.get(cluster, 'Cần phân tích thêm từ benchmark results.')} |")

    if len(cluster_lines) == 2:
        cluster_lines.append("| Không có cụm lỗi lớn | 0 | Phiên bản hiện tại không ghi nhận nhóm lỗi nổi bật. |")

    case_sections = []
    for index, case in enumerate(worst_cases, start=1):
        retrieval = case["ragas"]["retrieval"]
        metadata = case["test_case_raw"].get("metadata", {})
        case_sections.append(
            "\n".join(
                [
                    f"### Case #{index}: {case['test_case']}",
                    f"1. **Symptom:** Agent chỉ đạt {case['judge']['final_score']}/5 với agreement {case['judge']['agreement_rate']:.2f}.",
                    f"2. **Why 1:** Câu trả lời chưa khớp đủ với ground truth cho loại case `{metadata.get('type', 'unknown')}`.",
                    f"3. **Why 2:** Retrieval đạt hit_rate={retrieval['hit_rate']:.2f}, mrr={retrieval['mrr']:.2f}, cho thấy context lấy về chưa tối ưu.",
                    "4. **Why 3:** Phiên bản baseline/heuristic vẫn còn rút gọn hoặc thiếu chi tiết trong các tình huống khó.",
                    "5. **Why 4:** Logic trả lời chưa phân biệt mạnh giữa ambiguous / adversarial / multi-document cases.",
                    "6. **Root Cause:** Cần cải thiện chiến lược retrieval và response shaping theo loại câu hỏi thay vì dùng một hành vi chung.",
                ]
            )
        )

    metrics = summary["metrics"]
    return "\n".join(
        [
            "# Báo cáo Phân tích Thất bại (Failure Analysis Report)",
            "",
            "## 1. Tổng quan Benchmark",
            f"- **Tổng số cases:** {total}",
            f"- **Tỉ lệ Pass/Fail:** {pass_count}/{fail_count}",
            "- **Điểm RAGAS trung bình:**",
            f"    - Faithfulness: {metrics['faithfulness']:.2f}",
            f"    - Relevancy: {metrics['relevancy']:.2f}",
            f"    - Hit Rate: {metrics['hit_rate']:.2f}",
            f"    - MRR: {metrics['mrr']:.2f}",
            f"- **Điểm LLM-Judge trung bình:** {metrics['avg_score']:.2f} / 5.0",
            f"- **Agreement Rate trung bình:** {metrics['agreement_rate']:.2f}",
            "",
            "## 2. Phân nhóm lỗi (Failure Clustering)",
            *cluster_lines,
            "",
            "## 3. Phân tích 5 Whys (Chọn 3 case tệ nhất)",
            "",
            *case_sections,
            "",
            "## 4. Kế hoạch cải tiến (Action Plan)",
            "- [ ] Tăng độ chính xác retrieval cho các case multi-document và case khó bằng cách ưu tiên đầy đủ `expected_retrieval_ids`.",
            "- [ ] Tách prompt/logic phản hồi riêng cho ambiguous, adversarial và out-of-context cases.",
            "- [ ] Bổ sung bước hậu kiểm để phát hiện câu trả lời bị rút gọn quá mức trước khi chấm.",
            "- [ ] Theo dõi thêm pass_rate và latency trong regression gate để tránh tối ưu lệch một chiều.",
        ]
    )


async def run_benchmark_with_results(agent_version: str, mode: str) -> Tuple[List[Dict], Dict]:
    print(f"[INFO] Starting benchmark for {agent_version}...")
    dataset = load_dataset()
    runner = BenchmarkRunner(MainAgent(mode=mode), RetrievalEvaluator(top_k=3), LLMJudge())
    results = await runner.run_all(dataset)
    summary = build_summary(agent_version, results)
    return results, summary


async def main():
    try:
        v1_results, v1_summary = await run_benchmark_with_results("Agent_V1_Base", "base")
        v2_results, v2_summary = await run_benchmark_with_results("Agent_V2_Optimized", "optimized")
    except (FileNotFoundError, ValueError) as exc:
        print(f"[ERROR] {exc}")
        return

    regression = decide_release(v1_summary, v2_summary)
    v2_summary["regression"] = regression
    v2_summary["metadata"]["baseline_version"] = v1_summary["metadata"]["version"]

    print("\n[INFO] --- REGRESSION COMPARISON ---")
    print(f"V1 Score: {v1_summary['metrics']['avg_score']:.2f}")
    print(f"V2 Score: {v2_summary['metrics']['avg_score']:.2f}")
    print(f"Hit Rate Delta: {regression['hit_rate_delta']:+.2f}")
    print(f"Agreement Delta: {regression['agreement_delta']:+.2f}")
    print(f"Latency Delta: {regression['latency_delta']:+.2f}s")
    print(f"Decision: {regression['decision']}")

    os.makedirs("reports", exist_ok=True)
    with open("reports/summary.json", "w", encoding="utf-8") as f:
        json.dump(v2_summary, f, ensure_ascii=False, indent=2)
    with open("reports/benchmark_results.json", "w", encoding="utf-8") as f:
        json.dump(
            {
                "baseline": {"summary": v1_summary, "results": v1_results},
                "candidate": {"summary": v2_summary, "results": v2_results},
            },
            f,
            ensure_ascii=False,
            indent=2,
        )

    with open("analysis/failure_analysis.md", "w", encoding="utf-8") as f:
        f.write(build_failure_analysis(v2_results, v2_summary))


if __name__ == "__main__":
    asyncio.run(main())
