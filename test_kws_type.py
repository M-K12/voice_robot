import os
import sys
from pathlib import Path

# DLL Injection Logic
if sys.platform == "win32":
    import importlib.util
    spec = importlib.util.find_spec("sherpa_onnx")
    if spec and spec.origin:
        sherpa_onnx_dir = Path(spec.origin).parent
        if hasattr(os, "add_dll_directory"):
            os.add_dll_directory(str(sherpa_onnx_dir))
        os.environ["PATH"] = str(sherpa_onnx_dir) + os.pathsep + os.environ.get("PATH", "")

import sherpa_onnx
import numpy as np

cl_test_dir = Path(r"d:\projects\xiaoan\cl_test")
model_dir = cl_test_dir / "models" / "sherpa-onnx-kws-zipformer-wenetspeech-3.3M-2024-01-01"

spotter = sherpa_onnx.KeywordSpotter(
    tokens=str(model_dir / "tokens.txt"),
    encoder=str(model_dir / "encoder-epoch-12-avg-2-chunk-16-left-64.onnx"),
    decoder=str(model_dir / "decoder-epoch-12-avg-2-chunk-16-left-64.onnx"),
    joiner=str(model_dir / "joiner-epoch-12-avg-2-chunk-16-left-64.onnx"),
    num_threads=2,
    max_active_paths=4,
    keywords_file=str(model_dir / "keywords.txt"),
    keywords_score=1.0,
    keywords_threshold=0.25,
    num_trailing_blanks=1,
    provider="cpu"
)

stream = spotter.create_stream()
# Feeding some silence
silence = np.zeros(16000, dtype=np.float32)
stream.accept_waveform(16000, silence)
while spotter.is_ready(stream):
    spotter.decode_stream(stream)
result = spotter.get_result(stream)
print(f"Result type: {type(result)}")
print(f"Result value: {result}")
if result:
    print(f"Result keyword: {result.keyword}")
