# Painel dos agentes contábeis — roda na VPS, acessível pelo navegador.
#
# Sai do Vercel e vem para cá porque no Vercel só havia conversa: os agentes
# são Python e precisam ler XML, PDF, OneDrive e o Radar. Aqui eles rodam de
# verdade, e o escritório (que é home office) abre pelo navegador de qualquer
# lugar.
FROM python:3.12-slim

# pdfplumber depende do pdfminer, que é Python puro; nada de compilar.
# tzdata para o calendário da folha (5º dia útil) bater com o horário daqui.
ENV PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    TZ=America/Sao_Paulo \
    PYTHONPATH=/app/src

RUN apt-get update \
 && apt-get install -y --no-install-recommends tzdata ca-certificates openssh-client \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependências primeiro: mudar código não reinstala o mundo.
COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN pip install --no-cache-dir .

COPY config/ ./config/
COPY dashboard/ ./dashboard/
COPY scripts/ ./scripts/

# data/ é volume: cadastro de clientes, títulos em aberto e planilhas geradas
# não podem morrer junto com o container.
VOLUME ["/app/data"]
EXPOSE 8787

# host 0.0.0.0 porque quem fala com ele é o Caddy, de outro container.
CMD ["python", "-m", "escon_agentes", "dashboard", "--host", "0.0.0.0", "--port", "8787"]
