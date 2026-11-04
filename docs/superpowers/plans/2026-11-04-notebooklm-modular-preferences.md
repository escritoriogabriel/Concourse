# NotebookLM Modular Preferences Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Dar controle explícito sobre o prompt NotebookLM e sobre a distribuição do JSON importado, sem retirar a prévia/confirmacão auditável.

**Architecture:** O prompt passa a aceitar opções JSON e o frontend abre um formulário modal. A prévia do arquivo passa a exibir preferências de distribuição; o backend aplica essas preferências de forma determinística antes da confirmação e registra as regras utilizadas no snapshot.

**Tech Stack:** FastAPI/Pydantic, SQLite existente, JavaScript/CSS estático, pytest.

**Spec:** Solicitação do usuário de 2026-11-04 sobre modularidade de prompt e preferências de distribuição do cronograma.

## Global Constraints

- O NotebookLM continua sendo o motor de análise dos editais; o EditalOS apenas instrui, valida e organiza.
- O usuário sempre vê uma prévia antes de gravar sessões.
- Sessões concluídas/manuais e eventos de outros imports não podem ser removidos pelo novo fluxo.
- O QConcursos permanece externo; nenhum conteúdo protegido é copiado.

## Review Focus

- Opções ausentes ou inválidas devem usar defaults seguros ou retornar `422`.
- Preferências de matérias não podem gerar matérias inexistentes no arquivo.
- Limite semanal e período do plano devem continuar válidos após redistribuição.
- A confirmação sem preferências deve preservar o comportamento anterior.
- O prompt deve declarar as regras escolhidas de forma legível ao NotebookLM.

## Tasks

1. Backend de opções: schemas, prompt parametrizado, normalização e aplicação determinística das regras do import.
2. Modal de prompt: formulário com carga, dias, estratégia, sequência, matérias fixas, proporções e instruções livres.
3. Prévia do JSON: controles de horas, matérias/dia, prioridades, matérias diárias, sequência e modo de distribuição; confirmação envia as opções.
4. Testes de API, prompt, transformação e regressão visual por strings.
5. Validação completa, documentação breve e commit.
