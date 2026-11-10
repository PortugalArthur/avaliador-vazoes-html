"""Regressão das contas e histórico independente na comparação COBRE × COBRE."""
import json
import base64
import math
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
import unittest

import numpy as np
import pandas as pd
from scipy import stats

from aplicacao.executar import gerar
from aplicacao.fontes import inspecionar,recortar_historico
from relatorio.motor import _testes
from testes.fixtures import criar_caso
from testes.test_avaliador_html import ler_html


class DuasVersoesTest(unittest.TestCase):
    def conferir_bloco(self,a,b):
        # Agregações paralelas podem variar no último bit da soma float64.
        # O limite é ruído de máquina, não uma tolerância alterada nos testes estatísticos.
        if isinstance(a,dict):
            self.assertEqual(a.keys(),b.keys())
            if a.get('tipo')=='f8':
                self.assertEqual(a['forma'],b['forma'])
                np.testing.assert_allclose(np.frombuffer(base64.b64decode(a['b64']),dtype='<f8'),
                    np.frombuffer(base64.b64decode(b['b64']),dtype='<f8'),rtol=2e-12,atol=1e-12,equal_nan=True)
            elif set(a)=={'c','r'}:
                self.assertEqual(a['c'],b['c'])
                ordem=lambda row:tuple(str(v) for v in row if not isinstance(v,float))
                self.conferir_bloco(sorted(a['r'],key=ordem),sorted(b['r'],key=ordem))
            else:
                for k in a:self.conferir_bloco(a[k],b[k])
        elif isinstance(a,list):
            self.assertEqual(len(a),len(b))
            for x,y in zip(a,b):self.conferir_bloco(x,y)
        elif isinstance(a,float):self.assertTrue(math.isclose(a,b,rel_tol=2e-12,abs_tol=1e-12),(a,b))
        else:self.assertEqual(a,b)

    @classmethod
    def setUpClass(cls):
        cls.tmp=TemporaryDirectory();cls.base=Path(cls.tmp.name)
        cls.deck,cls.p=criar_caso(cls.base)
        cls.b=cls.base/'versao_b.parquet';shutil.copyfile(cls.p['novo'],cls.b)
        cls.html,cls.m=gerar(cls.deck,novo=cls.p['novo'],newave=cls.b,
            tipo_comparacao='novo_novo',deck_referencia=cls.deck,
            rotulo_novo='Novo modelo 0.19.1',rotulo_referencia='Novo modelo 0.20.0',
            saida=cls.base/'duas_versoes.html',progresso=lambda _:None)
        _,cls.blocks=ler_html(cls.html)

    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()

    def test_mesmos_dados_geram_todos_os_blocos_de_resultados_identicos(self):
        self.assertEqual(self.m['tipo_comparacao'],'novo_novo')
        self.assertEqual([m['nome'] for m in self.m['modelos']],['Novo modelo 0.19.1','Novo modelo 0.20.0'])
        pares=0
        for key,value in self.blocks.items():
            if key.startswith('novo_'):
                with self.subTest(bloco=key):self.conferir_bloco(value,self.blocks['newave_'+key[5:]])
                pares+=1
        self.assertGreater(pares,50)
        self.assertEqual(self.m['alfa'],.05)

    def test_historico_b_e_ids_sao_do_deck_b_sem_contaminar_a(self):
        with TemporaryDirectory() as tmp:
            d=Path(tmp)/'deck_b';shutil.copytree(self.deck,d)
            cadastro=json.loads((d/'system/hydros.json').read_text())
            for u in cadastro['hydros']:u['id']+=100
            (d/'system/hydros.json').write_text(json.dumps(cadastro))
            etapas=json.loads((d/'stages.json').read_text())
            for e in etapas['stages']:e['id']+=1000
            (d/'stages.json').write_text(json.dumps(etapas))
            h=pd.read_parquet(d/'scenarios/inflow_history.parquet')
            h=h[pd.to_datetime(h.start_date).dt.year.le(2009)].copy();h.hydro_id+=100
            h.loc[h.hydro_id.eq(100),'value_m3s']+=10
            h.to_parquet(d/'scenarios/inflow_history.parquet',index=False)
            data=pd.read_parquet(self.b);data.hydro_id+=100;data.stage_id+=1000
            b=Path(tmp)/'b.parquet';data.to_parquet(b,index=False)
            paths,_,fontes,_=inspecionar(self.deck,novo=self.p['novo'],newave=b,
                tipo_comparacao='novo_novo',deck_referencia=d)
            a,f=fontes
            self.assertEqual((a.fim_h,f.fim_h),('2010-12','2009-12'))
            self.assertEqual(f.ids_deck[100],0);self.assertEqual(f.ids_historico[100],100)
            hh=recortar_historico(f,paths['historico'],Path(tmp)/'recorte.parquet')
            for c in ['start_date','end_date']:h[c]=pd.to_datetime(h[c])
            pd.testing.assert_frame_equal(hh.reset_index(drop=True),h.reset_index(drop=True),check_dtype=False)
            r=_testes(data[data.hydro_id.eq(100)],hh[hh.hydro_id.eq(100)],100,f)
            for row in r['medias'].to_dict('records'):
                hist=hh.loc[hh.hydro_id.eq(100)&pd.to_datetime(hh.start_date).dt.month.eq(row['mes']),'value_m3s']
                synth=data.loc[data.hydro_id.eq(100)&data.stage_id.eq(row['stage_id']),'incremental_inflow_m3s']
                self.assertEqual(row['n_historico'],10)
                self.assertAlmostEqual(row['p_valor'],stats.ttest_ind(synth,hist,equal_var=False).pvalue,places=12)

    def test_bloqueia_origem_deck_e_rotulos_incompativeis(self):
        args=dict(deck=self.deck,novo=self.p['novo'],newave=self.b,tipo_comparacao='novo_novo')
        with self.assertRaisesRegex(ValueError,'respectivos decks'):inspecionar(**args)
        with self.assertRaisesRegex(ValueError,'Origem'):
            inspecionar(**dict(args,newave=self.p['newave']),deck_referencia=self.deck)
        with self.assertRaisesRegex(ValueError,'nomes diferentes'):
            inspecionar(**args,deck_referencia=self.deck,rotulo_novo='A',rotulo_referencia='a')
        with self.assertRaisesRegex(ValueError,'dois Parquets distintos'):
            inspecionar(**dict(args,newave=self.p['novo']),deck_referencia=self.deck)

    def test_historico_fora_do_deck_b_e_horizonte_diferente_bloqueiam(self):
        with self.assertRaisesRegex(ValueError,'fora dos limites'):
            inspecionar(self.deck,novo=self.p['novo'],newave=self.b,tipo_comparacao='novo_novo',
                deck_referencia=self.deck,periodos={'newave':('2000-01','2011-12')})
        with TemporaryDirectory() as tmp:
            d=Path(tmp)/'deck';shutil.copytree(self.deck,d)
            stages=json.loads((d/'stages.json').read_text())
            for e in stages['stages']:
                for k in ['start_date','end_date']:
                    e[k]=str((pd.Timestamp(e[k])+pd.DateOffset(years=1)).date())
            (d/'stages.json').write_text(json.dumps(stages))
            with self.assertRaisesRegex(ValueError,'mesmo horizonte'):
                inspecionar(self.deck,novo=self.p['novo'],newave=self.b,tipo_comparacao='novo_novo',deck_referencia=d)
