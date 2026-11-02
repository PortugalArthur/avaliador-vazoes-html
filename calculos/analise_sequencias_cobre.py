"""Contas auditáveis de sequências negativas, sem dependência de interface."""

from dataclasses import dataclass
import math

from calculos.base_estatistica_cobre import NOMES_MESES, _preparar_historico
import numpy as np
import pandas as pd


ESTATISTICAS = ["quantidade_sequencias", "comprimento_medio", "comprimento_maximo",
               "comprimento_minimo", "soma_media", "soma_mais_severa", "soma_menos_severa",
               "intensidade_media", "intensidade_mais_severa", "intensidade_menos_severa"]
VERSAO_JANELAS_HISTORICAS = 2
EVENTOS = ["hydro_id", "nome_usina", "fonte", "trajetoria_id", "numero_sequencia",
           "inicio", "fim", "comprimento", "soma", "intensidade", "borda_inicial", "borda_final"]


@dataclass
class ResultadoSequencias:
    horizonte: pd.DataFrame
    mlts: pd.DataFrame
    blocos: pd.DataFrame
    intervalos_nao_utilizados: pd.DataFrame
    resumos: pd.DataFrame
    eventos: pd.DataFrame
    diagnosticos: pd.DataFrame


def organizar_horizonte(calendario, ids_estagios):
    """Validação: horizonte mensal completo, ordenado pelas datas, sem IDs fixos."""
    ids = set(int(i) for i in ids_estagios)
    if not ids or ids - set(calendario):
        raise ValueError("Horizonte vazio ou com estágios sem calendário.")
    linhas = [{"stage_id": i, "periodo": pd.Period(calendario[i]["inicio"], freq="M")}
              for i in ids]
    tabela = pd.DataFrame(linhas).sort_values("periodo").reset_index(drop=True)
    esperados = pd.period_range(tabela.periodo.iloc[0], periods=len(tabela), freq="M")
    if tabela.periodo.tolist() != list(esperados):
        raise ValueError("O horizonte deve conter exatamente um estágio em cada mês consecutivo.")
    tabela["inicio"] = tabela.periodo.dt.to_timestamp()
    tabela["mes"] = tabela.periodo.dt.month
    return tabela


def calcular_mlts(historico, hydro_id, nome):
    """Etapa 1: médias dos meses com TODO o histórico, inclusive fora dos blocos."""
    linhas = []
    for mes in range(1, 13):
        grupo = historico.loc[historico["month"].eq(mes)]
        validos = grupo.loc[grupo.value_is_finite]
        valores = validos.value_m3s.to_numpy(dtype=float)
        # Soma compensada preserva a precisão antes da divisão, sem arredondar.
        # Se a soma exceder o limite numérico, calcular a mesma média escalonada.
        media = np.nan
        if len(valores):
            try:
                media = math.fsum(valores) / len(valores)
            except OverflowError:
                media = math.fsum(v / len(valores) for v in valores)
        linhas.append(dict(hydro_id=hydro_id, nome_usina=nome, mes=mes,
                           mes_nome=NOMES_MESES[mes], mlt=media, n_validos=len(validos),
                           n_invalidos=len(grupo)-len(validos),
                           primeiro_periodo=validos.start_date.min(),
                           ultimo_periodo=validos.start_date.max()))
    return pd.DataFrame(linhas)


def formar_blocos_historicos(inicio, fim, horizonte_meses, mes_inicial):
    """Etapa 2: janelas completas, mesmo mês inicial, recuando um ano por vez.

    A duração determina o mês final: nos estudos encerrados em dezembro, a
    primeira janela termina no dezembro mais recente disponível no histórico.
    Os meses compartilhados não são retirados das janelas posteriores.
    """
    h = int(horizonte_meses)
    if h < 1 or not 1 <= int(mes_inicial) <= 12:
        raise ValueError("Horizonte e mês inicial inválidos.")
    inicio, fim = pd.Period(inicio, freq="M"), pd.Period(fim, freq="M")
    if fim < inicio:
        raise ValueError("Limites históricos invertidos.")
    limite = fim - (h - 1)
    atual = limite - ((limite.month - int(mes_inicial)) % 12)
    passo = 12
    linhas = []
    while atual >= inicio:
        linhas.append(dict(trajetoria_id=len(linhas)+1, inicio=atual.start_time,
                           fim=(atual+h-1).start_time, horizonte_meses=h,
                           passo_meses=passo, intervalo_entre_blocos=max(0, passo-h),
                           sobreposicao_meses=max(0, h-passo)))
        atual -= passo
    colunas = ["trajetoria_id", "inicio", "fim", "horizonte_meses", "passo_meses",
               "intervalo_entre_blocos", "sobreposicao_meses"]
    blocos = pd.DataFrame(linhas, columns=colunas)
    intervalos, cursor = [], inicio
    for bloco in reversed(linhas):
        a, b = pd.Period(bloco["inicio"], freq="M"), pd.Period(bloco["fim"], freq="M")
        if cursor < a:
            intervalos.append(dict(inicio=cursor.start_time, fim=(a-1).start_time,
                                   meses=a.ordinal-cursor.ordinal,
                                   motivo="Trecho antigo" if cursor == inicio else "Intervalo entre blocos"))
        # Cobertura é a UNIÃO das janelas, sem contar meses sobrepostos duas vezes.
        cursor = max(cursor, b + 1)
    if cursor <= fim:
        intervalos.append(dict(inicio=cursor.start_time, fim=fim.start_time,
                               meses=fim.ordinal-cursor.ordinal+1,
                               motivo="Histórico sem bloco completo" if not linhas else "Trecho recente"))
    return blocos, pd.DataFrame(intervalos, columns=["inicio", "fim", "meses", "motivo"])


def _calcular_matriz(valores, limites, periodos, metadados, motivos):
    """Etapas 3–7: eventos, C, S, I e agregação. Uma linha por trajetória."""
    valores, limites = np.asarray(valores, float), np.asarray(limites, float)
    if valores.ndim != 2 or valores.shape[1] != len(limites):
        raise ValueError("Dimensões das trajetórias e limites incompatíveis.")
    n, h = valores.shape
    resumo = metadados.copy().reset_index(drop=True)
    motivos = np.asarray(motivos, dtype=object).copy()
    if not np.isfinite(limites).all():
        motivos[motivos == ""] = "MLT mensal indisponível ou não finita"
    motivos[(motivos == "") & ~np.isfinite(valores).all(axis=1)] = "Vazão ausente ou não finita"

    # Etapa 3: o marcador virtual False em cada borda encerra o evento,
    # sem alterar o primeiro/último valor nem acrescentar meses à sequência.
    validos = motivos == ""
    negativos = (valores < limites) & validos[:, None]
    anterior = np.pad(negativos, ((0, 0), (1, 0)), constant_values=False)[:, :-1]
    seguinte = np.pad(negativos, ((0, 0), (0, 1)), constant_values=False)[:, 1:]
    trajetorias, inicios = np.nonzero(negativos & ~anterior)
    trajetorias_fim, fins = np.nonzero(negativos & ~seguinte)
    if not np.array_equal(trajetorias, trajetorias_fim):
        raise ArithmeticError("Inícios e fins de sequências não correspondem.")

    # Etapa 4: comprimento é a contagem inclusiva dos meses negativos.
    comprimentos = fins - inicios + 1
    # Etapa 5: soma das diferenças ASSINADAS Q - MLT somente dentro do evento.
    with np.errstate(over="ignore", invalid="ignore"):
        diferencas = np.where(negativos, valores - limites, 0.)
        # Entre um início e o próximo só há este evento e diferenças zero.
        # Somar cada segmento evita subtrair grandes acumulados e perder
        # déficits pequenos de sequências posteriores por cancelamento.
        somas = (np.add.reduceat(diferencas.ravel(), trajetorias*h+inicios)
                 if len(inicios) else np.array([], dtype=float))
        # Etapa 6: intensidade de cada evento, nunca média ponderada por duração.
        intensidades = somas / comprimentos
    ruins = ~np.isfinite(somas) | ~np.isfinite(intensidades)
    if ruins.any():
        motivos[np.unique(trajetorias[ruins])] = "Resultado numérico não finito nas sequências"
        manter = motivos[trajetorias] == ""
        trajetorias, inicios, fins, comprimentos, somas, intensidades = [
            a[manter] for a in (trajetorias, inicios, fins, comprimentos, somas, intensidades)]

    # Etapa 7: médias aritméticas e extremos POR trajetória. K = 0 gera zeros.
    contagens = np.bincount(trajetorias, minlength=n)
    resumo["quantidade_sequencias"] = contagens
    for prefixo, numeros in [("comprimento", comprimentos), ("soma", somas), ("intensidade", intensidades)]:
        totais = np.bincount(trajetorias, weights=numeros, minlength=n)
        medias = np.divide(totais, contagens, out=np.zeros(n), where=contagens > 0)
        minimos, maximos = np.full(n, np.inf), np.full(n, -np.inf)
        np.minimum.at(minimos, trajetorias, numeros)
        np.maximum.at(maximos, trajetorias, numeros)
        minimos[contagens == 0] = maximos[contagens == 0] = 0
        resumo[prefixo + ("_medio" if prefixo == "comprimento" else "_media")] = medias
        resumo[prefixo + "_minimo"] = minimos
        resumo[prefixo + "_maximo"] = maximos
        if prefixo != "comprimento":
            resumo[prefixo + "_mais_severa"] = minimos
            resumo[prefixo + "_menos_severa"] = maximos
    numericas = list(resumo.columns[metadados.shape[1]:])
    overflow = ~np.isfinite(resumo[numericas].to_numpy(float)).all(axis=1)
    motivos[(motivos == "") & overflow] = "Resultado numérico não finito na agregação"
    resumo["status"] = np.where(motivos == "", "Calculado", "Não calculado")
    resumo["motivo"] = motivos
    resumo.loc[motivos != "", numericas] = np.nan

    eventos = metadados.iloc[trajetorias][["hydro_id", "nome_usina", "fonte", "trajetoria_id"]].reset_index(drop=True)
    eventos["numero_sequencia"] = eventos.groupby("trajetoria_id", sort=False).cumcount()+1
    datas = np.asarray(periodos, dtype="datetime64[ns]")
    eventos["inicio"], eventos["fim"] = datas[inicios], datas[fins]
    eventos["comprimento"], eventos["soma"], eventos["intensidade"] = comprimentos, somas, intensidades
    eventos["borda_inicial"], eventos["borda_final"] = inicios == 0, fins == h-1
    eventos = eventos.loc[motivos[trajetorias] == "", EVENTOS].reset_index(drop=True)
    return resumo, eventos


def analisar_trajetoria(valores, limites, periodos=None):
    """Entrada pequena para conferência manual, usando o mesmo núcleo do lote."""
    h = len(valores)
    if h == 0 or len(limites) != h:
        raise ValueError("Vetores vazios ou tamanhos incompatíveis.")
    periodos = pd.date_range("2000-01-01", periods=h, freq="MS") if periodos is None else periodos
    meta = pd.DataFrame([dict(hydro_id=0, nome_usina="Conferência", fonte="Sintético", trajetoria_id=0,
                              inicio=periodos[0], fim=periodos[-1], horizonte_meses=h)])
    resumo, eventos = _calcular_matriz(np.asarray(valores)[None, :], limites, periodos, meta, [""])
    return resumo.iloc[0].to_dict(), eventos


def _identificar(tabela, hydro_id, nome):
    tabela = tabela.copy()
    tabela.insert(0, "nome_usina", nome)
    tabela.insert(0, "hydro_id", hydro_id)
    return tabela


def calcular_sequencias_usina(cenarios, historico_bruto, hydro_id, nome, horizonte):
    """Aplica o núcleo à UHE inteira, preservando falhas por trajetória."""
    h = len(horizonte)
    periodos = pd.DatetimeIndex(horizonte.inicio)
    meses = horizonte.mes.to_numpy()
    diagnosticos = []
    historico = None
    try:
        historico, a, b, _ = _preparar_historico(historico_bruto, hydro_id)
        mlts = calcular_mlts(historico, hydro_id, nome)
        blocos, descartes = formar_blocos_historicos(a, b, h, int(meses[0]))
    except ValueError as erro:
        diagnosticos.append(dict(hydro_id=hydro_id, nome_usina=nome, fonte="Histórico", motivo=str(erro)))
        vazio = pd.DataFrame(columns=["month", "value_is_finite", "value_m3s", "start_date"])
        mlts = calcular_mlts(vazio, hydro_id, nome)
        blocos = pd.DataFrame(columns=["trajetoria_id", "inicio", "fim", "horizonte_meses"])
        descartes = pd.DataFrame(columns=["inicio", "fim", "meses", "motivo"])
    limites = mlts.set_index("mes").mlt.reindex(meses).to_numpy(float)

    ids = sorted(int(i) for i in cenarios.scenario_id.dropna().unique())
    meta = pd.DataFrame([dict(hydro_id=hydro_id, nome_usina=nome, fonte="Sintético", trajetoria_id=i,
                             inicio=periodos[0], fim=periodos[-1], horizonte_meses=h) for i in ids],
                        columns=["hydro_id", "nome_usina", "fonte", "trajetoria_id", "inicio", "fim", "horizonte_meses"])
    if ids:
        dados = cenarios.copy()
        dados["valor"] = pd.to_numeric(dados.incremental_inflow_m3s, errors="coerce")
        grupos = dados.groupby(["scenario_id", "stage_id"], sort=False)
        contagens = grupos.size().unstack().reindex(index=ids, columns=horizonte.stage_id, fill_value=0).fillna(0)
        matriz = grupos.valor.first().unstack().reindex(index=ids, columns=horizonte.stage_id).to_numpy(float)
        motivos = np.full(len(ids), "", dtype=object)
        motivos[(contagens == 0).any(axis=1)] = "Cenário com mês ausente no horizonte"
        motivos[(contagens > 1).any(axis=1)] = "Cenário com mês duplicado (inclusive entre nós)"
        fora = dados.loc[~dados.stage_id.isin(horizonte.stage_id), "scenario_id"]
        motivos[np.isin(ids, fora)] = "Cenário com estágio fora do horizonte"
    else:
        matriz, motivos = np.empty((0, h)), []
        diagnosticos.append(dict(hydro_id=hydro_id, nome_usina=nome, fonte="Sintético", motivo="Sem cenários para a UHE"))
    rs, es = _calcular_matriz(matriz, limites, periodos, meta, motivos)

    # Mesmo núcleo matemático, em lote: os índices mensais dos eventos são
    # reposicionados no calendário real de cada janela após as contas.
    metas_h, vetores_h, motivos_h, inicios_h = [], [], [], {}
    indexado = historico.set_index("periodo") if historico is not None else None
    for bloco in blocos.to_dict("records"):
        p = pd.period_range(bloco["inicio"], periods=h, freq="M")
        fatia = indexado.reindex(p)
        vetores_h.append(fatia.value_m3s.to_numpy(float))
        motivos_h.append("Bloco histórico com mês ausente" if fatia.hydro_id.isna().any() else "")
        metas_h.append(dict(hydro_id=hydro_id,nome_usina=nome,fonte="Histórico",
                            trajetoria_id=bloco["trajetoria_id"],inicio=p[0].start_time,
                            fim=p[-1].start_time,horizonte_meses=h))
        inicios_h[bloco["trajetoria_id"]] = p[0].ordinal
    if metas_h:
        rh, eh = _calcular_matriz(np.asarray(vetores_h),limites,periodos,pd.DataFrame(metas_h),motivos_h)
        base = pd.Period(periodos[0],freq="M").ordinal
        for coluna in ("inicio","fim"):
            deslocamentos = eh[coluna].dt.to_period("M").astype("int64") - base
            eh[coluna] = pd.PeriodIndex([pd.Period(ordinal=int(v),freq="M") for v in (eh.trajetoria_id.map(inicios_h)+deslocamentos)],freq="M").to_timestamp() if len(eh) else pd.Series(dtype="datetime64[ns]")
    else:
        rh, eh = rs.iloc[:0].copy(), es.iloc[:0].copy()
    if len(blocos):
        blocos = blocos.merge(rh[["trajetoria_id", "status", "motivo"]], on="trajetoria_id", validate="one_to_one")
    elif historico is not None:
        diagnosticos.append(dict(hydro_id=hydro_id, nome_usina=nome, fonte="Histórico", motivo="Nenhum bloco histórico completo para o horizonte e mês inicial"))
    return ResultadoSequencias(horizonte.copy(), mlts, _identificar(blocos, hydro_id, nome),
                               _identificar(descartes, hydro_id, nome), pd.concat([rs, rh], ignore_index=True),
                               pd.concat([es, eh], ignore_index=True),
                               pd.DataFrame(diagnosticos, columns=["hydro_id", "nome_usina", "fonte", "motivo"]))


def calcular_permanencia(valores):
    """P(X >= x), com denominador próprio, zeros e empates preservados."""
    numeros = np.asarray(valores, dtype=float)
    numeros = numeros[np.isfinite(numeros)]
    if not numeros.size:
        return pd.DataFrame(columns=["valor", "permanencia", "contagem", "n"])
    valores, contagens = np.unique(numeros, return_counts=True)
    valores, contagens = valores[::-1], contagens[::-1]
    return pd.DataFrame(dict(valor=valores, permanencia=100*np.cumsum(contagens)/len(numeros),
                             contagem=contagens, n=len(numeros)))
