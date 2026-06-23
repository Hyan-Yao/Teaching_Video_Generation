# Teaching Video Generator

**One OpenAI key + one topic → a narrated teaching video.**

This repo has two parts:

| Directory     | What it is                                                                 |
|---------------|----------------------------------------------------------------------------|
| **`teachgen/`** | The orchestrator and entry point. Plans a lesson, routes each segment to the best visual, narrates it, composites the video, and runs an MLLM review loop. |
| **`code2video/`** | The upstream **Code2Video** project — generates polished Manim animations. teachgen drives it as its `animation` renderer. See `code2video/README.md`. |
| `runs/`        | Generated output (`runs/<topic>/...`).                                     |

## Quickstart

```bash
pip install -r requirements.txt          # core deps (+ system ffmpeg)
export OPENAI_API_KEY=sk-...

python -m teachgen --topic "How the Fourier transform works"

# just the plan (cheap), before producing media:
python -m teachgen --topic "Vectors" --plan-only
```

The output video lands at `runs/<topic>/video/final.mp4`. See **`teachgen/README.md`**
for the architecture, the two-phase flow, the three renderers, and how to extend it.

## Install notes

- **Core** (`requirements.txt`): planner + slide + concept-image + audio + compositing.
- **System:** `ffmpeg` is required. LibreOffice is **not** (slides rasterize via Pillow).
- **Animation renderer (optional):** needs Manim + code2video's own deps —
  `pip install -r code2video/requirements.txt`. Without Manim, animation segments
  fall back to concept images.

## Layout

```
code2video/   Manim animation engine (upstream Code2Video) + prompts/, json_files/, assets/
teachgen/     orchestrator: planner, renderers, audio, compositor, feedback
              + make_slide.py and concept_image.py (the slide / image helpers)
runs/         generated lessons
```

> **Security:** `code2video/api_config.json` contains a real OpenAI key in git history.
> Revoke it and use the `OPENAI_API_KEY` environment variable instead.
