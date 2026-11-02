"""Correlação de lag zero entre somas de vazões incrementais de bacias.

Cada coeficiente sintético usa os anos de uma única trajetória. A distribuição
dos coeficientes não é um teste de hipótese nem uma média de correlações de UHEs.
"""

from dataclasses import dataclass

from calculos.correlacao_espacial_cobre import _calcular_estagio, _identificadores
from calculos.base_estatistica_cobre import _preparar_historico

import duckdb
import numpy as np
import pandas as pd


MOTIVOS_ANUAIS = {
    0: "",
    1: "Menos de dois anos completos comuns às duas bacias.",
    2: "Média anual de uma das bacias constante entre os anos pareados.",
    3: "Médias anuais quase constantes; correlação numericamente instável.",
    4: "Coeficiente numericamente inválido ou fora de [-1, 1].",
}


@dataclass
class ResultadoAnualBacias:
    sintetico: pd.DataFrame
    historico: pd.DataFrame
    composicao: pd.DataFrame
    sem_bacia: pd.DataFrame
    cenarios: tuple[int, ...]
    anos_completos: tuple[int, ...]
    anos_incompletos: tuple[int, ...]


def _conferir_datas_mensais(inicios, fins):
    inicio = pd.to_datetime(inicios, errors="coerce")
    fim = pd.to_datetime(fins, errors="coerce")
    periodos = inicio.dt.to_period("M")
    if (inicio.isna().any() or fim.isna().any()
            or not inicio.eq(periodos.dt.start_time).all()
            or not fim.eq((periodos + 1).dt.start_time).all()):
        raise ValueError("A análise anual exige registros mensais: início no dia 1 e fim no dia 1 do mês seguinte.")
    return periodos


def _medias_anuais(conexao, tabela, chaves):
    # Uma média anual só existe quando os 12 totais mensais são completos.
    # SUM/AVG ignoram nulos no SQL: a condição explícita impede somas parciais.
    grupos = ", ".join(chaves)
    return conexao.execute(f"""
        SELECT {grupos}, ano, count(*) AS meses_presentes,
               count(vazao_mensal) AS meses_validos,
               CASE WHEN count(*) = 12 AND count(DISTINCT mes) = 12
                         AND count(vazao_mensal) = 12
                    THEN avg(vazao_mensal) END AS media_anual_m3s
        FROM {tabela} GROUP BY {grupos}, ano ORDER BY {grupos}, ano
    """).df()


def gerar_medias_anuais_bacias(caminho, caminho_historico, calendario, cadastro):
    """Agrega antes de carregar em memória; conserva a composição nas duas fontes."""
    if cadastro.hydro_id.duplicated().any():
        raise ValueError("Uma UHE não pode participar de mais de uma bacia.")
    with duckdb.connect(database=":memory:") as conexao:
        cenarios, estagios, usinas = _identificadores(conexao, str(caminho), None)
        if set(estagios) - set(calendario):
            raise ValueError("Há estágios sintéticos sem datas no calendário.")
        composicao = cadastro.loc[cadastro.hydro_id.isin(usinas), ["hydro_id", "Usina", "bacia_id", "Bacia"]].copy()
        sem_cadastro = sorted(set(usinas) - set(composicao.hydro_id))
        if sem_cadastro:
            composicao = pd.concat([composicao, pd.DataFrame({
                "hydro_id": sem_cadastro, "Usina": [f"UHE {i}" for i in sem_cadastro],
                "bacia_id": pd.NA, "Bacia": None,
            })], ignore_index=True)
        sem_bacia = composicao.loc[composicao.bacia_id.isna()].copy()
        composicao = composicao.dropna(subset=["bacia_id"]).copy()
        if composicao.empty:
            raise ValueError("Nenhuma UHE do Parquet foi identificada nas bacias do cadastro.")
        composicao["bacia_id"] = composicao.bacia_id.astype(int)
        composicao["n_usinas"] = composicao.groupby("bacia_id").hydro_id.transform("size")
        datas = pd.DataFrame([{
            "stage_id": s, "inicio": calendario[s]["inicio"], "fim": calendario[s]["fim"],
        } for s in estagios])
        periodos = _conferir_datas_mensais(datas.inicio, datas.fim)
        if periodos.duplicated().any():
            raise ValueError("Há mais de um estágio sintético associado ao mesmo mês.")
        datas["ano"], datas["mes"] = periodos.dt.year, periodos.dt.month
        contagens = datas.groupby("ano").mes.nunique()
        anos = tuple(int(a) for a in contagens.index[contagens.eq(12)])
        incompletos = tuple(int(a) for a in contagens.index[contagens.ne(12)])
        conexao.register("composicao", composicao)
        conexao.register("calendario", datas[["stage_id", "ano", "mes"]])
        duplicada = conexao.execute("""
            SELECT p.hydro_id, p.stage_id, p.scenario_id
            FROM read_parquet(?) p JOIN composicao b USING(hydro_id)
            GROUP BY p.hydro_id, p.stage_id, p.scenario_id
            HAVING count(*) > 1 LIMIT 1
        """, [str(caminho)]).fetchone()
        if duplicada:
            raise ValueError("Chave UHE × estágio × cenário duplicada: " + str(duplicada))
        # Primeiro soma as UHEs no mesmo mês e cenário; nunca mistura trajetórias.
        conexao.execute("""
            CREATE TEMP TABLE mensal_sintetico AS
            SELECT p.scenario_id, b.bacia_id, k.ano, k.mes,
                CASE WHEN count(*) = max(b.n_usinas)
                          AND count(DISTINCT p.hydro_id) = max(b.n_usinas)
                          AND count(*) FILTER (WHERE isfinite(p.incremental_inflow_m3s)) = max(b.n_usinas)
                     THEN sum(p.incremental_inflow_m3s) END AS vazao_mensal
            FROM read_parquet(?) p JOIN composicao b USING(hydro_id)
                 JOIN calendario k USING(stage_id)
            GROUP BY p.scenario_id, b.bacia_id, k.ano, k.mes
        """, [str(caminho)])
        sintetico = _medias_anuais(conexao, "mensal_sintetico", ["scenario_id", "bacia_id"])

        bruto = conexao.execute("""
            SELECT p.hydro_id, p.start_date, p.end_date, p.value_m3s
            FROM read_parquet(?) p JOIN composicao b USING(hydro_id)
        """, [str(caminho_historico)]).df()
        preparados = []
        for hydro_id, grupo in bruto.groupby("hydro_id", sort=False):
            dados, _, _, _ = _preparar_historico(grupo, int(hydro_id))
            _conferir_datas_mensais(dados.start_date, dados.end_date)
            preparados.append(dados[["hydro_id", "year", "month", "value_m3s"]])
        historico_mensal = (pd.concat(preparados, ignore_index=True) if preparados else
                            pd.DataFrame(columns=["hydro_id", "year", "month", "value_m3s"]))
        conexao.register("historico_mensal", historico_mensal)
        # O denominador n_usinas é o mesmo do sintético, inclusive quando uma
        # UHE não possui histórico. Nesse caso o total incompleto fica nulo.
        conexao.execute("""
            CREATE TEMP TABLE mensal_historico AS
            SELECT b.bacia_id, h.year AS ano, h.month AS mes,
                CASE WHEN count(*) = max(b.n_usinas)
                          AND count(DISTINCT h.hydro_id) = max(b.n_usinas)
                          AND count(*) FILTER (WHERE isfinite(h.value_m3s)) = max(b.n_usinas)
                     THEN sum(h.value_m3s) END AS vazao_mensal
            FROM historico_mensal h JOIN composicao b USING(hydro_id)
            GROUP BY b.bacia_id, h.year, h.month
        """)
        historico = _medias_anuais(conexao, "mensal_historico", ["bacia_id"])
    return ResultadoAnualBacias(sintetico, historico, composicao.drop(columns="n_usinas"),
                               sem_bacia, cenarios, anos, incompletos)


def comparar_bacias_anuais(resultado, referencia):
    """Um coeficiente por cenário/par e um histórico, com anos comuns reais."""
    bacias = sorted(int(b) for b in resultado.composicao.bacia_id.unique())
    if referencia not in bacias:
        raise ValueError("Bacia de referência ausente na composição do estudo.")
    nomes = resultado.composicao.set_index("bacia_id").Bacia.to_dict()
    ref = bacias.index(referencia)
    outras = [i for i, b in enumerate(bacias) if b != referencia]
    indice = pd.MultiIndex.from_product([resultado.cenarios, resultado.anos_completos],
                                         names=["scenario_id", "ano"])
    matriz = resultado.sintetico.pivot(index=["scenario_id", "ano"], columns="bacia_id", values="media_anual_m3s")
    matriz = matriz.reindex(index=indice, columns=bacias).to_numpy(dtype=float)
    valores = matriz.reshape(len(resultado.cenarios), len(resultado.anos_completos), len(bacias))
    linhas = []
    for scenario_id, trajetoria in zip(resultado.cenarios, valores):
        # Reutiliza Pearson centralizado, os pares finitos e os diagnósticos da
        # aba 4. Aqui as linhas são ANOS do cenário, não cenários de um estágio.
        n, r, _, _, _, estados = _calcular_estagio(trajetoria)
        for j in outras:
            linhas.append({"Bacia referência": nomes[referencia], "bacia_id": bacias[j],
                           "Bacia comparada": nomes[bacias[j]], "scenario_id": scenario_id,
                           "Anos pareados": int(n[ref, j]), "Correlação": r[ref, j],
                           "Motivo": MOTIVOS_ANUAIS[int(estados[ref, j])]})
    coeficientes = pd.DataFrame(linhas, columns=["Bacia referência", "bacia_id", "Bacia comparada",
                                                "scenario_id", "Anos pareados", "Correlação", "Motivo"])
    hist = resultado.historico.pivot(index="ano", columns="bacia_id", values="media_anual_m3s").reindex(columns=bacias)
    h = hist.to_numpy(dtype=float)
    n, r, _, _, _, estados = _calcular_estagio(h)
    resumo = []
    for j in outras:
        grupo = coeficientes.loc[coeficientes.bacia_id.eq(bacias[j])]
        validos = int(grupo["Correlação"].notna().sum())
        anos_h = hist.index[np.isfinite(h[:, ref]) & np.isfinite(h[:, j])].tolist()
        resumo.append({"bacia_id": bacias[j], "Bacia comparada": nomes[bacias[j]],
                       "Cenários válidos": validos,
                       "Cenários indisponíveis": len(resultado.cenarios) - validos,
                       "Mínimo de anos por cenário": int(grupo["Anos pareados"].min()),
                       "Máximo de anos por cenário": int(grupo["Anos pareados"].max()),
                       "Correlação histórica": r[ref, j], "Anos históricos pareados": int(n[ref, j]),
                       "Anos históricos usados": ", ".join(str(int(a)) for a in anos_h),
                       "Motivo histórico": MOTIVOS_ANUAIS[int(estados[ref, j])]})
    return coeficientes, pd.DataFrame(resumo)
