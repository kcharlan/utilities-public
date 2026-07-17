import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from llm_proxy.config import settings
from llm_proxy.config_generator import generate_opencode_configs
from llm_proxy.provider_registry import ProviderRegistry, discover_and_register_providers

logging.basicConfig(level=settings.log_level.upper())
logger = logging.getLogger(__name__)

registry: ProviderRegistry | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global registry
    registry = await discover_and_register_providers(app)
    adapters = registry.get_all_adapters()
    total_models = sum(len(a.get_models()) for a in adapters)
    logger.info(f"LLM Proxy started: {len(adapters)} providers, {total_models} models")
    generate_opencode_configs(registry, settings.output_dir)
    yield


app = FastAPI(title="LLM Proxy", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/providers")
async def list_providers():
    if registry is None:
        return {"providers": []}
    return {
        "providers": [
            {
                "id": a.provider_id,
                "name": a.display_name,
                "models": len(a.get_models()),
                "base_path": f"/{a.provider_id}/v1",
            }
            for a in registry.get_all_adapters()
        ]
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=settings.host, port=settings.port, log_level=settings.log_level)
