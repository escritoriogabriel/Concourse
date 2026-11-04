# EditalOS Hardening and Product Improvements Implementation Plan

**Goal:** Aplicar as correções essenciais do code review, tornando o fluxo NotebookLM reversível, seguro para uso local, testável e preparado para evolução.

**Architecture:** Manter FastAPI/SQLite no MVP, mas reforçar fronteiras no próprio `app.py` com validações e invariantes, adicionar rastreabilidade por importação e separar dados locais do código. Evoluções maiores de modularização ficam documentadas e serão iniciadas pela extração de serviços puros apenas quando houver testes cobrindo o comportamento.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic, SQLite, pytest, unittest, JavaScript estático, GitHub Actions.

**Spec:** `/home/ubuntu/Concourse_code_review.md`

## Global Constraints

- Preservar o funcionamento local em `127.0.0.1`.
- Não executar IA nem coletar/copi ar conteúdo proprietário do QConcursos.
- Não apagar sessões concluídas nem sessões manuais em substituições.
- Não versionar banco SQLite, uploads, caches ou dados pessoais.
- Toda mudança de regra de negócio deve ter teste automatizado.

## Review Focus

- Substituição com dois imports NotebookLM sobrepostos não pode apagar eventos do import errado.
- Alocação semanal nunca pode exceder a disponibilidade configurada.
- Prévia deve expirar e não pode ser confirmada duas vezes.
- IDs e referências inválidas devem retornar 404/422, não sucesso ou erro 500.
- O repositório não deve conter banco de dados de usuário nem artefatos gerados.

---

### Task 1: Higienização do repositório e documentação operacional

**Files:**
- Create: `.gitignore`, `.env.example`, `CONTRIBUTING.md`, `docs/SECURITY.md`, `docs/BACKUP.md`, `scripts/seed_demo.py`, `.github/workflows/ci.yml`
- Modify: `README.md`, `requirements.txt`
- Remove from Git index: `data/editalos.db`

- [ ] Add ignore rules for SQLite, uploads, caches, environment files and generated artifacts.
- [ ] Add seed script that creates a demo database without committing user data.
- [ ] Document local-only security boundary, backup, restore and future web deployment requirements.
- [ ] Add dev dependencies and CI commands for pytest, compileall and Node syntax checks.
- [ ] Verify a clean clone can initialize and run tests without the committed database.

### Task 2: Integridade e rastreabilidade das importações

**Files:**
- Modify: `app.py`, `tests/test_notebooklm.py`

- [ ] Add `notebooklm_import_id` to `events` through additive migration.
- [ ] Persist imported events with the batch ID.
- [ ] In replace mode, compute only pending NotebookLM import IDs in the selected period and delete their sessions/events; preserve manual, completed and unrelated imports.
- [ ] Add expiring preview entries with a bounded in-memory store, cleanup on access and atomic consume via lock.
- [ ] Return a deletion summary in preview (`will_delete_sessions`, `will_delete_events`) for explicit UI confirmation.
- [ ] Add tests for overlapping imports, expiration, double-confirmation and deletion summary.

### Task 3: API validation and scheduling invariants

**Files:**
- Modify: `app.py`, `tests/test_notebooklm.py`

- [ ] Validate strategy values, date/time strings, exam references and foreign IDs consistently.
- [ ] Return 404 for update endpoints when the target does not exist.
- [ ] Ensure `allocate()` respects effective weekly capacity even when minimum subject allocations exceed it.
- [ ] Prevent `schedule_week` from dereferencing a missing current plan.
- [ ] Add tests for invalid IDs, invalid strategy, low weekly capacity and calendar conflicts.

### Task 4: Frontend safety and destructive-operation UX

**Files:**
- Modify: `static/app.js`, `static/index.html`, `static/styles.css`

- [ ] Show sessions/events that will be removed in the NotebookLM preview.
- [ ] Require an explicit confirmation state for replacement when deletions are nonzero.
- [ ] Add accessible live region for errors/toasts and improve labels/focus semantics.
- [ ] Ensure all dynamic destructive-operation copy is escaped and readable on mobile.

### Task 5: Test quality, tooling and final verification

**Files:**
- Create: `tests/test_security_and_validation.py`, `pyproject.toml`
- Modify: `tests/test_notebooklm.py`, `README.md`

- [ ] Add API and XSS regression tests.
- [ ] Add formatting/lint configuration and run it.
- [ ] Run pytest, unittest, compileall and Node syntax checks.
- [ ] Review Git diff, verify no database/cache artifacts are staged, then commit on `main` with the required attribution trailer.
