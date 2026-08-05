---
title: Prompt — continuar o projeto dos Agentes Contábeis
date: 2026-08-05
tags:
  - escon
  - agentes
  - prompt
  - handoff
status: ativo
projeto: Agentes Contabeis Escon
---

# Prompt para a próxima IA

> **Como usar:** copie o bloco abaixo inteiro e cole como primeira mensagem.
> Troque só a linha **TAREFA DE HOJE** pela letra que você quer que ela faça
> (A, B, C, D, E ou F — a lista está em [[Plano - Agentes Lancamentos Contabeis]]).

---

```text
Você vai continuar o projeto "Agentes Contábeis Escon" — um sistema
multiagente que faz a contabilidade dos clientes do escritório por REGRAS,
quase sem gastar token, com o contador revisando tudo antes de importar no
Contmatic.

PROJETO
C:\Users\ander\OneDrive\Desktop\Projetos\Agentes Contabeis Escon

Antes de qualquer comando:
  cd "C:\Users\ander\OneDrive\Desktop\Projetos\Agentes Contabeis Escon"
  $env:PYTHONPATH=".\src"

ANTES DE ESCREVER QUALQUER CÓDIGO, LEIA NESTA ORDEM:
1. docs/HANDOFF.md — retrato do sistema, o que não refazer e as armadilhas
   que já custaram caro. As armadilhas são reais e voltam se ignoradas.
2. docs/ESCON-CONTEXTO.md — memória datada do projeto: o que foi feito, e
   principalmente POR QUE cada decisão foi tomada.
3. O arquivo que a tarefa cita.

Não comece a mexer antes de ler os dois primeiros. Vários defeitos graves
deste projeto nasceram de presumir em vez de conferir.

TAREFA DE HOJE
>>> [ESCREVA AQUI A LETRA E O TÍTULO DA TAREFA, ex.: "B — Leitor do TRCT
oficial"]. O detalhe completo (o que fazer, qual arquivo, como conferir) está
no Obsidian em "Escon/Plano - Agentes Lancamentos Contabeis", seção "Tarefas
para a próxima IA". Se não tiver acesso ao Obsidian, peça ao Anderson o texto
da tarefa antes de começar. <<<

Faça UMA tarefa por vez. Ao terminar, rode o teste que a tarefa indica e
mostre o resultado real — não descreva o que deveria acontecer.

REGRAS INVIOLÁVEIS DO PROJETO
- Nada é importado no Contmatic sem revisão humana. O agente gera o Excel;
  quem importa é a pessoa.
- Conta fora do plano de contas é descartada, inclusive se o modelo sugerir.
- Documento sem data ou sem valor não vira lançamento: vai para pendentes.
- Data e valor NUNCA vêm do modelo, sempre do documento.
- Na dúvida, não decida. Dois títulos com o mesmo valor? Pergunte. Baixar o
  título errado deixa o saldo total certo e a conta do cliente errada — o
  erro que ninguém enxerga no balancete.
- Nunca crie regra contábil por adivinhação: regra errada contamina todos os
  lançamentos seguintes.
- Não recrie a Secretaria nem o Radar: são sistemas separados, em produção.
- Não duplique os parsers (xml_fiscal, ofx_parser, documents, folha_parser).
  O Alexandre consome o que eles estruturam e nunca relê formato.

COMO TRABALHAR
- Teste em documento REAL do Anderson, nunca em exemplo inventado. Todo
  defeito sério deste projeto apareceu em dado real e nenhum apareceria em
  teste sintético.
- Se achar um erro no que já existe, diga com clareza e mostre a evidência,
  mesmo que tenha sido a IA anterior que errou.
- Não invente resultado de execução. Se não rodou, diga que não rodou.
- Comente o código explicando POR QUE, não o que. Os comentários deste
  projeto contam a história dos erros já cometidos — mantenha esse padrão.
- Português do Brasil no código, nos commits e na conversa.

ONDE O SISTEMA RODA
Painel: https://lancamentos.escondigital.com.br (usuário escon)
VPS Hostinger 147.79.86.221, projeto em /opt/escon-agentes, container
escon-agentes. Atualizar depois de mexer: bash scripts/deploy_vps.sh
Detalhes e rollback: docs/VPS.md

ATENÇÃO NA VPS: ela também roda o EsconZap (WhatsApp da Secretaria), o
atendemei e o financeiro. Nunca rode "docker compose down" fora de
/opt/escon-agentes.

AO TERMINAR
1. Rode o teste indicado na tarefa e mostre a saída real.
2. Registre o que fez em docs/ESCON-CONTEXTO.md (uma linha na tabela, com a
   data, o que mudou e por quê — inclusive o que deu errado no caminho).
3. Commit e push. Mensagem em português explicando o motivo, não só o que
   mudou.
4. Se subiu código que o painel usa, rode o deploy e confirme no ar.
5. Diga ao Anderson o que ficou pendente e o que você NÃO conseguiu fazer.
```

---

## Variação: quando for só conferir alguma coisa

Para pedidos pequenos (conferir um número, olhar um cliente), use este bloco
mais curto:

```text
Projeto Agentes Contábeis Escon, em
C:\Users\ander\OneDrive\Desktop\Projetos\Agentes Contabeis Escon
(use $env:PYTHONPATH=".\src" antes dos comandos).

Leia docs/HANDOFF.md antes de responder.

Pedido: [ESCREVA AQUI]

Não altere código sem me avisar. Mostre o resultado real dos comandos que
rodar; não descreva o que deveria acontecer.
```

---

## Comandos úteis para colar junto

```powershell
# lançamentos de uma competência (sem gastar token)
python -m escon_agentes lancamentos -c 07603336000198 -m 2024-09 --forma caixa --sem-llm

# duplicatas e parcelas em aberto do cliente
python -m escon_agentes titulos -c 07603336000198 --vencidos

# folha de pagamento
python -m escon_agentes run "Fabiana, contabilize a folha" -c CLIENTE

# painel local (o da VPS é o mesmo código)
scripts\painel.bat
```

*Criado em 05/08/2026, junto com o [[Handoff - Agentes Contabeis 2026-08-05]].*
