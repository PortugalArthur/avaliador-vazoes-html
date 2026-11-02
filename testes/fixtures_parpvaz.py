"""Relatório pequeno com escalas distintas, AR(0) e estatísticas mensais/anuais."""

import numpy as np
from geradores.parametros_par_newave import MESES


def escrever_parpvaz(arquivo, usinas=((101, "SAO JOSE"), (305, "ITIQUIRA II")), config=72):
    linhas = ["MODELO ESTOCASTICO - PAR(p)", "ANALISE DO HISTORICO DE VAZAO INCREMENTAL",
              "NUM NOME POS " + " ".join(MESES)]
    for codigo, nome in usinas:
        linhas.append(f"{codigo:8d} {nome:<12}{codigo + 600:5d}" + " 0" * 24)
    for pos, (codigo, nome) in enumerate(usinas):
        q = np.arange(36, dtype=float).reshape(3, 12) + 10 + pos * 100
        a = np.zeros(36)
        for t in range(12, 36):
            a[t] = q.ravel()[t - 12:t].mean()
        for dados, validos in [(q, q), (a.reshape(3, 12), a[12:].reshape(2, 12))]:
            linhas += [f"\fSERIE  DE VAZOES   DA USINA {nome} (CONFIGURACAO No. {config})", "", " ".join(MESES), ""]
            for ano, valores in zip(range(2000, 2003), dados):
                linhas.append(str(ano) + " " + " ".join(f"{v:.2f}" for v in valores))
            for titulo, valores in [("MEDIA AMOSTRAL DAS VAZOES", validos.mean(axis=0)),
                                    ("DESVIO PADRAO AMOSTRAL DAS VAZOES", validos.std(axis=0))]:
                linhas += ["", titulo, "", " ".join(MESES), "", " ".join(f"{v:.2f}" for v in valores)]
        ordens = [1] * 12
        ordens[1], ordens[10], ordens[11] = 2, 0, 2
        linhas += ["", "*** ROTINA: VORDEM ***", "PERIODO     : FEV/PRE", "COEFICIENTE : -0.5", "",
                   "ORDEM ORIGINAL DO MODELO AUTORREGRESSIVO PARA CADA PERIODO", "", " ".join(MESES), "", "POS " + "3 " * 12, "",
                   "ORDEM FINAL DO MODELO AUTORREGRESSIVO PARA CADA PERIODO", "", " ".join(MESES), "",
                   "POS " + " ".join(map(str, ordens)), ""]
        for m, p in enumerate(ordens, 1):
            phi = [0.1 * m] + [-.02] * (p - 1) if p else []
            if m == 12:
                phi[0] = 0.0  # Zero efetivo de um lag ativo.
            linhas += [f"PERIODO: {MESES[m - 1]}/POS", f"COEFICIENTES DA EQUACAO DE REGRESSAO DE UM PROCESSO AR({p:2d})",
                       " ".join(f"{v:.3E}" for v in phi), " ".join(["9.990E+00"] * p),
                       "-.212E+00" if m == 2 else f"{.01 * m:.3E}", "9.990E+00", "", ""]
    arquivo.write_text("\n".join(linhas), encoding="utf-8")
