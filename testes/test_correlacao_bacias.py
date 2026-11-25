"""Confronta o JavaScript do relatório com Pearson independente do SciPy."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest

import numpy as np
from scipy.stats import pearsonr

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which('node') or str(Path.home() / '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe')


def caso():
    stages = [{'i': 0, 'mes': 1, 'rotulo': '01/2026'}, {'i': 1, 'mes': 2, 'rotulo': '02/2026'}, {'i': 2, 'mes': 1, 'rotulo': '01/2027'}]
    first = [[1, 2, 4, 3], [3, 0, 3, -3], [2, 4, 0, -3], [1, 6, 1, 1]]
    second = [[0, 4, -2, 8], [2, 1, -3, 0], [7, 0, 2, -5], [-1, 1, 4, 2]]
    third = [[2, 5, 0, -4], [0, -1, 9, 2], [8, -2, 3, 1], [1, 3, -2, 7]]
    ids = [10, 20, 30, 40]
    dates = [f'{year}-{month:02d}' for year in range(2000, 2004) for month in (1, 2)]
    historical_a = [10, 1, 20, 4, 30, 2, 40, 8]
    historical_b = [4, 10, 1, 30, 8, 20, 2, 80]
    data = {}
    for u in range(4):
        order = np.roll(np.arange(4), u).tolist()
        history_order = list(reversed(range(8))) if u % 2 else list(range(8))
        hist = historical_a if u < 2 else historical_b
        weight = [.25, .75, .6, .4][u]
        data[str(u)] = {'scenario_ids': [ids[i] for i in order],
                       'flows': [matrix[u][i] for i in order for matrix in (first, second, third)],
                       'presentes': [1] * 12,
                       'hist_dates': [dates[i] for i in history_order],
                       'hist_values': [hist[i] * weight for i in history_order]}
    model = {'cadastro': {'c': ['hydro_id', 'Usina', 'bacia_id', 'Bacia'],
                         'r': [[u, f'UHE {u}', 1 if u < 2 else 2, 'A' if u < 2 else 'B'] for u in range(4)]},
             'uhe': {str(u): {'id_original': u, 'bloco': str(u)} for u in range(4)}}
    return {'modelo': model, 'dados': data, 'estagios': stages}


@unittest.skipUnless(Path(NODE).is_file() or shutil.which(NODE), 'Node necessário para validar o JavaScript offline.')
class CorrelacaoBaciasTest(unittest.TestCase):
    def executar(self, input):
        result = subprocess.run([NODE, str(ROOT / 'testes/executar_correlacao_bacias.cjs')],
                                input=json.dumps(input), text=True, encoding='utf-8', capture_output=True, check=True)
        return json.loads(result.stdout)

    def test_soma_antes_de_pearson_pareamento_por_cenario_e_estagio(self):
        result = self.executar(caso())
        values = [([4, 2, 7, 0], [3, 10, 1, -2]), ([2, 5, -5, 8], [6, 1, 6, -3]), ([2, 4, 9, -2], [9, 1, 1, 8])]
        for row, (a, b) in zip(result['rows'], values):
            self.assertAlmostEqual(row['Correlação sintético'], pearsonr(a, b).statistic, places=14)
            self.assertEqual(row['Pares válidos sintético'], 4)
        self.assertEqual([r['Vazão da bacia A (m³/s)'] for r in result['sintetico']], values[0][0])
        self.assertEqual([r['Vazão da bacia B (m³/s)'] for r in result['sintetico']], values[0][1])
        mean_individual = np.mean([pearsonr(a, b).statistic for a in ([1, 2, 4, 3], [3, 0, 3, -3]) for b in ([2, 4, 0, -3], [1, 6, 1, 1])])
        self.assertGreater(abs(result['rows'][0]['Correlação sintético'] - mean_individual), .01)

    def test_historico_so_mes_civil_com_anos_alinhados(self):
        result = self.executar(caso())
        jan = pearsonr([10, 20, 30, 40], [4, 1, 8, 2]).statistic
        feb = pearsonr([1, 4, 2, 8], [10, 30, 20, 80]).statistic
        self.assertAlmostEqual(result['rows'][0]['Correlação histórico'], jan, places=14)
        self.assertAlmostEqual(result['rows'][1]['Correlação histórico'], feb, places=14)
        self.assertEqual(result['rows'][0]['Correlação histórico'], result['rows'][2]['Correlação histórico'])
        self.assertTrue(all(r['Mês histórico'].endswith('-01') for r in result['historico']))
        self.assertEqual(result['rows'][0]['Pares válidos histórico'], 4)

    def test_total_incompleto_nao_vira_soma_parcial_ou_zero(self):
        data = caso()
        plant = data['dados']['1']
        plant['presentes'][plant['scenario_ids'].index(10) * 3] = 0
        i = plant['hist_dates'].index('2001-01')
        del plant['hist_dates'][i]
        del plant['hist_values'][i]
        result = self.executar(data)
        row = result['rows'][0]
        self.assertEqual(row['Pares válidos sintético'], 3)
        self.assertEqual(row['Pares esperados sintético'], 4)
        self.assertAlmostEqual(row['Correlação sintético'], pearsonr([2, 7, 0], [10, 1, -2]).statistic, places=14)
        self.assertIsNone(result['sintetico'][0]['Vazão da bacia A (m³/s)'])
        self.assertFalse(result['sintetico'][0]['Par válido'])
        self.assertEqual(row['Pares válidos histórico'], 3)
        self.assertAlmostEqual(row['Correlação histórico'], pearsonr([10, 30, 40], [4, 8, 2]).statistic, places=14)

    def test_constante_indefinida_e_zero_com_negativos_preservados(self):
        data = caso()
        for u in ('2', '3'):
            data['dados'][u]['flows'] = [0 if u == '2' else 2] * 12
            data['dados'][u]['hist_values'] = [0] * 8
        result = self.executar(data)
        self.assertIsNone(result['rows'][0]['Correlação sintético'])
        self.assertIn('constante', result['rows'][0]['Motivo sintético'])
        self.assertIsNone(result['rows'][0]['Correlação histórico'])
        self.assertEqual(result['sintetico'][-1]['Vazão da bacia A (m³/s)'], 0)
        self.assertTrue(result['sintetico'][-1]['Par válido'])

    def test_simetria_inversao_das_bacias(self):
        result = self.executar(caso())
        for direct, reverse in zip(result['rows'], result['inverso']):
            for source in ('sintético', 'histórico'):
                self.assertEqual(direct['Correlação ' + source], reverse['Correlação ' + source])
                self.assertEqual(direct['Média da bacia A ' + source], reverse['Média da bacia B ' + source])
                self.assertEqual(direct['Pares válidos ' + source], reverse['Pares válidos ' + source])


if __name__ == '__main__':
    unittest.main()
