import importlib
import inspect
import logging
import pkgutil

from fastapi import FastAPI

from llm_proxy.provider_base import ProviderAdapter

logger = logging.getLogger(__name__)


class ProviderRegistry:
    def __init__(self):
        self._adapters: dict[str, ProviderAdapter] = {}

    def register(self, adapter: ProviderAdapter):
        n = len(adapter.get_models())
        self._adapters[adapter.provider_id] = adapter
        logger.info(
            f"Registered provider: {adapter.display_name} ({adapter.provider_id}) with {n} models"
        )

    def get_adapter(self, provider_id: str) -> ProviderAdapter | None:
        return self._adapters.get(provider_id)

    def get_all_adapters(self) -> list[ProviderAdapter]:
        return list(self._adapters.values())


async def discover_and_register_providers(app: FastAPI) -> ProviderRegistry:
    registry = ProviderRegistry()

    import llm_proxy.providers as providers_pkg

    for importer, modname, ispkg in pkgutil.iter_modules(providers_pkg.__path__):
        module = importlib.import_module(f"llm_proxy.providers.{modname}")

        for name, obj in inspect.getmembers(module):
            if (
                inspect.isclass(obj)
                and issubclass(obj, ProviderAdapter)
                and obj is not ProviderAdapter
            ):
                adapter = obj()
                await adapter.initialize()
                router = adapter.create_router()
                app.include_router(router, prefix=f"/{adapter.provider_id}")
                registry.register(adapter)

    return registry
