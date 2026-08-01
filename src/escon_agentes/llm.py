"""Cliente LLM — OpenRouter (multi-modelo) + xAI opcional."""

from __future__ import annotations

from typing import Any

from escon_agentes.config import Settings, get_settings


class LLMClient:
    def __init__(
        self,
        settings: Settings | None = None,
        model: str | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.model_override = model
        self._client = None
        self._provider: str | None = None

    @property
    def available(self) -> bool:
        return self.settings.llm_available

    @property
    def model_id(self) -> str:
        return self.settings.resolve_model(self.model_override)

    @property
    def provider(self) -> str:
        return self.settings.active_provider()

    def with_model(self, model: str | None) -> "LLMClient":
        return LLMClient(self.settings, model=model)

    def _get_client(self):
        provider = self.provider
        if self._client is not None and self._provider == provider:
            return self._client

        from openai import OpenAI

        if provider == "openrouter":
            self._client = OpenAI(
                api_key=self.settings.openrouter_api_key,
                base_url=self.settings.openrouter_base_url
                or "https://openrouter.ai/api/v1",
                default_headers={
                    "HTTP-Referer": "https://escondigital.com.br",
                    "X-Title": "Escon Agentes Contabeis",
                },
            )
        elif provider == "xai":
            self._client = OpenAI(
                api_key=self.settings.xai_api_key,
                base_url=self.settings.xai_base_url,
            )
        else:
            raise RuntimeError("Nenhum provider LLM configurado")

        self._provider = provider
        return self._client

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.2,
        max_tokens: int = 4096,
        model: str | None = None,
    ) -> str:
        if not self.available:
            return self._offline_reply(messages)

        model_id = self.settings.resolve_model(model or self.model_override)
        # xAI direto: se o model for id openrouter com barra, usa xai_model
        if self.provider == "xai" and "/" in model_id:
            model_id = self.settings.xai_model

        client = self._get_client()
        resp = client.chat.completions.create(
            model=model_id,
            messages=messages,  # type: ignore[arg-type]
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return (resp.choices[0].message.content or "").strip()

    def complete(self, system: str, user: str, **kwargs: Any) -> str:
        return self.chat(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            **kwargs,
        )

    def _offline_reply(self, messages: list[dict[str, str]]) -> str:
        last = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
        return (
            "[modo offline — configure OPENROUTER_API_KEY no .env]\n"
            "Aliases: kimi | gpt | gps | grok | deepseek | gemini | claude\n"
            "Tools determinísticas (XML, OFX, Contmatic, tarefas) seguem funcionando.\n\n"
            f"Última mensagem (trecho): {last[:400]}"
        )


def list_model_aliases(settings: Settings | None = None) -> dict[str, str]:
    s = settings or get_settings()
    return s.aliases()
