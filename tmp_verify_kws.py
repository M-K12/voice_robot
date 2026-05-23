import os
import sys
from pathlib import Path

# DLL Injection Logic
if sys.platform == "win32":
    import importlib.util
    spec = importlib.util.find_spec("sherpa_onnx")
    if spec and spec.origin:
        sherpa_onnx_dir = Path(spec.origin).parent
        print(f"Adding DLL directory: {sherpa_onnx_dir}")
        if hasattr(os, "add_dll_directory"):
            os.add_dll_directory(str(sherpa_onnx_dir))
        os.environ["PATH"] = str(sherpa_onnx_dir) + os.pathsep + os.environ.get("PATH", "")

import sherpa_onnx
import numpy as np

sherpa_dir = Path(r"d:\projects\xiaoan\sherpa")
model_dir = sherpa_dir / "models" / "sherpa-onnx-kws-zipformer-wenetspeech-3.3M-2024-01-01"

print(f"Initializing KeywordSpotter with models from {model_dir}")

try:
    spotter = sherpa_onnx.KeywordSpotter(
        tokens=str(model_dir / "tokens.txt"),
        encoder=str(model_dir / "encoder-epoch-12-avg-2-chunk-16-left-64.onnx"),
        decoder=str(model_dir / "decoder-epoch-12-avg-2-chunk-16-left-64.onnx"),
        joiner=str(model_dir / "joiner-epoch-12-avg-2-chunk-16-left-64.onnx"),
        num_threads=2,
        max_active_paths=4,
        keywords_file=str(sherpa_dir / "models" / "keywords.txt"),
        keywords_score=1.0,
        keywords_threshold=0.25,
        num_trailing_blanks=1,
        provider="cpu"
    )
    print("SUCCESS: KeywordSpotter created successfully!")
except Exception as e:
    print(f"FAILURE: {e}")
    import traceback
    traceback.print_exc()
