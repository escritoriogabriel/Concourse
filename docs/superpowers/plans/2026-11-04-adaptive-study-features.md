# Adaptive Study Features Implementation Plan

**Goal:** Transformar o EditalOS de uma agenda importada em um ciclo adaptativo de planejamento, execução, desempenho e replanejamento.

**Architecture:** Manter o MVP local com FastAPI/SQLite e adicionar entidades pequenas e rastreáveis: logs reais de estudo, erros, revisões, resumos diários e snapshots de importação. As regras de cálculo serão funções determinísticas no backend e o frontend continuará estático, com renderização escapada.

**Tech Stack:** FastAPI, SQLite, Pydantic, JavaScript/CSS estático, pytest.

## Escopo desta entrega

Serão implementados: modo foco e conclusão detalhada; registro de estudo realizado; dashboard de aderência; mapa de cobertura; caderno de erros; revisão espaçada; análise semântica da importação; comparação de versões/imports; replanejamento de pendências; filtros de agenda; janelas de disponibilidade básicas; exportação CSV/JSON; resumo diário; e navegação/UX para essas áreas.

Ficam como infraestrutura futura, não simulada no MVP local: login multiusuário, sincronização bidirecional com Google Calendar/Outlook, notificações push, app mobile nativo e integração automática com banco proprietário de questões.

## Invariantes

- Sessão planejada e execução real são registros distintos.
- Concluir uma sessão não apaga seu histórico.
- Replanejamento nunca altera sessões concluídas.
- Dados importados do edital continuam vinculados à fonte e ao import.
- Nenhum conteúdo do QConcursos é copiado ou automatizado.
- Toda nova regra terá teste.

## Tarefas

1. Schema/migrações: `study_logs`, `error_notebook`, `spaced_reviews`, snapshots e disponibilidade.
2. API: logs, erros, revisões, dashboard, cobertura, resumo diário, replanejamento, comparação, exportação.
3. Importação: validação semântica e relatório de diferenças.
4. Frontend: dashboard, modo foco, cobertura, erros, revisão e preview comparativo.
5. Testes, documentação, CI e commit.
