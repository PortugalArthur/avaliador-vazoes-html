"""Referências analíticas e leitura dos parâmetros do ciclo periódico."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from calculos.raio_espectral import raio_do_ciclo, calcular_raios_espectrais
import numpy as np
import pandas as pd
from scipy.optimize import brentq


def parametros(ar=(.8,), anual=0.):
    return {m: {'ar_order': len(ar), 'seasonal_std_m3s': 10.,
                'annual_coefficient': anual, 'annual_std_m3s': 10.,
                **{f'ar_coefficient_lag_{k}': v for k, v in enumerate(ar, 1)}}
            for m in range(1, 13)}


def caso(pasta, meses=24):
    periodos = pd.period_range('2026-08', periods=meses, freq='M')
    cal = {500 - 7*i: {'inicio': p.start_time.date(),
                       'fim': (p+1).start_time.date(), 'mes': p.month}
           for i, p in enumerate(periodos)}
    rows = []
    for c in (2, 9):
        for stage, e in cal.items():
            rows.append({'scenario_id': c, 'hydro_id': 17, 'stage_id': stage,
                         **parametros()[e['mes']]})
    file = Path(pasta)/'dados.parquet'
    pd.DataFrame(rows).sample(frac=1, random_state=4).to_parquet(file, index=False)
    return file, cal, rows


class RaioEspectralTest(unittest.TestCase):
    def test_ar1_periodico_produto_analitico(self):
        p = parametros()
        for mes in p:
            p[mes]['ar_coefficient_lag_1'] = .4 + mes/30
            p[mes]['seasonal_std_m3s'] = 3. + mes
        esperado = np.prod([v['ar_coefficient_lag_1'] for v in p.values()])
        for inicio in (1, 8, 12):
            self.assertAlmostEqual(raio_do_ciclo(p, inicio), esperado, places=13)

    def test_ar2_autovalores_complexos(self):
        # Raízes de z² - 0,6z + 0,64 têm módulo 0,8.
        self.assertAlmostEqual(raio_do_ciclo(parametros((.6, -.64))), .8**12, places=13)

    def test_anual_puro_raiz_positiva_independente(self):
        # Cada um dos 12 lags recebe 0,6/12 em unidades originais.
        p = parametros((), .6)
        for m in p:
            p[m]['seasonal_std_m3s'] = 5. + m
            p[m]['annual_std_m3s'] = 2. + m
            p[m]['annual_coefficient'] = .6*(2.+m)/(5.+m)
        raiz = brentq(lambda z: z**12 - .6/12*sum(z**k for k in range(12)), 0, 1, xtol=1e-15)
        self.assertAlmostEqual(raio_do_ciclo(p), raiz**12, places=12)

    def test_zero_real_e_modelo_instavel_nao_sao_ajustados(self):
        self.assertEqual(raio_do_ciclo(parametros(())), 0.)
        self.assertAlmostEqual(raio_do_ciclo(parametros((1.02,))), 1.02**12, places=12)

    def test_recusa_parametros_incompletos_ou_invalidos(self):
        for mudar in (lambda p: p.pop(12),
                       lambda p: p[1].update(ar_coefficient_lag_1=None),
                       lambda p: p[1].update(annual_coefficient=.2, annual_std_m3s=0.),
                       lambda p: p[1].update(seasonal_std_m3s=-1.)):
            p = parametros(); mudar(p)
            with self.assertRaises(ValueError): raio_do_ciclo(p)

    def test_calendario_agosto_ids_fora_da_ordem_e_todos_cenarios(self):
        with TemporaryDirectory() as temp:
            file, cal, _ = caso(temp)
            r = calcular_raios_espectrais(file, cal, [17])['17']
            self.assertEqual(r['motivo'], '')
            self.assertAlmostEqual(r['valor'], .8**12, places=13)

    def test_nao_escolhe_primeiro_cenario_quando_ha_divergencia(self):
        with TemporaryDirectory() as temp:
            file, cal, rows = caso(temp)
            rows[-1]['ar_coefficient_lag_1'] = .7
            pd.DataFrame(rows).to_parquet(file, index=False)
            r = calcular_raios_espectrais(file, cal, [17])['17']
            self.assertIsNone(r['valor']); self.assertIn('variam', r['motivo'])

    def test_inativo_null_ou_zero_equivale_sem_inventar_lag_ativo(self):
        with TemporaryDirectory() as temp:
            file, cal, rows = caso(temp)
            for i, row in enumerate(rows): row['ar_coefficient_lag_2'] = 0. if i%2 else None
            pd.DataFrame(rows).to_parquet(file, index=False)
            self.assertAlmostEqual(calcular_raios_espectrais(file, cal, [17])['17']['valor'], .8**12, places=13)

    def test_legado_sem_parametros_e_ciclo_incompleto(self):
        with TemporaryDirectory() as temp:
            file, cal, _ = caso(temp, 6)
            self.assertIsNone(calcular_raios_espectrais(file, cal, [17])['17']['valor'])
            pd.DataFrame([{'hydro_id': 17, 'stage_id': 500}]).to_parquet(file, index=False)
            r = calcular_raios_espectrais(file, cal, [17])['17']
            self.assertIsNone(r['valor']); self.assertIn('sem os parâmetros', r['motivo'])


if __name__ == '__main__': unittest.main()
