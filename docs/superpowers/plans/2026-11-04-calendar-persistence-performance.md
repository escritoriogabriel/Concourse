# Persistência, Performance e Calendário Interativo — Plano de Implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Corrigir conclusões que retornam Not Found, reduzir chamadas lentas de persistência e transformar a tela inicial em um calendário mensal com tags e detalhes do dia.

**Architecture:** Manter o SQLite como fonte principal quando persistente e usar o backup do navegador apenas em ambiente temporário. Cachear o status do armazenamento no frontend e sincronizar um único backup após refresh/mutação. Substituir a faixa semanal da agenda por uma grade mensal e abrir os detalhes do dia no modal existente.

**Tech Stack:** FastAPI, SQLite, JavaScript vanilla, CSS existente, pytest.

**Spec:** Solicitação do usuário em 2026-11-04 — corrigir Not Found ao concluir, acelerar carregamento, calendário inicial com tags e modal de detalhes, melhorar layout e investigar erros.

## Global Constraints

- Não remover a compatibilidade com importação NotebookLM, backups JSON/ZIP ou restauração.
- Conclusão de item inexistente deve ser tratada de forma idempotente no frontend, sem toast vermelho falso.
- A agenda deve continuar acessível em telas pequenas.
- Toda mudança deve ter teste automatizado ou verificação de sintaxe correspondente.

## Review Focus

- IDs obsoletos de sessão/evento após restauração serverless.
- Corrida entre refresh, backup local e restauração.
- Dias sem tarefas e tarefas longas no calendário mensal.
- Tags com texto dinâmico escapado contra XSS.
- Alterações de fuso/data ao navegar entre meses.

### Task 1: Conclusão resiliente

**Files:** `static/app.js`, `tests/test_security_and_validation.py`

- [ ] Testar que a ação de conclusão atualiza a tela sem toast vermelho quando a resposta 404 indica item já removido.
- [ ] Implementar refresh/reconciliação antes de exibir erro definitivo e mensagens informativas para item ausente.
- [ ] Validar sintaxe e testes.

### Task 2: Performance e persistência

**Files:** `static/app.js`, `docs/BACKUP.md`, `tests/test_security_and_validation.py`

- [ ] Testar que o frontend cacheia o status serverless e mantém as funções de backup.
- [ ] Remover exportação síncrona redundante de cada `post`/`patch`; sincronizar após o refresh, com status cacheado.
- [ ] Manter recuperação automática quando o bootstrap serverless retornar vazio.
- [ ] Validar carga inicial e testes.

### Task 3: Calendário mensal e modal

**Files:** `static/app.js`, `static/features.css`, `tests/test_security_and_validation.py`

- [ ] Testar presença da grade mensal, tags de atividades e ação de detalhes do dia.
- [ ] Implementar navegação de mês, células com sessões/eventos, tags de matérias/atividades e modal detalhado ao clicar no dia.
- [ ] Adicionar layout responsivo e estados vazios sem alterar os dados.
- [ ] Validar sintaxe, suíte e diff.

### Task 4: Publicação

- [ ] Executar `pytest -q`, `node --check static/app.js`, `python3 -m compileall -q .`, `ruff check tests scripts` e `git diff --check`.
- [ ] Commitar na `main` e publicar no GitHub.
