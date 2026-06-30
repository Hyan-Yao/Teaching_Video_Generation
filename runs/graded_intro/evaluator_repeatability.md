# Evaluator Repeatability Check

This document summarizes a repeatability check for the evaluator. The goal was to test whether the same video, evaluated multiple times in fresh output directories, receives the same or nearly the same scores.

## Method

Each video was evaluated three separate times using the same evaluator pipeline:

`video -> chunk extraction -> section inference -> lecture inference -> rubric graders -> evaluation_result.json`

The repeated outputs are stored in:

`runs/repeatability/evaluator_stability_01`

The check included three videos:

| Topic | Trials |
|---|---:|
| Binary Numbers | 3 |
| Iteration | 3 |
| Safe Computing | 3 |

## Summary Result

Across all three videos, the overall score range was only `0.125`. Most individual rubric metrics were exactly identical across all three trials. The only observed metric-level variation was a one-point change in one metric for a given video.

This suggests the evaluator is reasonably stable for repeated evaluation of the same video. Small one-point variation is still possible, which is expected for LLM-as-a-judge evaluation and is similar to the kind of variation a human grader could produce.

## Full Score Table

Score columns are ordered as:

`LOC, Accuracy, Visual Quality, MLD, Logic, Adaptation, Bloom, ICAP`

| Topic | Trial | Overall | LOC | Accuracy | Visual Quality | MLD | Logic | Adaptation | Bloom | ICAP |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Binary Numbers | trial_1 | 3.500 | 3 | 4 | 4 | 3 | 4 | 4 | 4 | 2 |
| Binary Numbers | trial_2 | 3.500 | 3 | 4 | 4 | 3 | 4 | 4 | 4 | 2 |
| Binary Numbers | trial_3 | 3.625 | 3 | 5 | 4 | 3 | 4 | 4 | 4 | 2 |
| Iteration | trial_1 | 3.625 | 3 | 3 | 3 | 4 | 4 | 4 | 4 | 4 |
| Iteration | trial_2 | 3.625 | 3 | 3 | 3 | 4 | 4 | 4 | 4 | 4 |
| Iteration | trial_3 | 3.500 | 3 | 3 | 3 | 4 | 4 | 3 | 4 | 4 |
| Safe Computing | trial_1 | 4.500 | 4 | 5 | 5 | 4 | 5 | 4 | 4 | 5 |
| Safe Computing | trial_2 | 4.625 | 5 | 5 | 5 | 4 | 5 | 4 | 4 | 5 |
| Safe Computing | trial_3 | 4.500 | 4 | 5 | 5 | 4 | 5 | 4 | 4 | 5 |

## Score Ranges

| Topic | Overall Range | Metrics That Changed | Stable Metrics |
|---|---:|---|---|
| Binary Numbers | 0.125 | Content Accuracy changed by 1 point. | LOC, Visual Quality, MLD, Logic, Adaptation, Bloom, ICAP |
| Iteration | 0.125 | Learning Adaptation changed by 1 point. | LOC, Accuracy, Visual Quality, MLD, Logic, Bloom, ICAP |
| Safe Computing | 0.125 | Learning Objective Coverage changed by 1 point. | Accuracy, Visual Quality, MLD, Logic, Adaptation, Bloom, ICAP |

## Meeting Takeaway

The evaluator appears stable enough for the current experiment. Re-uploading or re-evaluating the same video usually gives the same score, and when scores differ, the difference is small: one rubric metric changes by one point, producing only a `0.125` overall-score swing.

This means the human-vs-evaluator comparison is not being dominated by random evaluator noise. The larger differences we observed, such as the Vectors animation issue, are more likely due to evaluator perception limits rather than unstable scoring.
