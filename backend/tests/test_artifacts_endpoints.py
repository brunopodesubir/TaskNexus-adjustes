"""Testes de integração das rotas da aba Artefatos (Fase A, Parte 7 seções
7.4.3 e 7.7): criação pelo usuário, lista com filtros, edição, remoção,
conteúdo e arquivos crus (via file_serving), candidatos e importação, o hook
`publicar_artefato` e a publicação automática do `abrir_no_visualizador`.

Mesmo padrão de fixture de test_viewer_endpoints.py (reload de app.main com
env vars apontando para um tmp_path isolado)."""
from __future__ import annotations

import os
import sys
import time
import uuid as uuid_mod
from unittest.mock import patch

import pytest

PROJ = "podesubir/site"
SK = PROJ + "::claude"


def _fake_pdf(pages: int) -> bytes:
    body = b"%PDF-1.4\n" + b"2 0 obj << /Type /Pages /Count %d >> endobj\n" % pages
    for index in range(pages):
        body += b"%d 0 obj << /Type /Page /Parent 2 0 R >> endobj\n" % (index + 3)
    return body + b"%%EOF\n"


@pytest.fixture
def projects(tmp_path):
    site = tmp_path / "podesubir" / "site"
    (site / ".claude").mkdir(parents=True)
    (site / "docs").mkdir()
    (site / "README.md").write_text("# Site institucional\n\nPágina da empresa.\n", encoding="utf-8")
    (site / "docs" / "relatorio.html").write_text(
        "<html><head><title>Relatório de testes</title>"
        '<meta name="description" content="58 passaram, 2 falharam.">'
        '<link rel="stylesheet" href="style.css"></head><body><p>x</p></body></html>',
        encoding="utf-8",
    )
    (site / "docs" / "style.css").write_text("body { color: red }", encoding="utf-8")
    (site / "docs" / "manual.pdf").write_bytes(_fake_pdf(3))
    (site / "app.py").write_text("print('oi')\n", encoding="utf-8")
    (site / ".env").write_text("TOKEN=segredo", encoding="utf-8")
    (site / ".env.md").write_text("# segredo", encoding="utf-8")
    # Terceiro nível: podesubir/site/blog é um projeto dentro do site.
    blog = site / "blog"
    (blog / ".claude").mkdir(parents=True)
    (blog / "post.md").write_text("# Post do blog\n\nTexto.\n", encoding="utf-8")
    outro = tmp_path / "outro" / "app"
    (outro / ".claude").mkdir(parents=True)
    (outro / "notas.md").write_text("# Notas\n", encoding="utf-8")
    return tmp_path


@pytest.fixture
def client(tmp_path, projects, monkeypatch):
    monkeypatch.delenv("HOOK_CALLBACK_BASE_URL", raising=False)
    with patch.dict("os.environ", {
        "PROJECTS_ROOT": str(tmp_path),
        "SESSIONS_DB": str(tmp_path / "sessions.db"),
        "BOARD_UPLOADS_ROOT": str(tmp_path / "board_uploads"),
        "CLAUDE_CONFIG_PATH": str(tmp_path / "claude.json"),
        "CLEANUP_DELAY": "0.1",
    }):
        import importlib
        from fastapi.testclient import TestClient
        import app.main as main_mod
        importlib.reload(main_mod)
        from app.main import app
        with TestClient(app) as c:
            yield c


def _create(client, caminho, project_id=PROJ, **body):
    return client.post("/api/artifacts", json={"project_id": project_id, "caminho": caminho, **body})


def _list(client, **params):
    r = client.get("/api/artifacts", params=params)
    assert r.status_code == 200, r.text
    return r.json()["artifacts"]


def _paths(artifacts):
    return sorted(a["project_id"] + ":" + a["path"] for a in artifacts)


# -- POST /api/artifacts ------------------------------------------------------


def test_create_by_user_returns_201_with_the_documented_shape(client):
    r = _create(client, "docs/relatorio.html")
    assert r.status_code == 201
    artifact = r.json()
    assert set(artifact) == {
        "artifact_id", "project_id", "cliente_id", "path", "kind", "title",
        "description", "excerpt", "size", "mtime", "exists", "created_by",
        "agent_label", "created_at", "updated_at",
    }
    assert artifact["artifact_id"].startswith("af_")
    assert artifact["project_id"] == PROJ
    assert artifact["cliente_id"] == "podesubir"
    assert artifact["path"] == "docs/relatorio.html"
    assert artifact["kind"] == "html"
    assert artifact["title"] == "Relatório de testes"
    assert artifact["excerpt"] == "58 passaram, 2 falharam."
    assert artifact["description"] is None
    assert artifact["exists"] is True
    assert artifact["size"] > 0
    assert artifact["created_by"] == "user"
    assert artifact["agent_label"] is None


def test_create_twice_keeps_the_id_and_returns_200(client):
    first = _create(client, "README.md").json()
    r = _create(client, "./README.md", titulo="Leia-me", descricao="Porta de entrada.")
    assert r.status_code == 200
    second = r.json()
    assert second["artifact_id"] == first["artifact_id"]
    assert second["title"] == "Leia-me"
    assert second["description"] == "Porta de entrada."


def test_create_pdf_has_page_count_and_absolute_path_is_stored_relative(client, projects):
    r = _create(client, str(projects / "podesubir" / "site" / "docs" / "manual.pdf"))
    artifact = r.json()
    assert artifact["path"] == "docs/manual.pdf"
    assert artifact["kind"] == "pdf"
    assert artifact["title"] == "manual.pdf"
    assert artifact["excerpt"] == "3 páginas"


@pytest.mark.parametrize("caminho,status,error", [
    ("app.py", 400, "Artefatos aceitam .md, .html e .pdf"),
    ("docs/style.css", 400, "Artefatos aceitam .md, .html e .pdf"),
    (".env", 400, "Artefatos aceitam .md, .html e .pdf"),
    (".env.md", 403, "Arquivo protegido (segredos não são exibidos)"),
    ("../../outro/app/notas.md", 403, "Caminho fora do projeto"),
    ("nao-existe.md", 404, "Arquivo não encontrado: nao-existe.md"),
    ("", 400, "Informe o caminho do arquivo."),
])
def test_create_refusals_are_readable(client, caminho, status, error):
    r = _create(client, caminho)
    assert r.status_code == status
    assert r.json() == {"success": False, "error": error}


def test_create_with_unknown_project_or_bad_body(client):
    r = _create(client, "README.md", project_id="nao/existe")
    assert r.status_code == 404
    assert r.json() == {"success": False, "error": "Projeto não encontrado: nao/existe"}
    r = client.post("/api/artifacts", json={"caminho": "README.md"})
    assert r.status_code == 400
    assert r.json()["error"] == "Informe o projeto (project_id)."
    r = client.post("/api/artifacts", content=b"isto nao e json",
                    headers={"Content-Type": "application/json"})
    assert r.status_code == 400
    assert r.json() == {"success": False, "error": "Corpo da requisição inválido."}


# -- GET /api/artifacts -------------------------------------------------------


def _seed(client):
    _create(client, "README.md")
    _create(client, "docs/relatorio.html", descricao="Saída do pytest")
    _create(client, "docs/manual.pdf")
    _create(client, "post.md", project_id="podesubir/site/blog")
    _create(client, "notas.md", project_id="outro/app")


def test_list_without_filters_returns_everything(client):
    _seed(client)
    assert len(_list(client)) == 5


def test_list_by_cliente(client):
    _seed(client)
    assert _paths(_list(client, cliente_id="outro")) == ["outro/app:notas.md"]
    assert len(_list(client, cliente_id="podesubir")) == 4


def test_list_by_projeto_includes_the_subtree_of_3_levels(client):
    _seed(client)
    assert _paths(_list(client, projeto_id="podesubir/site")) == [
        "podesubir/site/blog:post.md",
        "podesubir/site:README.md",
        "podesubir/site:docs/manual.pdf",
        "podesubir/site:docs/relatorio.html",
    ]
    assert _paths(_list(client, projeto_id="podesubir/site/blog")) == ["podesubir/site/blog:post.md"]
    # O prefixo leva a barra: "podesubir/si" não é pai de "podesubir/site".
    assert _list(client, projeto_id="podesubir/si") == []


def test_list_by_tipo(client):
    _seed(client)
    assert _paths(_list(client, tipo="pdf")) == ["podesubir/site:docs/manual.pdf"]
    assert len(_list(client, tipo="md")) == 3
    assert len(_list(client, tipo="MARKDOWN")) == 3
    assert len(_list(client, tipo="todos")) == 5
    r = client.get("/api/artifacts", params={"tipo": "docx"})
    assert r.status_code == 400
    assert r.json() == {"success": False, "error": "Tipo inválido. Use md, html ou pdf."}


def test_list_search_in_title_path_and_description_ignoring_accents(client):
    _seed(client)
    assert _paths(_list(client, q="relatorio")) == ["podesubir/site:docs/relatorio.html"]
    assert _paths(_list(client, q="PYTEST")) == ["podesubir/site:docs/relatorio.html"]
    assert _paths(_list(client, q="manual.pdf")) == ["podesubir/site:docs/manual.pdf"]
    assert _list(client, q="nada-disso") == []


def test_list_order_by_name_and_by_recent(client, projects):
    _seed(client)
    by_name = [a["title"] for a in _list(client, ordem="nome")]
    assert by_name == sorted(by_name, key=str.casefold)
    # Alterar o arquivo no disco o leva ao topo de "recentes" (mtime atual).
    readme = projects / "podesubir" / "site" / "README.md"
    future = time.time() + 60
    os.utime(readme, (future, future))
    recent = _list(client)
    assert recent[0]["path"] == "README.md"
    assert recent[0]["mtime"] == pytest.approx(future)
    r = client.get("/api/artifacts", params={"ordem": "tamanho"})
    assert r.status_code == 400


def test_list_reports_exists_false_when_the_file_is_gone(client, projects):
    created = _create(client, "README.md").json()
    (projects / "podesubir" / "site" / "README.md").unlink()
    [artifact] = _list(client, projeto_id=PROJ)
    assert artifact["artifact_id"] == created["artifact_id"]
    assert artifact["exists"] is False
    # Sem o arquivo, ficam os números da última publicação.
    assert artifact["mtime"] == created["mtime"]
    assert client.get(f"/api/artifacts/{created['artifact_id']}").json()["exists"] is False


# -- GET / PATCH / DELETE /api/artifacts/{id} ---------------------------------


def test_get_one_and_unknown_is_404(client):
    created = _create(client, "README.md").json()
    r = client.get(f"/api/artifacts/{created['artifact_id']}")
    assert r.status_code == 200
    assert r.json() == created
    r = client.get("/api/artifacts/af_nao_existe")
    assert r.status_code == 404
    assert r.json() == {"success": False, "error": "Artefato não encontrado"}


def test_patch_renames_and_edits_description(client):
    artifact_id = _create(client, "README.md").json()["artifact_id"]
    r = client.patch(f"/api/artifacts/{artifact_id}", json={"titulo": "Leia-me", "descricao": "Entrada"})
    assert r.status_code == 200
    assert r.json()["title"] == "Leia-me"
    assert r.json()["description"] == "Entrada"
    r = client.patch(f"/api/artifacts/{artifact_id}", json={"descricao": None})
    assert r.json()["description"] is None
    assert r.json()["title"] == "Leia-me"
    # Republicar sem título não desfaz o nome dado pelo usuário.
    assert _create(client, "README.md").json()["title"] == "Leia-me"


def test_patch_refusals(client):
    artifact_id = _create(client, "README.md").json()["artifact_id"]
    r = client.patch(f"/api/artifacts/{artifact_id}", json={"titulo": "   "})
    assert r.status_code == 400
    assert r.json() == {"success": False, "error": "O título não pode ficar vazio."}
    r = client.patch("/api/artifacts/af_nao_existe", json={"titulo": "x"})
    assert r.status_code == 404


def test_delete_removes_from_the_list_but_not_the_file(client, projects):
    artifact_id = _create(client, "README.md").json()["artifact_id"]
    r = client.delete(f"/api/artifacts/{artifact_id}")
    assert r.status_code == 200
    assert r.json() == {"status": "removed"}
    assert (projects / "podesubir" / "site" / "README.md").is_file()
    assert _list(client) == []
    assert client.delete(f"/api/artifacts/{artifact_id}").status_code == 404


# -- content e f/ -------------------------------------------------------------


def test_content_of_markdown(client):
    artifact_id = _create(client, "README.md").json()["artifact_id"]
    r = client.get(f"/api/artifacts/{artifact_id}/content")
    assert r.status_code == 200
    body = r.json()
    assert body["artifact_id"] == artifact_id
    assert body["path"] == "README.md"
    assert body["kind"] == "markdown"
    assert body["is_text"] is True
    assert body["text"].startswith("# Site institucional")


def test_content_of_deleted_file_and_unknown_artifact_are_404(client, projects):
    artifact_id = _create(client, "README.md").json()["artifact_id"]
    (projects / "podesubir" / "site" / "README.md").unlink()
    r = client.get(f"/api/artifacts/{artifact_id}/content")
    assert r.status_code == 404
    assert r.json() == {"detail": "Arquivo não encontrado: README.md"}
    r = client.get("/api/artifacts/af_nao_existe/content")
    assert r.status_code == 404
    assert r.json() == {"detail": "Artefato não encontrado"}


def test_f_serves_html_and_neighbors_with_the_viewer_headers(client):
    artifact_id = _create(client, "docs/relatorio.html").json()["artifact_id"]
    r = client.get(f"/api/artifacts/{artifact_id}/f/docs/relatorio.html")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert "sandbox" in r.headers["content-security-policy"]
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["cache-control"] == "no-store"
    css = client.get(f"/api/artifacts/{artifact_id}/f/docs/style.css")
    assert css.status_code == 200
    assert css.headers["content-type"].startswith("text/css")


def test_f_pdf_download_and_refusals(client):
    artifact_id = _create(client, "docs/manual.pdf").json()["artifact_id"]
    r = client.get(f"/api/artifacts/{artifact_id}/f/docs/manual.pdf", params={"download": 1})
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert "content-security-policy" not in r.headers
    assert r.headers["content-disposition"].startswith('attachment; filename="manual.pdf"')
    assert client.get(f"/api/artifacts/{artifact_id}/f/.env").status_code == 403
    assert client.get(f"/api/artifacts/{artifact_id}/f/..%2F..%2F..%2Foutro/app/notas.md").status_code in (403, 404)
    assert client.get("/api/artifacts/af_nao_existe/f/README.md").status_code == 404


# -- Candidatos e importação --------------------------------------------------


def _candidates(client, project_id=PROJ):
    r = client.get(f"/api/projects/{project_id}/artifact-candidates")
    assert r.status_code == 200, r.text
    return r.json()


def test_candidates_list_md_html_pdf_and_skip_ignored_folders(client, projects):
    site = projects / "podesubir" / "site"
    for folder in ("node_modules/pkg", ".git", ".venv-win/lib", "dist", "build", ".escritorio", "__pycache__"):
        (site / folder).mkdir(parents=True, exist_ok=True)
        (site / folder / "lixo.md").write_text("# lixo", encoding="utf-8")
    (site / "docs" / "antigo.htm").write_text("<title>Antigo</title>", encoding="utf-8")
    (site / "docs" / "id_rsa.md").write_text("chave", encoding="utf-8")
    body = _candidates(client)
    assert body["truncated"] is False
    paths = [c["path"] for c in body["candidates"]]
    # Sem pastas ignoradas, sem denylist (.env.md, id_rsa*), sem o projeto
    # filho (blog/post.md é candidato de podesubir/site/blog), sem .py/.css.
    assert paths == ["README.md", "docs/antigo.htm", "docs/manual.pdf", "docs/relatorio.html"]
    first = body["candidates"][0]
    assert set(first) == {"path", "kind", "size", "mtime"}
    assert first["kind"] == "markdown"
    kinds = {c["path"]: c["kind"] for c in body["candidates"]}
    assert kinds["docs/antigo.htm"] == "html"
    assert kinds["docs/manual.pdf"] == "pdf"
    assert [c["path"] for c in _candidates(client, "podesubir/site/blog")["candidates"]] == ["post.md"]


def test_candidates_skip_already_published(client):
    _create(client, "README.md")
    paths = [c["path"] for c in _candidates(client)["candidates"]]
    assert "README.md" not in paths
    assert "docs/relatorio.html" in paths


def test_candidates_are_cut_at_300(client, projects):
    many = projects / "podesubir" / "site" / "muitos"
    many.mkdir()
    for index in range(305):
        (many / "n{0:03d}.md".format(index)).write_text("x", encoding="utf-8")
    body = _candidates(client)
    assert body["truncated"] is True
    assert len(body["candidates"]) == 300


def test_candidates_of_unknown_project_is_404(client):
    r = client.get("/api/projects/nao/existe/artifact-candidates")
    assert r.status_code == 404
    assert r.json() == {"success": False, "error": "Projeto não encontrado: nao/existe"}


def test_import_creates_artifacts_and_reports_errors_per_path(client):
    _create(client, "README.md")
    r = client.post("/api/artifacts/import", json={
        "project_id": PROJ,
        "caminhos": ["README.md", "docs/relatorio.html", "docs/manual.pdf", "app.py", "sumiu.md", 7],
    })
    assert r.status_code == 200
    body = r.json()
    # README.md já existia: entra em artifacts, mas não conta como criado.
    assert body["created"] == 2
    assert sorted(a["path"] for a in body["artifacts"]) == ["README.md", "docs/manual.pdf", "docs/relatorio.html"]
    assert all(a["created_by"] == "user" for a in body["artifacts"])
    assert body["errors"] == [
        {"caminho": "app.py", "erro": "Artefatos aceitam .md, .html e .pdf"},
        {"caminho": "sumiu.md", "erro": "Arquivo não encontrado: sumiu.md"},
        {"caminho": "7", "erro": "Informe o caminho do arquivo."},
    ]
    assert len(_list(client, projeto_id=PROJ)) == 3
    assert _candidates(client)["candidates"] == []


def test_import_refusals(client):
    r = client.post("/api/artifacts/import", json={"project_id": PROJ, "caminhos": []})
    assert r.status_code == 400
    assert r.json() == {"success": False, "error": "Informe a lista de caminhos (caminhos)."}
    r = client.post("/api/artifacts/import", json={"project_id": PROJ, "caminhos": ["a.md"] * 301})
    assert r.status_code == 400
    r = client.post("/api/artifacts/import", json={"project_id": "nao/existe", "caminhos": ["a.md"]})
    assert r.status_code == 404
