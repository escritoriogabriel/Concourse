# Contribuição

Instale as dependências com `python -m pip install -r requirements.txt -r requirements-dev.txt`. Antes de abrir uma alteração, execute `pytest -q`, `python -m unittest discover -s tests -v`, `python -m compileall -q .` e `node --check static/app.js`.

Toda mudança de regra de negócio deve incluir um teste. Não inclua `data/editalos.db`, uploads, caches, credenciais ou dados pessoais no commit.
