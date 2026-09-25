# TaskNexus no tablet — documentação das melhorias

Documentação de design, UX, arquitetura e implementação para tornar o
TaskNexus confortável no iPad e no celular: **chat no lugar do terminal**,
**visualizador e download de arquivos**, **layout pensado para toque** e
melhorias extras. Escrita para ser lida por você e executada por um agente
Claude, fase por fase.

![Mockup do chat no iPad](img/03-mockup-chat-ipad.svg)

## Partes

| Parte | Conteúdo | HTML |
|-------|----------|------|
| [0 · Visão geral e diagnóstico](00-visao-geral-e-diagnostico.md) | Como o sistema funciona hoje, por que o terminal é ruim no tablet, a solução numa imagem, decisões e alternativas descartadas | [html](00-visao-geral-e-diagnostico.html) |
| [1 · Visualizador de arquivos](01-visualizador-de-arquivos.md) | Ver `.md`, `.html`, código, imagens e PDF; baixar e compartilhar no iPad; API, segurança, componentes, testes | [html](01-visualizador-de-arquivos.html) |
| [2 · Chat conversacional](02-chat-conversacional.md) | Conversa estilo WhatsApp com markdown, código, links e aprovações; protocolo, banco, código, testes | [html](02-chat-conversacional.html) |
| [3 · Layout amigável](03-layout-amigavel.md) | Diagnóstico de UX, tokens, layouts por tamanho de tela, rotas, lista de conversas, atalhos, acessibilidade | [html](03-layout-amigavel.html) |
| [4 · Melhorias adicionais](04-melhorias-adicionais.md) | 14 melhorias com o quê, por quê, como, esforço e prioridade (inclui autenticação obrigatória) | [html](04-melhorias-adicionais.html) |
| [5 · Plano de execução e prompts](05-plano-de-execucao-e-prompts.md) | Fases F0–F4, critérios de pronto e prompts prontos para colar num agente | [html](05-plano-de-execucao-e-prompts.html) |

Versão em página única, com todas as partes e imagens embutidas:
[`documentacao-completa.html`](documentacao-completa.html) (boa para abrir no iPad).

## Imagens

| Arquivo | O que mostra |
|---------|--------------|
| `img/01-arquitetura-atual.svg` | Fluxo atual xterm.js ⇄ WebSocket ⇄ PTY ⇄ CLI e os problemas no tablet |
| `img/02-arquitetura-proposta.svg` | Chat estruturado, adaptadores, ChatStore e API de arquivos |
| `img/03-mockup-chat-ipad.svg` | Chat no iPad deitado |
| `img/04-mockup-arquivos-ipad.svg` | Visualizador de arquivos no iPad |
| `img/05-mockup-celular.svg` | Lista, conversa e arquivo no celular |
| `img/06-sequencia-turno.svg` | Sequência de um turno com streaming e aprovação |
| `img/07-fluxo-visualizador.svg` | Escolha do renderizador e fluxo de download/compartilhar |
| `img/08-navegacao-responsiva.svg` | Três layouts por largura de tela |
| `img/09-roadmap.svg` | Ordem das fases |

## Como regenerar os HTML

Os `.md` são a fonte. Depois de editar, rode:

```bash
pip install markdown pygments pymdown-extensions
python3 docs/melhorias-tablet/build_html.py
```

O script gera um `.html` por parte e o `documentacao-completa.html` com as
imagens embutidas.
