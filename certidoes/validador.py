"""Validação das certidões contra o contrato: produz o checklist com semáforo.

O validador nunca "aprova": aponta situação e mensagens. A decisão é do fiscal.
"""
from __future__ import annotations

import os
import unicodedata
from datetime import date
from typing import Optional

from .models import (
    Certidao,
    Contrato,
    ItemChecklist,
    ResultadoValidacao,
    Semaforo,
    Situacao,
    TipoCertidao,
    formatar_cnpj,
    so_digitos,
)

_ORDEM = {Semaforo.VERDE: 0, Semaforo.AMARELO: 1, Semaforo.VERMELHO: 2}

ROTULO_SEMAFORO = {
    Semaforo.VERDE: "OK",
    Semaforo.AMARELO: "ATENÇÃO",
    Semaforo.VERMELHO: "PENDENTE",
}

EMOJI_SEMAFORO = {
    Semaforo.VERDE: "🟢",
    Semaforo.AMARELO: "🟡",
    Semaforo.VERMELHO: "🔴",
}

ROTULO_SITUACAO = {
    Situacao.NEGATIVA: "Negativa",
    Situacao.POSITIVA_EFEITO_NEGATIVA: "Positiva com efeitos de negativa",
    Situacao.POSITIVA: "POSITIVA",
    Situacao.REGULAR: "Regular",
    Situacao.INDETERMINADA: "Não identificada",
}

MSG_SP = (
    "Em SP são exigidas a certidão da PGE (dívida ativa) e a da SEFAZ "
    "(débitos não inscritos); falta uma"
)


# ---------------------------------------------------------------- utilitários

def formatar_data(d: Optional[date]) -> str:
    return d.strftime("%d/%m/%Y") if d else ""


def _norm(s: Optional[str]) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(s.lower().split())


def _pior(a: Semaforo, b: Semaforo) -> Semaforo:
    return a if _ORDEM[a] >= _ORDEM[b] else b


def _relacao_cnpj(cert: Certidao, contrato: Contrato) -> str:
    """'igual', 'filial' (mesma raiz), 'diferente' ou 'ausente'."""
    c = so_digitos(cert.cnpj)
    k = so_digitos(contrato.cnpj)
    if len(c) != 14:
        return "ausente"
    if c == k:
        return "igual"
    if c[:8] == k[:8]:
        return "filial"
    return "diferente"


def _local(cert: Certidao, contrato: Contrato) -> int:
    """2 = da sede; 1 = não identificado; 0 = de outro local."""
    if cert.tipo == TipoCertidao.ESTADUAL:
        uf = (cert.uf or "").strip().upper()
        if not uf:
            return 1
        return 2 if uf == contrato.uf_sede.strip().upper() else 0
    if cert.tipo == TipoCertidao.MUNICIPAL:
        sede = _norm(contrato.municipio_sede)
        mun = _norm(cert.municipio)
        if mun:
            ok = mun == sede
            uf = (cert.uf or "").strip().upper()
            if ok and uf and uf != contrato.uf_sede.strip().upper():
                ok = False
            return 2 if ok else 0
        if sede and sede in _norm(cert.orgao_emissor):
            return 2
        return 1
    return 2


def _subtipo_sp(cert: Certidao) -> Optional[str]:
    """'pge' (dívida ativa), 'sefaz' (não inscritos) ou None."""
    orgao = _norm(cert.orgao_emissor)
    if "pge" in orgao or "procuradoria" in orgao:
        return "pge"
    if "sefaz" in orgao or "secretaria da fazenda" in orgao:
        return "sefaz"
    texto = _norm(cert.texto)
    alvo = orgao + " " + texto
    if "nao inscrit" in alvo:
        return "sefaz"
    if "procuradoria" in alvo or "pge" in alvo.split() or "divida ativa" in alvo:
        return "pge"
    return None


def _dias(n: int) -> str:
    return f"{n} dia" if abs(n) == 1 else f"{n} dias"


# ---------------------------------------------------------------- avaliação

def avaliar_certidao(
    cert: Certidao, contrato: Contrato, hoje: date, dias_alerta: int = 15
) -> tuple[Semaforo, str]:
    """Semáforo e mensagem de UMA certidão frente ao contrato."""
    vermelhos: list[str] = []
    amarelos: list[str] = []
    notas: list[str] = []

    # situação
    if cert.situacao == Situacao.POSITIVA:
        vermelhos.append("Certidão POSITIVA: débitos exigíveis. Não atestar sem regularização.")
    elif cert.situacao == Situacao.INDETERMINADA:
        if cert.validade is None:
            vermelhos.append(
                "Situação e validade não identificadas no documento: conferir no site do emissor."
            )
        else:
            amarelos.append("Situação (negativa/positiva) não identificada: conferir o documento.")
    elif cert.situacao == Situacao.POSITIVA_EFEITO_NEGATIVA:
        notas.append("Positiva com efeitos de negativa (aceita).")

    # validade
    validade_txt = ""
    if cert.validade is None:
        if cert.situacao != Situacao.INDETERMINADA:
            amarelos.append("Validade não identificada: conferir no documento.")
    else:
        restante = (cert.validade - hoje).days
        if restante < 0:
            vermelhos.insert(0, f"Vencida em {formatar_data(cert.validade)}.")
        elif restante == 0:
            amarelos.insert(0, f"Vence hoje ({formatar_data(cert.validade)}). Pedir certidão atualizada.")
        elif restante <= dias_alerta:
            amarelos.insert(
                0, f"Válida até {formatar_data(cert.validade)} ({_dias(restante)}): vence em breve."
            )
        else:
            validade_txt = f"Válida até {formatar_data(cert.validade)} ({_dias(restante)})."

    # CNPJ
    rel = _relacao_cnpj(cert, contrato)
    if rel == "diferente":
        vermelhos.append(
            f"CNPJ da certidão ({formatar_cnpj(cert.cnpj)}) é de outra empresa "
            f"(contrato: {formatar_cnpj(contrato.cnpj)})."
        )
    elif rel == "ausente":
        amarelos.append("CNPJ não encontrado no PDF: conferir.")
    elif rel == "filial":
        if cert.tipo == TipoCertidao.FEDERAL:
            notas.append(
                f"Emitida para {formatar_cnpj(cert.cnpj)}; a certidão federal abrange matriz e filiais."
            )
        else:
            amarelos.append(
                f"Emitida para outro estabelecimento da mesma empresa ({formatar_cnpj(cert.cnpj)}); "
                f"o contrato é com {formatar_cnpj(contrato.cnpj)}. Conferir se atende."
            )

    # local (estadual/municipal)
    if _local(cert, contrato) == 0:
        if cert.tipo == TipoCertidao.ESTADUAL:
            amarelos.append(
                f"Certidão estadual de {cert.uf}, mas a sede é em {contrato.uf_sede}: "
                "conferir se é a exigida."
            )
        else:
            amarelos.append(
                f"Certidão municipal de {cert.municipio}, mas a sede é em "
                f"{contrato.municipio_sede}: conferir se é a exigida."
            )

    # qualidade da leitura
    if cert.metodo == "ia":
        amarelos.append("Dados extraídos por IA: conferir manualmente.")
    if cert.confianca < 0.6:
        amarelos.append(f"Leitura com baixa confiança ({cert.confianca:.0%}): conferir.")
    if cert.avisos:
        amarelos.append("Avisos da leitura: " + "; ".join(cert.avisos))

    if vermelhos:
        sem = Semaforo.VERMELHO
    elif amarelos:
        sem = Semaforo.AMARELO
    else:
        sem = Semaforo.VERDE
    partes = vermelhos + ([validade_txt] if validade_txt else []) + amarelos + notas
    return sem, " ".join(p for p in partes if p)


def _chave(cert: Certidao, contrato: Contrato, hoje: date, dias_alerta: int):
    sem, _ = avaliar_certidao(cert, contrato, hoje, dias_alerta)
    mesma_raiz = so_digitos(cert.cnpj)[:8] == so_digitos(contrato.cnpj)[:8]
    return (
        _local(cert, contrato),
        mesma_raiz,  # certidão da própria contratada antes de documento de outra empresa
        cert.data_emissao or date.min,  # a mais recente prevalece
        -_ORDEM[sem],
        cert.situacao.aceita,
        cert.validade or date.min,
        cert.confianca,
    )


def _positiva_mais_recente(
    escolhida: Certidao, cands: list[Certidao], contrato: Contrato
) -> Optional[Certidao]:
    """POSITIVA do mesmo tipo/local/raiz emitida depois da escolhida (prevalece a mais recente)."""
    if escolhida.situacao == Situacao.POSITIVA:
        return None
    raiz = so_digitos(contrato.cnpj)[:8]
    local = _local(escolhida, contrato)
    achadas = [
        c for c in cands
        if c is not escolhida
        and c.situacao == Situacao.POSITIVA
        and c.data_emissao is not None
        and (escolhida.data_emissao is None or c.data_emissao > escolhida.data_emissao)
        and _local(c, contrato) == local
        and so_digitos(c.cnpj)[:8] == raiz
    ]
    return max(achadas, key=lambda c: c.data_emissao) if achadas else None


def _avaliar_no_grupo(
    cert: Certidao, cands: list[Certidao], contrato: Contrato, hoje: date, dias_alerta: int
) -> tuple[Semaforo, str]:
    sem, msg = avaliar_certidao(cert, contrato, hoje, dias_alerta)
    pos = _positiva_mais_recente(cert, cands, contrato)
    if pos is not None:
        sem = Semaforo.VERMELHO
        msg = (
            f"Há certidão POSITIVA mais recente (emitida em {formatar_data(pos.data_emissao)}) "
            f"— prevalece a mais recente ({os.path.basename(pos.arquivo)}). " + msg
        )
    return sem, msg


def _melhor(cands: list[Certidao], contrato: Contrato, hoje: date, dias_alerta: int) -> Optional[Certidao]:
    if not cands:
        return None
    return max(cands, key=lambda c: _chave(c, contrato, hoje, dias_alerta))


ROTULO_SP = {
    "pge": "PGE (dívida ativa)",
    "sefaz": "SEFAZ (não inscritos)",
    None: "Estadual (órgão não identificado: conferir se é PGE ou SEFAZ)",
}


def _item_estadual_sp(
    cands: list[Certidao], contrato: Contrato, hoje: date, dias_alerta: int
) -> tuple[ItemChecklist, list[Certidao]]:
    """SP: PGE (dívida ativa) + SEFAZ (não inscritos). Retorna item e certidões usadas."""
    locais = [c for c in cands if _local(c, contrato) >= 1]
    grupos: dict[Optional[str], list[Certidao]] = {"pge": [], "sefaz": [], None: []}
    for c in locais:
        grupos[_subtipo_sp(c)].append(c)
    pge = _melhor(grupos["pge"], contrato, hoje, dias_alerta)
    sefaz = _melhor(grupos["sefaz"], contrato, hoje, dias_alerta)
    resto = sorted(
        grupos[None], key=lambda c: _chave(c, contrato, hoje, dias_alerta), reverse=True
    )
    # certidões sem órgão identificado ocupam a vaga que faltar, mas sem rótulo presumido
    if pge is None and resto:
        pge = resto.pop(0)
    if sefaz is None and resto:
        sefaz = resto.pop(0)

    usadas = [c for c in (pge, sefaz) if c is not None]
    if not usadas:
        # nenhuma de SP: avalia a melhor de outra UF (gera amarelo de UF diferente)
        outra = _melhor(cands, contrato, hoje, dias_alerta)
        sem, msg = _avaliar_no_grupo(outra, cands, contrato, hoje, dias_alerta)
        return ItemChecklist(TipoCertidao.ESTADUAL, sem, msg, outra), [outra]

    sem = Semaforo.VERDE
    msgs = []
    pior_cert = usadas[0]
    pior_sem = Semaforo.VERDE
    for c in usadas:
        sub = _subtipo_sp(c)
        grupo = grupos[sub]
        s, m = _avaliar_no_grupo(c, grupo, contrato, hoje, dias_alerta)
        if sub is None:
            s = _pior(s, Semaforo.AMARELO)
        msgs.append(f"{ROTULO_SP[sub]}: {m}")
        sem = _pior(sem, s)
        if _ORDEM[s] > _ORDEM[pior_sem]:
            pior_sem, pior_cert = s, c
    if len(usadas) < 2:
        # falta uma das duas: é certidão faltante
        sem = Semaforo.VERMELHO
        sub = _subtipo_sp(usadas[0])
        if sub == "pge":
            faltante = "SEFAZ (débitos não inscritos)"
        elif sub == "sefaz":
            faltante = "PGE (dívida ativa)"
        else:
            faltante = "PGE ou SEFAZ"
        msgs.insert(0, f"{MSG_SP} ({faltante}).")
    return ItemChecklist(TipoCertidao.ESTADUAL, sem, " ".join(msgs), pior_cert), usadas


# ---------------------------------------------------------------- SICAF como comprovação

COBERTOS_SICAF = (
    TipoCertidao.FEDERAL, TipoCertidao.FGTS, TipoCertidao.TRABALHISTA,
    TipoCertidao.ESTADUAL, TipoCertidao.MUNICIPAL,
)
MSG_SICAF_SP = "SICAF traz uma única certidão estadual; em SP confira PGE e SEFAZ."
MSG_SICAF_MANUAL = (
    "Certidão inserida manualmente pelo fornecedor no SICAF: conferir a certidão no site do emissor."
)
_RANK_CNPJ = {"igual": 2, "filial": 1, "ausente": 0}

# A declaração do SICAF é "simples consulta, sem efeito legal": o fiscal deve emiti-la ele mesmo,
# perto do pagamento. Declaração mais antiga que isso (em dias) fica amarela.
SICAF_MAX_DIAS = 3


def sicaf_max_dias() -> int:
    """SICAF_MAX_DIAS, ou o valor de CERTIDOES_SICAF_MAX_DIAS (inteiro >= 0) se definido."""
    try:
        v = int(os.environ.get("CERTIDOES_SICAF_MAX_DIAS", ""))
    except ValueError:
        return SICAF_MAX_DIAS
    return v if v >= 0 else SICAF_MAX_DIAS


def _itens_sicaf(cert: Certidao) -> dict[str, dict]:
    """Itens da cobertura por tipo, sem as chaves reservadas ("_situacao")."""
    return {k: v for k, v in cert.cobertura_sicaf.items() if not k.startswith("_")}


def _sicafs_compativeis(certidoes: list[Certidao], contrato: Contrato) -> tuple[list[Certidao], list[Certidao]]:
    """(SICAF com CNPJ compatível, SICAF de outra empresa)."""
    sicafs = [c for c in certidoes if c.tipo == TipoCertidao.SICAF]
    compat = [c for c in sicafs if _relacao_cnpj(c, contrato) != "diferente"]
    return compat, [c for c in sicafs if c not in compat]


def _sicaf_para(tipo: TipoCertidao, compat: list[Certidao], contrato: Contrato) -> Optional[Certidao]:
    """Declaração mais recente (e de CNPJ mais próximo) que traz o tipo."""
    cands = [c for c in compat if tipo.value in _itens_sicaf(c)]
    if not cands:
        return None
    return max(cands, key=lambda c: (c.data_emissao or date.min, _RANK_CNPJ[_relacao_cnpj(c, contrato)]))


def avaliar_sicaf(
    sicaf: Certidao, tipo: TipoCertidao, contrato: Contrato, hoje: date, dias_alerta: int = 15
) -> tuple[Semaforo, str]:
    """Semáforo e mensagem do item ``tipo`` comprovado pela declaração do SICAF."""
    info = sicaf.cobertura_sicaf.get(tipo.value) or {}
    validade: Optional[date] = info.get("validade")
    automatica = bool(info.get("automatica"))
    pendencia = bool(info.get("pendencia"))
    vermelhos: list[str] = []
    amarelos: list[str] = []
    notas: list[str] = []

    validade_txt = ""
    if validade is None:
        amarelos.append("Validade não identificada na declaração do SICAF: conferir.")
    else:
        restante = (validade - hoje).days
        if restante < 0:
            vermelhos.append(f"SICAF: certidão vencida em {formatar_data(validade)}.")
        elif restante == 0:
            amarelos.append(f"Vence hoje ({formatar_data(validade)}). Pedir certidão atualizada.")
        elif restante <= dias_alerta:
            amarelos.append(f"Válida até {formatar_data(validade)} ({_dias(restante)}): vence em breve.")
        else:
            validade_txt = f"Válida até {formatar_data(validade)} ({_dias(restante)})."
    if not automatica:
        amarelos.append(MSG_SICAF_MANUAL)
    if pendencia:
        amarelos.append("A declaração do SICAF indica pendência neste nível: conferir a declaração.")
    elif not sicaf.situacao.aceita:
        amarelos.append(
            "A declaração do SICAF indica pendência ou situação não identificada: conferir a declaração."
        )

    sit = sicaf.cobertura_sicaf.get("_situacao") or {}
    if not sit.get("situacao"):
        amarelos.append("SICAF: situação do fornecedor não identificada na declaração: conferir.")
    elif not sit.get("credenciado"):
        amarelos.append(f"SICAF: fornecedor {sit['situacao']}.")
    if sit.get("impedimento"):
        amarelos.append(f"SICAF: {sit['impedimento']}.")

    max_dias = sicaf_max_dias()
    if sicaf.data_emissao is None:
        amarelos.append(
            "Data de emissão da declaração do SICAF não identificada: consulte o SICAF novamente "
            "na data do atesto."
        )
    elif (hoje - sicaf.data_emissao).days > max_dias:
        idade = (hoje - sicaf.data_emissao).days
        amarelos.append(
            f"Declaração do SICAF emitida em {formatar_data(sicaf.data_emissao)} (há {_dias(idade)}): "
            "consulte o SICAF novamente na data do atesto."
        )

    rel = _relacao_cnpj(sicaf, contrato)
    if rel == "ausente":
        amarelos.append("CNPJ não encontrado na declaração do SICAF: conferir.")
    elif rel == "filial":
        if tipo == TipoCertidao.FEDERAL:
            notas.append(
                f"Declaração de {formatar_cnpj(sicaf.cnpj)}; a certidão federal abrange matriz e filiais."
            )
        else:
            amarelos.append(
                f"Declaração do SICAF de outro estabelecimento da mesma empresa "
                f"({formatar_cnpj(sicaf.cnpj)}); o contrato é com {formatar_cnpj(contrato.cnpj)}. "
                "Conferir se atende."
            )
    if tipo == TipoCertidao.ESTADUAL and contrato.uf_sede.strip().upper() == "SP":
        amarelos.append(MSG_SICAF_SP)
    if sicaf.metodo == "ia":
        amarelos.append("Dados extraídos por IA: conferir manualmente.")
    if sicaf.confianca < 0.6:
        amarelos.append(f"Leitura com baixa confiança ({sicaf.confianca:.0%}): conferir.")

    origem = " (obtida automaticamente do emissor)" if automatica else ""
    if vermelhos:
        sem = Semaforo.VERMELHO
        cab = ""  # a primeira mensagem já diz "SICAF: certidão vencida em ..."
    elif amarelos:
        sem = Semaforo.AMARELO
        cab = f"Comprovada pelo SICAF{origem}, com ressalvas."
    else:
        sem = Semaforo.VERDE
        cab = f"Comprovada pelo SICAF{origem}."
    partes = [cab] + vermelhos + ([validade_txt] if validade_txt else []) + amarelos + notas
    return sem, " ".join(p for p in partes if p)


def _positiva_vigente(cands: list[Certidao], contrato: Contrato) -> Optional[Certidao]:
    """POSITIVA própria (mesma raiz, local compatível) não superada por certidão própria mais recente."""
    raiz = so_digitos(contrato.cnpj)[:8]
    proprias = [c for c in cands if so_digitos(c.cnpj)[:8] == raiz and _local(c, contrato) >= 1]
    positivas = [c for c in proprias if c.situacao == Situacao.POSITIVA]
    if not positivas:
        return None
    pos = max(positivas, key=lambda c: c.data_emissao or date.max)  # sem data: tratada como recente
    if pos.data_emissao is not None and any(
        c.situacao != Situacao.POSITIVA and c.data_emissao is not None and c.data_emissao > pos.data_emissao
        for c in proprias
    ):
        return None  # há certidão própria mais recente que não é positiva
    return pos


def _combinar_sicaf(
    tipo: TipoCertidao,
    cands: list[Certidao],
    proprio: Optional[ItemChecklist],
    compat: list[Certidao],
    incompat: list[Certidao],
    contrato: Contrato,
    hoje: date,
    dias_alerta: int,
) -> tuple[Optional[ItemChecklist], Optional[Certidao]]:
    """Item final e, se usado, o SICAF.

    Certidão própria aceitável (verde/amarela) tem prioridade; se a própria for vermelha,
    usa-se a melhor das duas e a mensagem menciona ambas. Certidão própria POSITIVA nunca
    deixa o item verde: se for mais recente (ou da mesma data) que a declaração, prevalece
    (vermelho); se a declaração for mais recente, é conflito (amarelo).
    """
    if proprio is not None and proprio.semaforo == Semaforo.VERDE:
        return proprio, None
    sic = _sicaf_para(tipo, compat, contrato)
    if sic is None:
        if proprio is not None:
            return proprio, None
        msg = "Não enviada."
        if compat:
            msg += " A declaração do SICAF enviada não traz esta certidão."
        elif incompat:
            msg += (" A declaração do SICAF enviada é de outro CNPJ ("
                    + ", ".join(formatar_cnpj(c.cnpj) for c in incompat) + "): não utilizada.")
        return ItemChecklist(tipo, Semaforo.VERMELHO, msg), None
    s_sem, s_msg = avaliar_sicaf(sic, tipo, contrato, hoje, dias_alerta)
    if proprio is None:
        return ItemChecklist(tipo, s_sem, s_msg, sic), sic
    arq = os.path.basename(proprio.certidao.arquivo) if proprio.certidao else "certidão própria"
    pos = _positiva_vigente(cands, contrato)
    if pos is not None and s_sem != Semaforo.VERMELHO:
        arq_pos = os.path.basename(pos.arquivo)
        d_pos, d_sic = pos.data_emissao, sic.data_emissao
        if d_pos is not None and d_sic is not None and d_sic > d_pos:
            msg = (f"Atenção, conflito: certidão própria POSITIVA de {formatar_data(d_pos)}; "
                   f"SICAF de {formatar_data(d_sic)} indica regular — confira no site do emissor "
                   f"(certidão própria: {arq_pos}). {s_msg}")
            return ItemChecklist(tipo, _pior(s_sem, Semaforo.AMARELO), msg, sic), sic
        if d_pos is None or d_sic is None:
            motivo = (
                f"Certidão própria POSITIVA ({arq_pos}"
                + (f", emitida em {formatar_data(d_pos)}" if d_pos else ", emissão não identificada")
                + ") e declaração do SICAF"
                + (f" de {formatar_data(d_sic)}" if d_sic else " sem data de emissão")
                + ": não é possível afirmar que a declaração é mais recente — prevalece a mais recente "
                "(a certidão do emissor) até conferência no site do emissor."
            )
        elif d_pos == d_sic:
            motivo = (f"Certidão própria POSITIVA emitida em {formatar_data(d_pos)} ({arq_pos}) é da mesma "
                      f"data da declaração do SICAF — prevalece a mais recente (a certidão do emissor).")
        else:
            motivo = (f"Certidão própria POSITIVA emitida em {formatar_data(d_pos)} é mais recente que a "
                      f"declaração do SICAF de {formatar_data(d_sic)} — prevalece a mais recente ({arq_pos}).")
        msg = f"{motivo} {proprio.mensagem} Declaração do SICAF (não prevaleceu): {s_msg}"
        return ItemChecklist(tipo, Semaforo.VERMELHO, msg, pos), None
    if proprio.semaforo == Semaforo.VERMELHO and _ORDEM[s_sem] < _ORDEM[proprio.semaforo]:
        msg = f"{s_msg} Certidão própria enviada ({arq}) não utilizada: {proprio.mensagem}"
        return ItemChecklist(tipo, s_sem, msg, sic), sic
    return ItemChecklist(tipo, proprio.semaforo, f"{proprio.mensagem} SICAF: {s_msg}", proprio.certidao), None


# ---------------------------------------------------------------- API

def validar(
    contrato: Contrato,
    certidoes: list[Certidao],
    hoje: date | None = None,
    dias_alerta: int = 15,
) -> ResultadoValidacao:
    hoje = hoje or date.today()
    itens: list[ItemChecklist] = []
    usadas_ids: set[int] = set()
    compat, incompat = _sicafs_compativeis(certidoes, contrato)

    for tipo in contrato.exigidas:
        cands = [c for c in certidoes if c.tipo == tipo]
        proprio: Optional[ItemChecklist] = None
        usadas: list[Certidao] = []
        if cands:
            if tipo == TipoCertidao.ESTADUAL and contrato.uf_sede.strip().upper() == "SP":
                proprio, usadas = _item_estadual_sp(cands, contrato, hoje, dias_alerta)
            else:
                melhor = _melhor(cands, contrato, hoje, dias_alerta)
                sem, msg = _avaliar_no_grupo(melhor, cands, contrato, hoje, dias_alerta)
                proprio, usadas = ItemChecklist(tipo, sem, msg, melhor), [melhor]
        if contrato.aceitar_sicaf and tipo in COBERTOS_SICAF:
            item, sic = _combinar_sicaf(tipo, cands, proprio, compat, incompat, contrato, hoje, dias_alerta)
            if sic is not None:
                usadas = [sic]
        else:
            item = proprio or ItemChecklist(tipo, Semaforo.VERMELHO, "Não enviada.")
        itens.append(item)
        usadas_ids.update(id(c) for c in usadas)

    extras = [c for c in certidoes if id(c) not in usadas_ids]
    # a certidão do item vem primeiro; complementares (SP) também ficam nos extras
    principais = {id(i.certidao) for i in itens if i.certidao is not None}
    for c in certidoes:
        if id(c) in usadas_ids and id(c) not in principais and c not in extras:
            extras.append(c)
    return ResultadoValidacao(contrato=contrato, data_referencia=hoje, itens=itens, extras=extras)


def _complementa_sp(cert: Certidao, resultado: ResultadoValidacao) -> bool:
    contrato = resultado.contrato
    return (
        cert.tipo == TipoCertidao.ESTADUAL
        and contrato.uf_sede.strip().upper() == "SP"
        and TipoCertidao.ESTADUAL in contrato.exigidas
        and _local(cert, contrato) >= 1
        and _subtipo_sp(cert) is not None
        and any(i.tipo == TipoCertidao.ESTADUAL and i.certidao is not None
                and i.certidao.tipo == TipoCertidao.ESTADUAL
                and i.certidao is not cert and _subtipo_sp(i.certidao) != _subtipo_sp(cert)
                for i in resultado.itens)
    )


def alerta_extra(cert: Certidao, resultado: ResultadoValidacao) -> str:
    """Alerta explícito para certidão extra POSITIVA ou vencida ("" se não houver)."""
    if _complementa_sp(cert, resultado):
        return ""  # já avaliada dentro do item Fazenda Estadual
    exigida = cert.tipo in resultado.contrato.exigidas
    complemento = "não utilizada no checklist" if exigida else "embora não exigida"
    partes = []
    if cert.situacao == Situacao.POSITIVA:
        partes.append(f"Atenção: certidão POSITIVA enviada, {complemento} — avaliar.")
    if cert.validade is not None and cert.validade < resultado.data_referencia:
        partes.append(
            f"Atenção: certidão vencida em {formatar_data(cert.validade)} enviada, "
            f"{complemento} — avaliar."
        )
    return " ".join(partes)


def nota_extra(cert: Certidao, resultado: ResultadoValidacao) -> str:
    """Explica por que uma certidão ficou fora do checklist principal."""
    alerta = alerta_extra(cert, resultado)
    base = _nota_extra_base(cert, resultado)
    return f"{alerta} {base}" if alerta else base


def _nota_extra_base(cert: Certidao, resultado: ResultadoValidacao) -> str:
    contrato = resultado.contrato
    exigidas = set(contrato.exigidas)
    if cert.tipo == TipoCertidao.SICAF and TipoCertidao.SICAF not in exigidas:
        if not contrato.aceitar_sicaf:
            return (
                "SICAF enviado, mas não exigido. Pode comprovar federal, FGTS e trabalhista (e "
                "estadual/municipal quando constarem); marque 'Aceitar SICAF' para usar a declaração "
                "como comprovação — o fiscal decide."
            )
        if _relacao_cnpj(cert, contrato) == "diferente":
            return (
                f"Declaração do SICAF de outro CNPJ ({formatar_cnpj(cert.cnpj)}): não utilizada "
                "como comprovação."
            )
        if not _itens_sicaf(cert):
            return "Declaração do SICAF sem itens de regularidade identificados: conferir manualmente."
        if any("SICAF" in i.mensagem for i in resultado.itens):
            return ("Declaração do SICAF considerada nos itens, mas não prevaleceu "
                    "(ver mensagens dos itens).")
        return "SICAF enviado e aceito, mas não utilizado: as certidões próprias já comprovam os itens."
    if _complementa_sp(cert, resultado):
        return (
            f"Complementa o item Fazenda Estadual (certidão {ROTULO_SP[_subtipo_sp(cert)]}); "
            "avaliada no item."
        )
    if cert.tipo in exigidas:
        if any(i.tipo == cert.tipo and i.certidao is not None
               and i.certidao.tipo == TipoCertidao.SICAF for i in resultado.itens):
            return ("Certidão própria não utilizada: o item foi comprovado pela declaração do SICAF "
                    "(ver mensagem do item).")
        return "Outra certidão do mesmo tipo; não utilizada porque havia opção melhor."
    if cert.tipo == TipoCertidao.DESCONHECIDA:
        return "Documento não identificado: conferir manualmente."
    return "Não corresponde a certidão exigida no contrato."


def resumo(resultado: ResultadoValidacao) -> dict:
    cont = {s.value: 0 for s in Semaforo}
    for i in resultado.itens:
        cont[i.semaforo.value] += 1
    return {
        **cont,
        "total": len(resultado.itens),
        "extras": len(resultado.extras),
        "apto_atesto": resultado.apto_atesto,
    }
