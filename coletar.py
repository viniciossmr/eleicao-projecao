"""Coleta snapshots (a cada 1 min) da apuração do TSE (2º turno presidente 2026) durante a noite.

Cada ciclo:
  1. baixa o arquivo de andamento de cada UF ({uf}-e006258-ab.json): seções
     totalizadas por município, sem votos;
  2. baixa os votos ({uf}{mun}-c0001-e006258-u.json) só dos municípios cujo
     número de seções totalizadas mudou desde o ciclo anterior;
  3. baixa o total nacional (br-c0001-e006258-u.json).

Tudo é salvo cru (arquivos -ab compactados em .gz) em dados/snapshots/AAAAMMDD_HHMMSS/. Um snapshot contém só
os municípios que mudaram; o estado num instante t = arquivo mais recente de
cada município até t.

Uso:
  py coletar.py            # roda em loop (Ctrl+C para parar)
  py coletar.py --uma-vez  # um ciclo só, para teste
"""
import argparse
import ctypes
import gzip
import json
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

BASE = "https://resultados.tse.jus.br/oficial/ele2026"
ELEICAO = "6258"  # Eleição Ordinária Federal - 2026 2º Turno
CARGO = "c0001"   # Presidente
UFS = ["ac", "al", "am", "ap", "ba", "ce", "df", "es", "go", "ma", "mg", "ms",
       "mt", "pa", "pb", "pe", "pi", "pr", "rj", "rn", "ro", "rr", "rs", "sc",
       "se", "sp", "to", "zz"]  # zz = exterior
INTERVALO_S = 60
THREADS = 16

PASTA = Path(__file__).parent / "dados" / "snapshots"
ESTADO = Path(__file__).parent / "dados" / "estado_coletor.json"
E = f"e{int(ELEICAO):06d}"


def baixar(url, tentativas=3):
    for i in range(tentativas):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                return r.read()
        except Exception as erro:
            if i == tentativas - 1:
                print(f"  falhou: {url} ({erro})")
                return None
            time.sleep(2)


def ciclo(ultimo_st):
    pasta = PASTA / datetime.now().strftime("%Y%m%d_%H%M%S")
    pasta.mkdir(parents=True, exist_ok=True)
    # marcador de fim de ciclo: "ok" se baixou andamento, totais de UF e br; senão
    # "incompleto" (os votos municipais da pasta ainda valem, os totais não)
    completo = False
    try:
        completo = _ciclo(ultimo_st, pasta)
    finally:
        ESTADO.write_text(json.dumps(ultimo_st))
        (pasta / ("ok" if completo else "incompleto")).touch()


def _ciclo(ultimo_st, pasta):

    # 1. andamento por UF
    urls_ab = {uf: f"{BASE}/{ELEICAO}/dados/{uf}/{uf}-{E}-ab.json" for uf in UFS}
    with ThreadPoolExecutor(THREADS) as ex:
        brutos_ab = dict(zip(urls_ab, ex.map(baixar, urls_ab.values())))

    falhas = sum(b is None for b in brutos_ab.values())
    mudaram = []
    for uf, bruto in brutos_ab.items():
        if bruto is None:
            continue
        (pasta / f"{uf}-{E}-ab.json.gz").write_bytes(gzip.compress(bruto))
        for abr in json.loads(bruto)["abr"]:
            if abr.get("tpabr") != "mun":
                continue
            chave = f"{uf}{abr['cdabr']}"
            st = int(abr["s"]["st"])
            if st != ultimo_st.get(chave, 0):
                mudaram.append((chave, st))

    # 2. votos dos municípios que mudaram
    def baixar_mun(item):
        chave, st = item
        uf = chave[:2]
        nome = f"{chave}-{CARGO}-{E}-u.json"
        bruto = baixar(f"{BASE}/{ELEICAO}/dados/{uf}/{nome}")
        if bruto is None:
            return None
        (pasta / nome).write_bytes(bruto)
        # o arquivo de votos pode vir mais velho que o -ab (cache do TSE): registra o st
        # do próprio arquivo, para baixar de novo no próximo ciclo se ainda estiver atrás
        return chave, int(json.loads(bruto)["s"]["st"])

    with ThreadPoolExecutor(THREADS) as ex:
        for ok in ex.map(baixar_mun, mudaram):
            if ok:
                ultimo_st[ok[0]] = ok[1]

    # 3. total por UF (serve para isolar o exterior: br − soma das UFs)
    def baixar_uf(uf):
        nome = f"{uf}-{CARGO}-{E}-u.json"
        bruto = baixar(f"{BASE}/{ELEICAO}/dados/{uf}/{nome}")
        if bruto:
            (pasta / nome).write_bytes(bruto)
        return bruto is not None

    with ThreadPoolExecutor(THREADS) as ex:
        falhas += sum(not ok for ok in ex.map(baixar_uf, UFS))

    # 4. total nacional
    nome_br = f"br-{CARGO}-{E}-u.json"
    bruto = baixar(f"{BASE}/{ELEICAO}/dados/br/{nome_br}")
    resumo = ""
    falhas += bruto is None
    if bruto:
        (pasta / nome_br).write_bytes(bruto)
        br = json.loads(bruto)
        cands = [c for a in br["carg"][0]["agr"] for p in a["par"] for c in p["cand"]]
        resumo = " | ".join(f"{c['nmu']} {c['pvap']}%" for c in cands)
        resumo = f"apurado {br['s']['pst']}% | {resumo}"

    print(f"{datetime.now():%H:%M:%S} {pasta.name}: {len(mudaram)} municípios "
          f"atualizados. {resumo}" + (f" | {falhas} FALHAS" if falhas else ""), flush=True)
    return falhas == 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--uma-vez", action="store_true")
    args = ap.parse_args()

    # impede a suspensão por inatividade do Windows enquanto o coletor roda (vale só
    # para este processo; ao sair, a configuração normal de energia volta a valer)
    if sys.platform == "win32":
        ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001
        ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)

    ultimo_st = json.loads(ESTADO.read_text()) if ESTADO.exists() else {}
    while True:
        inicio = time.time()
        try:
            ciclo(ultimo_st)
        except Exception as erro:  # o loop não pode morrer no meio da apuração
            print(f"erro no ciclo: {erro}", flush=True)
        if args.uma_vez:
            break
        time.sleep(max(0, INTERVALO_S - (time.time() - inicio)))


if __name__ == "__main__":
    main()
