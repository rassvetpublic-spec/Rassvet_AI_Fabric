"""rai_fabric.speculative_decoder - Конвейер спекулятивного декодирования (Stage R33 / Milestone M2 / R3).

Реализует спекулятивное генерирование с использованием черновой (draft) модели
(qwen2.5-coder:1.5b) и целевой (target) модели (qwen2.5-coder:7b) в рамках бюджета 16 GB VRAM
на аппаратном ускорителе RTX 5070 Ti с подтверждением блоков токенов (lookahead K=4).
"""

from __future__ import annotations

__version__ = "1.0.0"

import json
import logging
import time
import urllib.request
import urllib.error
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("raif.speculative_decoder")

DEFAULT_DRAFT_MODEL = "qwen2.5-coder:1.5b"
DEFAULT_TARGET_MODEL = "qwen2.5-coder:7b"
DEFAULT_LOOKAHEAD_K = 4


@dataclass
class SpeculativeResult:
    """Результат спекулятивной генерации."""
    text: str
    tokens_generated: int
    tokens_accepted: int
    draft_tokens_total: int
    throughput_tps: float
    draft_acceptance_rate: float
    latency_ms: float
    model_draft: str
    model_target: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "tokens_generated": self.tokens_generated,
            "tokens_accepted": self.tokens_accepted,
            "draft_tokens_total": self.draft_tokens_total,
            "throughput_tps": round(self.throughput_tps, 2),
            "draft_acceptance_rate": round(self.draft_acceptance_rate, 4),
            "latency_ms": round(self.latency_ms, 2),
            "model_draft": self.model_draft,
            "model_target": self.model_target,
        }


class SpeculativeDecoder:
    """Конвейер спекулятивного декодирования кодогенерации (Draft + Target Lookahead)."""

    def __init__(
        self,
        draft_model: str = DEFAULT_DRAFT_MODEL,
        target_model: str = DEFAULT_TARGET_MODEL,
        endpoint_url: str = "http://127.0.0.1:11434",
        draft_client: Optional[Any] = None,
        target_client: Optional[Any] = None,
        lookahead_k: int = DEFAULT_LOOKAHEAD_K,
        timeout: float = 30.0,
    ) -> None:
        self.draft_model = draft_model
        self.target_model = target_model
        self.endpoint_url = endpoint_url.rstrip("/")
        self.draft_client = draft_client
        self.target_client = target_client
        self.lookahead_k = max(1, lookahead_k)
        self.timeout = timeout

    def _query_model(self, client: Optional[Any], model: str, prompt: str, max_tokens: int) -> Tuple[str, List[str]]:
        """Запрос к модели через клиент или локальный HTTP эндпоинт."""
        if client is not None:
            if hasattr(client, "generate"):
                res = client.generate({"model": model, "prompt": prompt, "max_tokens": max_tokens})
                if isinstance(res, dict):
                    reply = res.get("text") or res.get("response") or ""
                    tokens = reply.split()
                    return reply, tokens
            elif callable(client):
                res = client(model, prompt, max_tokens)
                if isinstance(res, str):
                    return res, res.split()
                return str(res), str(res).split()

        # HTTP запрос к Ollama
        url = f"{self.endpoint_url}/api/generate"
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"num_predict": max_tokens, "temperature": 0.2},
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                if not isinstance(body, dict) or not isinstance(body.get("response"), str):
                    raise ValueError("Invalid model response contract")
                text = body["response"]
                return text, text.split()
        except Exception as exc:
            # Never disguise an HTTP/model failure as a genuine completion.
            logger.warning("Model query failed for %s (%s)", model, type(exc).__name__)
            raise RuntimeError(f"model query failed: {model}") from exc

    def generate(
        self,
        prompt: str,
        max_tokens: int = 128,
        draft_k: Optional[int] = None,
    ) -> SpeculativeResult:
        """Спекулятивная генерация с верификацией блоками по K токенов."""
        k = draft_k if draft_k is not None else self.lookahead_k
        t_start = time.perf_counter()

        current_prompt = prompt
        generated_tokens: List[str] = []
        total_draft_tokens = 0
        total_accepted_tokens = 0

        # Toy lexical proxy only: split() is NOT a verified model tokenizer.
        # Real speculative decoding needs target conditional token probabilities.
        while len(generated_tokens) < max_tokens:
            generated_before = len(generated_tokens)
            step_k = min(k, max_tokens - len(generated_tokens))
            if step_k <= 0:
                break

            # 1. Быстрый черновик K токенов драфт-моделью
            draft_text, draft_tokens = self._query_model(
                self.draft_client, self.draft_model, current_prompt, step_k
            )
            candidate_tokens = draft_tokens[:step_k]
            if not candidate_tokens:
                # Если черновик пуст, запрашиваем 1 токен целевой моделью
                target_text, target_tokens = self._query_model(
                    self.target_client, self.target_model, current_prompt, 1
                )
                if target_tokens:
                    tok = target_tokens[0]
                    generated_tokens.append(tok)
                    current_prompt += " " + tok
                break

            total_draft_tokens += len(candidate_tokens)

            # 2. Toy verification: compare with target continuation from the SAME
            # prefix, not from the prefix extended by unverified draft tokens.
            target_text, target_tokens = self._query_model(
                self.target_client, self.target_model, current_prompt, len(candidate_tokens) + 1
            )

            # 3. Верификация и принятие токенов
            accepted_in_step = 0
            for i, d_tok in enumerate(candidate_tokens):
                # В детерминированном тесте/клиенте: если целевой токен совпадает или верификатор одобряет
                if i < len(target_tokens) and target_tokens[i] == d_tok:
                    generated_tokens.append(d_tok)
                    accepted_in_step += 1
                else:
                    # При отклонении: берем исправленный токен целевой модели и прерываем текущую серию
                    if i < len(target_tokens):
                        generated_tokens.append(target_tokens[i])
                    break

            total_accepted_tokens += accepted_in_step

            # Если все K токенов приняты, добавляем бонусный токен от целевой модели (K+1)
            if (accepted_in_step == len(candidate_tokens)
                    and len(target_tokens) > len(candidate_tokens)
                    and len(generated_tokens) < max_tokens):
                bonus_token = target_tokens[len(candidate_tokens)]
                generated_tokens.append(bonus_token)
                # Target bonus was not a draft token; exclude from accepted count.

            current_prompt = prompt + " " + " ".join(generated_tokens)

            # Если ни один токен не принят и не добавлен, выходим во избежание зацикливания
            if len(generated_tokens) == generated_before:
                break

        elapsed = max(0.0001, time.perf_counter() - t_start)
        latency_ms = elapsed * 1000.0
        n_tokens = len(generated_tokens)
        throughput_tps = n_tokens / elapsed if elapsed > 0 else 0.0
        acc_rate = (total_accepted_tokens / total_draft_tokens) if total_draft_tokens > 0 else 1.0

        full_text = " ".join(generated_tokens)
        return SpeculativeResult(
            text=full_text,
            tokens_generated=n_tokens,
            tokens_accepted=total_accepted_tokens,
            draft_tokens_total=total_draft_tokens,
            throughput_tps=throughput_tps,
            draft_acceptance_rate=min(1.0, acc_rate),
            latency_ms=latency_ms,
            model_draft=self.draft_model,
            model_target=self.target_model,
        )
