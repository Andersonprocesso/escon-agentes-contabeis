---
title: Handoff — Agentes Contábeis Escon
date: 2026-08-05
tags:
  - escon
  - agentes
  - handoff
  - contabilidade
status: ativo
projeto: Agentes Contabeis Escon
substitui: "[[Handoff - Agentes Contabeis 2026-08-01]]"
---

# Handoff — onde o projeto está

> **Para a IA que vai continuar:** este arquivo é auto-suficiente. Leia ele
> inteiro antes de mexer em qualquer coisa. As duas seções que mais importam
> são **"O que NÃO refazer"** e **"Armadilhas que já custaram caro"** — quase
> todo defeito grave do projeto veio de repetir uma delas.

## Em uma frase

Sistema multiagente que faz a contabilidade dos clientes da Escon **por regras,
sem gastar token**, com o contador revisando tudo antes de importar no
Contmatic. Está rodando na VPS, acessível pelo navegador.

## Como acessar

| | |
|---|---|
| Painel | https://lancamentos.escondigital.com.br |
| Usuário | `escon` (senha com o Anderson) |
| Servidor | VPS Hostinger `147.79.86.221` (`srv653140`) |
| Projeto no servidor | `/opt/escon-agentes` |
| Container | `escon-agentes` |
| Repositório | github.com/Andersonprocesso/escon-agentes-contabeis |
| Projeto no PC | `C:\Users\ander\OneDrive\Desktop\Projetos\Agentes Contabeis Escon` |

Atualizar o servidor depois de mexer no código:

```bash
bash scripts/deploy_vps.sh
```

Detalhes de infraestrutura, rollback e troca de senha: `docs/VPS.md` no repo.

⚠️ **Nesta VPS também rodam o EsconZap (WhatsApp da Secretaria), o atendemei e
o financeiro.** Nunca rodar `docker compose down` fora de `/opt/escon-agentes`.

## Os agentes que funcionam hoje

| Agente | Faz | Validado em dado real |
|---|---|---|
| **Alexandre** | Lançamentos contábeis por regra | Alumax set/2024: 113 docs → 51 lançamentos, **0 token** · out/2024: 284 docs → 265 lançamentos |
| **Fabiana** | Folha: provisão, pagamento, férias/13º, Anexo IV | Jorge ago/2020: 27 funcionários, 223 lançamentos |
| **Xavier** | Lê XML e classifica CFOP | 268 XMLs, 0 CFOP fora da tabela |
| **John** | Concilia OFX e aponta baixa que falta lançar | testado com título real |
| **Pedro** | Cadastro (Acessórias → local → Radar) | 108 clientes |
| **Fernando** | Certificados digitais A1 | 4 vencidos achados |
| **Raquel** | E-mail: rascunho, anexos ao Drive | caixa contato@ |

## O fluxo que o Anderson usa

1. Abre o painel, seção **Contabilidade atrasada**
2. Escolhe cliente + competência, cola o caminho da pasta no OneDrive
3. Deixa em **Caixa** (padrão para atrasadas — é o que mais aparece)
4. Roda. Os lançamentos aparecem **em tela**, em três abas:
   - **Lançados** — o que foi contabilizado
   - **Aguardando você** — o que o agente não soube
   - **Sem lançamento** — DANFE, protocolo, declaração, folha (existem, estão certos, não viram lançamento)
5. Clica num pendente → o painel mostra o documento e **sugere o que o
   identifica** → escolhe as contas numa lista → **vira regra** e a competência
   é reprocessada
6. Só então baixa a planilha do Contmatic

## Como o sistema quase não gasta token

As regras saíram do **razão real da Escon** (2.090 lançamentos de 2020 e 2022,
lidos por `tools/razao_parser.py`). O dia a dia repete os mesmos pares de
conta, então o agente compara texto e já sabe débito, crédito e histórico.

O modelo só entra quando **nenhuma regra reconhece** — e mesmo aí, uma pergunta
por documento, com a resposta validada contra o plano de contas.

Em todos os fechamentos reais até agora: **0 chamadas de LLM.**

## Arquivos que importam

| Arquivo | O que é |
|---|---|
| `config/regras_lancamento.yaml` | As regras vindas do razão |
| `config/regras_aprendidas.yaml` | O que o contador ensinou pelo painel (vence as genéricas) |
| `config/plano_contas.yaml` | Contas e aliases — **já teve 22 códigos errados, conferir sempre** |
| `src/escon_agentes/agents/alexandre.py` | O agente de lançamentos |
| `src/escon_agentes/agents/fabiana.py` | Folha de pagamento |
| `src/escon_agentes/tools/cfop.py` | Decide se a nota gera lançamento |
| `src/escon_agentes/tools/titulos.py` | Razão auxiliar: duplicatas em aberto |
| `src/escon_agentes/tools/aprendizado.py` | Regras ensinadas no painel |
| `src/escon_agentes/tools/recorrentes.py` | Despesa de contrato, provisionada sem documento |
| `src/escon_agentes/workflows/fechamento.py` | O fechamento de uma competência |
| `dashboard/static/index.html` | O painel inteiro (uma página só) |
| `docs/ESCON-CONTEXTO.md` | **Memória do projeto — leia antes de decidir qualquer coisa** |

## O que NÃO refazer

- **Secretaria e Radar** — sistemas separados, já em produção. Não recriar.
- **Os parsers** (`xml_fiscal`, `ofx_parser`, `documents`, `folha_parser`) —
  são testados. O Alexandre consome o que eles estruturam e **nunca relê
  formato**. Duplicar leitura significa dois códigos para o mesmo formato
  divergindo com o tempo.
- **A ordem das regras** em `regras_lancamento.yaml` — vence a primeira que
  casa. A regra de duplicata em atraso precisa vir antes da comum, senão os
  juros se perdem. A de compra a prazo antes da compra à vista.
- **A separação dos dois logins Microsoft** — `mail` (contato@) e `arquivos`
  (anderson@) têm caches separados e guarda de identidade. Misturar já fez a
  Raquel operar na caixa errada.

## Armadilhas que já custaram caro

Cada uma destas foi um defeito real, encontrado testando em documento de
verdade. Nenhuma apareceria em teste sintético.

1. **O DANFE em PDF virava lançamento junto com o XML da mesma nota.** 43
   lançamentos duplicados em um único mês. Cada um, isolado, parecia correto —
   só o conjunto estava errado.
2. **O CFOP é escrito por quem EMITIU a nota.** A nota de compra recebida vem
   com `5102` (venda, na ótica do fornecedor). Ler o primeiro dígito faria
   toda compra virar venda.
3. **`5929`/`1929` é NF-e que só documenta cupom já lançado.** Lançar dobra a
   receita — numa loja com 200 cupons/mês isso é enorme.
4. **Valores 100× maiores:** XML usa ponto decimal (`20.70`), PDF brasileiro
   usa vírgula. Tratar todo ponto como milhar virava R$ 2.070,00.
5. **Duplicata vencendo no dia da emissão é à vista**, não a prazo. A simples
   existência do bloco `<dup>` não basta.
6. **Modelo Pydantic dentro de `create_app()`** com `from __future__ import
   annotations` → FastAPI devolve 422. Aconteceu **três vezes**. Todos os
   modelos agora ficam no nível do módulo.
7. **Traefik com configuração velha em cache** devolvia 401 sem log nenhum,
   enquanto o container respondia 200 no IP direto. `docker restart` no
   Traefik resolve.
8. **Recriar o container durante um login por device code** mata o processo
   antes de gravar o token.
9. **Gerar hash de senha dentro de `ssh "..."`** faz o shell remoto expandir
   `$2y`/`$05`. Gerar no servidor, com heredoc `<<'FIM'`.

## Regras invioláveis

- **Nada é importado no Contmatic sem revisão humana.** O agente gera o Excel;
  quem importa é a pessoa.
- **Conta fora do plano é descartada** — inclusive se o modelo sugerir.
- **Sem data ou sem valor, não lança** — vai para pendentes.
- **Data e valor nunca vêm do LLM**, sempre do documento.
- **Na dúvida, não decide.** Dois títulos com o mesmo valor: o agente pergunta.
  Baixar o título errado deixa o saldo total certo e a conta do cliente errada
   — o erro que ninguém enxerga no balancete.
- **Nunca criar regra por adivinhação.** Regra errada contamina todos os
  lançamentos seguintes.

## Pendências, em ordem

Ver `[[Plano - Agentes Lancamentos Contabeis]]` para o detalhe de cada uma.

1. **Conferir 4 códigos de conta deduzidos** (bloqueia usar em produção):
   `2141103` serviços/sindicato a pagar · `3221108` CPP patronal ·
   `3221109` aviso prévio · `3221110` multa FGTS
2. **Leitor do TRCT oficial** — não usar a Fabiana para rescisão até existir
3. **Marcar a Jorge como Anexo IV** (`anexo_simples: 4` + RAT da GFIP)
4. **Ampliar as regras** rodando as competências atrasadas e olhando os pendentes
5. **Token do Contmatic para o Contábil** (libera plano de contas e envio direto)
6. **John baixando títulos com extrato real** (adiado a pedido do Anderson)

## Como saber se está funcionando

O resumo do Alexandre traz a linha de economia:

```
Economia: 265 de 265 lançamento(s) sem consultar o modelo.
```

Se a proporção do modelo subir, faltam regras — olhe os pendentes.

---

*Substitui o handoff de 2026-08-01. A memória completa e datada do projeto
está em `docs/ESCON-CONTEXTO.md` no repositório.*
