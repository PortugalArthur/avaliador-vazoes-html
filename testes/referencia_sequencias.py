"""Referência congelada anterior à otimização em lote. Uso exclusivo dos testes."""
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

    resumos_h, eventos_h = [], []
    for bloco in blocos.to_dict("records"):
        p = pd.period_range(bloco["inicio"], periods=h, freq="M")
        fatia = historico.set_index("periodo").reindex(p)
        valores = fatia.value_m3s.to_numpy(float)
        motivo = "Bloco histórico com mês ausente" if fatia.hydro_id.isna().any() else ""
        metah = pd.DataFrame([dict(hydro_id=hydro_id, nome_usina=nome, fonte="Histórico",
                                  trajetoria_id=bloco["trajetoria_id"], inicio=p[0].start_time,
                                  fim=p[-1].start_time, horizonte_meses=h)])
        rh, eh = _calcular_matriz(valores[None, :], limites, p.to_timestamp(), metah, [motivo])
        resumos_h.append(rh)
        eventos_h.append(eh)
    rh = pd.concat(resumos_h, ignore_index=True) if resumos_h else rs.iloc[:0].copy()
    eh = pd.concat(eventos_h, ignore_index=True) if eventos_h else es.iloc[:0].copy()
    if len(blocos):
        blocos = blocos.merge(rh[["trajetoria_id", "status", "motivo"]], on="trajetoria_id", validate="one_to_one")
    elif historico is not None:
        diagnosticos.append(dict(hydro_id=hydro_id, nome_usina=nome, fonte="Histórico", motivo="Nenhum bloco histórico completo para o horizonte e mês inicial"))
    return ResultadoSequencias(horizonte.copy(), mlts, _identificar(blocos, hydro_id, nome),
                               _identificar(descartes, hydro_id, nome), pd.concat([rs, rh], ignore_index=True),
                               pd.concat([es, eh], ignore_index=True),
                               pd.DataFrame(diagnosticos, columns=["hydro_id", "nome_usina", "fonte", "motivo"]))
