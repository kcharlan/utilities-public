import json
import logging
from abc import ABC, abstractmethod
from typing import AsyncIterator

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from llm_proxy.auth import decode_credentials, extract_authorization
from llm_proxy.models import (
    ChatCompletionChunk,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ModelListResponse,
    ModelObject,
)


class ProviderAdapter(ABC):

    @property
    @abstractmethod
    def provider_id(self) -> str:
        """URL path prefix and unique identifier, e.g. 't3chat'.
        The adapter will be mounted at /{provider_id}/v1/"""
        ...

    @property
    @abstractmethod
    def display_name(self) -> str:
        """Human-readable name, e.g. 'T3 Chat'."""
        ...

    @property
    def requires_auth(self) -> bool:
        """Whether this provider requires authentication. Override to return
        False for providers that need no credentials."""
        return True

    @property
    def env_var_name(self) -> str:
        """Environment variable name for credentials, e.g. 'T3_CHAT_CREDS'.
        Override in subclasses if the default (PROVIDER_ID_CREDS) isn't right."""
        return f"{self.provider_id.upper()}_CREDS"

    @abstractmethod
    async def initialize(self) -> None:
        """Called once at startup. Use for model discovery, connection
        setup, or any async initialization."""
        ...

    @abstractmethod
    def get_models(self) -> list[ModelObject]:
        """Return list of models in OpenAI ModelObject format."""
        ...

    @abstractmethod
    def get_opencode_model_config(self) -> dict:
        """Return dict of model configs in OpenCode v1.2.10 format.
        Keys are model IDs, values are dicts with name, limit, etc."""
        ...

    @abstractmethod
    async def chat_completion(
        self,
        request: ChatCompletionRequest,
        credentials: dict,
    ) -> ChatCompletionResponse:
        """Execute a non-streaming chat completion."""
        ...

    @abstractmethod
    async def chat_completion_stream(
        self,
        request: ChatCompletionRequest,
        credentials: dict,
    ) -> AsyncIterator[ChatCompletionChunk]:
        """Execute a streaming chat completion."""
        ...

    def create_router(self) -> APIRouter:
        """Creates the FastAPI router with /v1/chat/completions and /v1/models."""
        router = APIRouter()
        adapter = self

        @router.post("/v1/chat/completions")
        async def chat_completions(request: Request):
            body = await request.json()

            # Debug: log tool names from the request
            if "tools" in body:
                tool_names = [
                    t.get("function", {}).get("name", "?")
                    for t in body.get("tools", [])
                ]
                logger.debug(
                    "REQUEST TOOLS: names=%s, tool_choice=%s",
                    tool_names,
                    body.get("tool_choice"),
                )

            chat_request = ChatCompletionRequest(**body)

            if adapter.requires_auth:
                auth_header = extract_authorization(request)
                credentials = decode_credentials(auth_header)
            else:
                credentials = {}

            if chat_request.stream:

                async def event_stream():
                    async for chunk in adapter.chat_completion_stream(
                        chat_request, credentials
                    ):
                        yield f"data: {chunk.model_dump_json()}\n\n"
                    yield "data: [DONE]\n\n"

                return StreamingResponse(
                    event_stream(),
                    media_type="text/event-stream",
                    headers={
                        "Cache-Control": "no-cache",
                        "Connection": "keep-alive",
                        "X-Accel-Buffering": "no",
                    },
                )
            else:
                response = await adapter.chat_completion(chat_request, credentials)
                return response

        @router.get("/v1/models")
        async def list_models():
            models = adapter.get_models()
            return ModelListResponse(data=models)

        return router
