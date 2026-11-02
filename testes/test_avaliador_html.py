"""Regressão numérica, correspondências e publicação do relatório independente."""
import ast
import base64
import gzip
import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory
import unittest

from aplicacao.executar import gerar
from aplicacao.fontes import inspecionar, recortar_historico
from relatorio.motor import _testes
from relatorio.blocos import json_seguro, tabela, vetor
from calculos import analise_sequencias_cobre as seq
from calculos.teste_welch_cobre import avaliar_welch
from calculos.teste_levene_cobre import preparar_medias_levene
from calculos.teste_ks_cobre import preparar_amostras_ks
from calculos.resultado_global_welch import calcular_welch_todas_usinas
from testes.fixtures import criar_caso
import numpy as np
import pandas as pd
from scipy import stats
import pyarrow.parquet as pq

RAIZ=Path(__file__).resolve().parents[1]

def ler_html(caminho):
    s=Path(caminho).read_text(encoding='utf-8')
    m=json.loads(re.search(r'<script id="manifesto" type="application/json">(.*?)</script>',s,re.S)[1])
    dados={k:json.loads(gzip.decompress(base64.b64decode(v))) for k,v in re.findall(
        r'<script type="application/octet-stream" id="bloco-([^"]+)">(.*?)</script>',s,re.S)}
    return m,dados

def dataframe(t): return pd.DataFrame(t['r'],columns=t['c'])

class TestCalculos(unittest.TestCase):
    def test_funcoes_nativas_100_amostras_e_ks_limite(self):
        rng=np.random.default_rng(20261102)
        for i in range(100):
            h=rng.lognormal(2,.4,95);s=rng.lognormal(2+i/200,.2+i/250,2000)
            w=avaliar_welch(h,s);n=stats.ttest_ind(s,h,equal_var=False)
            self.assertAlmostEqual(w['t'],n.statistic,places=12)
            self.assertAlmostEqual(w['p_valor'],n.pvalue,places=12)
            l=preparar_medias_levene(h,s);n=stats.levene(h,s,center='mean')
            np.testing.assert_allclose([l['estatistica_levene'],l['p_valor']],[n.statistic,n.pvalue],rtol=2e-12,atol=1e-13)
            k=preparar_amostras_ks(h,s);n=stats.ks_2samp(h,s)
            self.assertAlmostEqual(k['estatistica_ks'],n.statistic,places=14)
            self.assertEqual(k['p_valor'],stats.kstwobign.sf(k['z_ks']))
            self.assertEqual(k['rejeita_igualdade_distribuicoes'],k['p_valor']<.05)

    def test_constantes_zeros_e_dados_invalidos(self):
        for func in [avaliar_welch,preparar_medias_levene]:
            with self.assertRaises(ValueError):func([0.,0.,0.],[0.,0.,0.])
            with self.assertRaises(ValueError):func([1.,np.nan],[2.,3.])
        # KS permite duas distribuições constantes idênticas: D=0 e p=1.
        k=preparar_amostras_ks([0.,0.,0.],[0.,0.,0.])
        self.assertEqual((k['estatistica_ks'],k['p_valor']),(0.,1.))

    def test_intensidade_e_do_mesmo_evento_e_extremos_independentes(self):
        r,e=seq.analisar_trajetoria([9,9,9,11,3,11],[10]*6)
        self.assertEqual(e.comprimento.tolist(),[3,1])
        self.assertEqual(e.soma.tolist(),[-3.,-7.])
        self.assertEqual(e.intensidade.tolist(),[-1.,-7.])
        self.assertEqual(r['comprimento_maximo'],3)
        self.assertEqual(r['intensidade_mais_severa'],-7)
        r,e=seq.analisar_trajetoria([10,11],[10,10])
        self.assertEqual(r['quantidade_sequencias'],0)
        self.assertEqual(r['soma_mais_severa'],0)
        self.assertEqual(len(e),0)

    def test_janelas_mes_inicial_e_recuo_anual(self):
        b,_=seq.formar_blocos_historicos('1931-01','2025-12',65,8)
        self.assertEqual(len(b),90)
        self.assertEqual(str(b.inicio.iloc[0].date()),'2020-08-01')
        self.assertEqual(str(b.fim.iloc[0].date()),'2025-12-01')
        self.assertEqual(str(b.inicio.iloc[1].date()),'2019-08-01')
        b,_=seq.formar_blocos_historicos('1931-01','2024-12',72,1)
        self.assertEqual(len(b),89)

    def test_serializacao_sem_arredondamento_ou_injecao(self):
        v=np.array([0.,1/3,np.nan,np.inf,-7.])
        a=vetor(v);rest=np.frombuffer(base64.b64decode(a['b64']),dtype='<f8')
        np.testing.assert_array_equal(v,rest)
        self.assertEqual(tabela(pd.DataFrame({'a':v}))['r'][1][0],1/3)
        s=json_seguro({'s':'</script><img src=x>','n':np.nan})
        self.assertNotIn('<',s);self.assertIsNone(json.loads(s)['n'])


class TestEntradasEIntegracao(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=TemporaryDirectory();cls.base=Path(cls.tmp.name)
        cls.deck,cls.p=criar_caso(cls.base)
        cls.caminhos,cls.nomes,cls.fontes,_=inspecionar(cls.deck,**cls.p)
        cls.html,cls.manifesto=gerar(cls.deck,**cls.p,saida=cls.base/'comparacao.html',progresso=lambda _:None)
        _,cls.blocos=ler_html(cls.html)

    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()

    def test_correspondencia_por_nome_data_com_ids_diferentes(self):
        a,b=self.fontes
        self.assertNotEqual(set(a.nomes),set(b.nomes))
        self.assertEqual(set(a.ids_deck.values()),set(b.ids_deck.values()))
        self.assertNotEqual(set(a.calendario),set(b.calendario))
        self.assertEqual(a.fim_h,'2010-12');self.assertEqual(b.fim_h,'2009-12')
        self.assertEqual(a.inicio_h,b.inicio_h)
        self.assertEqual(self.manifesto['alfa'],.05)

    def test_recorte_remapeia_so_o_historico_e_nao_muda_entrada(self):
        f=self.fontes[1]
        antes=Path(self.caminhos['historico']).read_bytes()
        d=recortar_historico(f,self.caminhos['historico'],self.base/'hist_cut.parquet')
        self.assertEqual(set(d.hydro_id),set(f.nomes))
        self.assertEqual(pd.to_datetime(d.start_date).dt.year.max(),2009)
        self.assertEqual(Path(self.caminhos['historico']).read_bytes(),antes)

    def test_todos_estagios_nativos_com_o_historico_correto(self):
        # 29 estágios por modelo; todos os meses são amostras independentes.
        for modelo in self.manifesto['modelos']:
            f=next(f for f in self.fontes if f.chave==modelo['key'])
            h=recortar_historico(f,self.caminhos['historico'],self.base/(f.chave+'_h.parquet'))
            d=pd.read_parquet(f.caminho);uid=next(u for u in f.nomes if f.ids_deck[u]==0)
            for tipo in ['medias','variancias','distribuicao']:
                r=dataframe(self.blocos[modelo['testes'][tipo]])
                self.assertEqual(len(r),3*29)
                for row in r.loc[r.hydro_id.eq(uid)].to_dict('records'):
                    hh=h.loc[h.hydro_id.eq(uid)&pd.to_datetime(h.start_date).dt.month.eq(row['mes']),'value_m3s']
                    ss=d.loc[d.hydro_id.eq(uid)&d.stage_id.eq(row['stage_id']),'incremental_inflow_m3s']
                    if tipo=='medias':p=stats.ttest_ind(ss,hh,equal_var=False).pvalue
                    elif tipo=='variancias':p=stats.levene(hh,ss,center='mean').pvalue
                    else:
                        k=stats.ks_2samp(hh,ss).statistic
                        p=stats.kstwobign.sf(k*np.sqrt(len(hh)*len(ss)/(len(hh)+len(ss))))
                    self.assertEqual(row['n_historico'],11 if f.chave=='novo' else 10)
                    self.assertAlmostEqual(row['p_valor'],p,places=12)

    def test_welch_mesmo_resultado_geral_anterior(self):
        f=self.fontes[0]
        original=calcular_welch_todas_usinas(f.caminho,self.caminhos['historico'],f.nomes,f.calendario)
        atual=dataframe(self.blocos[self.manifesto['modelos'][0]['testes']['medias']])
        original=original.sort_values(['hydro_id','stage_id']).reset_index(drop=True)
        atual=atual.sort_values(['hydro_id','stage_id']).reset_index(drop=True)
        np.testing.assert_allclose(atual.p_valor,original.p_valor,rtol=2e-12,atol=2e-13,equal_nan=True)
        self.assertEqual((atual.p_valor<.05).tolist(),(original.p_valor<.05).tolist())

    def test_sequencias_em_lote_iguais_a_referencia_individual(self):
        texto=(RAIZ/'testes/referencia_sequencias.py').read_text(encoding='utf-8')
        ns=dict(vars(seq));exec(compile(texto,'referencia_sequencias.py','exec'),ns)
        referencia=ns['calcular_sequencias_usina'];f=self.fontes[0]
        horizonte=seq.organizar_horizonte(f.calendario,tuple(f.calendario))
        d=pd.read_parquet(f.caminho);h=pd.read_parquet(self.caminhos['historico'])
        # Cenário incompleto e histórico com mês ausente também devem manter o diagnóstico.
        for estragar in [False,True]:
            dd=d.copy();hh=h.copy()
            if estragar:dd=dd.drop(dd.index[0]);hh=hh.drop(hh.index[15])
            for u,n in f.nomes.items():
                a=seq.calcular_sequencias_usina(dd.loc[dd.hydro_id.eq(u)],hh,u,n,horizonte)
                b=referencia(dd.loc[dd.hydro_id.eq(u)],hh,u,n,horizonte)
                for campo in a.__dataclass_fields__:
                    pd.testing.assert_frame_equal(getattr(a,campo),getattr(b,campo),check_dtype=False,rtol=1e-13,atol=1e-13)

    def test_rejeita_usinas_horizonte_duplicadas_e_recorte_invalidos(self):
        dados=pd.read_parquet(self.p['novo'])
        def errado(d,trecho):
            arq=self.base/'errado.parquet';d.to_parquet(arq,index=False)
            with self.assertRaisesRegex(ValueError,trecho):inspecionar(self.deck,novo=arq,newave=self.p['newave'])
        errado(dados.loc[dados.hydro_id.ne(15)],'mesmas usinas')
        errado(dados.loc[dados.stage_id.ne(dados.stage_id.max())],'mesmo horizonte')
        errado(pd.concat([dados,dados.iloc[:1]]),'repetid|duplicad')
        with self.assertRaisesRegex(ValueError,'fora dos limites'):
            inspecionar(self.deck,novo=self.p['novo'],periodos={'novo':('2000-01','2011-12')})
        with self.assertRaisesRegex(ValueError,'Origem'):
            inspecionar(self.deck,novo=self.p['newave'])
        with self.assertRaisesRegex(ValueError,'AAAA-MM'):
            inspecionar(self.deck,novo=self.p['novo'],periodos={'novo':('2000','2010')})

    def test_publicacao_tres_modos_offline_e_sem_sobrescrita(self):
        for key in ['novo','newave']:
            path,meta=gerar(self.deck,**{key:self.p[key]},saida=self.base/(key+'.html'),progresso=lambda _:None)
            self.assertEqual(meta['modo'],'Análise');self.assertEqual(len(meta['modelos']),1)
            self.assertTrue(path.exists())
        with self.assertRaisesRegex(ValueError,'já existe'):
            gerar(self.deck,**self.p,saida=self.html,progresso=lambda _:None)
        self.assertEqual(set(self.manifesto['blocos']),set(self.blocos))
        for m in self.manifesto['modelos']:
            for k in m['uhe'].values():
                b=self.blocos[k['bloco']]
                self.assertEqual(b['flows']['forma'],[7,29])
                self.assertEqual(len(b['scenario_ids']),7)
        for f in self.manifesto['fontes']:self.assertEqual(len(f['sha256']),64)
        texto=self.html.read_text(encoding='utf-8')
        self.assertNotRegex(texto,r'<script\b[^>]*\bsrc=')
        self.assertNotRegex(texto,r'<link\b[^>]*\bhref=')

    def test_atualizar_interface_preserva_todos_blocos_e_relatorio_anterior(self):
        from relatorio.atualizar import atualizar
        antes=self.html.read_bytes()
        novo,r=atualizar(self.html,self.base/'interface_atualizada.html')
        meta,dados=ler_html(novo)
        self.assertEqual(dados,self.blocos)
        self.assertEqual(meta['modelos'],ler_html(self.html)[0]['modelos'])
        self.assertEqual(r['blocos_preservados'],len(self.blocos))
        self.assertEqual(self.html.read_bytes(),antes)
        with self.assertRaisesRegex(ValueError,'saída nova'):
            atualizar(self.html,self.html)

if __name__=='__main__':unittest.main()
