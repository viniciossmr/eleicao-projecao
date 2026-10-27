"""Projeção v2: swing sobre o 1º turno, com efeito de UF e faixa de incerteza.

Disputa de dois candidatos (A = candidatos[0], B = candidatos[1]). Tudo em logit da
fatia de A entre os dois:

  x = logit(A / (A + B)) no 1º turno do município
  y = logit(A / (A + B)) no apurado do 2º turno do município

1. Ajuste nacional: y = α + β·x (mínimos quadrados ponderados por votos apurados) nos
   municípios com seções apuradas. Com menos de MIN_MUN municípios: β = 1 (swing
   uniforme).
2. Efeito de UF: média ponderada do resíduo na UF, encolhida por m / (m + K_UF)
   (m = municípios apurados na UF).
3. Fatia prevista no que falta de cada município:
   - sem apuração: modelo (α + β·x + efeito UF);
   - parcialmente apurado: modelo + desvio observado do município (y − modelo) com
     peso st / (st + K_SEC) — no central equivale à mistura observado/modelo, e nas
     simulações a incerteza do modelo continua valendo para o restante;
   - sem 1º turno (resíduo do exterior): observado.
4. Votos que faltam:
   - apurado em parte: votos (A+B) × (te − est) / est;
   - sem apuração: válidos do 1º turno × r, r = votos 2º turno / válidos 1º turno
     equivalentes nos municípios apurados.
5. Incerteza (N_SIM simulações, semente fixa): bootstrap dos municípios apurados para
   α e β, efeito de UF sorteado em torno do estimado, ruído independente por
   município, e um choque comum a todo o país ~ N(0, SIGMA_NAC × fração do
   eleitorado ainda não apurado) — cobre o risco de os apurados não representarem o
   resto (ordem de apuração). SIGMA_NAC é premissa, não estimado do dado.
   Não inclui incerteza de comparecimento.
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

RAIZ = Path(__file__).parent
PASTA_T1 = RAIZ / "dados" / "1turno"
MIN_MUN = 30
K_UF = 10
K_SEC = 5
N_SIM = 2000
SEMENTE = 42
SIGMA_UF_MIN = 0.10
SIGMA_NAC = 0.15  # logit; ≈ 3,7 p.p. perto de 50% com nada apurado

_t1 = None


def logit(p):
    p = np.clip(p, 0.01, 0.99)
    return np.log(p / (1 - p))


def sigmoid(z):
    return 1 / (1 + np.exp(-z))


def ler_1turno():
    """(uf, mun) -> votos por candidato e válidos do 1º turno (lido uma vez por processo)."""
    global _t1
    if _t1 is None:
        linhas = []
        for f in PASTA_T1.glob("*-u.json"):
            d = json.loads(f.read_text(encoding="utf-8"))
            votos = {c["nmu"]: int(c["vap"])
                     for a in d["carg"][0]["agr"] for p in a["par"] for c in p["cand"]}
            linhas.append({"uf": f.name[:2], "mun": f.name[2:7], "vv1": int(d["v"]["vv"]),
                           **{f"t1_{k}": v for k, v in votos.items()}})
        _t1 = pd.DataFrame(linhas)
    return _t1


def ajustar(x, y, w):
    """WLS y = a + b·x. Retorna (a, b), com b = 1 se poucos pontos ou x sem variação."""
    sw = w.sum()
    mx, my = (w * x).sum() / sw, (w * y).sum() / sw
    vx = (w * (x - mx) ** 2).sum() / sw
    if len(x) < MIN_MUN or vx < 1e-4:
        return my - mx, 1.0
    b = (w * (x - mx) * (y - my)).sum() / sw / vx
    return my - b * mx, b


def projetar_v2(df, candidatos):
    """df: tabela por município de projetar.projetar(). Retorna (resumo, df com proj_v2_*)."""
    a_nome, b_nome = candidatos[0], candidatos[1]
    t1 = ler_1turno()
    df = df.merge(t1[["uf", "mun", "vv1", f"t1_{a_nome}", f"t1_{b_nome}"]],
                  on=["uf", "mun"], how="left")
    tem_t1 = df["vv1"].notna() & ((df[f"t1_{a_nome}"] + df[f"t1_{b_nome}"]) > 0)

    A, B = df[a_nome].to_numpy(float), df[b_nome].to_numpy(float)
    obs2 = A + B
    est, te, st = df["est"].to_numpy(float), df["te"].to_numpy(float), df["st"].to_numpy(float)
    x = np.where(tem_t1, logit(df[f"t1_{a_nome}"] / (df[f"t1_{a_nome}"] + df[f"t1_{b_nome}"])), 0.0)
    apur = (est > 0) & (obs2 > 0)
    y = np.where(apur, logit(np.where(obs2 > 0, A / np.where(obs2 > 0, obs2, 1), 0.5)), 0.0)
    fit = apur & tem_t1.to_numpy()
    if fit.sum() == 0:
        return None, df

    # 1. ajuste nacional
    alfa, beta = ajustar(x[fit], y[fit], obs2[fit])
    resid = y - (alfa + beta * x)

    # 2. efeito de UF encolhido
    ufs = df["uf"].to_numpy()
    ef_uf, sd_uf, m_uf = {}, {}, {}
    for uf in np.unique(ufs[fit]):
        sel = fit & (ufs == uf)
        m = sel.sum()
        bruto = (obs2[sel] * resid[sel]).sum() / obs2[sel].sum()
        ef_uf[uf] = bruto * m / (m + K_UF)
        m_uf[uf] = m
    brutos = np.array([ef_uf[u] / (m_uf[u] / (m_uf[u] + K_UF)) for u in ef_uf])
    sigma_uf = max(SIGMA_UF_MIN, float(np.sqrt(np.mean(brutos ** 2)))) if len(brutos) > 1 else 0.3
    for uf in np.unique(ufs):
        sd_uf[uf] = sigma_uf * np.sqrt(K_UF / (m_uf.get(uf, 0) + K_UF))
    efeito = np.array([ef_uf.get(u, 0.0) for u in ufs])
    resid2 = resid - efeito
    sigma_mun = float(np.sqrt((obs2[fit] * resid2[fit] ** 2).sum() / obs2[fit].sum()))

    # 4. votos que faltam
    te0 = df["te0"].to_numpy(float)
    vv1 = df["vv1"].fillna(0).to_numpy(float)
    eq_t1 = np.where(fit, vv1 * est / np.where(te0 > 0, te0, 1), 0)
    r = obs2[fit].sum() / eq_t1[fit].sum() if eq_t1[fit].sum() > 0 else 1.0
    # fração do eleitorado original que falta (te < te0 quando parte do município já
    # está na linha ATRASO da UF); vale também para est > 0 com 0 votos
    resto = np.where(te0 > 0, (te - est) / np.where(te0 > 0, te0, 1), 0.0)
    falta = np.where(apur, obs2 * (te - est) / np.where(est > 0, est, 1),
                     np.where(tem_t1, vv1 * r * resto, 0.0))
    falta = np.maximum(falta, 0)

    # 3. fatia prevista no que falta (em logit): modelo + desvio observado do município,
    # com peso w_obs. A incerteza do modelo (ajuste, UF, choque nacional) vale para todo
    # o restante, inclusive de município parcialmente apurado.
    tem_t1 = tem_t1.to_numpy()
    w_obs = np.where(apur & tem_t1, st / (st + K_SEC), 0.0)
    so_obs = apur & ~tem_t1  # ATRASO / RESID: só o observado
    sem_nada = ~tem_t1 & ~apur  # sem 1º turno e sem apuração: média nacional
    y_nac = logit(A.sum() / obs2.sum()) if obs2.sum() > 0 else 0.0
    modelo_c = alfa + beta * x + efeito
    desvio = np.where(apur & tem_t1, y - modelo_c, 0.0)

    def fatia(modelo):
        z = modelo + w_obs * desvio
        z = np.where(so_obs, y, z)
        return sigmoid(np.where(sem_nada, y_nac, z))

    s = fatia(modelo_c)
    projA, projB = A + falta * s, B + falta * (1 - s)
    central = projA.sum() / (projA.sum() + projB.sum())

    # 5. Monte Carlo
    rng = np.random.default_rng(SEMENTE)
    xf, yf, wf = x[fit], y[fit], obs2[fit]
    contagens = rng.multinomial(len(xf), np.full(len(xf), 1 / len(xf)), size=N_SIM)
    W = contagens * wf
    sw = W.sum(1)
    mx, my = (W @ xf) / sw, (W @ yf) / sw
    vx = (W @ xf ** 2) / sw - mx ** 2
    cxy = (W @ (xf * yf)) / sw - mx * my
    if len(xf) >= MIN_MUN:  # mesma regra do ajuste central, réplica a réplica
        bs = np.where(vx > 1e-4, cxy / np.where(vx > 1e-4, vx, 1), 1.0)
    else:
        bs = np.ones(N_SIM)
    as_ = my - bs * mx

    lista_uf = list(np.unique(ufs))
    idx_uf = np.array([lista_uf.index(u) for u in ufs])
    ef_sim = rng.normal([ef_uf.get(u, 0.0) for u in lista_uf], [sd_uf[u] for u in lista_uf],
                        size=(N_SIM, len(lista_uf)))[:, idx_uf]
    ruido = rng.normal(0, sigma_mun, size=(N_SIM, len(x)))
    nao_apurado = 1 - est.sum() / df["te0"].sum()
    choque_nac = rng.normal(0, SIGMA_NAC * nao_apurado, size=(N_SIM, 1))
    S = fatia(as_[:, None] + bs[:, None] * x[None, :] + ef_sim + ruido + choque_nac)
    simA = A.sum() + (falta * S).sum(1)
    simB = B.sum() + (falta * (1 - S)).sum(1)
    sim = simA / (simA + simB)

    df["proj_v2_" + a_nome], df["proj_v2_" + b_nome] = projA, projB
    resumo = {
        "a": a_nome, "b": b_nome,
        "pct_a": central * 100, "p5_a": np.percentile(sim, 5) * 100,
        "p95_a": np.percentile(sim, 95) * 100, "prob_a": (sim > 0.5).mean() * 100,
        "alfa": alfa, "beta": beta, "sigma_uf": sigma_uf, "sigma_mun": sigma_mun,
        "r_comparecimento": r, "n_mun_ajuste": int(fit.sum()),
    }
    return resumo, df
