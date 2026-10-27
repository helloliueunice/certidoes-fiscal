# Certidões Fiscal

Apoio ao fiscal de contrato na conferência mensal das certidões de regularidade
(Receita/PGFN, FGTS, CNDT, Fazenda Estadual e Municipal) antes do atesto da nota fiscal.

> **Protótipo (MVP).** Testado com PDFs sintéticos. Antes do uso oficial, valide as regras de
> leitura com certidões reais do seu órgão e leve o projeto à TI para hospedagem interna.

## O que faz
1. **Buscar certidões** — lista os portais oficiais da sede da contratada (federais, 27 UFs,
   27 capitais), com o CNPJ pronto para copiar. Portais com captcha são acessados pelo fiscal:
   o sistema **não contorna captcha**.
2. **Conferir** — o fiscal arrasta os PDFs; o sistema identifica cada certidão, extrai situação,
   validade, CNPJ e código de controle e monta um checklist com semáforo:
   - 🟢 OK · 🟡 ATENÇÃO (vence em breve, filial, extração incerta) · 🔴 PENDENTE (vencida,
     positiva, CNPJ de outra empresa, faltante).
3. **Documentar** — gera PDF com checklist, roteiro de conferência de autenticidade e **minuta**
   de atesto (ou de notificação à contratada, se houver pendência), além de CSV de controle.

## Como rodar
```bash
pip install -r requirements.txt
streamlit run app.py          # abre no navegador
python -m pytest -q           # 119 testes
python tests/gerar_amostras.py  # recria os PDFs de teste (fictícios)
```

## Configuração opcional (variáveis de ambiente)
| Variável | Para quê |
|---|---|
| `CERTIDOES_IA=1` + `ANTHROPIC_API_KEY` | Liga a IA só para PDFs que as regras não identificam. Envia o texto do PDF ao serviço da Anthropic: use apenas com autorização do órgão (LGPD). Desligada por padrão. |
| `CONECTA_CLIENT_ID`, `CONECTA_CLIENT_SECRET`, `CONECTA_AMBIENTE` | API Consulta CND do Conecta gov.br (certidão federal sem captcha). Exige adesão formal do órgão — ver `docs/adesao_conecta.md`. |

## Estrutura
```
app.py                 interface (Streamlit)
certidoes/
  models.py            contrato de dados
  extrator.py          leitura dos PDFs por regras (por emissor)
  ia.py                fallback opcional com IA
  validador.py         checklist e semáforo
  atesto.py            PDF do checklist + minuta; CSV de controle
  portais.py           catálogo de portais (data/portais.json)
  conecta.py           cliente da API Consulta CND (Conecta gov.br)
data/portais.json      70 links oficiais (57 confirmados em 27/10/2026)
docs/                  roadmap, cláusula contratual, ofício, adesão ao Conecta, fontes
tests/                 testes + PDFs fictícios marcados "DOCUMENTO DE TESTE"
.claude/agents/        equipe de agentes para continuar o desenvolvimento
CLAUDE.md              contexto e regras do projeto para os agentes
```

## Equipe de agentes (`.claude/agents/`)
Para continuar o desenvolvimento no Claude Code, abra a pasta e peça por nome, por exemplo
"use o extrator-certidoes para adicionar a certidão da SEFAZ-MG".

| Agente | Papel |
|---|---|
| `especialista-contratacoes` | Regras de negócio, Lei 14.133/2021, checklist, minutas e cláusulas |
| `extrator-certidoes` | Regras de leitura de PDF por emissor e fallback de IA |
| `integrador-oficial` | Conecta gov.br, SICAF e catálogo de portais |
| `desenvolvedor-app` | Interface, validador e geração do atesto |
| `revisor-qa` | Revisão independente: testes, casos de borda, segurança/LGPD |

## Pendências conhecidas
- Regras de leitura validadas só com PDFs sintéticos; estaduais/municipais fora de SP e RJ usam
  regra genérica.
- 13 links do catálogo aguardam confirmação (`verificado_em: null`), incluindo 11 prefeituras.
- Cliente Conecta: 4 detalhes de autenticação marcados `# CONFIRMAR NA DOCUMENTAÇÃO`.
- PDFs escaneados não têm OCR (geram aviso para conferência manual).
- Acórdão TCU 1505/2026 citado em `docs/` precisa ser confirmado no site do TCU.

Todo documento gerado é **apoio**: a conferência e a decisão são do fiscal do contrato.
