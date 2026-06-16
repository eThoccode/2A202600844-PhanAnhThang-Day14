from typing import Dict, List


class RetrievalEvaluator:
    def __init__(self, top_k: int = 3):
        self.top_k = top_k

    def calculate_hit_rate(self, expected_ids: List[str], retrieved_ids: List[str], top_k: int = 3) -> float:
        """
        Tính toán xem ít nhất 1 trong expected_ids có nằm trong top_k của retrieved_ids không.
        """
        if not expected_ids:
            return 1.0 # Nếu không có expected_ids (ví dụ: out of-context), coi như mặc định đạt
        top_retrieved = retrieved_ids[:top_k]
        hit = any(doc_id in top_retrieved for doc_id in expected_ids)
        return 1.0 if hit else 0.0

    def calculate_mrr(self, expected_ids: List[str], retrieved_ids: List[str]) -> float:
        """
        Tính Mean Reciprocal Rank.
        Tìm vị trí đầu tiên của một expected_id trong retrieved_ids.
        MRR = 1 / position (vị trí 1-indexed). Nếu không thấy thì là 0.
        """
        if not expected_ids:
            return 1.0 # Nếu không có expected_ids, coi như mặc định đạt
        for i, doc_id in enumerate(retrieved_ids):
            if doc_id in expected_ids:
                return 1.0 / (i + 1)
        return 0.0

    def evaluate_case(self, test_case: Dict, agent_response: Dict) -> Dict:
        expected_ids = test_case.get("expected_retrieval_ids", [])
        retrieved_ids = agent_response.get("retrieved_ids", [])

        hit_rate = self.calculate_hit_rate(expected_ids, retrieved_ids, top_k=self.top_k)
        mrr = self.calculate_mrr(expected_ids, retrieved_ids)

        return {
            "expected_retrieval_ids": expected_ids,
            "retrieved_ids": retrieved_ids,
            "hit_rate": hit_rate,
            "mrr": mrr,
        }

    async def evaluate_batch(self, dataset_results: List[Dict]) -> Dict:
        total_hit_rate = 0.0
        total_mrr = 0.0
        count = 0

        for res in dataset_results:
            test_case = res.get("test_case_raw", {})
            agent_response = res.get("agent_response_raw", {})
            case_metrics = self.evaluate_case(test_case, agent_response)
            total_hit_rate += case_metrics["hit_rate"]
            total_mrr += case_metrics["mrr"]
            count += 1

        if count == 0:
            return {"avg_hit_rate": 0.0, "avg_mrr": 0.0}

        return {
            "avg_hit_rate": total_hit_rate / count,
            "avg_mrr": total_mrr / count,
        }

