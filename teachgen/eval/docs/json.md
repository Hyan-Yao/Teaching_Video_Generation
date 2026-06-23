# Video-Only Lecture Evaluator Design

## Purpose

The evaluator grades an instructional video using the rubric in `rubric.md`.
Course requirements, learning objectives, topic labels, and student personas are
optional. When metadata is missing or too brief to support a judgment, the
evaluator infers the missing context from the video and clearly marks it as
inferred.

The evaluator uses a hierarchical pipeline so that both short lectures and
long lectures can be evaluated:

1. Split the video into ordered chunks.
2. Analyze each chunk independently into a structured `ChunkAnalysis`.
3. Synthesize all chunk analyses and optional metadata into one
   `LectureAnalysis`.
4. Send the `LectureAnalysis` to rubric-specific graders.
5. Adjudicate the grader outputs into a final evaluation.

The structured JSON is evidence for the graders. Chunk analyzers do not assign
final rubric scores.

---

## Evidence Provenance

Every provided or inferred contextual claim should include provenance:

- `source`: `provided`, `inferred`, or `mixed`
- `confidence`: number from `0.0` to `1.0`
- `evidence`: timestamped observations supporting the claim

Provided metadata should guide the evaluator, but it should not override clear
contradictory evidence from the video. Any disagreement between provided and
inferred context must be recorded.

---

## Optional Input Metadata

The evaluator may receive any subset of:

- `title_or_topic`
- `course_requirement`
- `learning_objectives`
- `student_persona`
- `intended_bloom_level`

Each field should record:

- its value
- whether it was provided
- whether it is sufficiently detailed to use for scoring

Missing or insufficient fields are inferred during lecture synthesis.

---

## Chunking Strategy

Short videos may be analyzed as one chunk. Long videos should be divided into
fixed-duration chunks, initially targeting approximately 10 to 15 minutes.

Each chunk must include:

- `chunk_id`
- `start_time`
- `end_time`
- overlap information, if overlapping chunks are used

Chunk analyzers infer only what is observable in their chunk. They should not
guess about the entire lecture or assign final rubric scores.

---

## ChunkAnalysis

Each chunk analyzer watches one video chunk and outputs the following.

### Chunk Identity

- `chunk_id`
- `start_time`
- `end_time`
- `analysis_confidence`

### Instructional Structure

- `sections`
  - `section_id`
  - `start_time`
  - `end_time`
  - `section_title_or_label`
  - `main_concepts`
  - `instructional_purpose`
  - `short_summary`
  - `transition_from_previous`

### Content Evidence

- `definitions_introduced`
- `claims_made`
- `formulas_or_procedures`
- `examples_used`
- `key_quoted_phrases`
- `possible_factual_risks`
- `possible_contradictions`
- `claims_requiring_verification`

Possible errors must include evidence and uncertainty. The chunk analyzer flags
risks; the accuracy grader decides whether they are actual errors.

### Local Pedagogical Inference

- `inferred_local_audience`
- `prerequisites_assumed`
- `possible_prerequisite_gaps`
- `possible_jargon_overload`
- `local_bloom_level`
- `bloom_evidence`
- `local_icap_level`
- `icap_evidence`
- `learner_action_expected`
- `scaffolding_observations`
- `pacing_observations`
- `checks_for_understanding`
- `questions_or_prompts`

### Visual and Multimedia Evidence

- `visual_elements_present`
  - text
  - diagrams
  - equations
  - charts
  - animations
  - demonstrations
- `visual_clarity_observations`
- `visual_bug_flags`
- `visual_audio_alignment`
- `visual_instructional_value`
- `missed_visual_opportunities`

### Local Strengths and Risks

- `strengths`
- `weaknesses`
- `notable_moments`

Every important strength, weakness, or risk should include a timestamp and a
short description of the observed evidence.

---

## LectureAnalysis

The lecture synthesizer receives the ordered `ChunkAnalysis` objects and all
optional metadata. It produces the canonical representation used by graders.

### Lecture Identity and Scope

- `title_or_topic`
- `subject_domain`
- `total_duration`
- `instructional_mode`
  - conceptual
  - worked-example
  - procedural
  - mixed
- `lecture_scope`
- `scope_confidence`

### Provided and Inferred Context

- `provided_context`
- `inferred_context`
  - `target_audience`
  - `assumed_prerequisites`
  - `main_instructional_goal`
  - `learning_objectives`
  - `intended_bloom_level`
  - `expected_icap_level`
- `context_disagreements`

Every inferred context field must include provenance, confidence, and evidence.

### Scope-Aware Content Expectations

- `non_negotiable_concepts`
- `supporting_concepts`
- `out_of_scope_concepts`
- `expectation_rationale`
- `coverage_evidence`
- `missing_or_underdeveloped_concepts`

Expectations must account for topic, inferred audience, lecture scope, and
duration. A short introductory lecture should not be judged as if it promised a
complete course.

### Global Lecture Structure

- `ordered_sections`
- `concept_progression`
- `transition_quality`
- `recap_and_closure`
- `global_logic_risks`

### Bloom and ICAP Profile

- `section_bloom_profile`
- `observed_bloom_center`
- `intended_bloom_level`
- `bloom_alignment_evidence`
- `section_icap_profile`
- `observed_icap_center`
- `expected_icap_level`
- `icap_alignment_evidence`

When intended Bloom or expected ICAP is not provided, it is inferred from the
topic, scope, audience, and instructional goal. Inferred targets must be marked.

### Global Content and Accuracy Evidence

- `major_claims`
- `definitions`
- `formulas_or_procedures`
- `examples`
- `factual_risks`
- `contradictions`
- `verification_needs`

### Global Visual and Multimedia Evidence

- `overall_visual_style`
- `visual_quality_patterns`
- `visual_bug_summary`
- `visual_audio_alignment_patterns`
- `visual_instructional_value_patterns`
- `missed_visual_opportunity_patterns`

### Global Pedagogical Evidence

- `audience_consistency`
- `prerequisite_gap_patterns`
- `jargon_patterns`
- `scaffolding_patterns`
- `pacing_patterns`
- `learner_engagement_patterns`
- `strengths`
- `weaknesses`
- `uncertainty_notes`

---

## Rubric-Specific Graders

### Content and Accuracy Grader

Scores:

- Learning Objective Coverage
- Content Accuracy

Uses:

- provided or inferred objectives
- scope-aware content expectations
- coverage evidence
- claims, definitions, formulas, examples, and factual risks

### Visual and Logic Grader

Scores:

- Visual Quality
- Multimedia Learning Design
- Logic

Uses:

- global lecture structure
- visual quality and bug evidence
- visual-audio alignment
- visual instructional value
- transitions and concept progression

### Pedagogical Effectiveness Grader

Scores:

- Learning Adaptation
- Bloom Alignment
- ICAP Alignment

Uses:

- provided or inferred audience and prerequisites
- intended and observed Bloom profiles
- expected and observed ICAP profiles
- scaffolding, pacing, jargon, and learner-action evidence

### Final Adjudicator

Receives:

- `LectureAnalysis`
- all grader outputs
- the complete rubric

Produces:

- final metric scores
- evidence-based rationales
- confidence and limitations per metric
- overall strengths and weaknesses
- consistency corrections when grader outputs conflict

The adjudicator must not invent new evidence. It may only use evidence present
in the `LectureAnalysis` or grader outputs.

---

## Grader Output Contract

Each rubric metric must produce:

- `metric_name`
- `score`: integer from `1` to `5`
- `confidence`: number from `0.0` to `1.0`
- `context_mode`: `provided`, `inferred`, or `mixed`
- `evidence`
- `rationale`
- `limitations`

Context-sensitive metrics should receive lower confidence when their required
context was inferred with low confidence.

---

## Initial Validation Plan

Use the two short videos to validate whether one chunk analyzer produces useful
and complete evidence. Use the 90-minute video to validate chunk boundaries,
cross-chunk synthesis, and global consistency.

Before implementing graders, manually review the generated `ChunkAnalysis` and
`LectureAnalysis` outputs. The first milestone is a structured representation
that contains enough grounded evidence for a human to apply the rubric.
