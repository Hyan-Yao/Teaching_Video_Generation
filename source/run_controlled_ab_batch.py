from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv


REQUEST_IDS = [
    "fault_tolerance_001",
    "statistical_inference_001",
    "circular_motion_001",
    "modern_physics_001",
    "cellular_respiration_001",
]


def run(cmd: list[str]) -> None:
    print("\n$ " + " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    load_dotenv(root / ".env")

    bank = json.loads((root / "examples" / "example_request_bank.json").read_text(encoding="utf-8"))
    by_id = {item["request_id"]: item for item in bank}

    requests_dir = root / "examples" / "tmp_controlled_ab_requests"
    requests_dir.mkdir(parents=True, exist_ok=True)

    for request_id in REQUEST_IDS:
        item = by_id[request_id]
        topic_slug = item["course"]["topic"].strip().lower().replace(" ", "_")
        request_path = requests_dir / f"{request_id}.json"
        request_path.write_text(json.dumps(item, indent=2), encoding="utf-8")

        base = Path("runs") / "controlled_ab" / request_id
        shared_run = base / "shared_plan"
        no_inner_run = base / "no_inner"
        with_inner_run = base / "with_inner"

        # The teachgen Config appends a safe topic slug under each run-dir.
        topic_dir_name = item["course"]["topic"].strip().lower()
        topic_dir_name = "".join(c if c.isalnum() else "-" for c in topic_dir_name).strip("-")
        while "--" in topic_dir_name:
            topic_dir_name = topic_dir_name.replace("--", "-")
        topic_dir_name = topic_dir_name[:60] or "untitled"

        shared_topic_dir = shared_run / topic_dir_name
        initial_plan = shared_topic_dir / "lesson_plan_initial.json"
        refined_plan = shared_topic_dir / "lesson_plan_refined_r1.json"

        print(f"\n=== {request_id}: {item['course']['topic']} ===", flush=True)

        if initial_plan.is_file() and refined_plan.is_file():
            print(f"[skip] shared plans already exist under {shared_topic_dir}", flush=True)
        else:
            run(
                [
                    sys.executable,
                    "-m",
                    "teachgen",
                    "--request-json",
                    str(request_path),
                    "--plan-refinement-mode",
                    "evaluator",
                    "--max-plan-rounds",
                    "1",
                    "--plan-only",
                    "--run-dir",
                    str(shared_run),
                ]
            )

        no_inner_topic_dir = no_inner_run / topic_dir_name
        if (no_inner_topic_dir / "video" / "final.mp4").is_file() and (
            no_inner_topic_dir / "evaluator_baseline" / "evaluation_result.json"
        ).is_file():
            print(f"[skip] no-inner render/eval already exists under {no_inner_topic_dir}", flush=True)
        else:
            run(
                [
                    sys.executable,
                    "source/render_from_plan.py",
                    "--request-json",
                    str(request_path),
                    "--plan-json",
                    str(initial_plan),
                    "--run-dir",
                    str(no_inner_run),
                    "--eval-baseline",
                ]
            )

        with_inner_topic_dir = with_inner_run / topic_dir_name
        if (with_inner_topic_dir / "video" / "final.mp4").is_file() and (
            with_inner_topic_dir / "evaluator_baseline" / "evaluation_result.json"
        ).is_file():
            print(f"[skip] with-inner render/eval already exists under {with_inner_topic_dir}", flush=True)
        else:
            run(
                [
                    sys.executable,
                    "source/render_from_plan.py",
                    "--request-json",
                    str(request_path),
                    "--plan-json",
                    str(refined_plan),
                    "--run-dir",
                    str(with_inner_run),
                    "--eval-baseline",
                ]
            )


if __name__ == "__main__":
    main()
