import json
import os
import stat
import tempfile

import pytest

from llm_proxy.config_generator import generate_opencode_configs
from llm_proxy.models import ModelObject
from llm_proxy.provider_base import ProviderAdapter
from llm_proxy.provider_registry import ProviderRegistry


class FakeAdapter(ProviderAdapter):
    @property
    def provider_id(self) -> str:
        return "fake"

    @property
    def display_name(self) -> str:
        return "Fake Provider"

    async def initialize(self) -> None:
        pass

    def get_models(self) -> list[ModelObject]:
        return [
            ModelObject(id="model-a", created=0, owned_by="fake"),
            ModelObject(id="model-b", created=0, owned_by="fake"),
        ]

    def get_opencode_model_config(self) -> dict:
        return {
            "model-a": {
                "name": "Model A",
                "limit": {
                    "context": 200000,
                    "output": 16000,
                },
            },
            "model-b": {
                "name": "Model B",
                "limit": {
                    "context": 200000,
                    "output": 16000,
                },
            },
        }

    async def chat_completion(self, request, credentials):
        pass

    async def chat_completion_stream(self, request, credentials):
        pass


class TestConfigGenerator:
    def test_creates_json_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = ProviderRegistry()
            registry.register(FakeAdapter())
            generate_opencode_configs(registry, tmpdir)

            json_path = os.path.join(tmpdir, "opencode_provider_fake.json")
            assert os.path.exists(json_path)

            with open(json_path) as f:
                data = json.load(f)
            assert "fake" in data
            assert data["fake"]["name"] == "Fake Provider"

    def test_creates_executable_script(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = ProviderRegistry()
            registry.register(FakeAdapter())
            generate_opencode_configs(registry, tmpdir)

            script_path = os.path.join(tmpdir, "update_opencode_config.sh")
            assert os.path.exists(script_path)
            assert os.stat(script_path).st_mode & stat.S_IEXEC

    def test_json_contains_all_models(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = ProviderRegistry()
            registry.register(FakeAdapter())
            generate_opencode_configs(registry, tmpdir)

            json_path = os.path.join(tmpdir, "opencode_provider_fake.json")
            with open(json_path) as f:
                data = json.load(f)
            assert len(data["fake"]["models"]) == 2
            assert "model-a" in data["fake"]["models"]
            assert "model-b" in data["fake"]["models"]

    def test_json_has_correct_opencode_format(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = ProviderRegistry()
            registry.register(FakeAdapter())
            generate_opencode_configs(registry, tmpdir)

            json_path = os.path.join(tmpdir, "opencode_provider_fake.json")
            with open(json_path) as f:
                data = json.load(f)
            provider = data["fake"]
            assert provider["npm"] == "@ai-sdk/openai-compatible"
            assert provider["options"]["baseURL"] == "http://localhost:4141/fake/v1"
            assert provider["options"]["apiKey"] == "{env:FAKE_CREDS}"

    def test_creates_output_dir_if_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            nested = os.path.join(tmpdir, "nested", "output")
            registry = ProviderRegistry()
            registry.register(FakeAdapter())
            generate_opencode_configs(registry, nested)
            assert os.path.isdir(nested)

    def test_update_script_uses_provider_key(self):
        """Verify the update script merges into 'provider' (not 'providers')."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = ProviderRegistry()
            registry.register(FakeAdapter())
            generate_opencode_configs(registry, tmpdir)

            script_path = os.path.join(tmpdir, "update_opencode_config.sh")
            with open(script_path) as f:
                script = f.read()
            assert "'provider'" in script
            assert "'providers'" not in script
