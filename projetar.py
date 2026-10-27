"""Projeções v1 e v2 a partir dos snapshots do coletor.

Para cada snapshot, em ordem de horário, reconstrói o estado da apuração naquele
momento (arquivo mais recente de cada município até ali) e projeta.

v1 (extrapolação por município):
  - município com seções apuradas: votos do candidato × eleitorado total /
    eleitorado das seções apuradas (o resto do município vota igual, com o mesmo
    comparecimento);
  - município sem nada apurado: eleitorado × votos por eleitor do candidato na UF
    (se ≥ COBERTURA_MIN_UF do eleitorado da UF estiver apurado), senão no Brasil
    (sem o exterior).

v2 (swing sobre o 1º turno, com faixa de incerteza): ver modelo_v2.py.

Correções de dado do TSE:
  - Exterior: tratado como a UF "zz" (total próprio + ATRASO) quando o TSE publica o
    total do exterior. Antes disso (no começo da noite o arquivo zz ficou parado),
    br − 27 UFs − cidades zz com dado vira a linha zz/RESID, projetada sobre o
    eleitorado das cidades zz sem dado.
  - Totais: o br pode ficar atrás das UFs (ou à frente); o apurado e os votos contados
    usam a soma das 27 UFs + exterior.
  - Atraso municipal: arquivos de votos por município podem vir mais velhos que o
    total da UF. A diferença (total da UF − soma dos municípios) vira a linha
    <uf>/ATRASO, já totalmente apurada, e o eleitorado correspondente sai dos
    municípios atrasados (diferença entre o est do -ab e o do arquivo de votos).

Saídas (em saida/, CSV com ; e vírgula decimal):
  historico.csv   uma linha por horário × candidato
  municipios.csv  estado atual, uma linha por município × candidato
  painel.html     painel para acompanhar (painel.py), recarrega a cada 1 min
  modelo.html     painel técnico para conferir o modelo (v1, v2, faixa, por UF)

Uso:
  py projetar.py         # calcula uma vez
  py projetar.py --loop  # processa cada snapshot novo assim que aparece
"""
import argparse
import gzip
import json
import os
import re
import shutil
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

import modelo_v2
import painel

RAIZ = Path(__file__).parent
SNAPS = RAIZ / "dados" / "snapshots"
CONFIG_MUN = RAIZ / "dados" / "config" / "mun-e006258-cm.json"
SAIDA = RAIZ / "saida"
PUBLICO = SAIDA / "publico"
INTERVALO_S = 15  # só checa se há snapshot novo; sem novo, não faz nada
COBERTURA_MIN_UF = 0.01
UFS_BR = ["ac", "al", "am", "ap", "ba", "ce", "df", "es", "go", "ma", "mg", "ms", "mt", "pa",
          "pb", "pe", "pi", "pr", "rj", "rn", "ro", "rr", "rs", "sc", "se", "sp", "to"]
UFS_TOT = UFS_BR + ["zz"]
ARQ_MUN = re.compile(r"^[a-z]{2}\d{5}-")


def num(x):
    return int(x) if x not in ("", None) else 0


def ler_municipios():
    """(uf, cod_tse) -> (nome, cod_ibge)"""
    cfg = json.loads(CONFIG_MUN.read_text(encoding="utf-8"))
    return {(uf["cd"], m["cd"]): (m["nm"], m["cdi"]) for uf in cfg["abr"] for m in uf["mu"]}


def ler_u(caminho):
    """Arquivo de votos (município, UF ou Brasil) -> dict resumido."""
    d = json.loads(caminho.read_text(encoding="utf-8"))
    votos = {c["nmu"]: num(c["vap"])
             for a in d["carg"][0]["agr"] for p in a["par"] for c in p["cand"]}
    return {"st": num(d["s"]["st"]), "ts": num(d["s"]["ts"]),
            "te": num(d["e"]["te"]), "est": num(d["e"]["est"]),
            "tv": num(d["v"]["tv"]), "brancos": num(d["v"]["vb"]), "nulos": num(d["v"]["tvn"]),
            "votos": votos,
            # candidatos marcados como eleitos pelo TSE ("e" = "s")
            "eleitos": [c["nmu"] for a in d["carg"][0]["agr"] for p in a["par"] for c in p["cand"]
                        if c.get("e") == "s"]}


def ler_ab(caminho):
    """Arquivo de andamento da UF -> {cod_mun: (ts, st, te, est)}"""
    bruto = gzip.decompress(caminho.read_bytes()) if caminho.suffix == ".gz" else caminho.read_bytes()
    return {a["cdabr"]: (num(a["s"]["ts"]), num(a["s"]["st"]), num(a["e"]["te"]), num(a["e"]["est"]))
            for a in json.loads(bruto)["abr"] if a.get("tpabr") == "mun"}


def montar_tabela(andamento, votos_mun, candidatos, br, uf_tot, resid_ant=None):
    """Estado atual por município, com as linhas de correção ATRASO e RESID.
    te0 = eleitorado original; te = eleitorado que o município ainda representa.
    Retorna (tabela, resíduo do exterior usado)."""
    linhas = []
    for (uf, mun), (ts, st, te, est_ab) in andamento.items():
        r = votos_mun.get((uf, mun))
        linhas.append({"uf": uf, "mun": mun, "ts": ts, "te": te, "te0": te, "est_ab": est_ab,
                       "st": r["st"] if r else 0, "est": r["est"] if r else 0,
                       **{k: (r[k] if r else 0) for k in ("tv", "brancos", "nulos")},
                       **{c: (r["votos"].get(c, 0) if r else 0) for c in candidatos}})
    df = pd.DataFrame(linhas)
    df["te"] = df["te"].astype(float)  # recebe redução fracionária no ajuste de atraso
    extras = []

    # atraso municipal: total da UF − soma dos municípios (exterior = UF "zz", quando o
    # TSE já publica o total dele)
    completo = len(uf_tot) == len(UFS_TOT)
    ext_publicado = completo and uf_tot["zz"]["st"] > 0
    if completo:
        for uf in UFS_TOT:
            if uf == "zz" and not ext_publicado:
                continue
            sel = df["uf"] == uf
            gap = {c: uf_tot[uf]["votos"].get(c, 0) - df.loc[sel, c].sum() for c in candidatos}
            gap_est = uf_tot[uf]["est"] - df.loc[sel, "est"].sum()
            gap_st = uf_tot[uf]["st"] - df.loc[sel, "st"].sum()
            if gap_est <= 0 or min(gap.values()) < 0:
                continue  # sem atraso, ou horários incompatíveis: não corrige
            # eleitorado do atraso sai primeiro dos municípios atrasados (est do -ab > est
            # do arquivo de votos); o que exceder sai do restante ainda não apurado da UF
            atrasado = (df.loc[sel, "est_ab"] - df.loc[sel, "est"]).clip(lower=0)
            if atrasado.sum() >= gap_est:
                reducao = atrasado * gap_est / atrasado.sum()
            else:
                livre = (df.loc[sel, "te"] - df.loc[sel, "est"] - atrasado).clip(lower=0)
                excesso = gap_est - atrasado.sum()
                if livre.sum() < excesso:
                    continue  # não cabe: horários incompatíveis, não corrige
                reducao = atrasado + livre * excesso / livre.sum()
            df.loc[sel, "te"] = df.loc[sel, "te"] - reducao
            extras.append({"uf": uf, "mun": "ATRASO", "ts": 0, "te": gap_est, "te0": 0,
                           "est_ab": gap_est, "st": gap_st, "est": gap_est, **gap,
                           **{k: max(0, uf_tot[uf][k] - df.loc[sel, k].sum())
                              for k in ("tv", "brancos", "nulos")}})

    # resíduo nacional: só enquanto o total do exterior (zz) não é publicado — br − 27 UFs
    # − cidades do exterior com dado. Se o deste ciclo for incoerente (br e UFs de
    # horários diferentes), usa o último válido, só se o conjunto de cidades do exterior
    # com dado próprio não mudou (senão contaria em dobro).
    resid = None
    sem_dado_ext = (df["uf"] == "zz") & (df["est"] == 0)
    ext_dado = df[(df["uf"] == "zz") & (df["est"] > 0)]
    cidades = frozenset(ext_dado["mun"])
    if ext_publicado:
        resid_ant = None
    elif br and completo:
        res = {c: br["votos"].get(c, 0) - sum(uf_tot[u]["votos"].get(c, 0) for u in UFS_BR)
               - ext_dado[c].sum() for c in candidatos}
        res_est = br["est"] - sum(uf_tot[u]["est"] for u in UFS_BR) - ext_dado["est"].sum()
        res_st = br["st"] - sum(uf_tot[u]["st"] for u in UFS_BR) - ext_dado["st"].sum()
        if res_est > 0 and min(res.values()) >= 0:
            resid = {"st": res_st, "est": res_est, "cidades": cidades, **res}
    if resid is None and resid_ant and resid_ant.get("cidades") == cidades:
        resid = resid_ant
    if resid and sem_dado_ext.any():
        ext = df[sem_dado_ext]
        df = df[~sem_dado_ext]
        extras.append({"uf": "zz", "mun": "RESID", "ts": ext["ts"].sum(), "te": ext["te"].sum(),
                       "te0": ext["te"].sum(), "est_ab": resid["est"],
                       **{c: resid.get(c, 0) for c in candidatos},
                       "st": resid["st"], "est": resid["est"],
                       "tv": sum(resid.get(c, 0) for c in candidatos), "brancos": 0, "nulos": 0})

    if extras:
        df = pd.concat([df, pd.DataFrame(extras)], ignore_index=True)
    return df, resid


def projetar_v1(df, candidatos):
    """Acrescenta proj_<candidato> (v1)."""
    df = df.copy()
    com_dado = df["est"] > 0
    nac = df[com_dado & (df["uf"] != "zz")]
    taxa_br = nac[candidatos].sum() / nac["est"].sum() if len(nac) else None
    g = df[com_dado].groupby("uf")
    taxa_uf = g[candidatos].sum().div(g["est"].sum(), axis=0)
    cobertura = g["est"].sum() / df.groupby("uf")["te0"].sum()
    taxa_uf = taxa_uf[cobertura.reindex(taxa_uf.index) >= COBERTURA_MIN_UF]

    for c in candidatos:
        df[f"proj_{c}"] = 0.0
        df.loc[com_dado, f"proj_{c}"] = df.loc[com_dado, c] * df.loc[com_dado, "te"] / df.loc[com_dado, "est"]
        if taxa_br is not None:
            taxa = df["uf"].map(taxa_uf[c]).fillna(taxa_br[c])
            df.loc[~com_dado, f"proj_{c}"] = df.loc[~com_dado, "te"] * taxa[~com_dado]
    return df


def snapshots_prontos():
    # só entra pasta com marcador de fim de ciclo ("ok" ou "incompleto"); sem marcador,
    # o coletor ainda está gravando
    if not SNAPS.exists():
        return []
    return sorted(p for p in SNAPS.iterdir()
                  if p.is_dir() and ((p / "ok").exists() or (p / "incompleto").exists()))


class Estado:
    """Estado acumulado entre rodadas do loop: cada snapshot é processado uma vez."""

    def __init__(self):
        self.vistos = set()
        self.tentativas = {}
        self.andamento, self.votos_mun, self.candidatos = {}, {}, []
        self.resid = None
        self.hist = []
        self.df = None
        self.br, self.uf_tot = None, {}  # totais do último snapshot completo


def calcular(estado):
    snaps = snapshots_prontos()
    novos = [s for s in snaps if s.name not in estado.vistos]
    if not novos:
        return
    nomes = ler_municipios()
    andamento, votos_mun, candidatos = estado.andamento, estado.votos_mun, estado.candidatos
    hist = estado.hist

    for snap in novos:
        # o snapshot só é marcado como visto depois de processado: se a leitura falhar
        # (ex.: arquivo travado pelo OneDrive), é relido na próxima rodada, até 3 vezes
        estado.tentativas[snap.name] = estado.tentativas.get(snap.name, 0) + 1
        if estado.tentativas[snap.name] > 3:
            print(f"snapshot {snap.name} pulado após 3 falhas de leitura", flush=True)
            estado.vistos.add(snap.name)
            continue
        uf_snap, br = {}, None  # totais de UF e Brasil valem só para o próprio ciclo
        for f in snap.glob("*-ab.json*"):
            uf = f.name[:2]
            for mun, v in ler_ab(f).items():
                andamento[(uf, mun)] = v
        for f in snap.glob("*-u.json"):
            if f.name.startswith("br-"):
                br = ler_u(f)
                continue
            if not ARQ_MUN.match(f.name):  # total de UF
                if f.name[:2] in UFS_TOT:
                    uf_snap[f.name[:2]] = ler_u(f)
                continue
            r = ler_u(f)
            chave = (f.name[:2], f.name[2:7])
            if chave in votos_mun and r["st"] < votos_mun[chave]["st"]:
                continue  # cache devolveu arquivo mais velho
            votos_mun[chave] = r
            for c in r["votos"]:
                if c not in candidatos:
                    candidatos.append(c)
        # linha no histórico só com br e os totais das 27 UFs + exterior do mesmo ciclo
        completo = (snap / "ok").exists() and br is not None and len(uf_snap) == len(UFS_TOT)
        if not completo or not candidatos or not andamento:
            estado.vistos.add(snap.name)
            continue

        base, estado.resid = montar_tabela(andamento, votos_mun, candidatos, br, uf_snap, estado.resid)
        df = projetar_v1(base, candidatos)
        v2, df = modelo_v2.projetar_v2(df, candidatos)
        estado.df, estado.br, estado.uf_tot = df, br, uf_snap
        momento = datetime.strptime(snap.name, "%Y%m%d_%H%M%S")
        tot_apur = df[candidatos].sum().sum()
        tot_proj = df[[f"proj_{c}" for c in candidatos]].sum().sum()
        pct_secoes = df["st"].sum() / df["ts"].sum() * 100
        for c in candidatos:
            linha = {
                "momento": momento, "pct_secoes_apuradas": pct_secoes,
                # mesma base do apurado: municípios + ATRASO (+ RESID, sem brancos/nulos)
                "votos_contados_total": int(df["tv"].sum()),
                "brancos": int(df["brancos"].sum()), "nulos": int(df["nulos"].sum()),
                "candidato": c,
                "votos_apurados": int(df[c].sum()),
                "pct_apurado": df[c].sum() / tot_apur * 100 if tot_apur else None,
                "votos_projetados_v1": round(df[f"proj_{c}"].sum()),
                "pct_projetado_v1": df[f"proj_{c}"].sum() / tot_proj * 100 if tot_proj else None,
                "pct_projetado_v2": None, "p5_v2": None, "p95_v2": None,
                "prob_vitoria_v2": None, "n_mun_ajuste_v2": None,
            }
            if v2:
                e_a = c == v2["a"]
                linha.update({
                    "pct_projetado_v2": v2["pct_a"] if e_a else 100 - v2["pct_a"],
                    "p5_v2": v2["p5_a"] if e_a else 100 - v2["p95_a"],
                    "p95_v2": v2["p95_a"] if e_a else 100 - v2["p5_a"],
                    "prob_vitoria_v2": v2["prob_a"] if e_a else 100 - v2["prob_a"],
                    "n_mun_ajuste_v2": v2["n_mun_ajuste"],
                })
            hist.append(linha)
        estado.vistos.add(snap.name)

    if not hist:
        print("sem dados ainda")
        return

    df = estado.df
    SAIDA.mkdir(exist_ok=True)
    hist = pd.DataFrame(hist)
    hist.to_csv(SAIDA / "historico.csv", sep=";", decimal=",", index=False, encoding="utf-8-sig")

    # estado atual por município, formato longo
    nomes[("zz", "RESID")] = ("EXTERIOR (resíduo, sem dado por cidade)", "")
    for uf in UFS_BR:
        nomes[(uf, "ATRASO")] = (f"{uf.upper()} (votos ainda sem arquivo municipal)", "")
    df["municipio"] = [nomes.get((u, m), ("", ""))[0] for u, m in zip(df["uf"], df["mun"])]
    df["cod_ibge"] = [nomes.get((u, m), ("", ""))[1] for u, m in zip(df["uf"], df["mun"])]
    df["pct_secoes_apuradas"] = (df["st"] / df["ts"] * 100).where(df["ts"] > 0)
    validos = df[candidatos].sum(axis=1)
    longo = []
    for c in candidatos:
        parte = df[["uf", "mun", "cod_ibge", "municipio", "ts", "st", "pct_secoes_apuradas", "te0"]].copy()
        parte["candidato"] = c
        parte["votos_apurados"] = df[c].astype(int)
        parte["pct_apurado"] = (df[c] / validos * 100).where(validos > 0)
        parte["votos_projetados_v1"] = df[f"proj_{c}"].round().astype("Int64")
        if f"proj_v2_{c}" in df:
            parte["votos_projetados_v2"] = df[f"proj_v2_{c}"].round().astype("Int64")
        longo.append(parte)
    longo = pd.concat(longo).rename(columns={"mun": "cod_tse", "ts": "secoes_total",
                                             "st": "secoes_apuradas", "te0": "eleitorado"})
    longo.to_csv(SAIDA / "municipios.csv", sep=";", decimal=",", index=False, encoding="utf-8-sig")

    escrever_modelo(hist, df, candidatos)
    painel.escrever(hist, df, candidatos, estado.br, estado.uf_tot, SAIDA / "painel.html")
    publicar()
    ult = hist[hist["momento"] == hist["momento"].max()]
    txt = " | ".join(
        f"{r.candidato}: apur {r.pct_apurado:.2f}% v1 {r.pct_projetado_v1:.2f}%"
        + (f" v2 {r.pct_projetado_v2:.2f}% [{r.p5_v2:.1f}–{r.p95_v2:.1f}] P {r.prob_vitoria_v2:.0f}%"
           if pd.notna(r.pct_projetado_v2) else "")
        for r in ult.itertuples())
    print(f"{datetime.now():%H:%M:%S} {len(snaps)} snapshots | {txt} | "
          f"seções {ult['pct_secoes_apuradas'].iloc[0]:.2f}%", flush=True)


def publicar():
    """Copia as páginas para saida/publico/ (única pasta servida pelo túnel). Grava num
    temporário e troca de uma vez, para o servidor nunca entregar arquivo pela metade."""
    PUBLICO.mkdir(exist_ok=True)
    for origem, destino in (("painel.html", "index.html"), ("painel.html", "painel.html"),
                            ("modelo.html", "modelo.html")):
        tmp = PUBLICO / (destino + ".tmp")
        shutil.copyfile(SAIDA / origem, tmp)
        os.replace(tmp, PUBLICO / destino)


def escrever_modelo(hist, df, candidatos):
    ult_t = hist["momento"].max()
    ult = hist[hist["momento"] == ult_t]
    cores = ["#2563eb", "#dc2626", "#16a34a", "#9333ea"]
    tem_v2 = ult["pct_projetado_v2"].notna().all()
    n_aj = int(ult["n_mun_ajuste_v2"].iloc[0]) if tem_v2 else 0

    def fmt(v, casas=2):
        return f"{v:.{casas}f}".replace(".", ",")

    cartoes = ""
    for i, r in enumerate(ult.itertuples()):
        if tem_v2:
            corpo = (f'<div class="big">{fmt(r.pct_projetado_v2)}%</div>'
                     f'<div class="sub">projeção pelo 1º turno (v2) · faixa 90%: {fmt(r.p5_v2, 1)}–{fmt(r.p95_v2, 1)}%</div>'
                     f'<div class="sub">prob. de vitória: <b>{fmt(r.prob_vitoria_v2, 0)}%</b></div>')
        else:
            corpo = '<div class="big">—</div><div class="sub">projeção pelo 1º turno ainda sem dado</div>'
        cartoes += (f'<div class="card" style="border-top:4px solid {cores[i % 4]}">'
                    f'<div class="nome">{r.candidato}</div>{corpo}'
                    f'<div class="sub">simples (v1): {fmt(r.pct_projetado_v1)}% · apurado: {fmt(r.pct_apurado)}%</div></div>')

    momentos = sorted(hist["momento"].unique())
    rotulos = [pd.Timestamp(t).strftime("%H:%M") for t in momentos]
    series = []
    for i, c in enumerate(candidatos):
        h = hist[hist["candidato"] == c].set_index("momento").reindex(momentos)
        cor = cores[i % 4]

        def lst(col):
            return [None if pd.isna(v) else round(float(v), 2) for v in h[col]]
        series += [
            {"label": f"{c} faixa", "data": lst("p95_v2"), "borderWidth": 0, "pointRadius": 0,
             "backgroundColor": cor + "22", "fill": False},
            {"label": f"{c} faixa ", "data": lst("p5_v2"), "borderWidth": 0, "pointRadius": 0,
             "backgroundColor": cor + "22", "fill": "-1"},
            {"label": f"{c} pelo 1º turno", "data": lst("pct_projetado_v2"), "borderColor": cor,
             "borderWidth": 2.5, "pointRadius": 0},
            {"label": f"{c} simples", "data": lst("pct_projetado_v1"), "borderColor": cor,
             "borderDash": [2, 3], "borderWidth": 1, "pointRadius": 0},
            {"label": f"{c} apurado", "data": lst("pct_apurado"), "borderColor": cor,
             "borderDash": [6, 4], "borderWidth": 1.5, "pointRadius": 0},
        ]

    agg = {"ts": ("ts", "sum"), "st": ("st", "sum"), **{c: (c, "sum") for c in candidatos}}
    if tem_v2:
        agg.update({f"proj_v2_{c}": (f"proj_v2_{c}", "sum") for c in candidatos})
    por_uf = df.groupby("uf").agg(**agg)
    linhas_uf = ""
    for uf, r in por_uf.iterrows():
        apur = sum(r[c] for c in candidatos)
        cels = ""
        for c in candidatos:
            cels += f"<td>{fmt(r[c] / apur * 100, 1) + '%' if apur else '—'}</td>"
            if tem_v2:
                proj = sum(r[f"proj_v2_{k}"] for k in candidatos)
                cels += f"<td>{fmt(r[f'proj_v2_{c}'] / proj * 100, 1) + '%' if proj else '—'}</td>"
        linhas_uf += f"<tr><td>{uf.upper()}</td><td>{fmt(r['st'] / r['ts'] * 100, 1)}%</td>{cels}</tr>"
    cab_uf = "".join(f"<th>{c}<br>apurado</th>" + (f"<th>{c}<br>proj. 1º turno</th>" if tem_v2 else "")
                     for c in candidatos)

    aviso = ""
    if tem_v2 and n_aj < modelo_v2.MIN_MUN:
        aviso = (f'<div class="aviso">Só {n_aj} municípios apurados entram no ajuste do v2 '
                 f'(mínimo {modelo_v2.MIN_MUN}): usando swing uniforme. Projeção ainda muito instável.</div>')

    html = f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta http-equiv="refresh" content="60"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Modelo — detalhes</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
body{{font-family:system-ui,sans-serif;margin:0 auto;max-width:1100px;padding:16px;background:#f8fafc;color:#0f172a}}
h1{{font-size:20px;margin:0 0 4px}} .meta{{color:#64748b;font-size:13px;margin-bottom:12px}}
.aviso{{background:#fef3c7;border:1px solid #f59e0b;border-radius:6px;padding:8px 12px;margin-bottom:12px;font-size:14px}}
.cards{{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:16px}}
.card{{background:#fff;border-radius:8px;padding:14px 18px;flex:1;min-width:220px;box-shadow:0 1px 3px #0001}}
.nome{{font-weight:600}} .big{{font-size:34px;font-weight:700}} .sub{{color:#64748b;font-size:13px;margin-top:2px}}
.box{{background:#fff;border-radius:8px;padding:14px;box-shadow:0 1px 3px #0001;margin-bottom:16px;overflow-x:auto}}
table{{border-collapse:collapse;width:100%;font-size:13px}} td,th{{padding:4px 8px;text-align:right;border-bottom:1px solid #e2e8f0}}
td:first-child,th:first-child{{text-align:left}}
</style></head><body>
<h1>Detalhes do modelo — Presidente 2º turno 2026</h1><div class="meta"><a href="painel.html">← voltar ao painel</a></div>
<div class="meta">Último snapshot: {pd.Timestamp(ult_t):%d/%m %H:%M:%S} · seções apuradas: {fmt(ult['pct_secoes_apuradas'].iloc[0])}% ·
recarrega a cada 1 min · pelo 1º turno = v2 (linha cheia, faixa 90%); simples = v1 (pontilhado fino); apurado (tracejado)</div>
{aviso}
<div class="cards">{cartoes}</div>
<div class="box"><canvas id="g" height="110"></canvas></div>
<div class="box"><table><tr><th>UF</th><th>seções apuradas</th>{cab_uf}</tr>{linhas_uf}</table></div>
<script>
new Chart(document.getElementById('g'),{{type:'line',data:{{labels:{json.dumps(rotulos)},datasets:{json.dumps(series)}}},
options:{{animation:false,spanGaps:true,interaction:{{mode:'index',intersect:false}},
plugins:{{legend:{{labels:{{filter:i=>!i.text.includes('faixa')}}}}}},
scales:{{y:{{title:{{display:true,text:'% dos votos válidos'}}}}}}}}}});
</script></body></html>"""
    (SAIDA / "modelo.html").write_text(html, encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--loop", action="store_true")
    args = ap.parse_args()
    estado = Estado()
    while True:
        inicio = time.time()
        try:
            calcular(estado)
        except Exception as erro:
            print(f"erro: {erro}", flush=True)
        if not args.loop:
            break
        time.sleep(max(0, INTERVALO_S - (time.time() - inicio)))


if __name__ == "__main__":
    main()
