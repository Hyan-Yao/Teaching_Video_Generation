#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

OUT_ROOT="runs/visual_refiner_ab_demo"
BASELINE_ROOT="$OUT_ROOT/baseline"
REFINED_ROOT="$OUT_ROOT/visual_refiner"

REQUESTS=(
  "examples/human_eval_10_requests/tm_cs_bin_001.json"
  "examples/human_eval_10_requests/tm_cs_saf_002.json"
  "examples/human_eval_10_requests/tm_phy_cir_004.json"
  "examples/human_eval_10_requests/tm_mat_vec_001.json"
  "examples/human_eval_10_requests/tm_bio_cel_001.json"
)

mkdir -p "$BASELINE_ROOT" "$REFINED_ROOT"

for req in "${REQUESTS[@]}"; do
  echo
  echo "============================================================"
  echo "Baseline: $req"
  echo "============================================================"
  uv run python -m teachgen \
    --request-json "$req" \
    --plan-refinement-mode none \
    --feedback-mode none \
    --max-rounds 0 \
    --animation-mode code2video_critic \
    --animation-feedback-rounds 0 \
    --eval-baseline \
    --max-workers 16 \
    --run-dir "$BASELINE_ROOT"

  topic_slug="$(.venv/bin/python - "$req" <<'PY'
import json
import sys
from pathlib import Path

text = json.loads(Path(sys.argv[1]).read_text())["course"]["topic"]
slug = "".join(c if c.isalnum() else "-" for c in text.strip().lower()).strip("-")
while "--" in slug:
    slug = slug.replace("--", "-")
print((slug[:60] or "untitled"))
PY
)"
  plan_json="$BASELINE_ROOT/$topic_slug/lesson_plan.json"

  echo
  echo "============================================================"
  echo "Animation visual refiner: $req"
  echo "Plan: $plan_json"
  echo "============================================================"
  uv run python -m teachgen \
    --request-json "$req" \
    --plan-json "$plan_json" \
    --plan-refinement-mode none \
    --feedback-mode evaluator \
    --outer-repair-mode asset_only \
    --asset-repair-modalities animation \
    --outer-plan-repair-threshold 4 \
    --max-rounds 2 \
    --animation-mode code2video_critic \
    --animation-feedback-rounds 1 \
    --animation-repair-policy critic_first \
    --eval-baseline \
    --max-workers 16 \
    --run-dir "$REFINED_ROOT"
done

echo
echo "Done. Videos are under:"
echo "  $BASELINE_ROOT/*/video/final.mp4"
echo "  $REFINED_ROOT/*/video/final.mp4"
