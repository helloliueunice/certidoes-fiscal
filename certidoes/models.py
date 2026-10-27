"""Contrato de dados compartilhado por todos os módulos.

NÃO altere nomes ou campos sem atualizar extrator, validador, atesto e app.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Optional


class TipoCertidao(str, Enum):
    FEDERAL = "federal"            # CND/CPEN Receita Federal + PGFN (tributos federais e dívida ativa da União)
    FGTS = "fgts"                  # CRF - Certificado de Regularidade do FGTS (Caixa)
    TRABALHISTA = "trabalhista"    # CNDT - Certidão Negativa de Débitos Trabalhistas (TST)
    ESTADUAL = "estadual"          # SEFAZ / PGE (débitos inscritos ou não inscritos em dívida ativa)
    MUNICIPAL = "municipal"        # Prefeitura (tributos mobiliários / ISS)
    SICAF = "sicaf"                # Declaração de situação do fornecedor no SICAF
    OUTRA = "outra"                # CEIS/CNEP, TCU, CNJ improbidade etc.
    DESCONHECIDA = "desconhecida"

    @property
    def rotulo(self) -> str:
        return {
            "federal": "Receita Federal / PGFN",
            "fgts": "FGTS (CRF - Caixa)",
            "trabalhista": "Trabalhista (CNDT - TST)",
            "estadual": "Fazenda Estadual",
            "municipal": "Fazenda Municipal",
            "sicaf": "SICAF",
            "outra": "Outra certidão",
            "desconhecida": "Não identificada",
        }[self.value]


class Situacao(str, Enum):
    NEGATIVA = "negativa"                          # sem débitos
    POSITIVA_EFEITO_NEGATIVA = "positiva_efeito_negativa"  # débitos suspensos/parcelados: aceita
    POSITIVA = "positiva"                          # débitos exigíveis: NÃO aceita
    REGULAR = "regular"                            # CRF do FGTS / SICAF regular
    INDETERMINADA = "indeterminada"

    @property
    def aceita(self) -> bool:
        return self in (Situacao.NEGATIVA, Situacao.POSITIVA_EFEITO_NEGATIVA, Situacao.REGULAR)


class Semaforo(str, Enum):
    VERDE = "verde"        # válida e aceita
    AMARELO = "amarelo"    # aceita, mas vence em <= dias_alerta, ou exige conferência manual
    VERMELHO = "vermelho"  # vencida, positiva, CNPJ divergente ou faltante


@dataclass
class Certidao:
    """Resultado da leitura de UM arquivo PDF."""
    arquivo: str
    tipo: TipoCertidao = TipoCertidao.DESCONHECIDA
    situacao: Situacao = Situacao.INDETERMINADA
    cnpj: Optional[str] = None            # só dígitos, 14 caracteres
    razao_social: Optional[str] = None
    orgao_emissor: Optional[str] = None   # ex.: "Receita Federal / PGFN", "SEFAZ-SP", "Prefeitura de São Paulo"
    uf: Optional[str] = None              # para estaduais/municipais, sigla da UF
    municipio: Optional[str] = None
    data_emissao: Optional[date] = None
    validade: Optional[date] = None
    codigo_controle: Optional[str] = None
    url_verificacao: Optional[str] = None
    metodo: str = "regras"                # "regras" ou "ia"
    confianca: float = 0.0                # 0..1
    avisos: list[str] = field(default_factory=list)
    texto: str = field(default="", repr=False)


@dataclass
class Contrato:
    numero: str
    cnpj: str                              # só dígitos
    razao_social: str
    uf_sede: str
    municipio_sede: str
    fiscal: str = ""
    gestor: str = ""
    objeto: str = ""
    competencia: str = ""                  # ex.: "10/2026"
    exigidas: list[TipoCertidao] = field(default_factory=lambda: [
        TipoCertidao.FEDERAL, TipoCertidao.FGTS, TipoCertidao.TRABALHISTA,
        TipoCertidao.ESTADUAL, TipoCertidao.MUNICIPAL,
    ])


@dataclass
class ItemChecklist:
    tipo: TipoCertidao
    semaforo: Semaforo
    mensagem: str
    certidao: Optional[Certidao] = None


@dataclass
class ResultadoValidacao:
    contrato: Contrato
    data_referencia: date
    itens: list[ItemChecklist]
    extras: list[Certidao] = field(default_factory=list)   # PDFs lidos que não correspondem a item exigido

    @property
    def apto_atesto(self) -> bool:
        return all(i.semaforo != Semaforo.VERMELHO for i in self.itens)


def so_digitos(valor: str | None) -> str:
    return "".join(c for c in (valor or "") if c.isdigit())


def formatar_cnpj(cnpj: str | None) -> str:
    d = so_digitos(cnpj)
    if len(d) != 14:
        return cnpj or ""
    return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"


def cnpj_valido(cnpj: str | None) -> bool:
    d = so_digitos(cnpj)
    if len(d) != 14 or d == d[0] * 14:
        return False
    def dv(base: str, pesos: list[int]) -> str:
        s = sum(int(n) * p for n, p in zip(base, pesos))
        r = s % 11
        return "0" if r < 2 else str(11 - r)
    p1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    p2 = [6] + p1
    return d[12] == dv(d[:12], p1) and d[13] == dv(d[:13], p2)
