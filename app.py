"""Interface Streamlit: conferência mensal das certidões de regularidade para o atesto.

Rodar: streamlit run app.py
"""
from __future__ import annotations

import os
import tempfile
from datetime import date

import streamlit as st

from certidoes.models import (
    Contrato,
    Semaforo,
    TipoCertidao,
    cnpj_valido,
    formatar_cnpj,
    so_digitos,
)
from certidoes.validador import (
    EMOJI_SEMAFORO,
    ROTULO_SEMAFORO,
    ROTULO_SITUACAO,
    formatar_data,
    alerta_extra,
    nota_extra,
    resumo,
    validar,
)
from certidoes.atesto import gerar_csv, gerar_pdf
from certidoes import planejamento

# Módulos de outros agentes: o app funciona mesmo sem eles.
try:
    from certidoes.extrator import ler_varios
except Exception as _e:  # pragma: no cover
    ler_varios = None
    _ERRO_EXTRATOR = str(_e)
else:
    _ERRO_EXTRATOR = ""

try:
    from certidoes import portais as _portais
except Exception:  # pragma: no cover
    _portais = None

try:
    from certidoes import conecta as _conecta
except Exception:  # pragma: no cover
    _conecta = None

try:
    from certidoes import ia as _ia
except Exception:  # pragma: no cover
    _ia = None

UFS = ["AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS", "MG", "PA",
       "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO"]

TIPOS_EXIGIVEIS = [TipoCertidao.FEDERAL, TipoCertidao.FGTS, TipoCertidao.TRABALHISTA,
                   TipoCertidao.ESTADUAL, TipoCertidao.MUNICIPAL, TipoCertidao.SICAF]
PADRAO = {TipoCertidao.FEDERAL, TipoCertidao.FGTS, TipoCertidao.TRABALHISTA,
          TipoCertidao.ESTADUAL, TipoCertidao.MUNICIPAL}

AVISO_IA_LGPD = (
    "Com a IA ligada, o texto dos PDFs não identificados (inclui CNPJ e razão social) é "
    "enviado ao serviço da Anthropic. Use apenas se autorizado pelo órgão (LGPD)."
)

DOC_CONECTA = "https://www.gov.br/conecta/catalogo/apis/consultar-certidao-negativa-de-debito"

st.set_page_config(page_title="Conferência de Certidões", page_icon=":material/fact_check:", layout="wide")

URL_SICAF = "https://www.gov.br/compras/pt-br/acesso-a-informacao/perguntas-frequentes/sicaf-sistema/sicaf-sistema"
AJUDA_SICAF = (
    "A declaração deve ser obtida por você, fiscal, no SICAF (Compras.gov.br), na data do atesto. "
    "A declaração enviada pela contratada não serve: é \"simples consulta\". Só os itens marcados "
    "\"Automática\" vêm direto do emissor (evitam os captchas da Receita, da Caixa e do TST); "
    "os marcados \"Manual\" foram inseridos pelo fornecedor e precisam ser conferidos no site do emissor."
)

# Ajustes visuais do Padrão Digital de Governo (gov.br DS) sobre o tema do Streamlit.
st.markdown("""
<style>
  .gov-header { border-bottom: 1px solid #e6e6e6; box-shadow: 0 3px 6px -3px rgba(51,51,51,.16);
    margin: -1rem 0 1.25rem; padding: 0 0 1rem; }
  .gov-header .sign { font-size: .8rem; color: #555; display: flex; align-items: center; gap: .5rem; margin-bottom: .5rem; }
  .gov-header .sign .barra { width: 1px; height: 1.1rem; background: #ccc; }
  .gov-header .marca { color: #1351B4; font-weight: 700; letter-spacing: .02em; }
  .gov-header .titulo { font-size: 1.6rem; font-weight: 400; color: #333; line-height: 1.2; }
  .gov-header .sub { font-size: .9rem; color: #555; margin-top: .15rem; }
  h1, h2, h3 { color: #333; }
  [data-testid="stMetricValue"] { font-weight: 700; }
  [data-testid="stSidebar"] { border-right: 1px solid #e6e6e6; }
  .stTabs [data-baseweb="tab"] { font-weight: 600; }
  .stButton button, .stDownloadButton button, .stLinkButton a { font-weight: 600; }
  .rodape-gov { margin-top: 3rem; padding: 1rem 1.25rem; background: #071D41; color: #fff; border-radius: 6px; font-size: .8rem; }
</style>
""", unsafe_allow_html=True)


def _ia_ligada() -> bool:
    try:
        return bool(_ia and _ia.habilitada())
    except Exception:
        return False


def _conecta_ok() -> bool:
    try:
        return bool(_conecta and _conecta.configurado())
    except Exception:
        return False


# ------------------------------------------------------------------ barra lateral
with st.sidebar:
    st.header("Dados do contrato")
    numero = st.text_input("Nº do contrato", key="numero")
    cnpj_txt = st.text_input("CNPJ da contratada", key="cnpj", placeholder="00.000.000/0000-00")
    cnpj = so_digitos(cnpj_txt)
    if cnpj_txt:
        if cnpj_valido(cnpj):
            st.caption(f"✔ CNPJ válido: {formatar_cnpj(cnpj)}")
        else:
            st.error("CNPJ inválido: confira os dígitos.")
    razao = st.text_input("Razão social", key="razao")
    col1, col2 = st.columns([1, 2])
    uf = col1.selectbox("UF da sede", UFS, index=UFS.index("DF"), key="uf")
    municipio = col2.text_input("Município da sede", key="municipio")
    fiscal = st.text_input("Fiscal do contrato", key="fiscal")
    hoje = date.today()
    mes_ant = (hoje.month - 2) % 12 + 1
    ano_ant = hoje.year if hoje.month > 1 else hoje.year - 1
    competencia = st.text_input("Competência (mês/ano)", value=f"{mes_ant:02d}/{ano_ant}",
                                key="competencia")
    orgao = st.text_input("Órgão", key="orgao")

    st.subheader("Certidões exigidas no contrato")
    exigidas = [t for t in TIPOS_EXIGIVEIS
                if st.checkbox(t.rotulo, value=t in PADRAO, key=f"exig_{t.value}")]
    aceitar_sicaf = st.checkbox(
        "Aceitar a declaração do SICAF como comprovação de federal, FGTS e trabalhista",
        value=False, key="aceitar_sicaf", help=AJUDA_SICAF)
    dias_alerta = st.number_input("Avisar quando faltar até (dias) para vencer",
                                  min_value=0, max_value=90, value=15, step=1, key="dias")
    st.divider()
    if _ia_ligada():
        st.caption("🤖 IA ligada (resultados por IA pedem conferência)")
        st.warning(AVISO_IA_LGPD)
    else:
        st.caption("IA desligada — leitura apenas por regras.")

contrato_ok = bool(numero and cnpj_valido(cnpj) and razao and municipio)


def _contrato() -> Contrato:
    return Contrato(numero=numero.strip(), cnpj=cnpj, razao_social=razao.strip(), uf_sede=uf,
                    municipio_sede=municipio.strip(), fiscal=fiscal.strip(),
                    competencia=competencia.strip(), exigidas=exigidas,
                    aceitar_sicaf=aceitar_sicaf)


st.markdown(
    '<div class="gov-header"><div class="sign"><span class="marca">CERTIDÕES</span><span class="barra"></span>'
    '<span>Apoio à fiscalização de contratos</span></div><div class="titulo">Conferência de Certidões</div>'
    '<div class="sub">Certidões de regularidade para atesto de contratos públicos · o sistema aponta, o fiscal confere e decide</div></div>',
    unsafe_allow_html=True)

aba1, aba2, aba4, aba3 = st.tabs(["1. Buscar certidões", "2. Conferir", "3. Planejar emissão do mês", "Como usar"])

# ------------------------------------------------------------------ aba 1
with aba1:
    st.info("Portais com captcha são acessados por você; o sistema não contorna captcha.")
    if cnpj_valido(cnpj):
        st.write("CNPJ para copiar e colar nos portais:")
        c1, c2 = st.columns(2)
        c1.caption("Com pontuação")
        c1.code(formatar_cnpj(cnpj), language=None)
        c2.caption("Só números")
        c2.code(cnpj, language=None)
    else:
        st.warning("Informe um CNPJ válido na barra lateral para facilitar a busca.")

    if _portais is None:
        st.warning("Catálogo de portais ainda não disponível nesta instalação.")
    elif not municipio:
        st.write("Informe UF e município da sede na barra lateral para ver os portais.")
    else:
        try:
            lista = _portais.portais_para(uf, municipio)
        except Exception as e:
            lista = []
            st.error(f"Não foi possível carregar o catálogo de portais: {e}")
        tipos_ok = {t.value for t in exigidas}
        for p in lista:
            tipo = p.get("tipo", "")
            if tipos_ok and tipo not in tipos_ok and tipo not in ("outra",):
                continue
            try:
                rot = TipoCertidao(tipo).rotulo
            except ValueError:
                rot = tipo
            col_a, col_b = st.columns([4, 1])
            icone = "🔒 com captcha" if p.get("captcha") else "sem captcha"
            col_a.markdown(f"**{p.get('nome', '')}** — {rot} · {icone}")
            if p.get("observacao"):
                col_a.caption(p["observacao"])
            if p.get("url"):
                col_b.link_button("Abrir portal", p["url"], width="stretch")
        if not lista:
            st.write("Nenhum portal cadastrado para esta UF/município.")

    st.subheader("Certidão federal pela API oficial (Conecta gov.br)")
    if _conecta_ok():
        if st.button("Consultar CND federal via Conecta", disabled=not cnpj_valido(cnpj)):
            with st.spinner("Consultando..."):
                try:
                    st.session_state["conecta_resp"] = _conecta.consultar_cnd(cnpj)
                except Exception as e:
                    st.session_state["conecta_resp"] = {"erro": str(e)}
        resp = st.session_state.get("conecta_resp")
        if resp:
            st.json(resp)
    else:
        st.caption(
            "A consulta automática da certidão federal exige adesão do órgão à API Consulta CND "
            f"do Conecta gov.br e configuração das credenciais. [Saiba mais]({DOC_CONECTA})."
        )

# ------------------------------------------------------------------ aba 2
with aba2:
    if not contrato_ok:
        st.warning("Preencha nº do contrato, CNPJ válido, razão social e município na barra lateral.")
    if not exigidas:
        st.warning("Marque ao menos uma certidão exigida.")

    arquivos = st.file_uploader("Arraste aqui os PDFs das certidões", type=["pdf"],
                                accept_multiple_files=True, key="upload")
    observacoes = st.text_area("Observações do fiscal (vão para o PDF)", key="obs", height=90)

    if ler_varios is None:
        st.error("Leitor de PDFs indisponível nesta instalação."
                 + (f" Detalhe técnico: {_ERRO_EXTRATOR}" if _ERRO_EXTRATOR else ""))
    elif arquivos and contrato_ok and exigidas:
        # Lê os PDFs só quando o conjunto de arquivos muda (evita reprocessar a cada clique).
        assinatura = tuple((a.name, a.size) for a in arquivos)
        if st.session_state.get("lidos_assin") != assinatura:
            with st.spinner("Lendo certidões..."):
                with tempfile.TemporaryDirectory(prefix="certidoes_") as tmp:
                    caminhos = []
                    for i, a in enumerate(arquivos):
                        nome = os.path.basename(a.name) or f"arquivo_{i}.pdf"
                        destino = os.path.join(tmp, f"{i:02d}_{nome}")
                        with open(destino, "wb") as f:
                            f.write(a.getbuffer())
                        caminhos.append(destino)
                    try:
                        certs = ler_varios(caminhos)
                    except Exception as e:
                        certs = []
                        st.error(f"Erro ao ler os PDFs: {e}")
                    # mostra o nome original do arquivo, não o caminho temporário
                    for c in certs:
                        base = os.path.basename(c.arquivo)
                        c.arquivo = base.split("_", 1)[1] if base[:2].isdigit() and "_" in base else base
            st.session_state["lidos_assin"] = assinatura
            st.session_state["certs"] = certs
        certs = st.session_state.get("certs", [])

        resultado = validar(_contrato(), certs, dias_alerta=int(dias_alerta))
        r = resumo(resultado)

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("🟢 OK", r["verde"])
        m2.metric("🟡 Atenção", r["amarelo"])
        m3.metric("🔴 Pendente", r["vermelho"])
        m4.metric("Outros documentos", r["extras"])
        if resultado.apto_atesto:
            st.success("Nenhuma pendência impeditiva. Confira os itens em atenção e a "
                       "autenticidade antes de atestar.")
        else:
            st.error("Há pendências. O PDF trará minuta de notificação à contratada.")

        linhas = []
        for i in resultado.itens:
            c = i.certidao
            linhas.append({
                "": EMOJI_SEMAFORO[i.semaforo],
                "Resultado": ROTULO_SEMAFORO[i.semaforo],
                "Certidão": i.tipo.rotulo,
                "Situação": ROTULO_SITUACAO[c.situacao] if c else "—",
                "Validade": formatar_data(c.validade) if c else "—",
                "Mensagem": i.mensagem,
                "Arquivo": c.arquivo if c else "—",
            })
        st.dataframe(linhas, width="stretch", hide_index=True)

        if resultado.extras:
            st.subheader("Outros documentos enviados")
            for x in resultado.extras:
                linha = f"**{x.arquivo}** ({x.tipo.rotulo}): {nota_extra(x, resultado)}"
                if alerta_extra(x, resultado):
                    st.error("⚠️ " + linha)
                else:
                    st.write("• " + linha)

        st.subheader("Detalhes de cada arquivo")
        for c in certs:
            with st.expander(f"{c.arquivo} — {c.tipo.rotulo}"):
                st.write({
                    "Tipo": c.tipo.rotulo,
                    "Situação": ROTULO_SITUACAO[c.situacao],
                    "CNPJ": formatar_cnpj(c.cnpj) or "não encontrado",
                    "Razão social": c.razao_social or "",
                    "Órgão emissor": c.orgao_emissor or "",
                    "UF / município": " / ".join(x for x in (c.uf, c.municipio) if x),
                    "Emissão": formatar_data(c.data_emissao),
                    "Validade": formatar_data(c.validade),
                    "Código de controle": c.codigo_controle or "",
                    "Leitura": f"{'IA' if c.metodo == 'ia' else 'regras'} "
                               f"(confiança {c.confianca:.0%})",
                })
                if c.url_verificacao:
                    st.markdown(f"Conferir autenticidade: [{c.url_verificacao}]({c.url_verificacao})")
                for a in c.avisos:
                    st.warning(a)

        st.subheader("Baixar")
        base = f"checklist_{so_digitos(numero) or 'contrato'}_{competencia.replace('/', '-')}"
        with tempfile.TemporaryDirectory(prefix="atesto_") as tmp:
            pdf_path = gerar_pdf(resultado, os.path.join(tmp, base + ".pdf"),
                                 orgao=orgao, observacoes=observacoes)
            csv_path = gerar_csv([resultado], os.path.join(tmp, base + ".csv"))
            with open(pdf_path, "rb") as f:
                pdf_bytes = f.read()
            with open(csv_path, "rb") as f:
                csv_bytes = f.read()
        d1, d2 = st.columns(2)
        d1.download_button("📄 Baixar checklist e minuta (PDF)", pdf_bytes,
                           file_name=base + ".pdf", mime="application/pdf",
                           width="stretch")
        d2.download_button("📊 Baixar planilha de controle (CSV)", csv_bytes,
                           file_name=base + ".csv", mime="text/csv", width="stretch")
        st.caption("O PDF é uma minuta: revise, confira a autenticidade e assine.")

        grupo = planejamento.grupo_de_resultado(resultado)
        if grupo["a_emitir"]:
            st.subheader("Pedir as certidões à contratada")
            st.caption("Assunto: " + planejamento.assunto_solicitacao(grupo))
            st.code(planejamento.texto_solicitacao(grupo, orgao=orgao), language=None, wrap_lines=True)
            st.caption("Use o botão de copiar no canto do quadro. O texto é uma minuta: revise antes de enviar.")

# ------------------------------------------------------------------ aba 4: planejamento do mês
TAG_PLANO = {"sem_validade": ("🔴", "sem certidão"), "vencida": ("🔴", "vencida"), "pendente": ("🔴", "pendente"),
             "vence_antes": ("🟡", "vence antes do corte"), "valida": ("🟢", "válida"), "reconferir": ("🟡", "reconferir")}

with aba4:
    st.markdown("Envie as planilhas de controle (CSV) das conferências anteriores. Para cada contratada, o sistema "
                "mostra o que ainda está válido na data de corte e o que precisa ser emitido, para você resolver o "
                "mínimo de captchas numa só sessão.")
    st.info(
        "**Estratégia para resolver menos captchas**  \n"
        "1. **Peça à contratada:** ela deve manter a regularidade durante todo o contrato (Lei nº 14.133/2021, "
        "art. 92, XVI) e, quando o contrato prever, enviar as certidões com a nota fiscal.  \n"
        f"2. **Use o [SICAF]({URL_SICAF}):** uma consulta feita por você, na data do atesto, cobre federal, FGTS "
        "e trabalhista nos itens marcados \"Automática\".  \n"
        "3. **Emita só o que vence** até a data de corte.  \n"
        "4. **Faça tudo numa sessão:** CNPJ copiado, portais abertos em sequência, cada item marcado como feito.  \n"
        "O sistema não contorna captcha: nos portais com captcha, é você quem resolve.")
    csvs = st.file_uploader("Planilhas de controle (CSV) baixadas na aba Conferir", type=["csv"],
                            accept_multiple_files=True, key="csvs")
    p1, p2, p3 = st.columns([1, 2, 1])
    ate = p1.date_input("Data de corte", value=planejamento.data_corte_padrao(date.today()),
                        format="DD/MM/YYYY", key="ate", help="A certidão precisa estar válida até esta data.")
    orgao_plano = p2.text_input("Órgão (vai no texto de solicitação)", value=orgao, key="orgao_plano")
    prazo = p3.number_input("Prazo para a contratada (dias úteis)", min_value=1, max_value=60, value=5, key="prazo")
    sicaf_todos = st.checkbox("Aceitar o SICAF para federal, FGTS e trabalhista de todas as contratadas",
                              key="sicaf_plano", help=AJUDA_SICAF)

    if csvs:
        linhas = planejamento.ler_csvs([a.getvalue() for a in csvs])
        if not linhas:
            st.error("Nenhuma linha válida encontrada. Use a planilha de controle (CSV) baixada no resultado da conferência.")
        else:
            grupos = planejamento.planejar(linhas, ate=ate, hoje=date.today(), aceitar_sicaf=sicaf_todos)
            t = planejamento.totalizar(grupos)
            st.subheader(f"Plano até {formatar_data(ate)}")
            c = st.columns(6)
            c[0].metric("Contratadas", t["contratadas"]); c[1].metric("🟢 Ainda válidas", t["ok"])
            c[2].metric("🔴 A emitir", t["a_emitir"]); c[3].metric("🟡 A reconferir", t["a_reconferir"])
            c[4].metric("Via SICAF", t["via_sicaf"]); c[5].metric("Captchas evitados", t["captchas_evitados"])
            st.caption("Captchas evitados = certidões ainda válidas + itens comprovados pelo SICAF. "
                       f"Estimativa de captchas a resolver hoje: **{t['captchas_a_resolver']}**.")
            st.download_button("Baixar lista do mutirão (CSV)", planejamento.csv_plano(grupos).encode("utf-8-sig"),
                               file_name=f"mutirao_{ate:%Y-%m-%d}.csv", mime="text/csv", icon=":material/download:")
            feitos, total = 0, 0
            for n, g in enumerate(grupos):
                acoes = g["a_emitir"] + g["consultar_sicaf"] + g["reconferir"]
                with st.container(border=True):
                    st.markdown(f"#### {g['razao_social'] or 'Contratada sem razão social'}")
                    st.caption(f"Contrato {g['contrato'] or '—'}"
                               + (f" · Sede {g['municipio_sede']}/{g['uf_sede']}" if g["municipio_sede"] else ""))
                    st.code(g["cnpj_formatado"], language=None)
                    if not acoes:
                        st.success(f"Nada a emitir até {formatar_data(ate)}.")
                    for i in acoes:
                        total += 1
                        emoji, rot = TAG_PLANO.get(i["situacao_plano"], ("🔴", "pendente"))
                        a, b = st.columns([3, 2])
                        feito = a.checkbox(f"**{i['rotulo']}** · {emoji} {rot}"
                                           + (" · consultar SICAF" if i["acao"] == "consultar SICAF" else ""),
                                           key=f"feito_{g['cnpj']}_{g['contrato']}_{i['tipo']}_{ate:%Y%m%d}")
                        feitos += int(feito)
                        a.caption(f"Validade registrada: {i['validade_txt'] or '—'} · {i['motivo']}")
                        for j, pt in enumerate(i["portais"]):
                            if pt.get("url"):
                                rot_b = ("Abrir SICAF" if i["acao"] == "consultar SICAF" else "Abrir portal") + \
                                        (f" {j + 1}" if len(i["portais"]) > 1 else "") + \
                                        (" · com captcha" if pt.get("captcha") is True else "")
                                b.link_button(rot_b, pt["url"], help=pt.get("nome"), icon=":material/open_in_new:")
                        if not i["portais"]:
                            b.caption("Portal não catalogado: use o site do emissor.")
                    if g["ok"]:
                        with st.expander(f"{len(g['ok'])} certidão(ões) ainda válida(s) na data de corte"):
                            for i in g["ok"]:
                                st.write(f"🟢 {i['rotulo']} — até {i['validade_txt']}" + (" (SICAF)" if i["via_sicaf"] else ""))
                    if g["a_emitir"]:
                        with st.expander("Texto de solicitação à contratada (minuta)"):
                            st.caption("Assunto: " + planejamento.assunto_solicitacao(g))
                            st.code(planejamento.texto_solicitacao(g, prazo_dias=int(prazo), orgao=orgao_plano),
                                    language=None, wrap_lines=True)
            if total:
                st.progress(feitos / total, text=f"Progresso do mutirão: {feitos} de {total} feitos")
            st.caption("As marcações de \"feito\" valem só nesta sessão. O plano é um apoio: a conferência e o atesto são do fiscal.")
    else:
        st.caption("Nada fica guardado: as planilhas são lidas e o plano é montado só nesta sessão.")

# ------------------------------------------------------------------ aba 3
with aba3:
    st.markdown(
        """
**Passo a passo mensal**

1. **Preencha os dados do contrato** na barra lateral e marque as certidões que o contrato exige.
2. **Aba 1 — Buscar certidões:** abra cada portal oficial, cole o CNPJ, resolva o captcha
   (é você quem resolve; o sistema não contorna) e salve o PDF.
   Se a contratada já enviou as certidões, pule esta etapa.
3. **Aba 2 — Conferir:** arraste todos os PDFs de uma vez. Veja o semáforo:
   - 🟢 **OK** — certidão válida e do CNPJ do contrato;
   - 🟡 **Atenção** — aceita, mas vence em breve ou precisa de conferência manual;
   - 🔴 **Pendente** — faltante, positiva, vencida ou de outra empresa.
4. **Confira a autenticidade** de cada certidão no site do emissor, pelo código de controle.
5. **Baixe o PDF**: ele traz o checklist e a minuta — de atesto, se não houver pendências, ou de
   notificação à contratada, se houver. Revise, complete o prazo e assine.
6. **Guarde o CSV** para o controle mensal e junte os documentos ao processo.
7. **No mês seguinte, use a aba Planejar emissão do mês:** envie os CSVs guardados e veja só o que
   vence até a data de corte, o que pode ser consultado no SICAF e o texto para pedir as certidões à contratada.

Os arquivos enviados são processados localmente e descartados após a leitura.
A decisão de atestar é sempre do fiscal do contrato.
"""
    )

st.markdown('<div class="rodape-gov">Ferramenta de apoio. O sistema aponta; a conferência e a decisão de atestar são do '
            'fiscal do contrato. Portais com captcha são acessados pelo próprio servidor: o sistema não contorna captcha.</div>',
            unsafe_allow_html=True)
