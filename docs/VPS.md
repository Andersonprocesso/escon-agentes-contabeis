# O painel na VPS

**https://lancamentos.escondigital.com.br** — usuário `escon`.

Saiu do Vercel porque lá só havia conversa: os agentes são Python e precisam
ler XML, PDF, OneDrive e o Radar. No Vercel o chat respondia *como se* tivesse
lançado, sem lançar nada. Aqui rodam de verdade, e o escritório (home office)
abre pelo navegador de qualquer lugar.

## Onde fica

VPS **147.79.86.221** (`srv653140`), a mesma do EsconZap. Assumiu o lugar do
sistema antigo de lançamentos, que ficava em `/docker/lancamentos`.

| | |
|---|---|
| Projeto | `/opt/escon-agentes` |
| Container | `escon-agentes` |
| Compose | `docker-compose.vps.yml` |
| HTTPS | Traefik + Let's Encrypt (já existia) |
| Senha | Traefik `basicauth`, hash em `PAINEL_BASICAUTH` no `.env` |
| Dados | volume `escon-agentes_agentes_data` → `/app/data` |
| Login Microsoft | volume `escon-agentes_agentes_msal` |

**Nesta VPS também rodam** o EsconZap (WhatsApp da Secretaria), o atendemei e
o financeiro. Nunca usar `docker compose down` fora de `/opt/escon-agentes`.

## Atualizar

```bash
bash scripts/deploy_vps.sh
```

Envia o código, reconstrói e sobe. `data/` e `.env` não são enviados: os dados
vivem no volume e os segredos já estão no servidor.

## Trocar a senha do painel

O `$` do hash precisa ser dobrado, senão o compose engole na interpolação:

```bash
ssh -i ~/.ssh/radar_escon_vps root@147.79.86.221
cd /opt/escon-agentes
HASH=$(htpasswd -nbB escon 'NOVA_SENHA')
grep -v '^PAINEL_BASICAUTH=' .env > .env.tmp
printf 'PAINEL_BASICAUTH=%s\n' "$(printf '%s' "$HASH" | sed 's/\$/\$\$/g')" >> .env.tmp
mv .env.tmp .env
docker compose -f docker-compose.vps.yml up -d --force-recreate
```

## Armadilha que custou tempo: Traefik com config velha em cache

Depois de trocar o container do domínio, o Traefik continuou devolvendo **401
mesmo sem middleware nenhum** — resposta de uma configuração antiga que ele não
soltou. Nenhum log, nenhuma pista; o container respondia 200 quando chamado
direto pelo IP.

```bash
docker restart traefik-qsuz-traefik-1   # ~2s de indisponibilidade nos outros sites
```

Se o roteamento parecer impossível, **é isso**. Antes de investigar a fundo,
reinicie o Traefik e teste de novo.

Segundo detalhe: gerar o hash com `$` numa linha `ssh "..."` faz o shell
**remoto** expandir `$2y`, `$05`. Gerar sempre no servidor, com heredoc
`<<'REMOTO'` (aspas simples).

## Primeira vez / depois de recriar o volume

```bash
# cadastro de clientes e demais dados do PC para o servidor
tar czf - data/clients data/web data/certificados_digitais.json data/titulos \
  | ssh -i ~/.ssh/radar_escon_vps root@147.79.86.221 "cat > /tmp/dados.tgz"
ssh -i ~/.ssh/radar_escon_vps root@147.79.86.221 \
  "docker cp /tmp/dados.tgz escon-agentes:/tmp/ && \
   docker exec escon-agentes bash -c 'cd /app && tar xzf /tmp/dados.tgz'"
```

O login da Microsoft (Raquel/OneDrive) é por device code e precisa ser feito
uma vez de dentro do container.

## O que muda em relação ao PC

- **Pasta do PC não existe mais** no fechamento de competência. Use OneDrive ou
  o Drive do Radar — os dois funcionam de qualquer lugar.
- **Sem chave de LLM configurada** (`llm_provider: none`). Não atrapalha o
  Alexandre nem a Fabiana, que rodam por regra e não gastam token; o que fica
  indisponível é o chat com o Max e o palpite para documento desconhecido.

## Rollback

O sistema antigo não foi apagado: container parado, imagem e pasta intactos.

```bash
cd /opt/escon-agentes && docker compose -f docker-compose.vps.yml down
cd /docker/lancamentos && docker compose start
docker restart traefik-qsuz-traefik-1
```

Backups em `/opt/backups/` (código do sistema antigo; os dados dele estavam no
Supabase, fora da VPS).
