# Certidões Fiscal — contexto do projeto

Ferramenta para fiscais e gestores de contratos públicos conferirem, todo mês, as certidões
de regularidade das contratadas antes do atesto da nota fiscal.

## Problema
O fiscal acessa vários portais (Receita/PGFN, Caixa, TST, SEFAZ, prefeitura), quase todos com
captcha, para cada contratada, todo mês. É tempo tirado das funções originais.

## Princípios inegociáveis
1. **Nunca contornar captcha.** Sem serviços de quebra de captcha, sem robôs que simulam usuário
   em portais protegidos. Onde houver captcha, o humano resolve.
2. **Canais oficiais primeiro:** API Consulta CND (Conecta gov.br) para a certidão federal;
   SICAF para federal/FGTS/trabalhista quando o órgão usa Compras.gov.br.
3. **Regras antes de IA.** A leitura dos PDFs é feita por regras determinísticas e auditáveis.
   A IA (LLM) só entra como fallback opcional, marcada como `metodo="ia"`, e o resultado sempre
   pede conferência humana (semáforo amarelo no mínimo).
4. **A decisão é do fiscal.** O sistema aponta, o servidor atesta. Toda saída é "minuta".
5. **Dados no órgão.** Nada de enviar PDFs a serviços externos sem configuração explícita
   (a chamada de IA é desligada por padrão e exige `CERTIDOES_IA=1` + chave).

## Arquitetura
```
certidoes/
  models.py     contrato de dados (Certidao, Contrato, Semaforo...) — fonte da verdade
  extrator.py   PDF -> texto -> Certidao (regras por tipo de certidão)
  ia.py         fallback LLM opcional para PDFs que as regras não identificam
  validador.py  Contrato + [Certidao] -> ResultadoValidacao (checklist com semáforo)
  atesto.py     ResultadoValidacao -> PDF (checklist + minuta de atesto)
  portais.py    catálogo de portais oficiais (data/portais.json)
  conecta.py    cliente da API Consulta CND (Conecta gov.br) — exige adesão do órgão
web/            interface web no padrão gov.br DS (FastAPI) — deploy no Railway
app.py          interface Streamlit (legada)
tests/          testes com PDFs sintéticos marcados "DOCUMENTO DE TESTE"
docs/           roteiros e minutas (cláusula contratual, ofício, adesão Conecta)
```

## Regras de negócio
- Aceitas: negativa, positiva com efeitos de negativa, CRF regular.
- Recusadas: positiva, vencida, CNPJ diferente do contrato.
- Alerta (amarelo): vence em até 15 dias (configurável), extraída por IA, CNPJ ausente no PDF,
  ou certidão de filial (raiz do CNPJ igual, ordem diferente) quando o contrato é com a matriz.
- Certidão federal vale para matriz e filiais (abrangência pela raiz do CNPJ).
- Sempre conferir autenticidade pelo código de controle no site do emissor.

## Convenções
- Python 3.11+, código e mensagens em português, tipagem nos módulos.
- CNPJ sempre armazenado só com dígitos; formatar só na exibição.
- Datas como `datetime.date`; texto de PDF em formato brasileiro (dd/mm/aaaa).
- Testes: `python -m pytest -q`.
- App: `uvicorn web.main:app --reload` (gov.br DS) ou `streamlit run app.py` (legada).

## Agentes do projeto (.claude/agents)
- `especialista-contratacoes` — regras de negócio, Lei 14.133, checklist e minutas
- `extrator-certidoes` — leitura de PDFs e regras por emissor
- `integrador-oficial` — Conecta gov.br, SICAF, catálogo de portais
- `desenvolvedor-app` — interface, validador e geração do atesto
- `revisor-qa` — testes, revisão de segurança/LGPD e conferência final
