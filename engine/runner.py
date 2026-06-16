import asyncio
import time
from typing import Dict, List


class BenchmarkRunner:
    def __init__(self, agent, evaluator, judge):
        self.agent = agent
        self.evaluator = evaluator
        self.judge = judge

    @staticmethod
    def _normalize_response(response) -> Dict:
        if isinstance(response, str):
            return {
                "answer": response,
                "retrieved_ids": [],
                "contexts": [],
                "metadata": {},
            }

        if not isinstance(response, dict):
            return {
                "answer": str(response),
                "retrieved_ids": [],
                "contexts": [],
                "metadata": {},
            }

        metadata = response.get("metadata") or {}
        contexts_metadata = response.get("contexts_metadata") or {}
        retrieved_ids = (
            response.get("retrieved_ids")
            or contexts_metadata.get("retrieved_ids")
            or metadata.get("retrieved_ids")
            or []
        )

        return {
            "answer": response.get("answer", ""),
            "retrieved_ids": retrieved_ids,
            "contexts": response.get("contexts", []),
            "metadata": metadata,
        }

    async def run_single_test(self, test_case: Dict) -> Dict:
        start_time = time.perf_counter()
        raw_response = await self.agent.query(test_case["question"], test_case=test_case)
        latency = time.perf_counter() - start_time
        response = self._normalize_response(raw_response)

        ragas_scores = self.evaluator.evaluate_case(test_case, response)
        judge_result = await self.judge.evaluate_multi_judge(
            test_case["question"],
            response["answer"],
            test_case["expected_answer"],
        )

        return {
            "test_case": test_case["question"],
            "test_case_raw": test_case,
            "agent_response": response["answer"],
            "agent_response_raw": response,
            "retrieved_ids": response["retrieved_ids"],
            "latency": latency,
            "ragas": {
                "faithfulness": round(min(1.0, judge_result["final_score"] / 5), 2),
                "relevancy": round(min(1.0, (judge_result["final_score"] + ragas_scores["hit_rate"]) / 6), 2),
                "retrieval": ragas_scores,
            },
            "judge": judge_result,
            "status": "fail" if judge_result["final_score"] < 3 else "pass",
        }

    async def run_all(self, dataset: List[Dict], batch_size: int = 5) -> List[Dict]:
        results = []
        for i in range(0, len(dataset), batch_size):
            batch = dataset[i:i + batch_size]
            tasks = [self.run_single_test(case) for case in batch]
            batch_results = await asyncio.gather(*tasks)
            results.extend(batch_results)
        return results
