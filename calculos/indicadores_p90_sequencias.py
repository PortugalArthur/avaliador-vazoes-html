"""P50/P90 por UHE e percentual de UHEs acima do respectivo histórico."""

import numpy as np
import pandas as pd


MEDIDAS_P90 = (
    ("Maior comprimento", "comprimento_maximo", "meses", False),
    ("Maior módulo da soma", "soma_mais_severa", "(m³/s)·mês", True),
    ("Maior módulo da intensidade", "intensidade_mais_severa", "m³/s", True),
)
COLUNAS_POR_USINA = [
    "hydro_id", "nome_usina", "medida", "unidade", "n_sintetico", "n_historico",
    "p90_sintetico", "p90_historico", "comparavel", "resultado", "motivo",
]
COLUNAS_INDICADORES = [
    "medida", "usinas_total", "usinas_comparaveis", "usinas_sintetico_maior",
    "usinas_iguais", "usinas_sintetico_menor", "usinas_sem_comparacao",
    "percentual_sintetico_maior",
]


def _calcular_indicadores_percentil(resumos, percentil):
    """Retorna tabela longa por UHE e três indicadores, sem misturar as fontes.

    Zero é uma observação válida. A comparação é estrita, sobre valores sem
    arredondar; nulos, infinitos e trajetórias não calculadas não entram no percentil.
    A ausência de uma fonte impede a comparação só daquela UHE/medida.
    """
    rotulo = f"P{percentil}"
    coluna_s, coluna_h = f"p{percentil}_sintetico", f"p{percentil}_historico"
    colunas_por_usina = [coluna_s if c == "p90_sintetico" else coluna_h if c == "p90_historico" else c
                        for c in COLUNAS_POR_USINA]
    obrigatorias = {"hydro_id", "nome_usina", "fonte", "trajetoria_id", "status",
                    *(m[1] for m in MEDIDAS_P90)}
    faltantes = obrigatorias - set(resumos.columns)
    if faltantes:
        raise ValueError(f"Resumo de sequências sem colunas do {rotulo}: " + ", ".join(sorted(faltantes)))
    if resumos.hydro_id.isna().any():
        raise ValueError(f"Há uma trajetória sem identificação de usina no resumo do {rotulo}.")
    if resumos.duplicated(["hydro_id", "fonte", "trajetoria_id"]).any():
        raise ValueError(f"Trajetória duplicada no resumo do {rotulo} de sequências.")
    if not resumos.fonte.isin(["Sintético", "Histórico"]).all():
        raise ValueError(f"Fonte desconhecida no resumo do {rotulo} de sequências.")
    linhas = []
    for hydro_id, grupo in resumos.groupby("hydro_id", sort=True, observed=True):
        nomes = grupo.nome_usina.dropna().unique()
        if len(nomes) != 1:
            raise ValueError(f"Nome ausente ou inconsistente para hydro_id {hydro_id} no resumo do {rotulo}.")
        validas = grupo.loc[grupo.status.eq("Calculado")]
        for medida, coluna, unidade, modulo in MEDIDAS_P90:
            valores_fontes, tamanhos = {}, {}
            for fonte in ("Sintético", "Histórico"):
                numeros = pd.to_numeric(validas.loc[validas.fonte.eq(fonte), coluna], errors="coerce")
                numeros = numeros.to_numpy(dtype=float, na_value=np.nan)
                numeros = numeros[np.isfinite(numeros)]
                if modulo:
                    numeros = np.abs(numeros)
                tamanhos[fonte] = len(numeros)
                valores_fontes[fonte] = float(np.quantile(numeros, percentil/100, method="linear")) if len(numeros) else np.nan
            s, h = valores_fontes["Sintético"], valores_fontes["Histórico"]
            comparavel = bool(np.isfinite(s) and np.isfinite(h))
            motivo = "; ".join(f"{fonte}: sem valores válidos para esta medida"
                               for fonte in ("Sintético", "Histórico") if tamanhos[fonte] == 0)
            resultado = ("Sintético maior" if s > h else "Sintético menor" if s < h else "Igual") if comparavel else "Sem comparação"
            linhas.append(dict(hydro_id=int(hydro_id), nome_usina=nomes[0], medida=medida,
                               unidade=unidade, n_sintetico=tamanhos["Sintético"], n_historico=tamanhos["Histórico"],
                               comparavel=comparavel, resultado=resultado, motivo=motivo,
                               **{coluna_s: s, coluna_h: h}))
    por_usina = pd.DataFrame(linhas, columns=colunas_por_usina)
    indicadores = []
    for medida, _, _, _ in MEDIDAS_P90:
        tabela = por_usina.loc[por_usina.medida.eq(medida)]
        n = int(tabela.comparavel.sum())
        maiores = int(tabela.resultado.eq("Sintético maior").sum())
        indicadores.append(dict(medida=medida, usinas_total=len(tabela), usinas_comparaveis=n,
                                usinas_sintetico_maior=maiores,
                                usinas_iguais=int(tabela.resultado.eq("Igual").sum()),
                                usinas_sintetico_menor=int(tabela.resultado.eq("Sintético menor").sum()),
                                usinas_sem_comparacao=len(tabela)-n,
                                percentual_sintetico_maior=100*maiores/n if n else np.nan))
    return por_usina, pd.DataFrame(indicadores, columns=COLUNAS_INDICADORES)


def calcular_indicadores_p90(resumos):
    """Preserva a análise do P90 e suas colunas de conferência."""
    return _calcular_indicadores_percentil(resumos, 90)


def calcular_indicadores_p50(resumos):
    """Mediana dos extremos por trajetória, com as mesmas regras do P90."""
    return _calcular_indicadores_percentil(resumos, 50)
