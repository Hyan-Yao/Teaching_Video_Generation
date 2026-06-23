from pathlib import Path

from teachgen.eval.models import ChunkAnalysis

def save_chunk_analysis(analysis: ChunkAnalysis, output_path: str | Path) -> Path:
    
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    path.write_text(analysis.model_dump_json(indent=2),encoding="utf-8")

    return path

def load_chunk_analysis(path: str | Path) -> ChunkAnalysis:

    path = Path(path)

    if not path.is_file():
        raise FileNotFoundError(f"File {path} does not exist") 
    
    json_text = path.read_text(encoding="utf-8")

    return ChunkAnalysis.model_validate_json(
        json_text
    )
