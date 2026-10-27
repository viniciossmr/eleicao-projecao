"""Gráfico para o post: placar parcial vs projeção pelo 1º turno, por % de urnas apuradas.

Uso (precisa de matplotlib): py grafico_linkedin.py
Saída: saida/grafico_linkedin.png
"""
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

RAIZ = Path(__file__).parent
VERMELHO, CINZA, TEXTO = "#d6293e", "#8a8f98", "#1d1f23"

h = pd.read_csv(RAIZ / "saida" / "historico.csv", sep=";", decimal=",")
h = h[(h.candidato == "LULA") & (h.pct_secoes_apuradas > 0) & h.pct_projetado_v2.notna()]
h = h.sort_values("momento").drop_duplicates("pct_secoes_apuradas", keep="last")
x = h.pct_secoes_apuradas
final = h.pct_apurado.iloc[-1]

fig, ax = plt.subplots(figsize=(12, 6.75), dpi=150)
fig.patch.set_facecolor("white")

ax.fill_between(x, h.p5_v2, h.p95_v2, color=VERMELHO, alpha=0.12, lw=0,
                label="Faixa de 90% das simulações")
ax.plot(x, h.pct_projetado_v2, color=VERMELHO, lw=2.8, label="Projeção do modelo")
ax.plot(x, h.pct_apurado, color=CINZA, lw=2.2, ls="--", label="Placar parcial (contado)")
ax.axhline(final, color=TEXTO, lw=1, alpha=0.6)
ax.axhline(50, color=CINZA, lw=0.8, alpha=0.5)
ax.text(100, final + 0.12, f"Resultado final: {final:.2f}%".replace(".", ","),
        ha="right", va="bottom", fontsize=11, color=TEXTO, weight="bold")

# trecho em que o placar mostrava o Flávio na frente
atras = h[h.pct_apurado < 50]
if len(atras):
    a, b = atras.pct_secoes_apuradas.min(), atras.pct_secoes_apuradas.max()
    ax.axvspan(a, b, color=CINZA, alpha=0.08, lw=0)
    ax.text((a + b) / 2, 46.3, "Placar mostrava\nFlávio na frente", ha="center",
            va="bottom", fontsize=10, color=CINZA)

p10 = h[h.pct_secoes_apuradas >= 10].iloc[0]
ax.annotate(f"Com 10% apurado:\nprojeção {p10.pct_projetado_v2:.1f}%".replace(".", ","),
            xy=(p10.pct_secoes_apuradas, p10.pct_projetado_v2), xytext=(14, 54.6),
            fontsize=10.5, color=VERMELHO, weight="bold",
            arrowprops=dict(arrowstyle="-", color=VERMELHO, lw=1))

ax.set_xlim(0, 100)
ax.set_ylim(46, 57)
ax.set_xlabel("% de urnas apuradas", fontsize=11, color=TEXTO)
ax.set_ylabel("Lula — % dos votos válidos", fontsize=11, color=TEXTO)
ax.xaxis.set_major_formatter(lambda v, _: f"{v:.0f}%")
ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0f}%")
for lado in ("top", "right"):
    ax.spines[lado].set_visible(False)
ax.tick_params(colors=TEXTO)
ax.grid(axis="y", alpha=0.2)
ax.legend(loc="upper right", frameon=False, fontsize=10)

fig.suptitle("2º turno 2026: o modelo acertou o resultado antes do placar",
             x=0.06, y=0.975, ha="left", fontsize=16, weight="bold", color=TEXTO)
ax.set_title("Projeção a partir da apuração parcial do TSE, comparando cada cidade com o 1º turno",
             loc="left", fontsize=11, color=CINZA, pad=10)
fig.text(0.06, 0.015, "Fonte: TSE (dados abertos de resultados). Elaboração própria.",
         fontsize=9, color=CINZA)
fig.tight_layout(rect=(0.02, 0.03, 1, 0.97))
fig.savefig(RAIZ / "saida" / "grafico_linkedin.png")
print("salvo:", RAIZ / "saida" / "grafico_linkedin.png")
