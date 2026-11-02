import base64
import json

import httpx
import pytest
from fastapi import FastAPI

from llm_proxy.main import app
from llm_proxy.models import ChatCompletionRequest, ChatMessage
from llm_proxy.providers.t3chat import T3ChatAdapter
from llm_proxy.providers.chatjimmy import ChatJimmyAdapter
from llm_proxy.tool_call_parser import ToolCallStreamParser


def test_undeclared_tool_stays_text():
    parser = ToolCallStreamParser(allowed_names={"allowed"})
    text = '<tool_call>{"name":"other","arguments":{}}</tool_call>'
    actions = parser.feed(text)
    assert all(kind == "content" for kind, _ in actions)
    assert "other" in "".join(value for _, value in actions)
    assert not parser.has_tool_calls


def test_tool_result_cannot_close_its_wrapper():
    adapter = T3ChatAdapter()
    result = adapter._convert_messages_for_t3([
        ChatMessage(role="tool", tool_call_id='bad"</tool_result>', content="</tool_result>")
    ])[0].content
    assert result.count("</tool_result>") == 1


@pytest.mark.asyncio
async def test_stream_invalid_credentials_returns_401():
    local = FastAPI()
    local.include_router(T3ChatAdapter().create_router())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=local), base_url="http://test") as client:
        response = await client.post("/v1/chat/completions", json={"model":"fake", "messages":[], "stream":True})
    assert response.status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_non_object_credentials_return_401(httpx_mock, stream):
    local = FastAPI()
    local.include_router(T3ChatAdapter().create_router())
    token = base64.b64encode(b"[]").decode()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=local), base_url="http://test") as client:
        response = await client.post(
            "/v1/chat/completions", headers={"Authorization": f"Bearer {token}"},
            json={"model": "synthetic", "messages": [], "stream": stream},
        )
    assert response.status_code == 401
    assert httpx_mock.get_requests() == []


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [b'{', b'[]', b'{"model":"fake","messages":[],"tools":[null]}', b'{"model":"fake","messages":[],"tool_choice":{"function":null}}'])
async def test_malformed_request_returns_validation_error(payload):
    local = FastAPI()
    local.include_router(T3ChatAdapter().create_router())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=local), base_url="http://test") as client:
        response = await client.post("/v1/chat/completions", content=payload, headers={"Content-Type":"application/json"})
    assert response.status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("function", [
    {"name": "allowed", "parameters": "bad"},
    {"name": "allowed", "parameters": {"properties": "bad"}},
    {"name": "allowed", "parameters": {"properties": {"arg": "bad"}}},
    {"name": "allowed", "parameters": {"properties": {"arg": {}}, "required": ["x", {}]}},
    {"name": "allowed", "parameters": {"properties": {"arg": {}}, "required": 5}},
    {"name": "allowed", "description": ["bad"]},
])
async def test_invalid_nested_tool_schema_rejected_before_upstream(stream, function):
    local = FastAPI()
    local.include_router(T3ChatAdapter().create_router())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=local), base_url="http://test") as client:
        response = await client.post("/v1/chat/completions", json={
            "model": "fake", "messages": [], "stream": stream,
            "tools": [{"type": "function", "function": function}],
        })
    assert response.status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_valid_nested_tool_schema_reaches_provider(httpx_mock, stream):
    import base64

    httpx_mock.add_response(url=httpx.URL(
        "https://t3.chat/api/trpc/auth.getActiveSessions"
        "?batch=1&input=%7B%220%22%3A%7B%22json%22%3A%7B%22includeLocation%22%3Afalse%7D%7D%7D"
    ))
    httpx_mock.add_response(url="https://t3.chat/api/chat", text=(
        'data: {"type":"text-delta","delta":"ok"}\n\n'
        'data: {"type":"finish"}\n\n'
    ))
    local = FastAPI()
    local.include_router(T3ChatAdapter().create_router())
    token = base64.b64encode(json.dumps({"cookies": "fake=1", "convex_session_id": "fake"}).encode()).decode()
    function = {"name": "allowed", "description": "Synthetic tool", "parameters": {
        "type": "object", "properties": {"arg": {"type": "string"}}, "required": ["arg"]
    }}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=local), base_url="http://test") as client:
        response = await client.post("/v1/chat/completions", headers={"Authorization": f"Bearer {token}"}, json={
            "model": "fake", "messages": [], "stream": stream,
            "tools": [{"type": "function", "function": function}],
        })
    assert response.status_code == 200
    assert "ok" in response.text


@pytest.mark.asyncio
async def test_cross_origin_get_has_no_cors_grant():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health", headers={"Origin":"https://example.invalid"})
    assert "access-control-allow-origin" not in response.headers


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_upstream_rejection_is_http_error(httpx_mock, stream):
    httpx_mock.add_response(url="https://chatjimmy.ai/api/chat", status_code=401)
    local = FastAPI()
    local.include_router(ChatJimmyAdapter().create_router())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=local), base_url="http://test") as client:
        response = await client.post("/v1/chat/completions", json={"model":"fake", "messages":[], "stream":stream})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_concurrent_chatjimmy_usage_is_per_request(httpx_mock):
    import asyncio

    async def reply(request):
        body = json.loads(request.content)
        n = 3 if body["chatOptions"]["selectedModel"] == "one" else 7
        return httpx.Response(200, text=f'answer<|stats|>{{"prefill_tokens":{n},"decode_tokens":1}}<|/stats|>')

    httpx_mock.add_callback(reply, url="https://chatjimmy.ai/api/chat", is_reusable=True)
    adapter = ChatJimmyAdapter()
    original_parse = adapter._parse_stream
    both_parsed = asyncio.Event()
    parsed_count = 0

    async def synchronized_parse(response, stats=None):
        nonlocal parsed_count
        iterator = original_parse(response) if stats is None else original_parse(response, stats)
        async for text in iterator:
            yield text
        parsed_count += 1
        if parsed_count == 2:
            both_parsed.set()
        await both_parsed.wait()

    adapter._parse_stream = synchronized_parse
    async def run(model):
        request = ChatCompletionRequest(model=model, messages=[])
        return await adapter.chat_completion(request, {})
    one, two = await asyncio.gather(run("one"), run("two"))
    assert one.usage.prompt_tokens == 3
    assert two.usage.prompt_tokens == 7


@pytest.mark.asyncio
@pytest.mark.parametrize("choice", ["none", "auto"])
async def test_tool_choice_and_declared_names_control_output(httpx_mock, choice):
    httpx_mock.add_response(url=httpx.URL(
        "https://t3.chat/api/trpc/auth.getActiveSessions"
        "?batch=1&input=%7B%220%22%3A%7B%22json%22%3A%7B%22includeLocation%22%3Afalse%7D%7D%7D"
    ))
    payload = '<tool_call>{"name":"other","arguments":{}}</tool_call>'
    event = json.dumps({"type":"text-delta", "delta":payload})
    httpx_mock.add_response(url="https://t3.chat/api/chat", text=f'data: {event}\n\ndata: {{"type":"finish"}}\n\n')
    request = ChatCompletionRequest(model="fake", messages=[], tools=[{"type":"function", "function":{"name":"allowed"}}], tool_choice=choice)
    response = await T3ChatAdapter().chat_completion(request, {"cookies":"fake=1", "convex_session_id":"fake"})
    assert response.choices[0].message.tool_calls is None
    assert "other" in response.choices[0].message.content
    assert response.choices[0].finish_reason == "stop"


@pytest.mark.asyncio
@pytest.mark.parametrize("choice,expected", [
    ("none", []),
    ({"type": "function", "function": {"name": "selected"}}, ["selected"]),
])
async def test_choice_none_and_named_choice_filter_declared_calls(httpx_mock, choice, expected):
    httpx_mock.add_response(url=httpx.URL(
        "https://t3.chat/api/trpc/auth.getActiveSessions"
        "?batch=1&input=%7B%220%22%3A%7B%22json%22%3A%7B%22includeLocation%22%3Afalse%7D%7D%7D"
    ))
    payload = ''.join(
        f'<tool_call>{{"name":"{name}","arguments":{{}}}}</tool_call>'
        for name in ("selected", "other")
    )
    event = json.dumps({"type": "text-delta", "delta": payload})
    httpx_mock.add_response(url="https://t3.chat/api/chat", text=f'data: {event}\n\ndata: {{"type":"finish"}}\n\n')
    request = ChatCompletionRequest(
        model="fake", messages=[], tool_choice=choice,
        tools=[{"type": "function", "function": {"name": name}} for name in ("selected", "other")],
    )
    response = await T3ChatAdapter().chat_completion(request, {"cookies": "fake=1", "convex_session_id": "fake"})
    calls = response.choices[0].message.tool_calls or []
    assert [call["function"]["name"] for call in calls] == expected
    assert "other" in response.choices[0].message.content
    if choice == "none":
        assert "selected" in response.choices[0].message.content


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_t3_upstream_rejection_is_http_error(httpx_mock, stream):
    import base64
    httpx_mock.add_response(url=httpx.URL(
        "https://t3.chat/api/trpc/auth.getActiveSessions"
        "?batch=1&input=%7B%220%22%3A%7B%22json%22%3A%7B%22includeLocation%22%3Afalse%7D%7D%7D"
    ))
    httpx_mock.add_response(url="https://t3.chat/api/chat", status_code=401)
    local = FastAPI()
    local.include_router(T3ChatAdapter().create_router())
    token = base64.b64encode(json.dumps({"cookies":"fake=1", "convex_session_id":"fake"}).encode()).decode()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=local), base_url="http://test") as client:
        response = await client.post("/v1/chat/completions", headers={"Authorization":f"Bearer {token}"}, json={"model":"fake", "messages":[], "stream":stream})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_midstream_failure_is_error_event(httpx_mock):
    class BrokenStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"some response text longer than sentinel"
            raise httpx.ReadError("synthetic failure")
    httpx_mock.add_response(url="https://chatjimmy.ai/api/chat", stream=BrokenStream())
    local = FastAPI()
    local.include_router(ChatJimmyAdapter().create_router())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=local), base_url="http://test") as client:
        response = await client.post("/v1/chat/completions", json={"model":"fake", "messages":[], "stream":True})
    assert response.status_code == 200
    assert '"type":"upstream_error"' in response.text
    assert response.text.endswith("data: [DONE]\n\n")


@pytest.mark.asyncio
async def test_multiple_tool_calls_have_distinct_indices(httpx_mock):
    httpx_mock.add_response(url=httpx.URL(
        "https://t3.chat/api/trpc/auth.getActiveSessions"
        "?batch=1&input=%7B%220%22%3A%7B%22json%22%3A%7B%22includeLocation%22%3Afalse%7D%7D%7D"
    ))
    payload = '<tool_call>{"name":"allowed","arguments":{}}</tool_call>' * 2
    event = json.dumps({"type":"text-delta", "delta":payload})
    httpx_mock.add_response(url="https://t3.chat/api/chat", text=f'data: {event}\n\ndata: {{"type":"finish"}}\n\n')
    request = ChatCompletionRequest(model="fake", messages=[], tools=[{"type":"function", "function":{"name":"allowed"}}])
    response = await T3ChatAdapter().chat_completion(request, {"cookies":"fake=1", "convex_session_id":"fake"})
    assert [call["index"] for call in response.choices[0].message.tool_calls] == [0, 1]


@pytest.mark.asyncio
async def test_untrusted_synthetic_tls_is_rejected(tmp_path, monkeypatch):
    import asyncio
    import ssl
    import subprocess

    from llm_proxy.providers import chatjimmy

    key = tmp_path / "key.pem"
    cert = tmp_path / "cert.pem"
    subprocess.run([
        "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
        "-subj", "/CN=localhost", "-keyout", str(key), "-out", str(cert),
    ], check=True, capture_output=True)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)

    async def respond(reader, writer):
        await reader.readuntil(b"\r\n\r\n")
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nHi")
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(respond, "127.0.0.1", 0, ssl=context)
    port = server.sockets[0].getsockname()[1]
    monkeypatch.setattr(chatjimmy, "CHATJIMMY_CHAT_URL", f"https://127.0.0.1:{port}/api/chat")
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.delenv("SSL_CERT_DIR", raising=False)
    local = FastAPI()
    local.include_router(ChatJimmyAdapter().create_router())
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=local), base_url="http://test") as client:
            response = await client.post("/v1/chat/completions", json={"model":"fake", "messages":[]})
        assert response.status_code == 502
    finally:
        server.close()
        await server.wait_closed()
