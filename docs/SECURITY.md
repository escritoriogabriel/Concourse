# Segurança

O EditalOS atual é um aplicativo local e single-user. O servidor deve permanecer ligado em `127.0.0.1`; não exponha a porta diretamente à rede nem altere o host para `0.0.0.0` sem adicionar autenticação, autorização por usuário, CSRF, rate limiting, headers de segurança e isolamento de dados.

O banco, os uploads, histórico de estudos e questões podem conter dados pessoais ou conteúdo protegido. Esses arquivos ficam fora do Git e devem ser protegidos pelo sistema operacional. Nunca commit dados de usuário, tokens, chaves ou arquivos de edital.

Ao reportar uma vulnerabilidade, não publique dados do banco. Preserve logs mínimos, remova informações pessoais e descreva passos reproduzíveis.
