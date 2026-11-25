"""Raio espectral do ciclo mensal do PAR(p)-A, a partir dos parâmetros exportados.

O produto das matrizes companheiras é cronológico, com o mês seguinte à
esquerda. Os coeficientes normalizados são convertidos antes de combinar AR
mensal e anual. Não usa amostras de vazões, condições iniciais ou p-valores.
"""
import re

from infraestrutura.preparar_ambiente import garantir_dependencias

garantir_dependencias({'duckdb': 'duckdb>=0.10', 'pandas': 'pandas>=2.0',
                       'numpy': 'numpy>=1.24', 'pyarrow': 'pyarrow>=14'})
import duckdb
import numpy as np
import pandas as pd
import pyarrow.parquet as pq


def _ausente(motivo):
    return {'valor': None, 'motivo': motivo}


def _numero(v, nome):
    if v is None or not np.isfinite(v):
        raise ValueError(f'{nome} ausente ou não finito.')
    return float(v)


def raio_do_ciclo(parametros, mes_inicial=1):
    """Recebe um parâmetro por mês civil; devolve rho(T_12 ... T_1)."""
    if set(parametros) != set(range(1, 13)):
        raise ValueError('São necessários parâmetros para os 12 meses civis.')
    if not 1 <= mes_inicial <= 12:
        raise ValueError('Mês inicial inválido.')
    desvios = {m: _numero(p.get('seasonal_std_m3s'), 'Desvio sazonal')
               for m, p in parametros.items()}
    if any(s < 0 for s in desvios.values()):
        raise ValueError('Desvio sazonal negativo.')
    produto = np.eye(12)
    for i in range(12):
        mes = (mes_inicial - 1 + i) % 12 + 1
        p = parametros[mes]
        ordem = _numero(p.get('ar_order'), 'Ordem mensal')
        if ordem != int(ordem) or not 0 <= ordem <= 12:
            raise ValueError('Ordem mensal incompatível com o ciclo de 12 meses.')
        anual = _numero(p.get('annual_coefficient'), 'Coeficiente anual')
        sd_anual = _numero(p.get('annual_std_m3s'), 'Desvio anual')
        if sd_anual < 0 or (anual != 0 and sd_anual == 0):
            raise ValueError('Desvio anual inválido para o coeficiente exportado.')
        peso_anual = anual * desvios[mes] / sd_anual / 12 if anual != 0 else 0.
        pesos = np.full(12, peso_anual)
        for lag in range(1, int(ordem) + 1):
            ar = _numero(p.get(f'ar_coefficient_lag_{lag}'), f'AR de lag {lag}')
            sd_lag = desvios[(mes - lag - 1) % 12 + 1]
            # Mesma guarda da conversão do gerador: desvio defasado zero
            # anula somente a parcela AR, preservando a parcela anual.
            if sd_lag != 0:
                pesos[lag - 1] += ar * desvios[mes] / sd_lag
        transicao = np.zeros((12, 12))
        transicao[0] = pesos
        transicao[1:, :-1] = np.eye(11)
        produto = transicao @ produto
    if not np.isfinite(produto).all():
        raise ValueError('Transição anual não finita.')
    valor = float(np.max(np.abs(np.linalg.eigvals(produto))))
    if not np.isfinite(valor):
        raise ValueError('Raio espectral não finito.')
    return valor


def calcular_raios_espectrais(caminho, calendario, ids_usinas):
    """Confere repetição entre todos os cenários/anos antes de calcular por UHE.

    Retorna valores ausentes para arquivos legados sem parâmetros ou para
    ciclos inconsistentes. Falhas de leitura do arquivo continuam sendo erros.
    """
    ids = sorted(int(u) for u in ids_usinas)
    if not ids:
        return {}
    campos = pq.read_schema(caminho).names
    obrigatorios = ['hydro_id', 'stage_id', 'ar_order', 'seasonal_std_m3s',
                    'annual_coefficient', 'annual_std_m3s']
    faltantes = sorted(set(obrigatorios) - set(campos))
    if faltantes:
        motivo = 'Parquet sem os parâmetros necessários: ' + ', '.join(faltantes) + '.'
        return {str(u): _ausente(motivo) for u in ids}
    etapas = []
    try:
        for stage, e in calendario.items():
            inicio, fim = pd.Timestamp(e['inicio']), pd.Timestamp(e['fim'])
            if inicio.day != 1 or fim != inicio + pd.offsets.MonthBegin():
                raise ValueError('O raio anual requer estágios mensais completos.')
            if int(e['mes']) != inicio.month:
                raise ValueError('Mês civil inconsistente no calendário.')
            etapas.append({'stage_id': int(stage), 'mes': inicio.month, 'inicio': inicio})
        etapas.sort(key=lambda e: e['inicio'])
        if not etapas:
            raise ValueError('Calendário vazio.')
        if any(a['inicio'] + pd.offsets.MonthBegin() != b['inicio']
               for a, b in zip(etapas, etapas[1:])):
            raise ValueError('Calendário com lacunas ou meses duplicados.')
    except (ValueError, KeyError, TypeError) as erro:
        return {str(u): _ausente(str(erro)) for u in ids}
    lags = sorted((c for c in campos if re.fullmatch(r'ar_coefficient_lag_[1-9]\d*', c)),
                  key=lambda c: int(c.rsplit('_', 1)[1]))
    parametros = obrigatorios[2:] + lags
    selecao = ', '.join('p."' + c + '"' for c in parametros)
    with duckdb.connect() as con:
        con.register('calendario_raio', pd.DataFrame(etapas)[['stage_id', 'mes']])
        con.register('usinas_raio', pd.DataFrame({'hydro_id': ids}))
        # DISTINCT inclui todas as linhas: não escolhe silenciosamente o
        # primeiro cenário quando os parâmetros divergem entre cenários/anos.
        rows = con.execute(f'''SELECT DISTINCT p.hydro_id, c.mes, {selecao}
            FROM read_parquet(?) p JOIN usinas_raio u USING(hydro_id)
            LEFT JOIN calendario_raio c USING(stage_id)''', [str(caminho)]).fetchall()
    grupos = {u: [] for u in ids}
    for u, mes, *valores in rows:
        grupos[u].append((mes, dict(zip(parametros, valores))))
    resultado = {}
    for u, registros in grupos.items():
        try:
            meses = {}
            for mes, p in registros:
                if mes is None:
                    raise ValueError('Parâmetros com estágio ausente do calendário.')
                # Lags inativos não fazem parte da equação, mesmo quando
                # arquivos equivalentes os representam como null ou zero.
                ordem = _numero(p.get('ar_order'), 'Ordem mensal')
                chave = {k: v for k, v in p.items()
                         if not k.startswith('ar_coefficient_lag_')
                         or int(k.rsplit('_', 1)[1]) <= ordem}
                if mes in meses and meses[mes] != chave:
                    raise ValueError('Parâmetros do mesmo mês variam entre cenários ou anos.')
                meses[mes] = chave
            valor = raio_do_ciclo(meses, etapas[0]['mes'])
            resultado[str(u)] = {'valor': valor, 'motivo': ''}
        except (ValueError, OverflowError, np.linalg.LinAlgError) as erro:
            resultado[str(u)] = _ausente(str(erro))
    return resultado
