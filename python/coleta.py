"""Painel de Conjuntura PREVIMPA - coleta dos dados.

Baixa as séries usadas pelo Comitê de Investimentos da PREVIMPA e grava os CSV de dados/ (vírgula,
ponto decimal, datas ISO):

  precos.csv        IPCA, abertura, núcleos e IGPs (BCB/SGS; FGV IBRE e IBGE via SGS), desde 2015
  meta.csv          metas de inflação do CMN e meta atuarial da PREVIMPA
  focus_anual.csv   Focus anual (mediana), últimas 26 semanas, ano corrente e os três seguintes
  focus_selic.csv   Focus da Selic por reunião do Copom (pesquisa mais recente e a de 4 semanas antes)
  focus_12m.csv     Focus da inflação 12 meses à frente (IPCA e IGP-M, suavizada)
  copom.csv         probabilidades das opções de Copom da B3, próximas reuniões, últimos 30 pregões
  juros.csv         meta Selic, CDI e dólar PTAX, diários, desde 2024
  bolsa.csv         Ibovespa e IFIX (B3) e S&P 500 (FRED), fechamentos diários, desde 2024
  titulos.csv       taxas indicativas ANBIMA de LTN, NTN-F e NTN-B (acumulado: a ANBIMA só publica 5 dias)
  ettj.csv          curva de juros ANBIMA (ETTJ) prefixada, real (IPCA) e inflação implícita (acumulado)
  ima.csv           quadro-resumo dos índices IMA da ANBIMA (acumulado)

Os arquivos "acumulados" guardam tudo o que já foi baixado: cada execução lê o CSV anterior, junta os
dias novos e grava de novo. Por isso o robô do GitHub também publica a pasta dados/.

Uso: python3 python/coleta.py
"""
import base64
import csv
import json
import subprocess
import time
from datetime import date, timedelta
from pathlib import Path

PASTA = Path(__file__).resolve().parent.parent
DADOS = PASTA / "dados"
HOJE = date.today()
INICIO = "2015-01-01"
NAVEGADOR = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120 Safari/537.36"

# Metas de inflação do CMN: centro e intervalo de tolerância (p.p.); meta contínua de 3% desde 2025
METAS = {2015: (4.5, 2.0), 2016: (4.5, 2.0), 2017: (4.5, 1.5), 2018: (4.5, 1.5), 2019: (4.25, 1.5),
         2020: (4.0, 1.5), 2021: (3.75, 1.5), 2022: (3.5, 1.5), 2023: (3.25, 1.5), 2024: (3.0, 1.5),
         2025: (3.0, 1.5), 2026: (3.0, 1.5), 2027: (3.0, 1.5), 2028: (3.0, 1.5)}
# Meta atuarial da PREVIMPA: IPCA + juro real (% a.a.), conforme a Política de Investimentos de cada ano
META_ATUARIAL = {2026: 5.30}


# ---------- download ----------
def curl(url, dados=None, tentativas=5, agente=NAVEGADOR):
    """Corpo da resposta (texto), pelo curl do sistema. Repete com espera crescente se a fonte falhar."""
    for i in range(tentativas):
        cmd = ["curl", "-sL", "-m", "180", "-A", agente, "-w", "\n%{http_code}", url]
        if dados:
            cmd += ["-X", "POST", "-d", dados]
        r = subprocess.run(cmd, capture_output=True)
        corpo, _, codigo = r.stdout.rpartition(b"\n")
        if codigo == b"200":            # corpo vazio = a fonte não tem dado para o dia (ANBIMA em feriado)
            try:
                return corpo.decode("utf-8")
            except UnicodeDecodeError:
                return corpo.decode("latin-1")
        if codigo == b"404":
            return None
        if i < tentativas - 1:
            espera = min(10 * 2 ** i, 120)
            print(f"  sem resposta de {url[:70]}... (HTTP {codigo.decode() or 'nenhum'}); de novo em {espera} s", flush=True)
            time.sleep(espera)
    raise RuntimeError(f"Fonte não respondeu em {tentativas} tentativas: {url}")


def baixar_json(url):
    for i in range(3):
        texto = curl(url)
        try:
            return json.loads(texto)
        except (TypeError, ValueError):
            time.sleep(15)
    raise RuntimeError(f"Resposta não é JSON: {url}")


def sgs(codigo, inicio="01/01/2013", fim=None):
    time.sleep(1.5)        # o SGS recusa quem pede muitas séries seguidas
    fim = fim or HOJE.strftime("%d/%m/%Y")
    x = baixar_json(f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{codigo}/dados?formato=json"
                    f"&dataInicial={inicio}&dataFinal={fim}")
    if not isinstance(x, list):
        raise RuntimeError(f"SGS {codigo}: {x}")
    return {f"{d['data'][6:10]}-{d['data'][3:5]}-{d['data'][:2]}": float(d["valor"]) for d in x if d["valor"] != ""}


def num_br(v):
    """'12.627,19' -> 12627.19; '--' ou vazio -> None."""
    v = (v or "").strip()
    if v in ("", "--", "-"):
        return None
    return float(v.replace(".", "").replace(",", "."))


def data_br(v):        # 23/10/2026 -> 2026-10-23
    return f"{v[6:10]}-{v[3:5]}-{v[:2]}"


def r4(v):
    return "" if v is None else round(v, 4)


def gravar(nome, colunas, linhas):
    with open(DADOS / f"{nome}.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(colunas)
        w.writerows(linhas)
    print(f"{nome:14s} {len(linhas):6d} linhas", flush=True)


def ler(nome):
    arq = DADOS / f"{nome}.csv"
    if not arq.exists():
        return []
    with open(arq, encoding="utf-8") as f:
        return list(csv.reader(f))[1:]


def acumular(nome, colunas, novas, chave):
    """Junta as linhas novas às já gravadas; em chave repetida, vale a linha nova."""
    todas = {tuple(l[i] for i in chave): l for l in ler(nome)}
    for l in novas:
        todas[tuple(str(l[i]) for i in chave)] = [str(x) for x in l]
    gravar(nome, colunas, sorted(todas.values()))


def dias_uteis_recentes(n=8):
    """Últimos n dias de semana até hoje (feriados a fonte simplesmente não tem)."""
    d, out = HOJE, []
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return out


def acum12(serie):
    datas, out = sorted(serie), {}
    for i in range(11, len(datas)):
        p = 1.0
        for d in datas[i - 11:i + 1]:
            p *= 1 + serie[d] / 100
        out[datas[i]] = (p - 1) * 100
    return out


def acum_ano(serie):
    out, p, ano = {}, 1.0, None
    for d in sorted(serie):
        if d[:4] != ano:
            p, ano = 1.0, d[:4]
        p *= 1 + serie[d] / 100
        out[d] = (p - 1) * 100
    return out


# ---------- preços: IPCA, núcleos e IGPs ----------
SERIES_PRECOS = {
    "IPCA": 433, "IPCA livres": 11428, "IPCA administrados": 4449, "IPCA serviços": 10844,
    "IPCA bens industriais": 27863,
    "Núcleo EX0": 11427, "Núcleo EX3": 27839, "Núcleo MS": 4466, "Núcleo DP": 16122, "Núcleo P55": 28750,
    "Núcleo EX-FE": 28751,
    "IGP-M": 189, "IGP-DI": 190, "IGP-10": 7447, "IPA-M": 7450, "IPC-M": 7453, "INCC-M": 7456,
    "IPA-DI agropecuário": 7460, "IPA-DI industrial": 7459, "IPC-Fipe": 193,
}
NUCLEOS_BCB = ["Núcleo EX0", "Núcleo EX3", "Núcleo MS", "Núcleo DP", "Núcleo P55"]   # os 5 do Relatório de Política Monetária


def precos():
    s = {nome: sgs(cod) for nome, cod in SERIES_PRECOS.items()}
    s["Média dos 5 núcleos"] = {d: sum(s[n][d] for n in NUCLEOS_BCB) / 5
                                for d in s[NUCLEOS_BCB[0]] if all(d in s[n] for n in NUCLEOS_BCB)}
    difusao = sgs(21379)
    linhas = []
    for nome, serie in s.items():
        a12, aa = acum12(serie), acum_ano(serie)
        linhas += [[d, nome, r4(round(serie[d], 2)), r4(a12.get(d) and round(a12[d], 2)), r4(round(aa[d], 2))]
                   for d in serie]
    linhas += [[d, "Índice de difusão", r4(v), "", ""] for d, v in difusao.items()]
    gravar("precos", ["data", "serie", "var_mensal", "var_12m", "var_ano"], sorted(l for l in linhas if l[0] >= INICIO))
    gravar("meta", ["ano", "centro", "tolerancia", "meta_atuarial_juro_real"],
           [[a, c, t, META_ATUARIAL.get(a, "")] for a, (c, t) in METAS.items()])


# ---------- Focus ----------
OLINDA = "https://olinda.bcb.gov.br/olinda/servico/Expectativas/versao/v1/odata/"
IND_FOCUS = ["IPCA", "IPCA Administrados", "IGP-M", "PIB Total", "Câmbio", "Selic",
             "Resultado primário", "Dívida líquida do setor público"]


def olinda(recurso, filtro, top=10000):
    q = (f"{OLINDA}{recurso}?$top={top}&$format=json&$orderby=Data%20desc&$filter="
         + filtro.replace(" ", "%20").replace("'", "%27"))
    return baixar_json(q)["value"]


def focus():
    desde = (HOJE - timedelta(weeks=26)).isoformat()
    anos = [str(HOJE.year + k) for k in range(4)]
    filtro_ind = " or ".join(f"Indicador eq '{i}'" for i in IND_FOCUS)
    x = olinda("ExpectativasMercadoAnuais", f"Data ge '{desde}' and baseCalculo eq 0 and ({filtro_ind})")
    # o Focus publica às segundas com a pesquisa da sexta; fica só uma linha por semana (a sexta)
    linhas = sorted([r["Indicador"], r["DataReferencia"], r["Data"], r4(r["Mediana"]), r["numeroRespondentes"]]
                    for r in x if r["DataReferencia"] in anos and date.fromisoformat(r["Data"]).weekday() == 4)
    gravar("focus_anual", ["indicador", "ano", "data", "mediana", "respondentes"], linhas)

    x = olinda("ExpectativasMercadoSelic", f"Data ge '{(HOJE - timedelta(weeks=6)).isoformat()}' and baseCalculo eq 0")
    sextas = sorted({r["Data"] for r in x if date.fromisoformat(r["Data"]).weekday() == 4})
    ult = sextas[-1]
    antes = max(d for d in sextas if d <= (date.fromisoformat(ult) - timedelta(weeks=4)).isoformat())
    linhas = []
    for r in x:
        if r["Data"] in (ult, antes):
            n, a = r["Reuniao"][1:].split("/")          # R8/2026 -> ordem 2026-08
            linhas.append([r["Reuniao"], f"{a}-{int(n):02d}", r["Data"], r4(r["Mediana"]), r["numeroRespondentes"]])
    gravar("focus_selic", ["reuniao", "ordem", "data", "mediana", "respondentes"], sorted(linhas, key=lambda l: (l[2], l[1])))

    # IPCA mensal esperado: completa a meta atuarial nos meses em que o IPCA ainda não saiu
    x = olinda("ExpectativaMercadoMensais",
               f"Data ge '{(HOJE - timedelta(days=10)).isoformat()}' and baseCalculo eq 0 and Indicador eq 'IPCA'")
    ult = max(r["Data"] for r in x)
    linhas = sorted([f"{r['DataReferencia'][3:]}-{r['DataReferencia'][:2]}-01", r["Data"], r4(r["Mediana"])]
                    for r in x if r["Data"] == ult)
    gravar("focus_ipca_mensal", ["mes", "data", "mediana"], linhas)

    x = olinda("ExpectativasMercadoInflacao12Meses",
               f"Data ge '{(HOJE - timedelta(days=730)).isoformat()}' and baseCalculo eq 0 and Suavizada eq 'S'")
    linhas = sorted([r["Indicador"], r["Data"], r4(r["Mediana"])] for r in x
                    if date.fromisoformat(r["Data"]).weekday() == 4)
    gravar("focus_12m", ["indicador", "data", "mediana"], linhas)


# ---------- opções de Copom (B3) ----------
def copom():
    base = "https://arquivos.b3.com.br/charts/chart/"
    ref = HOJE.isoformat()
    reunioes = baixar_json(base + "meetings/" + ref)
    selic = baixar_json(base + "selic/" + ref)
    linhas = []
    for r in reunioes[:4]:
        for o in baixar_json(f"{base}copom/{ref}/{r['dateRef']}?qt=30"):
            linhas.append([r["dateRef"], r["meetingDt"], o["rptDt"], o["scnroNm"], r4(o["refPric"]), o["opnIntrst"]])
    gravar("copom", ["reuniao", "reuniao_nome", "data", "cenario", "prob", "contratos_abertos"], sorted(linhas))
    (DADOS / "selic_b3.txt").write_text(f"{selic}\n", encoding="utf-8")


# ---------- juros e câmbio diários ----------
def juros():
    selic = sgs(432, "01/01/2024")
    cdi = sgs(12, "01/01/2024")          # CDI, % ao dia
    dolar = sgs(1, "01/01/2024")         # PTAX venda
    linhas = [[d, r4(selic.get(d)), r4(cdi.get(d)), r4(dolar.get(d))]
              for d in sorted(set(selic) | set(cdi) | set(dolar)) if d <= HOJE.isoformat()]
    gravar("juros", ["data", "selic_meta", "cdi_dia", "dolar"], linhas)


# ---------- bolsa: Ibovespa, IFIX e S&P 500 ----------
def b3_indice(indice, ano):
    p = base64.b64encode(json.dumps({"index": indice, "language": "pt-br", "year": str(ano)}).encode()).decode()
    x = baixar_json(f"https://sistemaswebb3-listados.b3.com.br/indexStatisticsProxy/IndexCall/GetPortfolioDay/{p}")
    out = {}
    for linha in x.get("results", []):
        for m in range(1, 13):
            v = num_br(linha.get(f"rateValue{m}"))
            if v is not None:
                out[f"{ano}-{m:02d}-{linha['day']:02d}"] = v
    return out


def bolsa():
    linhas = []
    for indice, nome in [("IBOV", "Ibovespa"), ("IFIX", "IFIX")]:
        for ano in range(2024, HOJE.year + 1):
            linhas += [[d, nome, v] for d, v in b3_indice(indice, ano).items()]
    txt = curl("https://fred.stlouisfed.org/graph/fredgraph.csv?id=SP500&cosd=2024-01-01", agente="curl/8")
    for l in txt.splitlines()[1:]:
        d, v = l.split(",")
        if v not in ("", "."):
            linhas.append([d, "S&P 500 (US$)", float(v)])
    gravar("bolsa", ["data", "indice", "fechamento"], sorted(linhas))


# ---------- ANBIMA: títulos públicos, ETTJ e IMA (acumulados) ----------
def titulos():
    novas = []
    for d in dias_uteis_recentes():
        txt = curl(f"https://www.anbima.com.br/informacoes/merc-sec/arqs/ms{d:%y%m%d}.txt")
        if not txt or "@" not in txt:
            continue
        for l in txt.splitlines():
            c = l.split("@")
            if len(c) > 8 and c[0] in ("LTN", "NTN-F", "NTN-B"):
                dv = f"{c[4][:4]}-{c[4][4:6]}-{c[4][6:]}"
                novas.append([d.isoformat(), c[0], dv, num_br(c[7]), num_br(c[8])])
    if not novas:
        raise RuntimeError("ANBIMA sem arquivo de títulos nos últimos dias")
    acumular("titulos", ["data", "titulo", "vencimento", "taxa_indicativa", "pu"], novas, chave=(0, 1, 2))


def ettj():
    novas = []
    for d in dias_uteis_recentes():
        txt = curl("https://www.anbima.com.br/informacoes/est-termo/CZ-down.asp",
                   f"Idioma=PT&Dt_Ref={d:%d/%m/%Y}&saida=csv")
        if not txt or not txt.startswith(f"{d:%d/%m/%Y}"):
            continue
        tabela = False
        for l in txt.splitlines():
            c = l.split(";")
            if c[0].startswith("Vertices"):
                tabela = True
                continue
            if tabela:
                if len(c) < 2 or not c[0].strip() or not c[0].strip()[0].isdigit():
                    break
                novas.append([d.isoformat(), int(num_br(c[0])), r4(num_br(c[2])), r4(num_br(c[1])), r4(num_br(c[3]))])
    if not novas:
        raise RuntimeError("ANBIMA sem ETTJ nos últimos dias")
    acumular("ettj", ["data", "du", "prefixada", "ipca", "inflacao_implicita"], novas, chave=(0, 1))


def ima():
    novas = []
    for d in dias_uteis_recentes():
        txt = curl("https://www.anbima.com.br/informacoes/ima/ima-geral-down.asp",
                   f"Tipo=&DataRef=&Pai=ima&escolha=2&Idioma=PT&saida=csv&Dt_Ref_Ver={HOJE:%Y%m%d}&Dt_Ref={d:%d/%m/%Y}")
        if not txt or "QUADRO-RESUMO" not in txt:
            continue
        for l in txt.splitlines():
            c = l.split(";")
            if len(c) > 9 and c[1][:2].isdigit() and data_br(c[1]) == d.isoformat():
                novas.append([d.isoformat(), c[0], num_br(c[2]), num_br(c[3]), num_br(c[4]), num_br(c[5]),
                              num_br(c[6]), num_br(c[9])])
    if not novas:
        raise RuntimeError("ANBIMA sem IMA nos últimos dias")
    acumular("ima", ["data", "indice", "numero_indice", "var_dia", "var_mes", "var_ano", "var_12m", "duration_du"],
             novas, chave=(0, 1))


ETAPAS = (precos, focus, copom, juros, bolsa, titulos, ettj, ima)


def main():
    """Cada fonte roda separada: se uma não responder, fica o CSV anterior dela e as outras seguem.

    As fontes que falharam vão para falhas.txt; o robô do GitHub publica o resto e depois avisa.
    """
    DADOS.mkdir(exist_ok=True)
    falhas = []
    for etapa in ETAPAS:
        try:
            etapa()
        except Exception as e:
            print(f"FALHOU {etapa.__name__}: {e} (mantido o dado anterior)", flush=True)
            falhas.append(f"{etapa.__name__}: {e}")
    (PASTA / "falhas.txt").write_text("".join(f + "\n" for f in falhas), encoding="utf-8")
    print("Coleta concluída em", time.strftime("%d/%m/%Y %H:%M"),
          f"({len(falhas)} fonte(s) com falha)" if falhas else "")


if __name__ == "__main__":
    main()
