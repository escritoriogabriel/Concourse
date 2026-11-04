"""Copia dados de uma instalação anterior sem alterar ou apagar a origem."""
from __future__ import annotations
import sqlite3
import shutil
import sys
from pathlib import Path

DEST = Path(__file__).resolve().parent / 'data'

def migrate(folder: str):
    path=Path(folder.strip().strip('"').strip("'")).expanduser().resolve()
    origin=path if path.name.lower()=='data' else path / 'data'
    if not origin.is_dir() or not (origin / 'editalos.db').is_file():
        raise ValueError('Banco anterior não encontrado. Selecione a pasta EditalOS antiga ou sua subpasta data.')
    if origin.resolve()==DEST.resolve():
        raise ValueError('Esta já é a pasta de dados desta instalação; não é necessário migrar.')
    if DEST.exists() and any(DEST.iterdir()):
        raise ValueError('A nova pasta data já contém arquivos. Migração cancelada para evitar sobrescrever dados.')
    con=sqlite3.connect(f'file:{(origin / "editalos.db").as_posix()}?mode=ro',uri=True)
    try:
        if con.execute('PRAGMA quick_check').fetchone()[0]!='ok':
            raise ValueError('O banco anterior precisa ser verificado antes da migração.')
    finally:
        con.close()
    # O diretório deve estar vazio. Nunca altera a instalação de origem.
    if DEST.exists():DEST.rmdir()
    try:
        shutil.copytree(origin,DEST)
    except Exception:
        if DEST.exists():shutil.rmtree(DEST)
        raise
    print(f'Dados preservados: {origin}')
    print(f'Nova cópia criada: {DEST}')
    print('O banco e os PDFs originais não foram modificados.')

if __name__=='__main__':
    print('Feche as duas versões do EditalOS antes da migração.')
    folder=sys.argv[1] if len(sys.argv)>1 else input('Cole o caminho da pasta EditalOS antiga: ').strip()
    try:
        migrate(folder)
    except Exception as exc:
        print('Migração cancelada:',exc)
        sys.exit(1)
