# Corrigir falha de inicialização FastAPI na Vercel — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fazer a aplicação `atto` inicializar corretamente na Vercel e responder à rota raiz sem `FUNCTION_INVOCATION_FAILED`.

**Architecture:** Declarar as dependências de produção no `pyproject.toml`, que é a fonte usada pelo build detectado da Vercel. Separar o armazenamento local persistente do armazenamento efêmero de funções serverless, usando `/tmp/editalos` apenas quando a aplicação estiver rodando na Vercel. Validar importação, rota raiz e suíte existente antes do push.

**Tech Stack:** Python 3.12, FastAPI, Uvicorn, SQLite, Vercel Python runtime, pytest.

**Spec:** Incidente de produção `FUNCTION_INVOCATION_FAILED` no deployment `dpl_s1RbsG9ju5yNSjGpes3HDQf5sJHr`.

## Global Constraints

- Manter execução local usando `data/` por padrão.
- Declarar no `pyproject.toml` as mesmas dependências necessárias em `requirements.txt`.
- Não incluir segredos nem alterar dados locais no Git.
- O comportamento da API e dos testes existentes deve permanecer compatível.

## Review Focus

- Importação do módulo sem `python-multipart` instalado: deve ser resolvida pela declaração de dependências do projeto.
- Inicialização em filesystem somente leitura da Vercel: deve usar diretório gravável e efêmero.
- Rota `/` e `/static/*`: devem continuar servindo os arquivos do frontend.
- Suíte existente: não deve sofrer regressões.

---

### Task 1: Corrigir metadados de dependências e armazenamento serverless

**Files:**
- Modify: `pyproject.toml`
- Modify: `app.py:24-30`
- Test: `tests/test_deployment_smoke.py`

**Interfaces:**
- `pyproject.toml` passa a declarar `fastapi`, `uvicorn`, `python-multipart`, `tzdata` e `httpx` em `project.dependencies`.
- `app.py` mantém `EDITALOS_DATA` como override explícito; em Vercel, sem override, usa `/tmp/editalos`; fora da Vercel, usa `ROOT / data`.

- [ ] Adicionar metadados mínimos `[project]` e dependências de produção ao `pyproject.toml`.
- [ ] Alterar o default de `DATA_DIR` para selecionar `/tmp/editalos` quando `VERCEL=1`, preservando `EDITALOS_DATA` e o comportamento local.
- [ ] Adicionar smoke tests que validem `GET /`, resposta estática e que o default serverless não aponta para a raiz somente leitura.
- [ ] Rodar o teste novo isoladamente e confirmar PASS.

### Task 2: Validar aplicação e qualidade

**Files:**
- Review: alterações da Task 1

- [ ] Instalar dependências a partir de `pyproject.toml` em ambiente limpo.
- [ ] Rodar `pytest -q`.
- [ ] Rodar `python -m unittest discover -s tests -v`.
- [ ] Rodar `python -m compileall -q .`, `node --check static/app.js` e `ruff check tests scripts`.
- [ ] Iniciar a aplicação local com `VERCEL=1`, testar `/` e encerrar o processo.

### Task 3: Commit, push e verificar novo deployment

**Files:**
- Git commit no branch `main`

- [ ] Revisar diff e confirmar que não há banco, uploads, segredos ou artefatos temporários.
- [ ] Criar commit com mensagem `fix: declare vercel fastapi runtime dependencies`.
- [ ] Fazer push para `origin/main`.
- [ ] Consultar o novo deployment na Vercel e aguardar estado `READY` ou diagnosticar logs se falhar.
- [ ] Reproduzir a URL de produção e confirmar HTTP 200 na raiz.
