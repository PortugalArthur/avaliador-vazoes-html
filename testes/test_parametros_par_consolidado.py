"""Ajuste PAR por estágio, seletores orientados e consolidado enriquecido."""

from contextlib import redirect_stdout
import hashlib
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from geradores.parametros_par_consolidado import carregar_parametros_par, validar_pasta_saida, validar_pasta_deck
from geradores.consolidar_vazoes_incrementais_e_lags import consolidar, selecionar_pastas, COLUNAS_SAIDA
import polars as pl
import pandas as pd


class TestParametrosPARConsolidado(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.pasta = Path(self.tmp.name)
        self.deck, self.output = self.pasta/"entrada", self.pasta/"resultado_extraido"
        (self.deck/"system").mkdir(parents=True)
        self.stochastic = self.output/"stochastic"
        self.stochastic.mkdir(parents=True)
        self.hydros = self.output/"simulation"/"hydros"
        self.saida = self.pasta/"consolidado.parquet"
        self.config = {"estimation":{"max_order":6}}
        self.stages = {"season_definitions":{"cycle_type":"monthly", "seasons":[
            {"id":m-1,"month_start":m,"label":str(m)} for m in range(1,13)]},
            "stages":[{"id":30,"start_date":"2027-07-01","end_date":"2027-08-01","season_id":6},
                      {"id":4,"start_date":"2027-08-01","end_date":"2027-09-01","season_id":7}]}
        self._json(self.deck/"config.json",self.config)
        self._json(self.deck/"stages.json",self.stages)
        self._json(self.deck/"system"/"hydros.json",{"hydros":[{"id":u,"name":nome} for u,nome in [(0,"CAMARGOS"),(7,"FURNAS")]]})
        self.ajustes = {(0,30):[0.,-.2], (0,4):[], (7,30):[.3], (7,4):[.4,.5,.6]}
        self.report = {"hydros":{}}
        for u in [0,7]:
            listas = [[] for _ in range(12)]
            listas[6],listas[7] = self.ajustes[u,30],self.ajustes[u,4]
            self.report["hydros"][str(u)] = {"selected_order":5,"coefficients":listas}
        self._json(self.stochastic/"fitting_report.json",self.report)
        self.ar = pl.DataFrame([dict(hydro_id=u,stage_id=e,lag=i,coefficient=v)
                                for (u,e),valores in self.ajustes.items() for i,v in enumerate(valores,1)])
        self.anual = pl.DataFrame([dict(hydro_id=u,stage_id=e,annual_coefficient=.1,
                                       annual_mean_m3s=20.+u,annual_std_m3s=0. if u == 7 else 3.) for u,e in self.ajustes])
        self.sazonal = pl.DataFrame([dict(hydro_id=u,stage_id=e,mean_m3s=30.+u,std_m3s=5.+u) for u,e in self.ajustes])
        self._restaurar_parametros()
        for c in [0,11]:
            linhas = [dict(scenario_id=c,stage_id=e,node_id=c+100,hydro_id=u,block_id=b,
                            incremental_inflow_m3s=float(10+c+u) if b is None else 999.,
                            inflow_nonnegativity_slack_m3s=.5 if b == 0 else 99.)
                      for u,e in self.ajustes for b in [None,0,1]]
            destino = self.hydros/f"scenario_id={c:04d}"
            destino.mkdir(parents=True)
            pl.DataFrame(linhas).with_columns([pl.col(k).cast(pl.Int32) for k in
                                               ["hydro_id","stage_id","node_id","scenario_id"]]).write_parquet(destino/"data.parquet")

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def _json(caminho, dados):
        caminho.write_text(json.dumps(dados),encoding="utf-8")

    def _restaurar_parametros(self):
        for nome,tabela in [("inflow_ar_coefficients",self.ar),("inflow_annual_component",self.anual),("inflow_seasonal_stats",self.sazonal)]:
            tabela.write_parquet(self.stochastic/(nome+".parquet"))
        self._json(self.stochastic/"fitting_report.json",self.report)

    def gerar(self):
        with redirect_stdout(StringIO()):
            return consolidar(self.hydros,self.saida,pasta_deck=self.deck,pasta_stochastic=self.stochastic)

    def test_18_colunas_p_mensal_zeros_nulos_e_associacao_m_para_1(self):
        self.gerar()
        tabela = pl.read_parquet(self.saida)
        self.assertEqual(tabela.height,8)
        self.assertEqual(len(tabela.columns),18)
        self.assertEqual(tabela.columns[:6],COLUNAS_SAIDA)
        self.assertTrue(all(tabela.schema[f"ar_coefficient_lag_{i}"] == pl.Float64 for i in range(1,7)))
        self.assertFalse(any(c.startswith("lag_") for c in tabela.columns))
        for c in [0,11]:
            linha = tabela.filter((pl.col("scenario_id")==c)&(pl.col("hydro_id")==0)&(pl.col("stage_id")==30)).row(0,named=True)
            self.assertEqual(linha["ar_order"],2)  # selected_order=5 não substitui a ordem de julho.
            self.assertEqual(linha["ar_coefficient_lag_1"],0.)
            self.assertEqual(linha["ar_coefficient_lag_2"],-.2)
            self.assertIsNone(linha["ar_coefficient_lag_3"])
            self.assertEqual(linha["incremental_inflow_m3s"],10+c)
            self.assertEqual(linha["inflow_nonnegativity_slack_m3s"],.5)
            self.assertEqual(linha["seasonal_mean_m3s"],30.)
            zero = tabela.filter((pl.col("scenario_id")==c)&(pl.col("hydro_id")==0)&(pl.col("stage_id")==4)).row(0,named=True)
            self.assertEqual(zero["ar_order"],0)
            self.assertTrue(all(zero[f"ar_coefficient_lag_{i}"] is None for i in range(1,7)))

    def test_ordem_maxima_dinamica(self):
        self._json(self.deck/"config.json",{"estimation":{"max_order":3}})
        self.gerar()
        tabela = pl.read_parquet(self.saida)
        self.assertEqual(len(tabela.columns),15)
        self.assertNotIn("ar_coefficient_lag_4",tabela.columns)

    def test_falhas_no_ajuste_preservam_saida(self):
        self.gerar()
        anterior = hashlib.sha256(self.saida.read_bytes()).hexdigest()
        casos = [
            ("inflow_ar_coefficients",self.ar.filter(~((pl.col("hydro_id")==0)&(pl.col("lag")==2))),"ausentes"),
            ("inflow_ar_coefficients",pl.concat([self.ar,self.ar.head(1)]),"duplicada"),
            ("inflow_ar_coefficients",self.ar.with_columns(pl.lit(99.).alias("coefficient")),"difere"),
            ("inflow_annual_component",self.anual.head(3),"mesmos pares"),
            ("inflow_annual_component",self.anual.with_columns(pl.lit(float("nan")).alias("annual_coefficient")),"não finito"),
            ("inflow_seasonal_stats",pl.concat([self.sazonal,self.sazonal.head(1)]),"duplicada"),
            ("inflow_seasonal_stats",self.sazonal.with_columns(pl.lit(-1.).alias("std_m3s")),"negativo"),
        ]
        for nome,dados,mensagem in casos:
            with self.subTest(caso=mensagem):
                self._restaurar_parametros()
                dados.write_parquet(self.stochastic/(nome+".parquet"))
                with self.assertRaisesRegex(ValueError,mensagem):
                    self.gerar()
                self.assertEqual(hashlib.sha256(self.saida.read_bytes()).hexdigest(),anterior)
                self.assertFalse(self.saida.with_name(self.saida.name+".tmp").exists())

    def test_rejeita_deck_ou_estacao_incompativel_e_falta_de_relatorio(self):
        self.stages["stages"][0]["season_id"] = 0
        self._json(self.deck/"stages.json",self.stages)
        with self.assertRaisesRegex(ValueError,"mês"):
            self.gerar()
        self.stages["stages"][0]["season_id"] = 6
        self._json(self.deck/"stages.json",self.stages)
        self._json(self.deck/"system"/"hydros.json",{"hydros":[{"id":99,"name":"Outro deck"}]})
        with self.assertRaisesRegex(ValueError,"ausente no deck"):
            self.gerar()
        self._json(self.deck/"system"/"hydros.json",{"hydros":[{"id":u,"name":str(u)} for u in [0,7]]})
        self._json(self.stochastic/"fitting_report.json",{"hydros":{}})
        with self.assertRaisesRegex(ValueError,"12 listas"):
            self.gerar()

    def test_cobertura_de_simulacao_e_metadados_exigidos_conjuntamente(self):
        self.gerar()
        anterior = self.saida.read_bytes()
        caminho = self.hydros/"scenario_id=0011"/"data.parquet"
        pl.read_parquet(caminho).with_columns(pl.when(pl.col("hydro_id")==0)
                                               .then(pl.lit(88,dtype=pl.Int32)).otherwise(pl.col("hydro_id"))
                                               .alias("hydro_id")).write_parquet(caminho)
        with self.assertRaisesRegex(ValueError,"sem parâmetros"):
            self.gerar()
        self.assertEqual(self.saida.read_bytes(),anterior)
        self.assertFalse(self.saida.with_name(self.saida.name+".tmp").exists())
        with self.assertRaisesRegex(ValueError,"conjuntamente"), redirect_stdout(StringIO()):
            consolidar(self.hydros,self.saida,pasta_deck=self.deck)

    def test_seletores_reabrem_pasta_incorreta_e_cancelamento(self):
        with patch("geradores.consolidar_vazoes_incrementais_e_lags.filedialog.askdirectory",side_effect=[
            str(self.deck/"system"),str(self.deck),str(self.hydros),str(self.output)]) as escolher, \
             patch("geradores.consolidar_vazoes_incrementais_e_lags.messagebox.showinfo"), \
             patch("geradores.consolidar_vazoes_incrementais_e_lags.messagebox.showerror") as erro:
            resultado = selecionar_pastas(None)
            self.assertEqual(resultado,(self.deck.resolve(),self.hydros.resolve(),self.stochastic.resolve()))
            self.assertEqual(escolher.call_count,4)
            self.assertEqual(erro.call_count,2)
            self.assertIn("SAÍDA EXTRAÍDA",escolher.call_args.kwargs["title"])
        for respostas in [[""],[str(self.deck),""]]:
            with patch("geradores.consolidar_vazoes_incrementais_e_lags.filedialog.askdirectory",side_effect=respostas), \
                 patch("geradores.consolidar_vazoes_incrementais_e_lags.messagebox.showinfo"):
                self.assertIsNone(selecionar_pastas(None))
        with self.assertRaisesRegex(ValueError,"DECK DE ENTRADA"):
            validar_pasta_deck(self.stochastic)
        with self.assertRaisesRegex(ValueError,"Extraia output.zip"):
            validar_pasta_saida(self.deck)



if __name__ == "__main__":
    unittest.main()
