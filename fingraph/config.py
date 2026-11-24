"""Runtime settings. Everything is overridable with environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def env(name: str, default: str) -> str:
    return os.environ.get(name, default)


@dataclass
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(env("FINGRAPH_DATA", str(ROOT / "data"))))
    models_dir: Path = field(default_factory=lambda: Path(env("FINGRAPH_MODELS", str(ROOT / ".models"))))

    # Generation model. "ollama:<name>" (local) or "openai:<name>" (any OpenAI-compatible endpoint).
    llm: str = field(default_factory=lambda: env("FINGRAPH_LLM", "ollama:qwen3.5:4b"))
    # Embedding model is fixed per index: changing it requires a re-index.
    embedder: str = field(default_factory=lambda: env("FINGRAPH_EMBEDDER", "ollama:qwen3-embedding:0.6b"))
    ollama_url: str = field(default_factory=lambda: env("OLLAMA_URL", "http://127.0.0.1:11434"))
    openai_base_url: str = field(default_factory=lambda: env("OPENAI_BASE_URL", "https://api.openai.com/v1"))
    openai_api_key: str = field(default_factory=lambda: env("OPENAI_API_KEY", ""))
    openai_models: str = field(default_factory=lambda: env("OPENAI_MODELS", "gpt-4.1-mini"))
    ocr: str = field(default_factory=lambda: env("FINGRAPH_OCR", "auto"))  # auto | vision | llm
    reranker_model: str = "Xenova/ms-marco-MiniLM-L-6-v2"
    use_reranker: bool = field(default_factory=lambda: env("FINGRAPH_RERANK", "1") == "1")
    fake_models: bool = field(default_factory=lambda: env("FINGRAPH_FAKE_MODELS", "0") == "1")

    # Ingestion limits
    max_file_mb: int = 25
    max_pages: int = 200
    min_text_chars_per_page: int = 50  # below this a PDF page is treated as scanned -> OCR
    ocr_low_confidence: float = 0.6

    # Retrieval
    chunk_max_chars: int = 1200
    chunk_overlap: int = 150
    candidates: int = 30
    top_k: int = 8
    per_doc_cap: int = 3
    rrf_k: int = 60
    # Calibrated on eval/golden.json (see reports/eval.md); override with env vars.
    min_similarity: float = field(default_factory=lambda: float(env("FINGRAPH_MIN_SIM", "0.45")))
    min_rerank: float = field(default_factory=lambda: float(env("FINGRAPH_MIN_RERANK", "-4.0")))
    history_turns: int = 6

    @property
    def db_path(self) -> Path:
        return self.data_dir / "fingraph.sqlite3"

    @property
    def upload_dir(self) -> Path:
        return self.data_dir / "uploads"

    def ensure_dirs(self) -> None:
        for p in (self.data_dir, self.upload_dir, self.models_dir):
            p.mkdir(parents=True, exist_ok=True)
