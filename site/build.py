"""Monta a versão que roda no navegador em site/dist (publicável como página estática).

Uso:  python site/build.py [--pyodide PASTA]
  --pyodide  pasta com os arquivos do pacote npm `pyodide@0.27.7` (pyodide.js, pyodide.asm.js,
             pyodide.asm.wasm, python_stdlib.zip, pyodide-lock.json). Sem ela, o script baixa o
             pacote com `npm pack`.

Gera também site/dist/files.json: o mapa caminho publicado -> arquivo local (com o tipo de
conteúdo quando a extensão não basta), usado para publicar.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
from datetime import date
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SITE = RAIZ / "site"
DIST = SITE / "dist"
PYODIDE_VERSAO = "0.27.7"
PY_ARQUIVOS = ["__init__.py", "models.py", "extrator.py", "validador.py", "planejamento.py",
               "portais.py", "atesto.py", "navegador.py"]
EXEMPLOS = ["federal_negativa", "fgts_regular", "cndt_positiva", "estadual_sp_pge",
            "estadual_sp_sefaz", "municipal_sp", "cnpj_divergente"]


def _pyodide(pasta: str | None) -> Path:
    if pasta:
        return Path(pasta)
    tmp = Path(tempfile.mkdtemp(prefix="pyodide_"))
    subprocess.run(["npm", "pack", f"pyodide@{PYODIDE_VERSAO}", "-q"], cwd=tmp, check=True)
    with tarfile.open(next(tmp.glob("pyodide-*.tgz"))) as t:
        t.extractall(tmp, filter="data")
    return tmp / "package"


def _csv_exemplo(destino: Path) -> None:
    sys.path.insert(0, str(RAIZ))
    from certidoes.atesto import gerar_csv
    from certidoes.extrator import ler_pdf
    from certidoes.models import Contrato, TipoCertidao as T
    from certidoes.validador import validar

    am = RAIZ / "tests" / "amostras"
    if not (am / "federal_negativa.pdf").exists():
        from tests.gerar_amostras import gerar
        gerar(am)
    esperado = json.loads((am / "esperado.json").read_text(encoding="utf-8"))["arquivos"]
    outro = esperado["cnpj_divergente.pdf"]["cnpj"]
    tipos = [T.FEDERAL, T.FGTS, T.TRABALHISTA, T.ESTADUAL, T.MUNICIPAL]
    c1 = Contrato("045/2026", "12345678000195", "EMPRESA EXEMPLO DE SERVIÇOS LTDA", "SP", "São Paulo",
                  fiscal="Fiscal de Exemplo", competencia="09/2026", exigidas=tipos)
    c2 = Contrato("051/2026", outro, "OUTRA EMPRESA EXEMPLO LTDA", "RJ", "Rio de Janeiro",
                  fiscal="Fiscal de Exemplo", competencia="09/2026", exigidas=tipos)
    r1 = validar(c1, [ler_pdf(am / f"{n}.pdf") for n in
                      ["federal_negativa", "fgts_regular", "cndt_negativa", "estadual_sp_pge", "municipal_sp"]])
    r2 = validar(c2, [ler_pdf(am / "cnpj_divergente.pdf")])
    gerar_csv([r1, r2], str(destino))


def montar(pasta_pyodide: str | None = None) -> dict:
    if DIST.exists():
        shutil.rmtree(DIST)
    (DIST / "py" / "certidoes").mkdir(parents=True)
    (DIST / "py" / "data").mkdir(parents=True)
    (DIST / "exemplos").mkdir()
    arquivos: dict[str, object] = {}

    def copiar(origem: Path, publicado: str, tipo: str | None = None):
        alvo = DIST / publicado
        alvo.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(origem, alvo)
        if publicado != "index.html":
            arquivos[publicado] = {"from": str(alvo), "contentType": tipo} if tipo else str(alvo)

    for nome in ["index.html", "app.css", "app.js", "texto_pdf.js", "pdf_atesto.js"]:
        copiar(SITE / "src" / nome, nome)
    for f in sorted((SITE / "vendor").rglob("*")):
        if f.is_file():
            copiar(f, "vendor/" + f.relative_to(SITE / "vendor").as_posix(),
                   "text/plain" if f.suffix.lower() not in {".css", ".js", ".woff2", ".txt"} else None)
    pyo = _pyodide(pasta_pyodide)
    for nome in ["pyodide.js", "pyodide.asm.js", "pyodide.asm.wasm", "pyodide-lock.json"]:
        copiar(pyo / nome, "py/" + nome)
    # .zip não é um tipo servido: vai com extensão binária aceita (o Pyodide lê os bytes)
    copiar(pyo / "python_stdlib.zip", "py/python_stdlib.zip.wasm")
    for nome in PY_ARQUIVOS:
        copiar(RAIZ / "certidoes" / nome, f"py/certidoes/{nome}", "text/plain")
    copiar(RAIZ / "data" / "portais.json", "py/data/portais.json")
    for n in EXEMPLOS:
        copiar(RAIZ / "tests" / "amostras" / f"{n}.pdf", f"exemplos/{n}.pdf")
    _csv_exemplo(DIST / "exemplos" / "controle_exemplo.csv")
    arquivos["exemplos/controle_exemplo.csv"] = str(DIST / "exemplos" / "controle_exemplo.csv")
    (DIST / "files.json").write_text(json.dumps(arquivos, indent=1, ensure_ascii=False), encoding="utf-8")
    return arquivos


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--pyodide")
    a = ap.parse_args()
    m = montar(a.pyodide)
    total = sum((DIST / k).stat().st_size for k in m) + (DIST / "index.html").stat().st_size
    print(f"{len(m) + 1} arquivos, {total / 1048576:.1f} MB em {DIST} ({date.today():%d/%m/%Y})")
