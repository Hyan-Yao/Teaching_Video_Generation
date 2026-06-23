import argparse
from pathlib import Path

from teachgen.eval.aggregate import aggregate_evaluation
from teachgen.eval.extractors import (
    ChunkAnalyzer,
    ContentExtractor,
    PedagogyExtractor,
    VisualMultimediaExtractor,
)
from teachgen.eval.graders import ContentGrader, PedagogyGrader, PresentationGrader
from teachgen.eval.inference import LectureInferencer, SectionInferencer
from teachgen.eval.models import EvaluationRequest, GraderOutput, LectureInference, SectionInference
from teachgen.eval.storage import load_chunk_analysis, save_chunk_analysis
from teachgen.eval.text_llm import TextLLM
from teachgen.eval.video import VideoChunk, get_video_duration, plan_chunks_for_video, write_video_chunk
from teachgen.eval.video_llm import VideoLLM


def _write_json(path: Path, value) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value.model_dump_json(indent=2), encoding="utf-8")
    return path


def _load_section(path: Path) -> SectionInference:
    return SectionInference.model_validate_json(path.read_text(encoding="utf-8"))


def _load_lecture(path: Path) -> LectureInference:
    return LectureInference.model_validate_json(path.read_text(encoding="utf-8"))


def _load_grader_output(path: Path) -> GraderOutput:
    return GraderOutput.model_validate_json(path.read_text(encoding="utf-8"))


def run_evaluation(
    request: EvaluationRequest,
    output_dir: Path,
    chunk_seconds: float,
) -> Path:
    video_path = Path(request.video_path)
    output_dir.mkdir(parents=True, exist_ok=True)

    chunks_dir = output_dir / "chunks"
    chunk_analysis_dir = output_dir / "chunk_analyses"
    sections_dir = output_dir / "sections"

    video_llm = VideoLLM()
    text_llm = TextLLM()
    chunk_analyzer = ChunkAnalyzer(
        ContentExtractor(video_llm),
        VisualMultimediaExtractor(video_llm),
        PedagogyExtractor(video_llm),
    )
    section_inferencer = SectionInferencer(text_llm)
    lecture_inferencer = LectureInferencer(text_llm)

    planned_chunks = plan_chunks_for_video(video_path, chunk_seconds)
    chunk_analyses = []

    for chunk in planned_chunks:
        chunk_name = f"chunk_{chunk.index:03d}"
        chunk_video_path = chunks_dir / f"{chunk_name}.mp4"
        chunk_json_path = chunk_analysis_dir / f"{chunk_name}.json"

        if chunk_json_path.is_file():
            print(f"[skip] chunk analysis {chunk_json_path}")
            chunk_analyses.append(load_chunk_analysis(chunk_json_path))
            continue

        if not chunk_video_path.is_file():
            print(f"[write] video chunk {chunk_video_path}")
            write_video_chunk(video_path, chunk, chunk_video_path)
        else:
            print(f"[skip] video chunk {chunk_video_path}")

        chunk_duration = get_video_duration(chunk_video_path)
        local_chunk = VideoChunk(
            index=chunk.index,
            start_time_seconds=0,
            end_time_seconds=chunk_duration,
        )

        print(f"[run] chunk extraction {chunk_json_path}")
        analysis = chunk_analyzer.analyze(chunk_video_path, local_chunk)
        save_chunk_analysis(analysis, chunk_json_path)
        chunk_analyses.append(analysis)

    section_inferences = []
    for analysis in chunk_analyses:
        section_path = sections_dir / f"section_{analysis.chunk_index:03d}.json"

        if section_path.is_file():
            print(f"[skip] section inference {section_path}")
            section_inferences.append(_load_section(section_path))
            continue

        print(f"[run] section inference {section_path}")
        section = section_inferencer.infer(analysis)
        _write_json(section_path, section)
        section_inferences.append(section)

    lecture_path = output_dir / "lecture.json"
    if lecture_path.is_file():
        print(f"[skip] lecture inference {lecture_path}")
        lecture = _load_lecture(lecture_path)
    else:
        print(f"[run] lecture inference {lecture_path}")
        lecture = lecture_inferencer.infer(section_inferences, request)
        _write_json(lecture_path, lecture)

    content_grades_path = output_dir / "content_grades.json"
    if content_grades_path.is_file():
        print(f"[skip] content grader {content_grades_path}")
        content_grades = _load_grader_output(content_grades_path)
    else:
        print(f"[run] content grader {content_grades_path}")
        content_grades = ContentGrader(text_llm).grade(
            request,
            lecture,
            section_inferences,
            [analysis.content for analysis in chunk_analyses],
        )
        _write_json(content_grades_path, content_grades)

    presentation_grades_path = output_dir / "presentation_grades.json"
    if presentation_grades_path.is_file():
        print(f"[skip] presentation grader {presentation_grades_path}")
        presentation_grades = _load_grader_output(presentation_grades_path)
    else:
        print(f"[run] presentation grader {presentation_grades_path}")
        presentation_grades = PresentationGrader(text_llm).grade(
            lecture,
            section_inferences,
            [analysis.visual_multimedia for analysis in chunk_analyses],
            [analysis.pedagogy for analysis in chunk_analyses],
        )
        _write_json(presentation_grades_path, presentation_grades)

    pedagogy_grades_path = output_dir / "pedagogy_grades.json"
    if pedagogy_grades_path.is_file():
        print(f"[skip] pedagogy grader {pedagogy_grades_path}")
        pedagogy_grades = _load_grader_output(pedagogy_grades_path)
    else:
        print(f"[run] pedagogy grader {pedagogy_grades_path}")
        pedagogy_grades = PedagogyGrader(text_llm).grade(
            request,
            lecture,
            section_inferences,
            [analysis.pedagogy for analysis in chunk_analyses],
        )
        _write_json(pedagogy_grades_path, pedagogy_grades)

    result = aggregate_evaluation(
        request,
        lecture,
        [content_grades, presentation_grades, pedagogy_grades],
    )
    result_path = output_dir / "evaluation_result.json"
    print(f"[write] evaluation result {result_path}")
    _write_json(result_path, result)
    return result_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate an instructional video.")
    parser.add_argument("--video", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--chunk-seconds", type=float, default=900)
    parser.add_argument("--course-requirement")
    parser.add_argument("--learning-objective", action="append", dest="learning_objectives")
    parser.add_argument("--student-persona")
    parser.add_argument("--intended-bloom")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    request = EvaluationRequest(
        video_path=args.video,
        course_requirement=args.course_requirement,
        learning_objectives=args.learning_objectives,
        student_persona=args.student_persona,
        intended_bloom=args.intended_bloom,
    )
    result_path = run_evaluation(
        request=request,
        output_dir=Path(args.output),
        chunk_seconds=args.chunk_seconds,
    )
    print(f"Saved final evaluation to {result_path}")


if __name__ == "__main__":
    main()
