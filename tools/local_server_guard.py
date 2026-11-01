class LocalOriginGuard:
    """Reject foreign Host on every request, and foreign Origin on state changes."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        server = scope.get("server")
        port = server[1] if server and len(server) > 1 else None
        allowed = {f"127.0.0.1:{port}", f"localhost:{port}"}
        headers = [(k.lower(), v.decode("latin-1")) for k, v in scope.get("headers", [])]
        hosts = [v for k, v in headers if k == b"host"]
        origins = [v for k, v in headers if k == b"origin"]
        ok = type(port) is int and 1 <= port <= 65535 and len(hosts) == 1 and hosts[0] in allowed
        if ok and (scope["type"] == "websocket" or scope["method"] not in ("GET", "HEAD")):
            ok = len(origins) == 1 and origins[0] == f"http://{hosts[0]}"
        if ok:
            await self.app(scope, receive, send)
        elif scope["type"] == "websocket":
            await receive()
            await send({"type": "websocket.close", "code": 1008})
        else:
            await send({"type": "http.response.start", "status": 403,
                        "headers": [(b"content-type", b"text/plain")]})
            await send({"type": "http.response.body", "body": b"Forbidden"})
