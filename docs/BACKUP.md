# Backup e restauração

O EditalOS grava automaticamente alterações no banco SQLite local configurado por `EDITALOS_DATA` (por padrão, `data/`). Isso inclui progresso, editais importados, matérias, cronograma, sessões, logs de estudo, revisões, erros, eventos, configurações e histórico do NotebookLM.

## Backup pela aplicação

Na tela **Configurações**, use **Baixar backup completo (.zip)**. O arquivo contém o backup JSON de todas as tabelas e, quando existirem, os uploads antigos em `data/uploads/`. O JSON também pode ser baixado pela rota `/api/export/backup.json`.

Para restaurar um backup JSON, ainda na tela **Configurações**, use **Restaurar backup**. A restauração substitui os dados atuais; faça um backup do estado atual antes de confirmar.

## Backup manual local

Feche o EditalOS antes de copiar os dados e preserve o diretório inteiro:

```bash
cp -a data /caminho/seguro/editalos-backup-$(date +%Y%m%d)
```

Para restaurar manualmente, feche a aplicação, substitua o diretório `data/` por uma cópia válida e inicie novamente. Antes de restaurar, mantenha uma cópia do estado atual. O banco deve passar por `PRAGMA quick_check` antes de ser utilizado.

## Hospedagem serverless

A Vercel e ambientes serverless podem apagar o filesystem entre execuções; o `/tmp/editalos` usado nesses ambientes **não é persistente**. Não use a implantação atual com dados reais esperando que SQLite sobreviva a novos deploys ou cold starts. Para produção, conecte a aplicação a um banco externo persistente (Postgres/Turso/Supabase) ou execute-a em uma máquina/volume persistente e configure autenticação antes de expor dados pessoais.

## Fallback no navegador em ambientes temporários

Quando o status indica ambiente serverless, o frontend mantém uma cópia do backup JSON no armazenamento local do navegador e tenta restaurá-la automaticamente se o servidor retornar vazio após um recarregamento. Esse mecanismo é específico do navegador e não substitui um banco persistente: os dados não são compartilhados entre navegadores ou dispositivos. Continue baixando backups ZIP e migre para um banco externo para uso em produção.
