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

## Versão no navegador (sem servidor)
`site/` gera uma página estática que roda o mesmo pacote `certidoes` no navegador (Pyodide) e lê os
PDFs com pdf.js: os arquivos não saem do computador de quem usa. Visual no padrão gov.br DS
(CSS oficial 3.7.0, fonte Rawline e ícones Font Awesome 5, tudo embutido).
```bash
python site/build.py        # monta site/dist (baixa o Pyodide 0.27.7 via npm)
```
A paridade da leitura foi conferida nas 17 amostras (pdf.js x pdfplumber: mesmos resultados).
A consulta ao Conecta gov.br não existe nessa versão (exige credenciais do órgão no servidor).

## Menos captchas, sem contornar
- **SICAF:** marque "Aceitar o SICAF" e envie a declaração que *você* emitiu no Compras.gov.br na
  data do atesto. Itens "Automática" comprovam federal, FGTS e trabalhista sem abrir esses portais.
  O sistema alerta declaração antiga (> 3 dias), pendência, item "Manual", descredenciamento e
  conflito com certidão própria positiva.
- **Planejar emissão do mês** (`/mutirao`): envie os CSVs de controle dos meses anteriores e veja,
  por contratada, só o que vence até a data de corte, o que dá para consultar no SICAF, o texto de
  solicitação à contratada e os portais em sequência para um mutirão numa sessão só.
- **Conecta gov.br:** com a adesão do órgão, baixa a CND federal em PDF sem captcha.
- Minutas: `docs/estrategia_captcha.md`, `docs/oficio_orgaos_emissores.md`, cláusula atualizada.

## Como rodar
```bash
pip install -r requirements.txt
uvicorn web.main:app --reload   # interface gov.br DS em http://localhost:8000
streamlit run app.py            # interface antiga (Streamlit)
python -m pytest -q           # 234 testes
python tests/gerar_amostras.py  # recria os PDFs de teste (fictícios)
```

## Publicar no Railway
1. Em railway.com, **New Project → Deploy from GitHub repo** e escolha este repositório.
2. O Railway lê `railway.json`: instala `requirements.txt` (Python 3.12) e roda
   `uvicorn web.main:app` com verificação de saúde em `/saude`.
3. Em **Settings → Networking**, clique em **Generate Domain** para ter o link público.
4. Opcional, em **Variables**: `SISTEMA_NOME`, `SISTEMA_SUBTITULO`, `MAX_ARQUIVOS`,
   `MAX_MB_POR_ARQUIVO` e as variáveis abaixo.

A interface web (`web/`) usa o CSS oficial do Padrão Digital de Governo
(`@govbr-ds/core` 3.7.0, licença MIT) com a fonte Raleway servida pelo próprio app (`web/static/fonts`, licença OFL; números alinhados ativados), sem a marca gov.br.

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
