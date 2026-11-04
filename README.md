# EditalOS — agenda de estudos integrada ao NotebookLM

EditalOS 3.0 — agenda diária integrada ao NotebookLM. O EditalOS não incorpora nem executa modelos de IA. O NotebookLM analisa os editais e produz um arquivo estruturado; o EditalOS valida o arquivo, apresenta uma prévia e coloca as sessões e os prazos no calendário somente depois da confirmação.

## Fluxo recomendado

1. Abra o [NotebookLM](https://notebooklm.google.com/) e crie um notebook para os concursos que está preparando.
2. Adicione como fontes os editais de abertura, conteúdo programático, anexos, retificações e documentos oficiais relevantes.
3. No EditalOS, abra **Planejamento NotebookLM** e clique em **Gerar prompt personalizado**. O prompt inclui sua carga horária, dias disponíveis e os concursos já cadastrados.
4. Copie o prompt para o NotebookLM e solicite um único arquivo chamado `editalos_plano.json`.
5. Baixe o JSON criado pelo NotebookLM. A disponibilidade da exportação estruturada pode variar conforme a conta e os recursos liberados. Se não houver opção de arquivo JSON, peça para ele exibir o objeto JSON completo, copie o conteúdo e salve em um arquivo `.json` UTF-8.
6. No EditalOS, importe o arquivo, revise cargos, matérias, datas, sessões e avisos e confirme a inclusão.
7. A aplicação abre a agenda na data do primeiro bloco do planejamento importado.

## Formato aceito

- **Preferencial:** JSON UTF-8 (`editalos_plano.json`).
- **Alternativas:** TXT ou Markdown contendo somente o objeto JSON. Cercas Markdown como ```` ```json ```` são removidas quando aparecem no início e no fim do arquivo.
- Limite atual: 8 MB.
- Versão do esquema: `editalos.notebooklm.v1`.

O modelo de referência está em `static/modelo_notebooklm.json`. Ele contém dados fictícios apenas para ilustrar a estrutura; não importe esse modelo como se fosse seu planejamento real. A tela Planejamento NotebookLM também oferece o prompt completo, adaptado às preferências salvas no EditalOS, com opções para copiar ou baixar em TXT. O arquivo `PROMPT_BASE_NOTEBOOKLM.txt` é uma versão genérica de referência; prefira o prompt personalizado gerado dentro do aplicativo.

## Campos importados

- Concursos/cargos: nome, instituição, banca, cargo, prioridade e data de prova.
- Disciplinas: nome, peso, número de questões e lista de tópicos.
- Sessões: data, horário, duração, matéria, tópico, tipo de atividade, objetivo e referência da fonte/página.
- QConcursos: filtros para pesquisa manual (matéria, assunto, banca, órgão, anos, dificuldade, formato e quantidade sugerida). O EditalOS não copia nem extrai questões do QConcursos.
- Eventos: inscrições, isenções, pagamentos, prova, recursos, resultados, convocações e outros prazos.

## Modos de importação

- **Acrescentar ao calendário:** mantém todas as sessões já existentes e adiciona o novo planejamento.
- **Substituir blocos pendentes anteriores do NotebookLM no período:** remove apenas sessões pendentes que foram importadas anteriormente do NotebookLM dentro do período substituído. Sessões concluídas e sessões criadas manualmente são preservadas.

O EditalOS não apaga automaticamente sessões ou eventos. Revise os avisos da prévia antes de confirmar.

## QConcursos

O EditalOS considera que o usuário possui sua própria assinatura. Para as sessões `questoes`, o calendário apresenta os filtros sugeridos e os botões **Copiar filtros** e **Abrir QConcursos**. O botão abre o banco oficial; os filtros são copiados para aplicação manual na sua conta, pois não há integração oficial de preenchimento automático. Não há login compartilhado, raspagem, cópia de enunciados, comentários ou gabaritos.

## Executar no Windows

1. Instale Python 3.11 ou superior.
2. Extraia esta pasta.
3. Execute `iniciar_windows.bat`.
4. O script instala as dependências e abre `http://127.0.0.1:8000`.

O aplicativo funciona localmente e não precisa de API, chave, Ollama ou conexão com NotebookLM para executar. A conexão com o NotebookLM é feita pelo usuário, pelo navegador, por meio do arquivo JSON baixado.

## Segurança e dados locais

Esta distribuição é local e single-user: mantenha o servidor em `127.0.0.1`. Não use `--host 0.0.0.0` nem publique a porta sem implementar autenticação, autorização, CSRF, rate limiting e isolamento por usuário. O banco e os uploads não fazem parte do Git; consulte `docs/SECURITY.md` e `docs/BACKUP.md` para operação segura.

Para criar uma base fictícia de demonstração, execute `python scripts/seed_demo.py`. Para desenvolvimento, instale também `requirements-dev.txt` e execute a suíte de testes e o lint conforme `CONTRIBUTING.md`.

## Dados e atualização

Os dados ficam em `data/editalos.db`, e PDFs antigos, quando existentes, ficam em `data/uploads`. Esses arquivos são locais e ignorados pelo Git. A inicialização da versão atual faz migrações aditivas no SQLite para acrescentar campos de instituição, rastreabilidade de importação e metadados das sessões, sem apagar os registros anteriores.

Antes de substituir arquivos de uma instalação existente, feche o EditalOS e copie a pasta `data` para um local seguro. Para instalar em outra pasta, execute `MIGRAR_DADOS_ANTERIORES_WINDOWS.bat` e informe o caminho da pasta da instalação anterior. O migrador não altera a origem e não sobrescreve um diretório de destino que já contenha dados.

## Calendário

A tela inicial abre diretamente na agenda diária. A faixa semanal permite escolher outro dia; os blocos mostram matéria, tópico, duração, horário, objetivo e conclusão. A agenda pode ser exportada em `.ics`; horários definidos são exportados como eventos com horário local de São Paulo.

## Versão e testes

Esta é a versão 3.0.0, focada na agenda diária e na integração por arquivo com NotebookLM. Não há chamadas para Gemini, OpenAI ou Ollama.

Os testes de integração desta versão cobrem importação JSON, validação de referências, gravação de concursos/matérias/sessões/prazos, substituição controlada, preservação de sessões concluídas e exportação do calendário. Para executar manualmente:

```bat
python -m unittest discover -s tests -v
```

O CI também executa pytest, compilação Python, verificação de sintaxe JavaScript e Ruff. As prévias NotebookLM têm TTL, confirmação de uso único, rastreabilidade por importação e resumo dos itens que serão removidos em uma substituição.

A conferência do conteúdo e das datas no edital original continua sendo responsabilidade do usuário. O NotebookLM pode omitir ou interpretar incorretamente informações; a prévia do EditalOS existe para revisão antes da gravação.
