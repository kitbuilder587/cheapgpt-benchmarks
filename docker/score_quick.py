import json
from collections import defaultdict
from pathlib import Path

from lcb_runner.benchmarks.code_generation import CodeGenerationProblem
from lcb_runner.evaluation.compute_code_generation_metrics import codegen_metrics
from lcb_runner.lm_styles import LMStyle
from lcb_runner.utils.extraction_utils import extract_code
from livebench.if_runner.instruction_following_eval import evaluation_main
from livebench.process_results.coding.utils import LCB_generation_process_results
from livebench.process_results.data_analysis.tablereformat.utils import table_process_results
from livebench.process_results.math.AMPS_Hard.utils import amps_hard_process_results
from livebench.process_results.math.math_competitions.utils import (
    aime_process_results,
    mathcontest_process_results,
)
from livebench.process_results.reasoning.zebra_puzzle.utils import get_zebra_puzzle_evaluator
from livebench.process_results.writing.typos.utils import typos_process_results

INPUT = Path("/input")
QUICK = Path("/quick")
OUTPUT = Path("/output")


def output_text(body):
    chunks = []
    for output in (body or {}).get("output", []):
        if not isinstance(output, dict) or output.get("type") != "message":
            continue
        for content in output.get("content", []):
            if isinstance(content, dict) and content.get("type") == "output_text":
                chunks.append(str(content.get("text", "")))
    return "\n".join(chunks)


def load_records(benchmark):
    return [
        record
        for line in (INPUT / "attempts.jsonl").read_text(encoding="utf-8").split("\n")
        if line.strip()
        and (record := json.loads(line))["status"] == "completed"
        and record["benchmark"] == benchmark
    ]


def score_instruction_following(question, answer):
    prompt = str(question["turns"][0])
    item = evaluation_main.InputExample(
        key=question["question_id"],
        instruction_id_list=question["instruction_id_list"],
        prompt=prompt,
        kwargs=[
            {key: value for key, value in values.items() if value is not None}
            for values in question["kwargs"]
        ],
    )
    result = evaluation_main.test_instruction_following_strict(item, {prompt: answer})
    instruction_score = sum(result.follow_instruction_list) / len(result.follow_instruction_list)
    return (float(result.follow_all_instructions) + instruction_score) / 2


def score_livebench_answer(question, answer):
    task = str(question["task"])
    if task in {"LCB_generation", "coding_completion"}:
        return LCB_generation_process_results(question, answer)
    if task == "tablereformat":
        return table_process_results(
            str(question["turns"][0]), str(question["ground_truth"]), answer, "v1"
        )
    if question["category"] == "instruction_following":
        return score_instruction_following(question, answer)
    if task == "AMPS_Hard":
        return amps_hard_process_results(str(question["ground_truth"]), answer)
    if task == "math_comp":
        ground_truth = str(question["ground_truth"])
        if str(question.get("subtask", "")).startswith("aime"):
            return aime_process_results(ground_truth, answer)
        return mathcontest_process_results(ground_truth, answer, str(question["turns"][0]))
    if task == "zebra_puzzle":
        evaluator = get_zebra_puzzle_evaluator(str(question["livebench_release_date"]))
        return evaluator(str(question["ground_truth"]), answer)
    if task == "typos":
        return typos_process_results(str(question["ground_truth"]), answer)
    raise ValueError(f"Unsupported quick-v1 task: {task}")


def score_livebench():
    question_data = json.loads((QUICK / "livebench.json").read_text(encoding="utf-8"))
    questions = {
        f"livebench-{question['category']}-{question['question_id'][:12]}": question
        for question in question_data["questions"]
    }
    scores = []
    for record in load_records("livebench"):
        question = questions[record["item_id"]]
        value = score_livebench_answer(question, output_text(record["response"]["body"]))
        scores.append(
            {
                "benchmark": "livebench",
                "item_id": record["item_id"],
                "attempt": record["attempt"],
                "category": question["category"],
                "task": question["task"],
                "score": value,
                "source_content_sha256": record["content_sha256"],
            }
        )
    by_category = defaultdict(list)
    for score in scores:
        by_category[score["category"]].append(float(score["score"]))
    categories = {
        category: round(sum(values) / len(values) * 100, 3)
        for category, values in sorted(by_category.items())
    }
    summary = {
        "benchmark": "livebench",
        "release": question_data["release"],
        "questions": len(questions),
        "attempts_per_item": 3,
        "scored_attempts": len(scores),
        "categories": categories,
        "score": round(sum(categories.values()) / len(categories), 3) if categories else None,
    }
    return scores, summary


def score_livecodebench():
    question_data = json.loads((QUICK / "livecodebench.json").read_text(encoding="utf-8"))
    problems = [CodeGenerationProblem(**question) for question in question_data["questions"]]
    records = load_records("livecodebench")
    by_attempt = {(record["item_id"], record["attempt"]): record for record in records}
    samples = []
    generations = []
    ordered_records = []
    for problem in problems:
        item_id = f"livecodebench-{problem.question_id}"
        problem_records = [
            by_attempt[(item_id, attempt)]
            for attempt in range(1, 4)
            if (item_id, attempt) in by_attempt
        ]
        if not problem_records:
            continue
        samples.append(problem.get_evaluation_sample())
        generations.append(
            [
                extract_code(output_text(record["response"]["body"]), LMStyle.OpenAIReason)
                for record in problem_records
            ]
        )
        ordered_records.append(problem_records)
    if not samples:
        return [], {
            "benchmark": "livecodebench",
            "questions": len(problems),
            "attempts_per_item": 3,
            "scored_attempts": 0,
            "score": None,
        }
    metrics, results, metadata = codegen_metrics(
        samples, generations, k_list=[1], num_process_evaluate=len(samples), timeout=6
    )
    scores = []
    for problem_index, problem_records in enumerate(ordered_records):
        for attempt_index, result in enumerate(results[problem_index]):
            record = problem_records[attempt_index]
            passed = all(value > 0 for value in result)
            scores.append(
                {
                    "benchmark": "livecodebench",
                    "item_id": record["item_id"],
                    "attempt": record["attempt"],
                    "passed": passed,
                    "score": int(passed),
                    "source_content_sha256": record["content_sha256"],
                    "grader_metadata": metadata[problem_index][attempt_index],
                }
            )
    summary = {
        "benchmark": "livecodebench",
        "release": question_data["release"],
        "dataset_revision": question_data["dataset_revision"],
        "questions": len(problems),
        "attempts_per_item": 3,
        "scored_attempts": len(scores),
        "passed_attempts": sum(score["passed"] for score in scores),
        "score": round(float(metrics["pass@1"]) * 100, 3),
    }
    return scores, summary


all_scores = []
summaries = {}
for scorer in (score_livebench, score_livecodebench):
    scores, summary = scorer()
    all_scores.extend(scores)
    summaries[summary["benchmark"]] = summary
OUTPUT.mkdir(parents=True, exist_ok=True)
(OUTPUT / "scores.jsonl").write_text(
    "".join(json.dumps(score, ensure_ascii=False, sort_keys=True) + "\n" for score in all_scores),
    encoding="utf-8",
)
(OUTPUT / "score-summary.json").write_text(
    json.dumps(summaries, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
    encoding="utf-8",
)
