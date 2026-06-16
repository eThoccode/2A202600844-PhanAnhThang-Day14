import json
import os

def validate_lab():
    print("[INFO] Validating lab submission format...")

    required_files = [
        "reports/summary.json",
        "reports/benchmark_results.json",
        "analysis/failure_analysis.md"
    ]

    # 1. Kiểm tra sự tồn tại của tất cả file
    missing = []
    for f in required_files:
        if os.path.exists(f):
            print(f"[OK] Found: {f}")
        else:
            print(f"[ERROR] Missing file: {f}")
            missing.append(f)

    if missing:
        print(f"\n[ERROR] Missing {len(missing)} required file(s). Add them before submission.")
        return

    # 2. Kiểm tra nội dung summary.json
    try:
        with open("reports/summary.json", "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        print(f"[ERROR] reports/summary.json is not valid JSON: {e}")
        return

    if "metrics" not in data or "metadata" not in data:
        print("[ERROR] summary.json is missing 'metrics' or 'metadata'.")
        return

    metrics = data["metrics"]

    print(f"\n--- Quick stats ---")
    print(f"Total cases: {data['metadata'].get('total', 'N/A')}")
    print(f"Average score: {metrics.get('avg_score', 0):.2f}")

    # EXPERT CHECKS
    has_retrieval = "hit_rate" in metrics
    if has_retrieval:
        print(f"[OK] Retrieval metrics found (Hit Rate: {metrics['hit_rate']*100:.1f}%)")
    else:
        print(f"[WARN] Retrieval metrics missing (hit_rate).")

    has_multi_judge = "agreement_rate" in metrics
    if has_multi_judge:
        print(f"[OK] Multi-judge metrics found (Agreement Rate: {metrics['agreement_rate']*100:.1f}%)")
    else:
        print(f"[WARN] Multi-judge metrics missing (agreement_rate).")

    if data["metadata"].get("version"):
        print(f"[OK] Agent version metadata found (Regression Mode)")

    print("\n[OK] Lab artifacts are ready for grading.")

if __name__ == "__main__":
    validate_lab()
