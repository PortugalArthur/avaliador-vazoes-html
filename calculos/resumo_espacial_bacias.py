"""Médias dos coeficientes individuais da correlação espacial por bacia."""

import numpy as np
import pandas as pd


def resumir_correlacoes_bacias(comparacao, cadastro, hydro_id_referencia):
    """Retorna os pares com bacia e a média assinada, não ponderada, por fonte."""
    if comparacao.hydro_id.duplicated().any() or cadastro.hydro_id.duplicated().any():
        raise ValueError("Há usinas duplicadas na associação das correlações às bacias.")
    outras = comparacao.loc[~comparacao.hydro_id.eq(hydro_id_referencia)].copy()
    pares = outras.merge(cadastro[["hydro_id", "bacia_id", "Bacia"]],
                         on="hydro_id", how="left", validate="one_to_one")
    for coluna in ("Correlação sintética", "Correlação histórica"):
        pares[coluna] = pd.to_numeric(pares[coluna], errors="raise").replace([np.inf, -np.inf], np.nan)
    resumo = pares.dropna(subset=["bacia_id"]).groupby(["bacia_id", "Bacia"], sort=True).agg(
        **{"Usinas na bacia": ("hydro_id", "size"),
           "Correlação média sintética": ("Correlação sintética", "mean"),
           "Correlação média histórica": ("Correlação histórica", "mean"),
           "Correlações sintéticas válidas": ("Correlação sintética", "count"),
           "Correlações históricas válidas": ("Correlação histórica", "count")}
    ).reset_index()
    return pares, resumo
