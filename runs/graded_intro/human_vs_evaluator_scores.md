# Human vs. Evaluator Scores

This document tracks manual human grading against the evaluator's LLM-as-a-judge scores for the introductory-topic video set.

## Meeting Summary Table

Score format: `Human / Evaluator`.

| Run | Topic | Video | LOC | Accuracy | Visual Quality | MLD | Logic | Adaptation | Bloom | ICAP | Main Human Finding | Main Evaluator Finding | Meeting Takeaway |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---|
| 02 | Safe Computing | `runs/graded_intro/run_02/safe-computing/video/final.mp4` | 4 / 5 | 5 / 5 | 3 / 3 | 3 / 3 | 4-5 / 4 | 4 / 4 | 4 / 4 | 5 / 5 | Lacked depth and had weak/bad animations. | Strong content, but abstract/placeholder visuals hurt visual and multimedia quality. | Mostly aligned. Evaluator may be slightly generous on objective coverage when content is present but shallow. |
| 04 | Iteration | `runs/graded_intro/run_04/iteration/video/final.mp4` | 3 / 3 | 5 / 4 | 5 / 5 | 3 / 3 | 4-5 / 4 | 4 / 4 | 4 / 4 | 5 / 5 | Did not write/show a basic loop; example slide was abrupt and weak. | Practical examples section lacks actual code, so the loop-writing objective is not met. | Strong alignment. Evaluator correctly caught the central pedagogical failure. |
| 05 | Identifying and Correcting Errors | `runs/graded_intro/run_05/identifying-and-correcting-errors/video/final.mp4` | 5 / 5 | 5 / 4 | 4 / 4 | 4 / 4 | 5 / 5 | 4 / 4 | 5 / 4 | 5 / 4 | Strong video; math question visual was weird and could hurt learning. | Strong coverage and structure, but math example visual is confusing. | Mostly aligned. Evaluator was stricter on accuracy, Bloom, and ICAP because it penalized the visual flaw and higher-level prompt. |
| 06 | Objects: Instances of Classes | `runs/graded_intro/run_06/objects-instances-of-classes/video/final.mp4` | 3 / 3 | 5 / 5 | 3 / 3 | 3 / 4 | 5 / 5 | 4 / 4 | 3 / 3 | 2 / 2 | Missing programming example; animation broke; values were outside boxes and hard to see. | Accurate and logically strong, but lacks code/application and has visual clutter. | Strong alignment. Evaluator correctly caught Bloom/ICAP mismatch from passive delivery despite an Apply objective. |
| 07 | Vectors | `runs/graded_intro/run_07/vectors/video/final.mp4` | 4 / 4 | 5 / 5 | 3 / 4 | 3 / 4 | 5 / 5 | 4 / 4 | 5 / 5 | 5 / 5 | Broken animations in vector addition and magnitude/direction; vector addition animation may mislead students. | Strong lesson with only minor visual issues, mainly missing grid in components section. | Important evaluator miss. Human review caught serious animation problems that the evaluator treated as minor. |

### Metric Legend

| Abbreviation | Metric |
|---|---|
| LOC | Learning Objective Coverage |
| Accuracy | Content Accuracy |
| MLD | Multimedia Learning Design |
| Adaptation | Learning Adaptation |
| Bloom | Bloom Alignment |
| ICAP | ICAP Alignment |

### Preliminary Findings

| Finding | Evidence From Runs |
|---|---|
| The evaluator usually agrees with human grading on major pedagogical failures. | Iteration and Objects both show strong agreement on missing application/code examples. |
| The evaluator is good at identifying objective-level mismatch. | Objects had an Apply objective, but the video was passive; both human and evaluator gave low Bloom/ICAP scores. |
| The evaluator catches many visual/multimedia issues, but can miss severe animation failures. | Vectors is the clearest miss: human saw broken/misleading animation, while evaluator only noted minor visual issues. |
| The evaluator may be generous when content is present but shallow. | Safe Computing received evaluator LOC 5, while human LOC was 4 because the explanations lacked depth. |
| Human and evaluator scores are close enough to support LLM-as-judge usefulness, but human validation is still necessary. | Most metric pairs match exactly or differ by 1 point; the largest concern is qualitative evidence around visual artifacts. |

## Run 02: Safe Computing

**Video:** `runs/graded_intro/run_02/safe-computing/video/final.mp4`  
**Evaluator output:** `runs/graded_intro/run_02/safe-computing/evaluator_baseline/evaluation_result.json`  
**Topic:** Safe Computing  
**Audience:** introductory students  
**Evaluator duration:** 96.68 seconds

### Source Context

| Field | Value |
|---|---|
| Provided learning objectives | Identify common cyber threats and their impact on users.; Understand basic safety measures for protecting personal information online.; Recognize safe practices for device security and software use. |
| Inferred Bloom target | Understand |
| Inferred ICAP target | Passive |
| Inferred lesson structure | Linear overview: importance of safe computing, cyber threats, personal information protection, device security, safe software use, and recap. |
| Main evaluator concern | Some visuals are abstract or placeholder-like, especially during cyber threats and personal information protection. |
| Main human concern | Lack of depth and weak/bad animations, otherwise good. |

### Score Comparison

| Metric | Human Score | Human Notes | Evaluator Score | Evaluator Notes | Agreement |
|---|---:|---|---:|---|---|
| Learning Objective Coverage | 4 | Talked about all topics but did not go deeply into some fields. | 5 | Evaluator judged all core objectives covered at the required introductory depth. | Partial disagreement: human wanted more depth; evaluator accepted brief coverage. |
| Content Accuracy | 5 | No accuracy issues noted. | 5 | Evaluator found definitions, examples, and recommendations factually correct. | Agreement. |
| Visual Quality | 3 | Some animations or pictures do not make sense. | 3 | Evaluator flagged abstract or placeholder visuals for cyber threats and personal information protection. | Agreement. |
| Multimedia Learning Design | 3 | Bad animations. | 3 | Evaluator said some visuals support narration, but others miss instructional opportunities. | Agreement. |
| Logic | 4-5 | Transitions are weird and there is no real in-depth talk. | 4 | Evaluator found clear linear structure with only minor weaknesses. | Mostly aligned, though human noted transition awkwardness more strongly. |
| Learning Adaptation | 4 | No extra note. | 4 | Evaluator found the lesson generally appropriate for introductory students, with minor clarity issues from abstract visuals. | Agreement. |
| Bloom Alignment | 4 | No extra note. | 4 | Evaluator inferred Understand as the target and judged the video mostly aligned. | Agreement. |
| ICAP Alignment | 5 | No extra note. | 5 | Evaluator inferred Passive as the target and judged the passive lecture format fully aligned. | Agreement. |

### Overall Notes

| Reviewer | Overall Interpretation |
|---|---|
| Human | Good video overall, but loses points for lack of depth and bad animations/visuals. |
| Evaluator | Strong content accuracy and objective coverage, but visual quality and multimedia learning design are limited by abstract or placeholder visuals. |

## Run 04: Iteration

**Video:** `runs/graded_intro/run_04/iteration/video/final.mp4`  
**Evaluator output:** `runs/graded_intro/run_04/iteration/evaluator_baseline/evaluation_result.json`  
**Topic:** Iteration  
**Audience:** introductory students  
**Evaluator duration:** 81.79 seconds

### Source Context

| Field | Value |
|---|---|
| Provided learning objectives | Understand the concept of iteration in programming; Identify different forms of loops used for iteration; Write basic loops to repeat a set of instructions; Differentiate between for-loops and while-loops. |
| Inferred Bloom target | Understand |
| Inferred ICAP target | Passive |
| Inferred lesson structure | Linear overview: iteration concept, analogy, loops, for-loop, while-loop, practical example, and recap. |
| Main evaluator concern | The practical examples section does not show actual loop code or a step-by-step code-writing walkthrough. |
| Main human concern | Did not write a basic loop; example slide is abrupt/weak; some diagrams did not make sense; one slide had no useful animation or picture. |

### Score Comparison

| Metric | Human Score | Human Notes | Evaluator Score | Evaluator Notes | Agreement |
|---|---:|---|---:|---|---|
| Learning Objective Coverage | 3 | Did not write a basic loop. | 3 | Evaluator said the lesson covers iteration, for-loops, and while-loops, but fails the objective requiring students to write basic loops. | Agreement. |
| Content Accuracy | 5 | No accuracy issues noted. | 4 | Evaluator found the content accurate overall, but marked a minor issue because missing code could confuse students trying to write loops. | Partial disagreement: human treated missing code as coverage/Bloom issue, not accuracy. |
| Visual Quality | 5 | No visual quality issues noted. | 5 | Evaluator found the visuals clear, readable, and technically well rendered. | Agreement. |
| Multimedia Learning Design | 3 | Some diagrams did not make sense, and one slide had no animation or picture, making the slide useless. | 3 | Evaluator said visuals mostly support narration, but the practical examples section misses essential visual support for loop syntax and structure. | Agreement. |
| Logic | 4-5 | Logic and flow are good, except the example slide is abrupt and weak. | 4 | Evaluator found a clear flow, but said the practical examples section slightly disrupts the otherwise coherent structure. | Agreement. |
| Learning Adaptation | 4 | Missing code hurts beginner learning. | 4 | Evaluator said the lesson is mostly adapted to beginners, but missing code makes it harder to bridge from concept to practice. | Agreement. |
| Bloom Alignment | 4 | Does not support loop writing. | 4 | Evaluator said the lecture supports understanding, but weakly supports the objective of writing basic loops. | Agreement. |
| ICAP Alignment | 5 | No extra note. | 5 | Evaluator judged the passive lecture format aligned with the inferred passive ICAP target. | Agreement. |

### Overall Notes

| Reviewer | Overall Interpretation |
|---|---|
| Human | Strong basic explanation and good overall flow, but the video fails the loop-writing objective because it does not show actual basic loop code. |
| Evaluator | Accurate and visually clear video, but the practical examples section is a major instructional miss because it lacks real code demonstration. |
| Shared takeaway | The evaluator and human grading strongly agree on the central failure: the video explains loops but does not actually teach students to write one. |

## Run 05: Identifying and Correcting Errors

**Video:** `runs/graded_intro/run_05/identifying-and-correcting-errors/video/final.mp4`  
**Evaluator output:** `runs/graded_intro/run_05/identifying-and-correcting-errors/evaluator_baseline/evaluation_result.json`  
**Topic:** Identifying and Correcting Errors  
**Audience:** introductory students  
**Evaluator duration:** 91.58 seconds

### Source Context

| Field | Value |
|---|---|
| Provided learning objectives | Understand the common types of errors in assignments; Learn strategies for identifying these errors; Develop skills to correct errors effectively; Enhance overall accuracy and precision in your work. |
| Inferred Bloom target | Understand |
| Inferred ICAP target | Passive to Active |
| Inferred lesson structure | Linear overview: introduction, error types, spotting strategies, correction steps, example, and recap. |
| Main evaluator concern | The math example visual has a confusing intermediate step, described as `5 + 510`. |
| Main human concern | Math question visual/error is weird and weakens learning, but the rest of the video is strong. |

### Score Comparison

| Metric | Human Score | Human Notes | Evaluator Score | Evaluator Notes | Agreement |
|---|---:|---|---:|---|---|
| Learning Objective Coverage | 5 | No extra note. | 5 | Evaluator judged all objectives covered, including error types, strategies, correction steps, and an example. | Agreement. |
| Content Accuracy | 5 | No extra note. | 4 | Evaluator marked a minor issue because the math example visual is confusing, but did not find a major factual error. | Partial disagreement: human did not treat the math visual as an accuracy issue. |
| Visual Quality | 4 | Math question error is weird. | 4 | Evaluator found visuals generally clear, but penalized the confusing `5 + 510` math visual. | Agreement. |
| Multimedia Learning Design | 4 | Math question flaw hurts learning. | 4 | Evaluator said visuals support narration overall, but the math example flaw weakens the demonstration. | Agreement. |
| Logic | 5 | No extra note. | 5 | Evaluator found the lesson very well organized with smooth transitions. | Agreement. |
| Learning Adaptation | 4 | Confusing visual could hurt beginners. | 4 | Evaluator said the lesson is well adapted, but the math visual could confuse some introductory learners. | Agreement. |
| Bloom Alignment | 5 | Ending was higher, but acceptable. | 4 | Evaluator said the reflection prompt briefly goes above Understand, but the lesson is mostly aligned. | Partial disagreement: human judged the higher-level ending acceptable enough for full credit. |
| ICAP Alignment | 5 | Toward the end it asked for practice, which is higher but acceptable. | 4 | Evaluator inferred Passive to Active and judged the active reflection/practice prompt as aligned but not perfect. | Partial disagreement: human gave full credit for the active/practice element. |

### Overall Notes

| Reviewer | Overall Interpretation |
|---|---|
| Human | Strong video overall. Main issue is the weird/confusing math question visual, but the video still meets the learning goals well. |
| Evaluator | Strong coverage, structure, and pedagogy, with the main weakness being the confusing math example visual. |
| Shared takeaway | Human and evaluator agree that the main flaw is the math example visual. The evaluator is slightly stricter on accuracy, Bloom, and ICAP because it treats that flaw and the higher-level reflection/practice prompt as score-limiting. |

## Run 06: Objects: Instances of Classes

**Video:** `runs/graded_intro/run_06/objects-instances-of-classes/video/final.mp4`  
**Evaluator output:** `runs/graded_intro/run_06/objects-instances-of-classes/evaluator_baseline/evaluation_result.json`  
**Topic:** Objects: Instances of Classes  
**Audience:** introductory students  
**Evaluator duration:** 86.83 seconds

### Source Context

| Field | Value |
|---|---|
| Provided learning objectives | Understand what an object is in programming.; Identify how objects are created from classes.; Recognize the relationship between classes and objects.; Apply the concept of objects in simple programming examples. |
| Inferred Bloom target | Understand and Apply |
| Inferred ICAP target | Active |
| Inferred lesson structure | Object definition, class/blueprint analogy, instantiation, car class example, and recap. |
| Main evaluator concern | The video supports understanding, but does not fully support application because it lacks code, step-by-step programming application, and active learner engagement. |
| Main human concern | Missing programming example; one animation broke; values were outside boxes and hard to see. |

### Score Comparison

| Metric | Human Score | Human Notes | Evaluator Score | Evaluator Notes | Agreement |
|---|---:|---|---:|---|---|
| Learning Objective Coverage | 3 | Missing programming example; gave a simple car example instead. | 3 | Evaluator said all objectives are touched, but the apply objective is weak because there is no code or step-by-step programming demonstration. | Agreement. |
| Content Accuracy | 5 | No extra note. | 5 | Evaluator found definitions, analogies, and explanations accurate. | Agreement. |
| Visual Quality | 3 | One animation completely broke, while one had values outside of the boxes and was hard to see. | 3 | Evaluator flagged clutter, small text, overlapping boxes, and misalignment in key slides. | Agreement. |
| Multimedia Learning Design | 3 | Bad visual quality hurts the video's multimedia learning design. | 4 | Evaluator said visuals generally align with narration, but the car example could be clearer. | Partial disagreement: human penalized visual failures more strongly. |
| Logic | 5 | No extra note. | 5 | Evaluator found a clear, coherent progression with smooth transitions. | Agreement. |
| Learning Adaptation | 4 | No programming example may hurt CS students, otherwise made sense. | 4 | Evaluator said the lesson is generally adapted for beginners, but visual clutter and missing active application may hurt clarity. | Agreement. |
| Bloom Alignment | 3 | Understand at best. | 3 | Evaluator said the lesson supports Understand but only weakly supports Apply. | Agreement. |
| ICAP Alignment | 2 | Passive. | 2 | Evaluator expected Active because the objective says Apply, but observed only passive watching/listening. | Agreement. |

### Overall Notes

| Reviewer | Overall Interpretation |
|---|---|
| Human | The explanation is accurate and logically organized, but the video misses the programming/application objective and has serious visual issues in the animations. |
| Evaluator | Accurate and logically strong, but shallow on application and visually cluttered in key examples. |
| Shared takeaway | Human and evaluator strongly agree on the main pedagogical failure: the video says students should apply objects in programming examples, but the produced video mostly explains concepts passively and does not show a real programming example. |

## Run 07: Vectors

**Video:** `runs/graded_intro/run_07/vectors/video/final.mp4`  
**Evaluator output:** `runs/graded_intro/run_07/vectors/evaluator_baseline/evaluation_result.json`  
**Topic:** Vectors  
**Audience:** introductory students  
**Evaluator duration:** 83.89 seconds

### Source Context

| Field | Value |
|---|---|
| Provided learning objectives | Define what a vector is and its components.; Understand the difference between scalars and vectors.; Illustrate how to add two vectors geometrically.; Explain the concept of vector magnitude and direction. |
| Inferred Bloom target | Understand |
| Inferred ICAP target | Passive |
| Inferred lesson structure | Definition, scalar/vector comparison, components, vector addition, magnitude/direction, and recap. |
| Main evaluator concern | The vector components section mentions a grid, but the visual does not show a grid; magnitude and direction are somewhat brief. |
| Main human concern | Broken animations in vector addition and magnitude/direction; the vector addition animation may give incorrect information to students. |

### Score Comparison

| Metric | Human Score | Human Notes | Evaluator Score | Evaluator Notes | Agreement |
|---|---:|---|---:|---|---|
| Learning Objective Coverage | 4 | Magnitude and direction could be better. | 4 | Evaluator said all objectives are covered, but magnitude/direction are brief and components lack the referenced grid. | Agreement. |
| Content Accuracy | 5 | No extra note. | 5 | Evaluator found definitions and vector operations accurate. | Agreement on narrated content, but human visual concern may affect actual learner interpretation. |
| Visual Quality | 3 | Broken animation in both vector addition and vector direction/magnitude description. | 4 | Evaluator found visuals mostly clear, with only a minor missing-grid issue. | Disagreement: human caught more serious animation/rendering problems. |
| Multimedia Learning Design | 3 | Vector addition animation mistake gives incorrect information to student. | 4 | Evaluator said visuals generally align well, with the missing grid as the main missed opportunity. | Disagreement: human judged the animation issue as instructionally harmful. |
| Logic | 5 | No extra note. | 5 | Evaluator found excellent sequence and smooth transitions. | Agreement. |
| Learning Adaptation | 4 | Addition problem could give issues. | 4 | Evaluator said the lesson is beginner-appropriate, but minor visual mismatch could cause confusion. | Agreement in score, but human identified a more serious cause. |
| Bloom Alignment | 5 | No extra note. | 5 | Evaluator judged the lesson fully aligned with Understand-level objectives. | Agreement. |
| ICAP Alignment | 5 | No extra note. | 5 | Evaluator judged the passive video format aligned with the passive ICAP target. | Agreement. |

### Overall Notes

| Reviewer | Overall Interpretation |
|---|---|
| Human | Strong topic flow and accurate narration, but broken animations reduce visual quality and may make the vector addition explanation misleading. |
| Evaluator | Strong introductory lesson with accurate content, clear flow, and only minor visual/multimedia issues. |
| Shared takeaway | Human and evaluator agree on the high-level lesson structure and most scores, but this is an important evaluator miss: the human review found animation errors that may create incorrect understanding, while the evaluator mostly treated the visuals as clear. |
