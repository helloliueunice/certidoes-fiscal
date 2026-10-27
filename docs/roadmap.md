# MINUTA — Roadmap do projeto Certidões Fiscal

> **MINUTA para discussão com a chefia e a área de TI.** As metas e prazos são estimativas a validar no diagnóstico.

**Indicador principal:** tempo gasto pelo fiscal, **por contrato e por mês**, para reunir e conferir as certidões antes do atesto.
Linha de base a medir na Fase 0. A hipótese inicial é de 20 a 40 minutos por contrato, porque o fiscal passa por 5 a 6 portais, a maioria com captcha.

---

## Fase 0 — Diagnóstico (2 a 3 semanas)
**Entregáveis**
- Inventário dos contratos ativos: número, CNPJ, UF e município da sede, fiscal responsável, se o fornecedor está no SICAF.
- Cronometragem do processo atual em uma amostra de 10 a 20 contratos, por tipo de certidão.
- Levantamento das cláusulas contratuais vigentes sobre a comprovação de regularidade.
- Verificação da elegibilidade do órgão ao Conecta gov.br.

**Indicadores:** tempo médio por contrato (linha de base); % de certidões entregues pela contratada sem cobrança; % de contratadas cadastradas no SICAF.

## Fase 1 — Ganho rápido (1 mês)
**Entregáveis**
- Envio do ofício às contratadas (`docs/oficio_contratadas.md`), transferindo a emissão para a contratada.
- Cláusula padrão para novos contratos (`docs/clausula_contratual.md`), validada pela assessoria jurídica.
- Uso do SICAF como primeira consulta, quando o fornecedor estiver cadastrado.
- Catálogo de portais oficiais (`data/portais.json`) disponível aos fiscais.

**Indicadores:** % de NFs recebidas com o conjunto completo de certidões; redução do tempo por contrato (meta indicativa: -40%).

## Fase 2 — MVP do validador (1 a 2 meses)
**Entregáveis**
- Leitura determinística dos PDFs (`extrator.py`) e checklist com semáforo (`validador.py`).
- Minuta de atesto em PDF (`atesto.py`) e interface Streamlit (`app.py`).
- Testes automatizados com documentos sintéticos.

**Indicadores:** % de PDFs identificados por regras (meta indicativa ≥ 90%); falsos "verdes" iguais a zero na amostra de conferência; tempo de conferência por contrato.

## Fase 3 — Integrações oficiais (2 a 4 meses, depende da adesão)
**Entregáveis**
- Adesão ao Conecta gov.br e uso da API Consulta CND para a certidão federal (`conecta.py`, `docs/adesao_conecta.md`).
- Avaliação de integrações oficiais disponíveis para SICAF/Compras.gov.br.
- Registro do código de controle e da URL de verificação no checklist.

**Indicadores:** % de certidões federais obtidas pela API; disponibilidade da integração; custo por consulta dentro do orçamento.

## Fase 4 — Assistente de portais (1 mês)
**Entregáveis**
- Para cada contratada, a lista dos links oficiais de emissão e verificação (federal, estadual e municipal), gerada a partir do catálogo, com a indicação de captcha.
- **Sem automação de portais com captcha:** o fiscal resolve o captcha. O sistema só organiza os links e recebe os PDFs.
- Rotina de revisão trimestral dos links do catálogo (campo `verificado_em`).

**Indicadores:** % de links do catálogo verificados nos últimos 90 dias; tempo gasto na busca de portais (meta: perto de zero).

## Fase 5 — Piloto e institucionalização (2 a 3 meses)
**Entregáveis**
- Piloto com [__] fiscais e [__] contratos por 2 ciclos mensais.
- Revisão de segurança e LGPD. Os dados ficam no órgão e a IA vem desligada por padrão.
- Ato normativo interno ou orientação da unidade de contratos adotando o fluxo.
- Manual do fiscal e capacitação.

**Indicadores**
| Indicador | Antes (linha de base) | Depois (meta indicativa) |
|---|---|---|
| Tempo por contrato/mês para certidões | [__] min | redução ≥ 70% |
| NFs com certidões completas no recebimento | [__]% | ≥ 90% |
| Atestos devolvidos por falta ou erro de certidão | [__] | redução ≥ 50% |
| Satisfação dos fiscais (pesquisa) | — | ≥ 4/5 |

---

**Princípios em todas as fases:** nunca contornar captcha; usar canais oficiais primeiro; aplicar regras antes de IA; a decisão é sempre do fiscal, e toda saída é minuta.
