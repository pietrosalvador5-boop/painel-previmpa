"""Painel de Conjuntura PREVIMPA - gera a página em um único arquivo HTML.

Junta pagina/index.html, os CSV de dados/ (gerados por coleta.py), a biblioteca d3 (pagina/vendor/d3.min.js)
o brasão da PUCRS e o logotipo da PREVIMPA (pagina/img/) em offline/Painel_PREVIMPA.html e copia para index.html
na raiz do site (pasta site/ no computador; raiz do repositório no GitHub). Abre sem internet.

Uso: python3 python/gerar_site.py
"""
import base64
import csv
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

PASTA = Path(__file__).resolve().parent.parent
DADOS, PAGINA = PASTA / "dados", PASTA / "pagina"
SAIDA = PASTA / "offline" / "Painel_PREVIMPA.html"
DATASETS = ["precos", "meta", "focus_anual", "focus_selic", "focus_ipca_mensal", "focus_12m", "copom",
            "juros", "bolsa", "titulos", "ettj", "ima", "ntnb_bcb"]


def main():
    dados = {}
    for ds in DATASETS:
        arq = DADOS / f"{ds}.csv"
        if not arq.exists():
            continue
        with open(arq, encoding="utf-8") as f:
            r = csv.DictReader(f)
            dados[ds] = {"columns": r.fieldnames, "rows": list(r)}
    html = (PAGINA / "index.html").read_text(encoding="utf-8")
    brasao = base64.b64encode((PAGINA / "img" / "brasao_pucrs.png").read_bytes()).decode()
    previmpa = base64.b64encode((PAGINA / "img" / "previmpa_branco.png").read_bytes()).decode()
    agora = datetime.now(ZoneInfo("America/Sao_Paulo"))
    html = (html.replace("{{D3}}", (PAGINA / "vendor" / "d3.min.js").read_text(encoding="utf-8"))
                .replace("{{DADOS}}", json.dumps(dados, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/"))
                .replace("{{BRASAO}}", f"data:image/png;base64,{brasao}")
                .replace("{{LOGO_PREVIMPA}}", f"data:image/png;base64,{previmpa}")
                .replace("{{GERADO}}", agora.strftime("%d/%m/%Y às %Hh%M")))
    SAIDA.parent.mkdir(exist_ok=True)
    SAIDA.write_text(html, encoding="utf-8")
    print("Salvo:", SAIDA, f"({len(html.encode()) / 1024:.0f} KB)")
    site = PASTA / "site"
    destino = site / "index.html" if site.is_dir() else PASTA / "index.html"
    destino.write_text(html, encoding="utf-8")
    print("Copiado para", destino.relative_to(PASTA))


if __name__ == "__main__":
    main()
