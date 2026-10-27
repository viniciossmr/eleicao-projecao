"""Painel para acompanhar a apuração (saida/painel.html), gerado pelo projetar.py.

Mostra: projeção pelo 1º turno (v2) com margem e chance de vitória, projeção simples
(v1) para comparação, votos contados e que faltam, dois gráficos (contado × projeção)
e a tabela por estado. Os detalhes técnicos ficam em modelo.html.
"""
import json

import pandas as pd

REF = "LULA"  # candidato de referência nos gráficos (o outro é 100 − ele)
COR = {"LULA": "#d6293e", "FLAVIO BOLSONARO": "#1f5fbf"}
COR_OUTRO = "#6b7280"
NOME_CURTO = {"LULA": "Lula", "FLAVIO BOLSONARO": "Flávio Bolsonaro"}
NOME_UF = {
    "ac": "Acre", "al": "Alagoas", "am": "Amazonas", "ap": "Amapá", "ba": "Bahia", "ce": "Ceará",
    "df": "Distrito Federal", "es": "Espírito Santo", "go": "Goiás", "ma": "Maranhão",
    "mg": "Minas Gerais", "ms": "Mato Grosso do Sul", "mt": "Mato Grosso", "pa": "Pará",
    "pb": "Paraíba", "pe": "Pernambuco", "pi": "Piauí", "pr": "Paraná", "rj": "Rio de Janeiro",
    "rn": "Rio Grande do Norte", "ro": "Rondônia", "rr": "Roraima", "rs": "Rio Grande do Sul",
    "sc": "Santa Catarina", "se": "Sergipe", "sp": "São Paulo", "to": "Tocantins", "zz": "Exterior",
}


def pct(v, casas=1):
    return "—" if v is None or pd.isna(v) else f"{v:.{casas}f}".replace(".", ",") + "%"


def inteiro(n):
    return f"{int(round(n)):,}".replace(",", ".")


def grande(n):
    """Número legível: 401.060 / 1,2 mi / 120 mi."""
    if n >= 10_000_000:
        return f"{n / 1e6:.0f} mi"
    if n >= 1_000_000:
        return f"{n / 1e6:.1f} mi".replace(".", ",")
    return inteiro(n)


def escrever(hist, df, candidatos, br, uf_tot, destino):
    ref = REF if REF in candidatos else candidatos[0]
    outro = next(c for c in candidatos if c != ref)
    nome = lambda c: NOME_CURTO.get(c, c.title())
    cor = lambda c: COR.get(c, COR_OUTRO)

    ult_t = hist["momento"].max()
    ult = hist[hist["momento"] == ult_t].set_index("candidato")
    r_ref, r_out = ult.loc[ref], ult.loc[outro]
    tem_v2 = pd.notna(r_ref["pct_projetado_v2"])

    # --- totais do Brasil: mesma base da projeção (municípios + ATRASO/RESID), que usa
    # o arquivo mais atual entre município e total da UF
    tot = {k: df[k].sum() for k in ("tv", "brancos", "nulos", "st", "ts", "te0", "est")}
    tot["te"] = tot["te0"]
    validos_cont = df[candidatos].sum().sum()
    tem_proj = all(f"proj_v2_{c}" in df for c in candidatos)
    validos_proj = sum(df[f"proj_v2_{c}"].sum() for c in candidatos) if tem_proj else None
    faltam = max(0, validos_proj - df[candidatos].sum().sum()) if tem_proj else None
    pct_urnas = r_ref["pct_secoes_apuradas"]

    # --- destaque
    if tem_v2:
        lider = ref if r_ref["pct_projetado_v2"] >= 50 else outro
        chance = ult.loc[lider, "prob_vitoria_v2"]
        p_ref, lo, hi = r_ref["pct_projetado_v2"], r_ref["p5_v2"], r_ref["p95_v2"]

        def votos(c):
            proj = f"≈ {grande(df[f'proj_v2_{c}'].sum())} de votos no final" if tem_proj else ""
            p_cont = df[c].sum() / validos_cont * 100 if validos_cont else None
            return (f'<span class="votos">{proj}</span>'
                    f'<span class="votos contado">Contado até agora: <b>{pct(p_cont)}</b> · '
                    f'{inteiro(df[c].sum())} votos</span>')
        destaque = f"""
<div class="rotulo-proj">Projeção do resultado final</div>
<div class="duelo">
  <div class="cand"><span class="nome" style="color:{cor(ref)}">{nome(ref)}</span>
    <span class="num">{pct(p_ref)}</span>{votos(ref)}</div>
  <div class="cand dir"><span class="nome" style="color:{cor(outro)}">{nome(outro)}</span>
    <span class="num">{pct(100 - p_ref)}</span>{votos(outro)}</div>
</div>
<div class="barra" title="Projeção pelo 1º turno; faixa clara = margem de 90%">
  <div class="lado" style="width:{p_ref:.2f}%;background:{cor(ref)}"></div>
  <div class="lado" style="flex:1;background:{cor(outro)}"></div>
  <div class="margem" style="left:{lo:.2f}%;width:{hi - lo:.2f}%"></div>
  <div class="meio"></div>
</div>
<div class="legenda-barra"><span>projeção do resultado final · % dos votos válidos</span><span>50%</span></div>
<div class="resumo">
  <div><b>Chance de vitória:</b> <span style="color:{cor(lider)}">{nome(lider)} {pct(chance, 0)}</span></div>
  <div><b>Margem (90%):</b> {nome(ref)} entre {pct(lo)} e {pct(hi)}</div>
</div>
<div class="simples">Projeção simples, para comparar: {nome(ref)} {pct(r_ref['pct_projetado_v1'])} ·
  {nome(outro)} {pct(r_out['pct_projetado_v1'])}</div>"""
    else:
        destaque = '<div class="vazio">Projeção ainda sem dados suficientes.</div>'

    # --- card de status: oficial (TSE) > projeção, com níveis conservadores
    eleitos = [c for c in candidatos if c in br.get("eleitos", [])]
    # matematicamente definido: a vantagem em votos supera todos os eleitores ainda não apurados
    na_frente = max(candidatos, key=lambda c: df[c].sum())
    vantagem = df[na_frente].sum() - max(df[c].sum() for c in candidatos if c != na_frente)
    restantes = tot["te"] - tot["est"]
    if eleitos:
        c = eleitos[0]
        status = (cor(c), f"{nome(c)} eleito", "Resultado confirmado pelo TSE")
    elif vantagem > restantes:
        status = (cor(na_frente), f"{nome(na_frente)} eleito",
                  f"Matematicamente definido: a vantagem de {grande(vantagem)} votos é maior que os "
                  f"{grande(restantes)} eleitores que ainda faltam apurar · proclamação oficial do TSE pendente")
    elif tem_v2:
        sub = f"Chance de vitória pela projeção: {pct(chance, 0)} · {pct(pct_urnas, 1)} das urnas apuradas"
        if chance >= 99 and pct_urnas >= 20:
            status = (cor(lider), f"{nome(lider)} deve ser eleito", sub + " · ainda não é oficial")
        elif chance >= 90:
            status = (cor(lider), f"{nome(lider)} é o favorito", sub)
        elif chance >= 70:
            status = (cor(lider), f"Vantagem de {nome(lider)}", sub)
        else:
            status = (COR_OUTRO, "Disputa indefinida", sub)
    else:
        status = (COR_OUTRO, "Aguardando dados", "Projeção começa com as primeiras urnas")
    card_status = (f'<div class="status-card" style="border-left-color:{status[0]}">'
                   f'<div class="st-tit" style="color:{status[0]}">{status[1]}</div>'
                   f'<div class="st-sub">{status[2]}</div></div>')

    aviso = ""
    if tem_v2 and r_ref["n_mun_ajuste_v2"] < 30:
        aviso = ('<div class="aviso">Começo da apuração: poucas cidades contadas, projeção ainda '
                 'muito instável. Leia a margem, não só o número.</div>')

    # --- contadores
    contadores = f"""
<div class="contadores">
  <div class="cont"><div class="rot">Votos contados</div><div class="val">{grande(tot['tv'])}</div>
    <div class="det">{inteiro(validos_cont)} válidos · {inteiro(tot['brancos'])} brancos · {inteiro(tot['nulos'])} nulos</div></div>
  <div class="cont"><div class="rot">Urnas apuradas</div><div class="val">{pct(pct_urnas, 2)}</div>
    <div class="det">{inteiro(tot['st'])} de {inteiro(tot['ts'])} seções</div></div>
  <div class="cont"><div class="rot">Faltam (estimativa)</div><div class="val">{('≈ ' + grande(faltam)) if faltam is not None else '—'}</div>
    <div class="det">votos válidos · {grande(tot['te'] - tot['est'])} eleitores ainda por apurar</div></div>
</div>"""

    # --- gráficos (só o candidato de referência; 50% = empate)
    h_ref = hist[hist["candidato"] == ref].sort_values("momento").reset_index(drop=True)
    # corta o trecho inicial parado (apuração pausada): começa no último snapshot antes de
    # a % de urnas mudar pela primeira vez
    mudou = h_ref.index[h_ref["pct_secoes_apuradas"] != h_ref["pct_secoes_apuradas"].iloc[0]]
    if len(mudou):
        h_ref = h_ref.iloc[max(0, mudou[0] - 1):]
    momentos = list(h_ref["momento"])
    rot = [pd.Timestamp(t).strftime("%H:%M") for t in momentos]
    linha50 = {"label": "50%", "data": [50] * len(rot), "borderColor": "#9ca3af",
               "borderDash": [4, 4], "borderWidth": 1, "pointRadius": 0}
    g_real, g_proj = [], []
    for c in (ref, outro):
        h = hist[hist["candidato"] == c].set_index("momento").reindex(momentos)
        lst = lambda col: [None if pd.isna(v) else round(float(v), 2) for v in h[col]]
        g_real.append({"label": nome(c), "data": lst("pct_apurado"), "borderColor": cor(c),
                       "backgroundColor": cor(c), "borderWidth": 2.5, "pointRadius": 0})
        g_proj += [
            {"label": f"margem {c}", "data": lst("p95_v2"), "borderWidth": 0, "pointRadius": 0,
             "backgroundColor": cor(c) + "22", "fill": False},
            {"label": f"margem {c} ", "data": lst("p5_v2"), "borderWidth": 0, "pointRadius": 0,
             "backgroundColor": cor(c) + "22", "fill": "-1"},
            {"label": f"{nome(c)} · pelo 1º turno", "data": lst("pct_projetado_v2"),
             "borderColor": cor(c), "backgroundColor": cor(c), "borderWidth": 2.5, "pointRadius": 0},
            {"label": f"{nome(c)} · simples", "data": lst("pct_projetado_v1"), "borderColor": cor(c),
             "backgroundColor": cor(c), "borderDash": [3, 3], "borderWidth": 1.2, "pointRadius": 0},
        ]
    g_real.append(linha50)
    g_proj.append(linha50)

    # --- perfil de cidade: grupos pelo voto de ref no 1º turno (só ref × outro)
    grupos_html, resumo_faltam = "", ""
    falta_lado = {ref: 0.0, outro: 0.0}  # votos válidos que faltam, por lado do 1º turno
    t1r, t1o = f"t1_{ref}", f"t1_{outro}"
    if t1r in df and t1o in df:
        cid = df[df[t1r].notna() & ((df[t1r] + df[t1o]) > 0)].copy()
        cid["s1"] = cid[t1r] / (cid[t1r] + cid[t1o]) * 100
        faixas = [(f"Fortes de {nome(ref)}", 60, 101, cor(ref)),
                  (f"Inclinadas a {nome(ref)}", 50, 60, cor(ref)),
                  (f"Inclinadas a {nome(outro)}", 40, 50, cor(outro)),
                  (f"Fortes de {nome(outro)}", -1, 40, cor(outro))]
        for rotulo, lo_, hi_, cr in faixas:
            g = cid[(cid["s1"] >= lo_) & (cid["s1"] < hi_)]
            if g.empty:
                continue
            urn = g["st"].sum() / g["ts"].sum() * 100 if g["ts"].sum() else 0
            s1 = g[t1r].sum() / (g[t1r] + g[t1o]).sum() * 100
            cont = g[ref].sum() + g[outro].sum()
            real = g[ref].sum() / cont * 100 if cont else None
            proj, falta_g = None, None
            if tem_proj:
                pt = g[f"proj_v2_{ref}"].sum() + g[f"proj_v2_{outro}"].sum()
                proj = g[f"proj_v2_{ref}"].sum() / pt * 100 if pt else None
                falta_g = max(0, pt - cont)
                falta_lado[ref if lo_ >= 50 else outro] += falta_g
            grupos_html += (
                f"<tr><td><span class='bolinha' style='background:{cr}'></span>{rotulo}</td>"
                f"<td>{inteiro(len(g))}</td><td>{grande(g['te0'].sum())}</td>"
                f"<td><div class='mini'><div style='width:{min(urn, 100):.1f}%'></div></div><b>{pct(urn)}</b></td>"
                f"<td>{'≈ ' + grande(falta_g) if falta_g is not None else '—'}</td>"
                f"<td class='sep'>{pct(s1)}</td><td>{pct(real)}</td><td><b>{pct(proj)}</b></td></tr>")
        if tem_proj:
            resumo_faltam = (
                f"<div class='faltam-lado'>Ainda faltam (estimativa): "
                f"<b style='color:{cor(ref)}'>≈ {grande(falta_lado[ref])} de votos</b> em cidades de {nome(ref)} · "
                f"<b style='color:{cor(outro)}'>≈ {grande(falta_lado[outro])}</b> em cidades de {nome(outro)}</div>")

    # --- tabela por estado (mais apurado primeiro)
    agg = {"ts": ("ts", "sum"), "st": ("st", "sum"), "te0": ("te0", "sum"),
           **{c: (c, "sum") for c in candidatos}}
    if tem_proj:
        agg.update({f"proj_v2_{c}": (f"proj_v2_{c}", "sum") for c in candidatos})
    por_uf = df.groupby("uf").agg(**agg)
    tv_uf = df.groupby("uf")["tv"].sum().to_dict()
    ordem = sorted(por_uf.index, key=lambda u: -(por_uf.loc[u, "st"] / por_uf.loc[u, "ts"]
                                                 if por_uf.loc[u, "ts"] else 0))
    linhas = ""
    for uf in ordem:
        r = por_uf.loc[uf]
        cont = sum(r[c] for c in candidatos)
        real = r[ref] / cont * 100 if cont else None
        if tem_proj:
            proj_tot = sum(r[f"proj_v2_{c}"] for c in candidatos)
            proj = r[f"proj_v2_{ref}"] / proj_tot * 100 if proj_tot else None
            falta_uf = max(0, proj_tot - cont)
        else:
            proj, falta_uf = None, None
        real_o = None if real is None else 100 - real
        proj_o = None if proj is None else 100 - proj
        venc = None if proj is None else (ref if proj >= 50 else outro)
        neg = lambda c, v: f"<td style='color:{cor(c)}'><b>{pct(v)}</b></td>" if venc == c else f"<td>{pct(v)}</td>"
        urnas = r["st"] / r["ts"] * 100 if r["ts"] else 0
        linhas += (f"<tr><td>{NOME_UF.get(uf, uf.upper())}</td>"
                   f"<td><div class='mini'><div style='width:{min(urnas, 100):.1f}%'></div></div>{pct(urnas, 0)}</td>"
                   f"<td>{grande(tv_uf.get(uf, 0))}</td>"
                   f"<td>{'≈ ' + grande(falta_uf) if falta_uf is not None else '—'}</td>"
                   f"<td class='sep'>{pct(real)}</td>{neg(ref, proj)}"
                   f"<td class='sep'>{pct(real_o)}</td>{neg(outro, proj_o)}</tr>")

    html = f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta http-equiv="refresh" content="60"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Apuração 2º turno</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
:root{{--fundo:#f5f6f8;--cartao:#fff;--texto:#111827;--suave:#6b7280;--linha:#e5e7eb}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--fundo);color:var(--texto);font:15px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif}}
main{{max-width:1040px;margin:0 auto;padding:20px 16px 40px}}
header{{display:flex;justify-content:space-between;align-items:baseline;flex-wrap:wrap;gap:8px;margin-bottom:14px}}
h1{{font-size:18px;margin:0;font-weight:650}} .status{{color:var(--suave);font-size:13px}}
.status a{{color:var(--suave)}}
.cartao{{background:var(--cartao);border-radius:14px;padding:20px;box-shadow:0 1px 2px #0000000d,0 4px 16px #0000000a;margin-bottom:14px}}
.duelo{{display:flex;justify-content:space-between;align-items:flex-end}}
.cand{{display:flex;flex-direction:column}} .cand.dir{{text-align:right}}
.cand .nome{{font-weight:650;font-size:15px}}
.votos{{color:var(--suave);font-size:13px;font-variant-numeric:tabular-nums}} .votos b{{color:var(--texto)}}
.votos.contado{{margin-top:2px;font-size:12px}}
.rotulo-proj{{text-align:center;color:var(--suave);font-size:12px;text-transform:uppercase;letter-spacing:.06em;margin-bottom:-6px}}
.status-card{{background:var(--cartao);border-radius:14px;padding:14px 18px;margin-bottom:14px;border-left:6px solid;box-shadow:0 1px 2px #0000000d}}
.st-tit{{font-size:22px;font-weight:750}} .st-sub{{color:var(--suave);font-size:13px}}
.cand .num{{font-size:46px;font-weight:750;letter-spacing:-1px;line-height:1.05;font-variant-numeric:tabular-nums}}
.barra{{position:relative;display:flex;height:18px;border-radius:9px;overflow:hidden;margin:12px 0 4px}}
.lado{{height:100%}}
.margem{{position:absolute;top:0;bottom:0;background:#ffffff66;border-left:2px solid #fff;border-right:2px solid #fff}}
.meio{{position:absolute;left:50%;top:-3px;bottom:-3px;width:2px;background:#111827;transform:translateX(-1px)}}
.legenda-barra{{display:flex;justify-content:space-between;color:var(--suave);font-size:12px;position:relative}}
.legenda-barra span:last-child{{position:absolute;left:50%;transform:translateX(-50%)}}
.resumo{{display:flex;gap:24px;flex-wrap:wrap;margin-top:14px;font-size:15px}}
.simples{{margin-top:8px;color:var(--suave);font-size:13px}}
.aviso{{background:#fff7e6;border:1px solid #f5c26b;color:#7a4b00;border-radius:10px;padding:8px 12px;font-size:13px;margin-bottom:14px}}
.vazio{{color:var(--suave)}}
.contadores{{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin-bottom:14px}}
.cont{{background:var(--cartao);border-radius:14px;padding:14px 16px;box-shadow:0 1px 2px #0000000d}}
.rot{{color:var(--suave);font-size:12px;text-transform:uppercase;letter-spacing:.04em}}
.val{{font-size:26px;font-weight:700;font-variant-numeric:tabular-nums}} .det{{color:var(--suave);font-size:12px}}
.graficos{{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:14px}}
.graficos .cartao{{margin:0}} h2{{font-size:14px;margin:0 0 2px;font-weight:650}}
.sub{{color:var(--suave);font-size:12px;margin-bottom:8px}}
table{{width:100%;border-collapse:collapse;font-size:14px;font-variant-numeric:tabular-nums}}
th{{text-align:right;color:var(--suave);font-weight:500;font-size:12px;padding:6px 8px;border-bottom:1px solid var(--linha)}}
td{{text-align:right;padding:7px 8px;border-bottom:1px solid var(--linha)}}
th:first-child,td:first-child{{text-align:left}} tr:last-child td{{border-bottom:0}}
.mini{{display:inline-block;width:46px;height:6px;background:var(--linha);border-radius:3px;margin-right:6px;vertical-align:middle;overflow:hidden}}
.mini div{{height:100%;background:#9ca3af}}
.tabela{{overflow-x:auto}} .faltam-lado{{margin-top:10px;font-size:14px}} .bolinha{{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:7px}} .sep{{border-left:1px solid var(--linha)}}
@media (max-width:720px){{.contadores,.graficos{{grid-template-columns:1fr}} .cand .num{{font-size:36px}}}}
</style></head><body><main>
<header><h1>Presidente · 2º turno 2026</h1>
<div class="status">{pct(pct_urnas, 2)} das urnas · atualizado {pd.Timestamp(ult_t):%H:%M} ·
<a href="modelo.html">detalhes do modelo</a></div></header>
{card_status}
{aviso}
<div class="cartao">{destaque}</div>
{contadores}
<div class="graficos">
  <div class="cartao"><h2>Votos contados até agora</h2>
    <div class="sub">% dos votos válidos já apurados</div>
    <canvas id="real" height="190"></canvas></div>
  <div class="cartao"><h2>Projeção do resultado final</h2>
    <div class="sub">linha cheia = pelo 1º turno, com margem de 90% · tracejado = simples</div>
    <canvas id="proj" height="190"></canvas></div>
</div>
<div class="cartao tabela"><h2>Apuração por perfil de cidade</h2>
<div class="sub">cidades agrupadas pelo voto no 1º turno (só {nome(ref)} × {nome(outro)}) · % de {nome(ref)} nos votos válidos dos dois</div>
<table><tr><th>Grupo</th><th>Cidades</th><th>Eleitorado</th><th>Urnas apuradas</th><th>Faltam (est.)</th>
<th class='sep'>{nome(ref)} 1º turno</th><th>{nome(ref)} contado</th><th>{nome(ref)} projeção</th></tr>{grupos_html}</table>{resumo_faltam}</div>
<div class="cartao tabela"><h2>Por estado</h2>
<div class="sub">do mais apurado ao menos apurado · projeção pelo 1º turno · em destaque, quem vence no estado</div>
<table><tr><th>Estado</th><th>Urnas</th><th>Votos contados</th><th>Faltam (est.)</th>
<th class='sep' style='color:{cor(ref)}'>{nome(ref)}<br>contado</th><th style='color:{cor(ref)}'>{nome(ref)}<br>projeção</th>
<th class='sep' style='color:{cor(outro)}'>{nome(outro)}<br>contado</th><th style='color:{cor(outro)}'>{nome(outro)}<br>projeção</th></tr>{linhas}</table></div>
</main>
<script>
const rot={json.dumps(rot)};
const op={{animation:false,spanGaps:true,interaction:{{mode:'index',intersect:false}},
 plugins:{{legend:{{labels:{{boxWidth:12,filter:i=>!i.text.startsWith('margem')&&i.text!=='50%'}}}},
  tooltip:{{filter:i=>!i.dataset.label.startsWith('margem'),callbacks:{{label:c=>c.dataset.label+': '+(c.parsed.y==null?'—':c.parsed.y.toFixed(1).replace('.',',')+'%')}}}}}},
 scales:{{x:{{grid:{{display:false}},ticks:{{maxTicksLimit:8}}}},y:{{ticks:{{callback:v=>v+'%'}}}}}}}};
new Chart(document.getElementById('real'),{{type:'line',data:{{labels:rot,datasets:{json.dumps(g_real)}}},options:op}});
new Chart(document.getElementById('proj'),{{type:'line',data:{{labels:rot,datasets:{json.dumps(g_proj)}}},options:op}});
</script></body></html>"""
    destino.write_text(html, encoding="utf-8")
