# Backup e restauração

Feche o EditalOS antes de copiar os dados. Faça backup do diretório configurado em `EDITALOS_DATA` (por padrão, `data/`), incluindo `editalos.db` e `uploads/`.

Exemplo:

```bash
cp -a data /caminho/seguro/editalos-backup-$(date +%Y%m%d)
```

Para restaurar, feche a aplicação, substitua o diretório `data/` por uma cópia válida e inicie novamente. Antes de restaurar, mantenha uma cópia do estado atual. O banco deve passar por `PRAGMA quick_check` antes de ser utilizado.
