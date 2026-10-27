"""Baixa uma vez o resultado final do 1º turno (presidente, eleição 6257) por município.

Salva cru em dados/1turno/{uf}{mun}-c0001-e006257-u.json. Pula o que já existe.
Baixa antes a lista de municípios do 2º turno (dados/config/mun-e006258-cm.json),
usada também pelo projetar.py.

Uso: py baixar_1turno.py
"""
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from coletar import BASE, CARGO, baixar

ELEICAO_T1 = "6257"
E_T1 = f"e{int(ELEICAO_T1):06d}"
RAIZ = Path(__file__).parent
PASTA = RAIZ / "dados" / "1turno"
CONFIG_MUN = RAIZ / "dados" / "config" / "mun-e006258-cm.json"


def main():
    PASTA.mkdir(parents=True, exist_ok=True)
    if not CONFIG_MUN.exists():
        CONFIG_MUN.parent.mkdir(parents=True, exist_ok=True)
        bruto = baixar(f"{BASE}/6258/config/{CONFIG_MUN.name}")
        if bruto is None:
            sys.exit("não consegui baixar a lista de municípios do TSE; tente de novo")
        CONFIG_MUN.write_bytes(bruto)
    cfg = json.loads(CONFIG_MUN.read_text(encoding="utf-8"))
    nomes = [f"{uf['cd']}{m['cd']}-{CARGO}-{E_T1}-u.json" for uf in cfg["abr"] for m in uf["mu"]]
    faltam = [n for n in nomes if not (PASTA / n).exists()]
    print(f"{len(nomes)} municípios, {len(faltam)} a baixar")

    def um(nome):
        bruto = baixar(f"{BASE}/{ELEICAO_T1}/dados/{nome[:2]}/{nome}")
        if bruto:
            (PASTA / nome).write_bytes(bruto)
        return bruto is not None

    with ThreadPoolExecutor(16) as ex:
        ok = sum(ex.map(um, faltam))
    print(f"baixados {ok}, falharam {len(faltam) - ok}")


if __name__ == "__main__":
    main()
