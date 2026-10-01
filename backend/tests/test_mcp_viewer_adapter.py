"""Testa mcp_viewer_adapter.py como SUBPROCESSO Python — nunca o CLI do
agente. Dirige o protocolo JSON-RPC por linha no stdio exatamente como o
`claude`/`codex` fariam, e aponta o POST do adaptador para um http.server
local efêmero em vez do backend (via ESCRITORIO_HOOK_VIEWER_OPEN_URL). Mesmo
estilo de test_mcp_card_adapter.py.
"""
from __future__ import annotations

import http.server
import json
import os
import queue as queue_mod
import subprocess
import sys
import threading

ADAPTER_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "app", "mcp_viewer_adapter.py"
)
HOOK_PATH = "/api/hooks/viewer/open"

# Texto EXATO da Parte 6, seção 6.4.6.
EXPECTED_DESCRIPTION = (
    "Abre um arquivo do projeto no visualizador do TaskNexus, na tela do usuário "
    "(inclusive no iPad), numa aba nova. Use SEMPRE que criar ou alterar um arquivo "
    "que o usuário deva ler ou conferir (relatórios .html, documentos .md, planos, "
    "diagramas, trechos de código importantes) e sempre que o usuário pedir para ver, "
    "abrir ou mostrar um arquivo. O usuário não consegue clicar em links no terminal, "
    "então esta é a forma de mostrar arquivos a ele. Markdown aparece renderizado, "
    "HTML aparece como página, código aparece com destaque de sintaxe, e o usuário "
    "pode baixar o arquivo."
)
EXPECTED_SCHEMA = {
    "type": "object",
    "properties": {
        "caminho": {"type": "string", "description": "Caminho do arquivo, relativo à raiz do projeto (ex.: docs/plano.md) ou absoluto dentro do projeto."},
        "titulo": {"type": "string", "description": "Opcional. Nome curto da aba. Padrão: nome do arquivo."},
        "linha": {"type": "integer", "description": "Opcional. Linha para rolar e destacar (arquivos de código)."},
    },
    "required": ["caminho"],
}


class _Handler(http.server.BaseHTTPRequestHandler):
    received: "queue_mod.Queue" = queue_mod.Queue()
    response: dict = {}
    status: int = 200

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        self.__class__.received.put({"path": self.path, "body": json.loads(body) if body else None})
        payload = json.dumps(self.__class__.response).encode("utf-8")
        self.send_response(self.__class__.status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt, *args):
        pass


class _Server:
    def __init__(self, response, status=200):
        _Handler.received = queue_mod.Queue()
        _Handler.response = response
        _Handler.status = status
        self.httpd = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.url = "http://127.0.0.1:{0}{1}".format(self.httpd.server_address[1], HOOK_PATH)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()


def _env(url, session_id="sid-viewer"):
    env = os.environ.copy()
    env["ESCRITORIO_HOOK_VIEWER_OPEN_URL"] = url
    env["ESCRITORIO_CLAUDE_SESSION_ID"] = session_id
    return env


class _Adapter:
    """Subprocesso do adaptador falando JSON-RPC por linha. Em modo binário
    (`raw=True`) escreve UTF-8 cru no stdin, sem passar pela codificação de
    texto do Python deste lado — é o que reproduz o bug de mojibake."""

    def __init__(self, env, raw=False):
        self.raw = raw
        self.proc = subprocess.Popen(
            [sys.executable, ADAPTER_PATH],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=env, text=not raw, bufsize=0 if raw else 1,
        )
        self._lines: "queue_mod.Queue" = queue_mod.Queue()
        threading.Thread(target=self._read_loop, daemon=True).start()

    def _read_loop(self):
        for line in self.proc.stdout:
            self._lines.put(line)

    def write_line(self, text):
        data = text + "\n"
        self.proc.stdin.write(data.encode("utf-8") if self.raw else data)
        self.proc.stdin.flush()

    def send(self, message):
        self.write_line(json.dumps(message, ensure_ascii=False))

    def recv(self, timeout=3.0):
        line = self._lines.get(timeout=timeout)
        return json.loads(line.decode("utf-8") if self.raw else line)

    def close(self):
        try:
            self.proc.stdin.close()
        except Exception:
            pass
        try:
            self.proc.wait(timeout=2.0)
        except Exception:
            self.proc.kill()


def _adapter(url, session_id="sid-viewer"):
    return _Adapter(_env(url, session_id))


def _call(adapter, arguments, request_id=1, timeout=5.0):
    adapter.send({
        "jsonrpc": "2.0", "id": request_id, "method": "tools/call",
        "params": {"name": "abrir_no_visualizador", "arguments": arguments},
    })
    return adapter.recv(timeout=timeout)["result"]["content"][0]["text"]


_ITEM = {"item_id": "vw_x", "path": "docs/relatorio.html"}


def test_initialize_announces_the_viewer_server():
    adapter = _adapter("http://127.0.0.1:1" + HOOK_PATH)
    try:
        adapter.send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                      "params": {"protocolVersion": "2025-06-18"}})
        result = adapter.recv()["result"]
        assert result["protocolVersion"] == "2025-06-18"
        assert result["serverInfo"]["name"] == "escritorio-visualizador"
        assert result["capabilities"] == {"tools": {}}
        # Notificação não tem resposta; o próximo pedido ainda é atendido.
        adapter.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        adapter.send({"jsonrpc": "2.0", "id": 2, "method": "ping-inexistente"})
        assert adapter.recv()["error"]["code"] == -32601
    finally:
        adapter.close()


def test_tools_list_has_exactly_the_specified_tool():
    adapter = _adapter("http://127.0.0.1:1" + HOOK_PATH)
    try:
        adapter.send({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        tools = adapter.recv()["result"]["tools"]
        assert len(tools) == 1
        tool = tools[0]
        assert tool["name"] == "abrir_no_visualizador"
        assert tool["description"] == EXPECTED_DESCRIPTION
        assert tool["inputSchema"] == EXPECTED_SCHEMA
    finally:
        adapter.close()


def test_call_success_new_tab_posts_and_reports_delivered():
    response = {"success": True, "item": _ITEM, "reused": False, "delivered": True, "evicted": []}
    with _Server(response) as server:
        adapter = _adapter(server.url, session_id="sess-123")
        try:
            text = _call(adapter, {"caminho": "docs/relatorio.html", "titulo": "Relatório", "linha": 12})
            assert text == "Aberto no visualizador do usuário: docs/relatorio.html (aba nova)."
            received = _Handler.received.get(timeout=3.0)
            assert received["path"] == HOOK_PATH
            assert received["body"] == {
                "claude_session_id": "sess-123",
                "caminho": "docs/relatorio.html",
                "titulo": "Relatório",
                "linha": 12,
            }
        finally:
            adapter.close()


def test_optional_arguments_are_omitted_when_absent():
    response = {"success": True, "item": _ITEM, "reused": False, "delivered": True}
    with _Server(response) as server:
        adapter = _adapter(server.url)
        try:
            _call(adapter, {"caminho": "README.md"})
            body = _Handler.received.get(timeout=3.0)["body"]
            assert body == {"claude_session_id": "sid-viewer", "caminho": "README.md"}
        finally:
            adapter.close()


def test_call_success_reused_tab():
    response = {"success": True, "item": _ITEM, "reused": True, "delivered": True}
    with _Server(response) as server:
        adapter = _adapter(server.url)
        try:
            assert _call(adapter, {"caminho": "docs/relatorio.html"}) == (
                "Aberto no visualizador do usuário: docs/relatorio.html "
                "(aba já existia, foi atualizada)."
            )
        finally:
            adapter.close()


def test_call_success_with_screen_closed():
    response = {"success": True, "item": _ITEM, "reused": False, "delivered": False}
    with _Server(response) as server:
        adapter = _adapter(server.url)
        try:
            assert _call(adapter, {"caminho": "docs/relatorio.html"}) == (
                "Registrado no visualizador: docs/relatorio.html. "
                "O usuário verá ao abrir o TaskNexus."
            )
        finally:
            adapter.close()


def test_backend_error_is_passed_through_verbatim():
    response = {"success": False, "error": "Arquivo protegido (segredos não são exibidos)"}
    with _Server(response) as server:
        adapter = _adapter(server.url)
        try:
            assert _call(adapter, {"caminho": ".env"}) == "Arquivo protegido (segredos não são exibidos)"
        finally:
            adapter.close()


def test_error_body_of_a_403_is_still_read():
    response = {"success": False, "error": "O hook do visualizador só aceita chamadas da própria máquina."}
    with _Server(response, status=403) as server:
        adapter = _adapter(server.url)
        try:
            assert "própria máquina" in _call(adapter, {"caminho": "README.md"})
        finally:
            adapter.close()


def test_backend_down_does_not_hang_and_returns_generic_text():
    adapter = _adapter("http://127.0.0.1:1" + HOOK_PATH)  # porta 1: conexão recusada
    try:
        assert _call(adapter, {"caminho": "README.md"}, timeout=8.0) == (
            "Não foi possível falar com o TaskNexus agora."
        )
    finally:
        adapter.close()


def test_unknown_tool_and_garbage_lines_do_not_kill_the_adapter():
    adapter = _adapter("http://127.0.0.1:1" + HOOK_PATH)
    try:
        adapter.write_line("isto nao e json")
        adapter.write_line("[1,2]")
        adapter.send({"jsonrpc": "2.0", "id": 9, "method": "tools/call",
                      "params": {"name": "outra_tool", "arguments": {}}})
        text = adapter.recv()["result"]["content"][0]["text"]
        assert text == "Tool desconhecida: outra_tool"
    finally:
        adapter.close()


def test_accented_path_survives_hostile_windows_encoding():
    """Mesma regressão de mojibake coberta no adaptador de cards: caminho com
    acento escrito em UTF-8 cru no stdin, com o processo filho em cp1252."""
    response = {"success": True, "item": {"path": "docs/relatório.md"}, "reused": False, "delivered": True}
    with _Server(response) as server:
        env = _env(server.url)
        env.pop("PYTHONUTF8", None)
        env["PYTHONIOENCODING"] = "cp1252"
        adapter = _Adapter(env, raw=True)
        try:
            adapter.send({
                "jsonrpc": "2.0", "id": 1, "method": "tools/call",
                "params": {"name": "abrir_no_visualizador",
                           "arguments": {"caminho": "docs/relatório.md"}},
            })
            text = adapter.recv(timeout=5.0)["result"]["content"][0]["text"]
            assert text == "Aberto no visualizador do usuário: docs/relatório.md (aba nova)."
            assert _Handler.received.get(timeout=3.0)["body"]["caminho"] == "docs/relatório.md"
        finally:
            adapter.close()
