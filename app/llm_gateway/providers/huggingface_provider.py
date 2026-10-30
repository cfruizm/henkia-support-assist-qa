from __future__ import annotations

import time
from huggingface_hub import InferenceClient

from app.llm_gateway.errors import LLMGatewayError, normalize_error
from app.llm_gateway.models import LLMResult
from app.llm_gateway.providers.base import BaseProvider


class HuggingFaceProvider(BaseProvider):
    def __init__(self, token, provider=None, bill_to=None, disable_thinking=True,
                 timeout_seconds=75, structured_mode="json_schema"):
        if not token:
            raise LLMGatewayError("missing_api_key", "Falta HF_TOKEN.")
        self.provider = provider
        self.bill_to = str(bill_to or "").strip() or None
        self.disable_thinking = bool(disable_thinking)
        self.structured_mode = str(structured_mode or "json_schema").casefold()
        self.timeout_seconds = max(10, min(120, int(timeout_seconds)))
        kwargs = {"token": token, "timeout": self.timeout_seconds}
        if provider:
            kwargs["provider"] = provider
        if self.bill_to:
            kwargs["bill_to"] = self.bill_to
        try:
            self.client = InferenceClient(**kwargs)
        except TypeError as exc:
            if self.bill_to and "bill_to" in str(exc):
                raise LLMGatewayError(
                    "unsupported_hf_billing_client",
                    "La version instalada de huggingface_hub no soporta HF_BILL_TO.",
                ) from exc
            raise

    def _response_format(self, request):
        mode = str(getattr(request, "response_format_mode", "auto") or "auto").casefold()
        if mode == "text" or not request.response_schema:
            return None, "text"
        if mode == "json_object" or self.structured_mode == "json_object":
            return {"type": "json_object"}, "json_object"
        return {
            "type": "json_schema",
            "json_schema": {
                "name": "structured_response",
                "strict": True,
                "schema": request.response_schema,
            },
        }, "json_schema"

    def complete(self, request, model):
        response_format, format_mode = self._response_format(request)
        provider_name = str(self.provider or "").strip().casefold()
        kwargs = {
            "model": model,
            "messages": [dict(message) for message in request.messages],
            "max_tokens": max(32, min(4096, int(request.max_tokens))),
            "temperature": max(1e-8, float(request.temperature)),
            "stream": False,
        }
        if response_format:
            kwargs["response_format"] = response_format

        thinking_control = "not_sent"
        if self.disable_thinking:
            if provider_name == "cerebras":
                kwargs["extra_body"] = {"reasoning_effort": "none"}
                thinking_control = "reasoning_effort_none"
            elif provider_name == "deepinfra":
                kwargs["extra_body"] = {"chat_template_kwargs": {"enable_thinking": False}}
                thinking_control = "chat_template_enable_thinking_false"
            elif provider_name == "ovhcloud":
                # Qwen's OpenAI-compatible API documents enable_thinking as a
                # direct extra_body field. Test this independently, without
                # adding another system instruction or changing token budgets.
                kwargs["extra_body"] = {"enable_thinking": False}
                thinking_control = "enable_thinking_false_direct"
            else:
                kwargs["extra_body"] = {"chat_template_kwargs": {"enable_thinking": False}}
                thinking_control = "chat_template_enable_thinking_false"

        started = time.perf_counter()
        try:
            response = self.client.chat_completion(**kwargs)
        except Exception as exc:
            raise normalize_error(exc) from exc
        latency = round((time.perf_counter() - started) * 1000, 3)

        try:
            choice = response.choices[0]
            text = str(choice.message.content or "")
            finish = choice.finish_reason
        except Exception:
            raise LLMGatewayError("invalid_response", "Respuesta HF no reconocida.")

        usage = getattr(response, "usage", None)
        usage_dict = {
            "prompt_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
            "completion_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
            "total_tokens": int(getattr(usage, "total_tokens", 0) or 0),
        }
        metadata = {
            "provider_route": self.provider,
            "billing_organization": self.bill_to,
            "thinking_disabled": thinking_control != "not_sent",
            "thinking_disabled_requested": self.disable_thinking,
            "thinking_control": thinking_control,
            "response_format_mode": format_mode,
            "timeout_seconds": self.timeout_seconds,
        }

        if not text.strip():
            code = "empty_truncated_response" if str(finish).casefold() == "length" else "empty_response"
            exc = LLMGatewayError(
                code,
                "Hugging Face devolvio contenido vacio" +
                (" al agotar el presupuesto de salida." if code == "empty_truncated_response" else "."),
                code == "empty_truncated_response",
            )
            exc.metadata = {
                **metadata,
                "finish_reason": finish,
                "usage": usage_dict,
                "attempted_model": model,
            }
            raise exc

        return LLMResult(
            True, text, "huggingface", model, request.purpose, latency,
            usage_dict, finish, metadata=metadata,
        )
