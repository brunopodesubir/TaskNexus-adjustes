// frontend/src/features/viewer/ViewerContext.test.jsx
// Fase V-2 (6.7, "Frontend"): regras do ViewerContext — abre sozinho com a
// conversa visível, soma no contador com ela oculta, aba reaproveitada não
// duplica, fechar a última aba fecha o painel, `evicted` tira a aba certa.
import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest';
import { render, cleanup, act } from '@testing-library/react';
import {
  MAX_TABS,
  SURFACE_CHAT,
  ViewerProvider,
  openerLabel,
  surfaceForScope,
  useViewer,
  useViewerHost,
} from './ViewerContext.jsx';

const SK = 'projA::claude';
const SCOPE = `session:${SK}`;

function item(id, extra = {}) {
  return {
    item_id: id,
    session_key: SK,
    project_id: 'projA',
    path: `docs/${id}.md`,
    title: `${id}.md`,
    line: null,
    kind: 'markdown',
    language: 'markdown',
    opened_by: 'agent',
    created_at: 1,
    updated_at: 1,
    ...extra,
  };
}

function jsonResponse(body, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: () => Promise.resolve(body) };
}

let viewer;
function Probe({ host }) {
  viewer = useViewer();
  useViewerHost(host);
  return null;
}

function mount(host) {
  return render(
    <ViewerProvider>
      <Probe host={host} />
    </ViewerProvider>,
  );
}

describe('ViewerContext', () => {
  let originalFetch;
  beforeEach(() => {
    originalFetch = global.fetch;
    global.fetch = vi.fn(() => Promise.resolve(jsonResponse({ items: [] })));
  });
  afterEach(() => {
    cleanup();
    global.fetch = originalFetch;
    viewer = null;
  });

  it('carrega as abas da conversa ativa ao montar', async () => {
    global.fetch = vi.fn(() => Promise.resolve(jsonResponse({ items: [item('a'), item('b', { updated_at: 5 })] })));
    await act(async () => { mount({ activeSessionKey: SK, chatVisible: true }); });
    expect(global.fetch).toHaveBeenCalledWith(`/api/sessions/${SK}/viewer`);
    const scope = viewer.getScope(SCOPE);
    expect(scope.items.map((i) => i.id)).toEqual(['a', 'b']);
    // Sem aba ativa salva: a mais recente.
    expect(scope.activeId).toBe('b');
    expect(scope.loaded).toBe(true);
  });

  it('receiveOpen com a conversa visível abre o painel na aba nova', async () => {
    await act(async () => { mount({ activeSessionKey: SK, chatVisible: true, isMobile: false }); });
    act(() => { viewer.receiveOpen(SK, item('a'), false, []); });
    expect(viewer.getSurface(SURFACE_CHAT)).toEqual({ open: true, fullscreen: false });
    expect(viewer.getScope(SCOPE).activeId).toBe('a');
    expect(viewer.unseen[SCOPE] || 0).toBe(0);
    expect(viewer.toast).toBeNull();
  });

  it('no celular a abertura do agente vai direto para tela cheia', async () => {
    await act(async () => { mount({ activeSessionKey: SK, chatVisible: true, isMobile: true }); });
    act(() => { viewer.receiveOpen(SK, item('a')); });
    expect(viewer.getSurface(SURFACE_CHAT)).toEqual({ open: true, fullscreen: true });
  });

  it('receiveOpen com a conversa oculta soma no contador e mostra o aviso', async () => {
    await act(async () => { mount({ activeSessionKey: 'outro::claude', chatVisible: true }); });
    act(() => { viewer.receiveOpen(SK, item('relatorio')); });
    expect(viewer.getSurface(SURFACE_CHAT).open).toBe(false);
    expect(viewer.unseen[SCOPE]).toBe(1);
    expect(viewer.toast).toMatchObject({ kind: 'open', sessionKey: SK, text: 'claude abriu relatorio.md' });
  });

  it('com a tela de chat fora de vista (Board) também não abre sozinho', async () => {
    await act(async () => { mount({ activeSessionKey: SK, chatVisible: false }); });
    act(() => { viewer.receiveOpen(SK, item('a')); });
    expect(viewer.getSurface(SURFACE_CHAT).open).toBe(false);
    expect(viewer.unseen[SCOPE]).toBe(1);
  });

  it('aba reaproveitada (mesmo item_id) não duplica e fica no mesmo lugar', async () => {
    await act(async () => { mount({ activeSessionKey: SK, chatVisible: true }); });
    act(() => {
      viewer.receiveOpen(SK, item('a'));
      viewer.receiveOpen(SK, item('b'));
      viewer.receiveOpen(SK, item('a', { line: 42, updated_at: 9 }), true, []);
    });
    const scope = viewer.getScope(SCOPE);
    expect(scope.items.map((i) => i.id)).toEqual(['a', 'b']);
    expect(scope.items[0].line).toBe(42);
    expect(scope.activeId).toBe('a');
  });

  it('evicted tira a aba que o backend fechou pelo limite', async () => {
    await act(async () => { mount({ activeSessionKey: SK, chatVisible: true }); });
    act(() => {
      viewer.receiveOpen(SK, item('velha'));
      viewer.receiveOpen(SK, item('nova'), false, ['velha']);
    });
    expect(viewer.getScope(SCOPE).items.map((i) => i.id)).toEqual(['nova']);
  });

  it('fechar a última aba fecha o painel e chama o DELETE', async () => {
    await act(async () => { mount({ activeSessionKey: SK, chatVisible: true }); });
    act(() => { viewer.receiveOpen(SK, item('a')); });
    global.fetch = vi.fn(() => Promise.resolve(jsonResponse({ status: 'closed' })));
    await act(async () => { viewer.closeItem(SCOPE, 'a'); });
    expect(viewer.getScope(SCOPE).items).toEqual([]);
    expect(viewer.getSurface(SURFACE_CHAT).open).toBe(false);
    expect(global.fetch).toHaveBeenCalledWith(`/api/sessions/${SK}/viewer/a`, { method: 'DELETE' });
  });

  it('fechar a aba ativa ativa a vizinha', async () => {
    await act(async () => { mount({ activeSessionKey: SK, chatVisible: true }); });
    act(() => {
      viewer.receiveOpen(SK, item('a'));
      viewer.receiveOpen(SK, item('b'));
      viewer.receiveOpen(SK, item('c'));
      viewer.setActive(SCOPE, 'b');
    });
    global.fetch = vi.fn(() => Promise.resolve(jsonResponse({ status: 'closed' })));
    await act(async () => { viewer.closeItem(SCOPE, 'b'); });
    expect(viewer.getScope(SCOPE).activeId).toBe('c');
    expect(viewer.getSurface(SURFACE_CHAT).open).toBe(true);
  });

  it('openByPath faz o POST e abre a aba; erro vira aviso', async () => {
    await act(async () => { mount({ activeSessionKey: SK, chatVisible: true }); });
    global.fetch = vi.fn(() => Promise.resolve(jsonResponse({
      success: true, item: item('b'), reused: false, delivered: true, evicted: [],
    })));
    let result;
    await act(async () => {
      result = await viewer.openByPath(SCOPE, '../b.md', { relativoA: 'docs/a.md' });
    });
    expect(result.ok).toBe(true);
    expect(viewer.getScope(SCOPE).activeId).toBe('b');
    expect(viewer.getSurface(SURFACE_CHAT).open).toBe(true);

    global.fetch = vi.fn(() => Promise.resolve(jsonResponse({ success: false, error: 'Arquivo protegido (segredos não são exibidos)' }, 403)));
    await act(async () => { result = await viewer.openByPath(SCOPE, '.env'); });
    expect(result).toEqual({ ok: false, error: 'Arquivo protegido (segredos não são exibidos)' });
    expect(viewer.toast).toMatchObject({ kind: 'error', text: 'Arquivo protegido (segredos não são exibidos)' });
  });

  it('abrir o painel do chat zera o contador da conversa ativa', async () => {
    await act(async () => { mount({ activeSessionKey: SK, chatVisible: false }); });
    act(() => { viewer.receiveOpen(SK, item('a')); });
    expect(viewer.unseen[SCOPE]).toBe(1);
    act(() => { viewer.setOpen(SURFACE_CHAT, true); });
    expect(viewer.unseen[SCOPE]).toBe(0);
  });

  it('"Ver" do aviso chama o casco para mostrar a conversa e abre o painel', async () => {
    const onShowSession = vi.fn();
    await act(async () => { mount({ activeSessionKey: 'outro::x', chatVisible: true, onShowSession }); });
    act(() => { viewer.receiveOpen(SK, item('a')); });
    act(() => { viewer.revealToast(viewer.toast); });
    expect(onShowSession).toHaveBeenCalledWith(SK);
    expect(viewer.getSurface(SURFACE_CHAT).open).toBe(true);
    expect(viewer.toast).toBeNull();
  });

  it('escopo local (Fase A) com openItem respeita o limite de abas', async () => {
    await act(async () => { mount({ activeSessionKey: null, chatVisible: false }); });
    act(() => {
      for (let i = 0; i < MAX_TABS + 2; i += 1) {
        viewer.openItem('artefatos', { artifact_id: `af_${i}`, path: `${i}.md`, updated_at: i }, { source: 'artifact' });
      }
    });
    const scope = viewer.getScope('artefatos');
    expect(scope.items).toHaveLength(MAX_TABS);
    expect(scope.items[0]).toMatchObject({ id: 'af_2', source: 'artifact' });
    expect(viewer.getSurface('artefatos').open).toBe(true);
    expect(surfaceForScope('artefatos')).toBe('artefatos');
    expect(surfaceForScope(SCOPE)).toBe(SURFACE_CHAT);
  });

  it('openerLabel usa o agente da session_key ou "Você"', () => {
    expect(openerLabel({ opened_by: 'agent' }, 'p::codex::x1')).toBe('codex');
    expect(openerLabel({ opened_by: 'user' }, 'p::codex')).toBe('Você');
  });
});
