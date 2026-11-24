"""Model providers behind small interfaces: generation, embeddings, reranking.

A provider is addressed by a spec string, e.g. "ollama:qwen3.5:4b" or "openai:gpt-4.1-mini", so the
generation model can be switched at runtime from the Settings page without restarting the server.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import threading
from dataclasses import dataclass

import httpx
import numpy as np

from .config import Settings

THINK_RE = re.compile(r"<think>.*?</think>", re.S)


def unit_rows(m: np.ndarray) -> np.ndarray:
    return m / np.clip(np.linalg.norm(m, axis=1, keepdims=True), 1e-9, None)


class ModelError(RuntimeError):
    """Raised when a model endpoint is unreachable or returns an error."""


# ------------------------------------------------------------------ generation
class ChatModel:
    spec: str

    def complete(self, system: str, user: str, *, json_out: bool = False, history: list[dict] | None = None,
                 images: list[bytes] | None = None, temperature: float = 0.1) -> str:
        raise NotImplementedError


class OllamaChat(ChatModel):
    def __init__(self, base_url: str, model: str):
        self.base, self.model, self.spec = base_url.rstrip("/"), model, f"ollama:{model}"
        self.http = httpx.Client(timeout=httpx.Timeout(600, connect=5))

    def complete(self, system, user, *, json_out=False, history=None, images=None, temperature=0.1):
        last = {"role": "user", "content": user}
        if images:
            last["images"] = [base64.b64encode(i).decode() for i in images]
        payload = {
            "model": self.model, "stream": False, "think": False, "keep_alive": "20m",
            "messages": [{"role": "system", "content": system}, *(history or []), last],
            "options": {"temperature": temperature, "num_ctx": 12288},
        }
        if json_out:
            payload["format"] = "json"
        try:
            r = self.http.post(f"{self.base}/api/chat", json=payload)
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise ModelError(f"Ollama request failed ({self.model}): {e}") from e
        return THINK_RE.sub("", r.json()["message"]["content"]).strip()


class OpenAIChat(ChatModel):
    def __init__(self, base_url: str, key: str, model: str):
        self.base, self.model, self.spec = base_url.rstrip("/"), model, f"openai:{model}"
        self.http = httpx.Client(timeout=httpx.Timeout(300, connect=10),
                                 headers={"Authorization": f"Bearer {key}"} if key else {})

    def complete(self, system, user, *, json_out=False, history=None, images=None, temperature=0.1):
        content: object = user
        if images:
            content = [{"type": "text", "text": user}] + [
                {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(i).decode()}}
                for i in images]
        payload = {"model": self.model, "temperature": temperature,
                   "messages": [{"role": "system", "content": system}, *(history or []),
                                {"role": "user", "content": content}]}
        if json_out:
            payload["response_format"] = {"type": "json_object"}
        try:
            r = self.http.post(f"{self.base}/chat/completions", json=payload)
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise ModelError(f"Cloud LLM request failed ({self.model}): {e}") from e
        return THINK_RE.sub("", r.json()["choices"][0]["message"]["content"] or "").strip()


# ------------------------------------------------------------------ embeddings
class Embeddings:
    spec: str

    def encode(self, texts: list[str]) -> np.ndarray:
        raise NotImplementedError


class OllamaEmbeddings(Embeddings):
    def __init__(self, base_url: str, model: str, batch: int = 24):
        self.base, self.model, self.batch, self.spec = base_url.rstrip("/"), model, batch, f"ollama:{model}"
        self.http = httpx.Client(timeout=httpx.Timeout(300, connect=5))

    def encode(self, texts):
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.batch):
            part = [t[:5000] for t in texts[start:start + self.batch]]
            try:
                r = self.http.post(f"{self.base}/api/embed", json={"model": self.model, "input": part,
                                                                   "keep_alive": "20m"})
                r.raise_for_status()
            except httpx.HTTPError as e:
                raise ModelError(f"Embedding request failed ({self.model}): {e}") from e
            vectors += r.json()["embeddings"]
        return unit_rows(np.asarray(vectors, dtype=np.float32))


class OpenAIEmbeddings(Embeddings):
    def __init__(self, base_url: str, key: str, model: str):
        self.base, self.model, self.spec = base_url.rstrip("/"), model, f"openai:{model}"
        self.http = httpx.Client(timeout=300, headers={"Authorization": f"Bearer {key}"} if key else {})

    def encode(self, texts):
        try:
            r = self.http.post(f"{self.base}/embeddings", json={"model": self.model, "input": texts})
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise ModelError(f"Cloud embedding request failed: {e}") from e
        rows = sorted(r.json()["data"], key=lambda d: d["index"])
        return unit_rows(np.asarray([d["embedding"] for d in rows], dtype=np.float32))


# ------------------------------------------------------------------ reranking
class Reranker:
    """Cross-encoder (question, passage) scorer. Lazy-loaded; returns None when unavailable."""

    def __init__(self, model: str, cache_dir: str):
        self.model_name, self.cache_dir = model, cache_dir
        self._model = None
        self._lock = threading.Lock()
        self.error: str | None = None

    def scores(self, query: str, passages: list[str]) -> list[float] | None:
        with self._lock:
            if self._model is None and self.error is None:
                try:
                    from fastembed.rerank.cross_encoder import TextCrossEncoder
                    self._model = TextCrossEncoder(self.model_name, cache_dir=self.cache_dir)
                except Exception as e:  # missing package / model download blocked
                    self.error = str(e)
            if self._model is None:
                return None
            return [float(s) for s in self._model.rerank(query, passages)]


# ------------------------------------------------------------------ offline fakes (tests)
class FakeEmbeddings(Embeddings):
    spec = "fake:hashing-256"

    def encode(self, texts):
        out = np.zeros((len(texts), 256), dtype=np.float32)
        for row, text in enumerate(texts):
            for word in re.findall(r"[a-z0-9]+", text.lower()):
                out[row, int(hashlib.sha1(word.encode()).hexdigest()[:8], 16) % 256] += 1
        return unit_rows(out)


class FakeChat(ChatModel):
    spec = "fake:echo"

    def complete(self, system, user, *, json_out=False, history=None, images=None, temperature=0.1):
        if json_out:
            return json.dumps({"doc_type": None, "entities": [], "relations": [], "summary": "Test document."})
        if "standalone question" in system.lower():
            return user.rsplit("Follow-up:", 1)[-1].strip()
        cited = re.findall(r"^\[(\d+)\]", user, flags=re.M)
        return f"The documents cover this [{cited[0] if cited else 1}]."


class FakeReranker(Reranker):
    def __init__(self):
        super().__init__("fake", "")

    def scores(self, query, passages):
        from .store import fts_terms
        q = set(fts_terms(query))
        # shaped like a cross-encoder logit: no shared words -> clearly negative
        return [2.0 * len(q & set(re.findall(r"[a-z0-9]+", p.lower()))) - 5.0 for p in passages]


# ------------------------------------------------------------------ registry
@dataclass
class Models:
    chat: ChatModel
    embeddings: Embeddings
    reranker: Reranker
    vision: ChatModel


class ModelRegistry:
    def __init__(self, s: Settings):
        self.s = s
        self._lock = threading.Lock()
        if s.fake_models:
            self.models = Models(FakeChat(), FakeEmbeddings(), FakeReranker(), FakeChat())
        else:
            self.models = Models(self._chat(s.llm), self._embeddings(s.embedder),
                                 Reranker(s.reranker_model, str(s.models_dir)), self._chat(s.llm))

    def _chat(self, spec: str) -> ChatModel:
        provider, _, name = spec.partition(":")
        if provider == "openai":
            return OpenAIChat(self.s.openai_base_url, self.s.openai_api_key, name)
        return OllamaChat(self.s.ollama_url, name)

    def _embeddings(self, spec: str) -> Embeddings:
        provider, _, name = spec.partition(":")
        if provider == "openai":
            return OpenAIEmbeddings(self.s.openai_base_url, self.s.openai_api_key, name)
        return OllamaEmbeddings(self.s.ollama_url, name)

    @property
    def chat(self) -> ChatModel:
        return self.models.chat

    @property
    def embeddings(self) -> Embeddings:
        return self.models.embeddings

    @property
    def reranker(self) -> Reranker:
        return self.models.reranker

    @property
    def vision(self) -> ChatModel:
        return self.models.vision

    def switch_chat(self, spec: str) -> None:
        if self.s.fake_models:
            return
        with self._lock:
            self.models.chat = self._chat(spec)
            self.s.llm = spec

    def available(self) -> dict:
        """Chat models the UI may offer: installed Ollama models + configured cloud models."""
        local: list[str] = []
        ollama_ok = False
        if not self.s.fake_models:
            try:
                r = httpx.get(f"{self.s.ollama_url}/api/tags", timeout=3)
                r.raise_for_status()
                ollama_ok = True
                local = sorted(m["name"] for m in r.json()["models"] if "embed" not in m["name"])
            except httpx.HTTPError:
                pass
        cloud = ([f"openai:{m.strip()}" for m in self.s.openai_models.split(",") if m.strip()]
                 if self.s.openai_api_key else [])
        return {"ollama_reachable": ollama_ok, "local": [f"ollama:{m}" for m in local], "cloud": cloud,
                "current": self.chat.spec, "embedder": self.embeddings.spec,
                "reranker": None if self.s.fake_models else self.s.reranker_model}
