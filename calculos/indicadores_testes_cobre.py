"""Contadores gerais dos testes, calculados somente para o intervalo visível."""

import pandas as pd


def mascara_testes_validos(resultados):
    p = pd.to_numeric(resultados["p_valor"], errors="coerce")
    return resultados["status_teste"].eq("Calculado") & p.between(0, 1).fillna(False)


def calcular_indicadores_gerais(resultados,coluna_decisao):
    validos = mascara_testes_validos(resultados)
    reprovados = validos & resultados[coluna_decisao].fillna(False).astype(bool)
    calculadas = int(validos.sum())
    rejeitadas = int(reprovados.sum())
    etapas = int(resultados.stage_id.nunique())
    dados = resultados[["hydro_id","stage_id"]].assign(valido=validos.to_numpy(),reprovado=reprovados.to_numpy())
    grupos = dados.groupby("hydro_id",observed=True)
    contagens = grupos.valido.sum()
    testadas = contagens.gt(0)
    total_usinas = int(testadas.sum())
    # Uma ausência de reprovação não basta: cada estágio do intervalo precisa
    # ter um teste válido e aprovado, inclusive quando faltam linhas na fonte.
    etapas_validas = dados.loc[dados.valido].groupby("hydro_id",observed=True).stage_id.nunique()
    completos = etapas_validas.reindex(contagens.index,fill_value=0).eq(etapas)
    sem_falhas = grupos.valido.all()
    sem_reprovacao = ~grupos.reprovado.any()
    totalmente_aprovadas = int((testadas & completos & sem_falhas & sem_reprovacao).sum())
    return dict(combinacoes_calculadas=calculadas,combinacoes_reprovadas=rejeitadas,
                percentual_combinacoes_aprovadas=100*(calculadas-rejeitadas)/calculadas if calculadas else None,
                total_usinas=total_usinas,usinas_reprovadas=int(resultados.loc[reprovados,"hydro_id"].nunique()),
                percentual_usinas_completamente_aprovadas=100*totalmente_aprovadas/total_usinas if total_usinas else None,
                usinas_completamente_aprovadas=totalmente_aprovadas,
                usinas_sem_testes_validos=int(resultados.hydro_id.nunique())-total_usinas,
                combinacoes_nao_calculadas=len(resultados)-calculadas)
