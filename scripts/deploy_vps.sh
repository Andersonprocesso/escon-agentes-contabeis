#!/usr/bin/env bash
# Sobe o painel dos agentes na VPS da Hostinger.
#
# Rodar do PC:  bash scripts/deploy_vps.sh
# Precisa da chave ~/.ssh/radar_escon_vps.
#
# Esta VPS roda também o EsconZap (WhatsApp da Secretaria), o atendemei e o
# financeiro: o script mexe só no projeto `escon-agentes`, nunca em `docker
# compose down` global.
set -euo pipefail

VPS="${VPS:-root@147.79.86.221}"
CHAVE="${CHAVE:-$HOME/.ssh/radar_escon_vps}"
DESTINO="/opt/escon-agentes"
SSH=(ssh -i "$CHAVE" -o StrictHostKeyChecking=no "$VPS")

echo "==> enviando o projeto para $DESTINO"
"${SSH[@]}" "mkdir -p $DESTINO"
# --delete mantém o servidor igual ao repositório; data/ e segredos ficam de
# fora (data é volume do Docker; .env vai separado, por scp, uma vez só).
tar czf - \
  --exclude='.git' --exclude='data' --exclude='__pycache__' \
  --exclude='.msal_cache' --exclude='*.pyc' --exclude='.venv' \
  Dockerfile docker-compose.vps.yml pyproject.toml README.md \
  src config dashboard scripts api \
| "${SSH[@]}" "tar xzf - -C $DESTINO"

echo "==> conferindo o .env no servidor"
if ! "${SSH[@]}" "test -f $DESTINO/.env"; then
  echo "!! Falta o $DESTINO/.env — envie uma vez com:"
  echo "   scp -i $CHAVE .env $VPS:$DESTINO/.env"
  exit 1
fi

# Chave SSH do Radar (MinIO em 76.x) dentro do container — sem ela o Drive
# (Radar) falha e o fechamento dependia só do OneDrive. A chave NÃO vai no
# tar do código; copia-se do PC (mesma usada neste deploy).
echo "==> chave SSH do Radar em $DESTINO/secrets/"
"${SSH[@]}" "mkdir -p $DESTINO/secrets && chmod 700 $DESTINO/secrets"
if [[ -f "$CHAVE" ]]; then
  scp -i "$CHAVE" -o StrictHostKeyChecking=no "$CHAVE" "$VPS:$DESTINO/secrets/radar_escon_vps"
  "${SSH[@]}" "chmod 600 $DESTINO/secrets/radar_escon_vps"
else
  echo "!! Chave $CHAVE não encontrada no PC — Radar no container pode falhar."
  # compose exige o arquivo do volume bind; cria vazio só para o mount não quebrar
  "${SSH[@]}" "test -f $DESTINO/secrets/radar_escon_vps || : > $DESTINO/secrets/radar_escon_vps"
fi

echo "==> build e sobe"
"${SSH[@]}" "cd $DESTINO && docker compose -f docker-compose.vps.yml up -d --build"

echo "==> estado"
"${SSH[@]}" "docker ps --filter name=escon-agentes --format '{{.Names}} {{.Status}}'"
"${SSH[@]}" "docker exec escon-agentes curl -fsS localhost:8787/api/health || echo 'painel ainda subindo'"

echo
echo "Pronto. Falta uma vez só, na primeira subida:"
echo "  1) login da Microsoft:  ssh -i $CHAVE $VPS 'docker exec -it escon-agentes python -m escon_agentes graph-login'"
echo "  2) PAINEL_BASICAUTH no .env do servidor (ver docs/VPS.md)"
