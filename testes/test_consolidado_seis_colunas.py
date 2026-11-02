"""Geração só de hydros, integridade das vazões e compatibilidade das cinco abas."""

from contextlib import redirect_stdout
import hashlib
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from geradores.consolidar_vazoes_incrementais_e_lags import consolidar, COLUNAS_SAIDA, COLUNA_SLACK
from dados.validacao_dados_cobre import validar_parquet_consolidado
import polars as pl
import pandas as pd


class TestConsolidadoSeisColunas(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.pasta = Path(self.tmp.name)
        self.hydros = self.pasta/"hydros"
        self.saida = self.pasta/"inflows_with_lags.parquet"
        self.fontes = {}
        self.calendario = {}
        for ordem, (stage_id, periodo) in enumerate(zip([30,4], pd.period_range("2027-07",periods=2,freq="M"))):
            self.calendario[stage_id] = dict(inicio=periodo.start_time.date(), fim=(periodo+1).start_time.date())
        for c in [0,8]:
            linhas = []
            for u in [0,7]:
                for ordem, stage in enumerate(self.calendario):
                    for block in [None,0,1]:
                        q = float(10+c+u+ordem)
                        linhas.append(dict(scenario_id=c, stage_id=stage, node_id=c+100, hydro_id=u,
                                           block_id=block, incremental_inflow_m3s=q if block is None else q+999+block,
                                           inflow_nonnegativity_slack_m3s=float(c/10+u/100+ordem) if block == 0 else 9999.))
            self.fontes[c] = pl.DataFrame(linhas)
            destino = self.hydros/f"scenario_id={c:04d}"
            destino.mkdir(parents=True)
            self.fontes[c].write_parquet(destino/"data.parquet")

    def tearDown(self):
        self.tmp.cleanup()

    def gerar(self):
        with redirect_stdout(StringIO()):
            return consolidar(self.hydros, self.saida)

    def test_seis_colunas_sem_fonte_de_lags_e_slack_do_bloco_zero(self):
        self.saida = self.pasta/"parquet gerado novo modelo"/"inflows_with_lags.parquet"
        with patch("geradores.consolidar_vazoes_incrementais_e_lags.PASTA_PROJETO",self.pasta), redirect_stdout(StringIO()):
            self.assertEqual(consolidar(self.hydros),self.saida)
        tabela = pl.read_parquet(self.saida)
        self.assertEqual(tabela.columns, COLUNAS_SAIDA)
        self.assertEqual(tabela.height, 8)
        self.assertFalse((self.pasta/"inflow_lags").exists())
        for linha in tabela.iter_rows(named=True):
            ordem = list(self.calendario).index(linha["stage_id"])
            self.assertEqual(linha["incremental_inflow_m3s"], 10+linha["scenario_id"]+linha["hydro_id"]+ordem)
            self.assertEqual(linha[COLUNA_SLACK], linha["scenario_id"]/10+linha["hydro_id"]/100+ordem)
        meta = validar_parquet_consolidado(self.saida)
        self.assertEqual(meta["lags"], [])
        self.assertEqual(meta["cenarios"], 2)
        self.assertEqual(meta["ids_estagios"], [4,30])

    def test_estrutura_sem_registro_de_estagio_confere_vazao_entre_blocos(self):
        for c, fonte in self.fontes.items():
            dados = fonte.filter(pl.col("block_id").is_not_null()).with_columns(
                (pl.lit(10.)+pl.col("scenario_id")+pl.col("hydro_id")+
                 (pl.col("stage_id")==4).cast(pl.Float64)).alias("incremental_inflow_m3s"))
            dados.write_parquet(self.hydros/f"scenario_id={c:04d}"/"data.parquet")
        self.gerar()
        linha = pl.read_parquet(self.saida).filter((pl.col("scenario_id")==8) & (pl.col("stage_id")==4) & (pl.col("hydro_id")==7)).row(0,named=True)
        self.assertEqual(linha["incremental_inflow_m3s"], 26)
        self.assertEqual(linha[COLUNA_SLACK], 1.87)

    def test_falha_preserva_saida_anterior_e_remove_temporario(self):
        self.gerar()
        anterior = hashlib.sha256(self.saida.read_bytes()).hexdigest()
        self.fontes[8].drop(COLUNA_SLACK).write_parquet(self.hydros/"scenario_id=0008"/"data.parquet")
        with self.assertRaisesRegex(ValueError,COLUNA_SLACK):
            self.gerar()
        self.assertEqual(hashlib.sha256(self.saida.read_bytes()).hexdigest(),anterior)
        self.assertFalse(self.saida.with_name(self.saida.name+".tmp").exists())

    def test_rejeita_chaves_ambiguas_blocos_ausentes_e_vazoes_divergentes(self):
        original = self.fontes[0]
        casos = [
            (original.filter(pl.col("block_id")!=0), "block_id=0"),
            (pl.concat([original,original.filter(pl.col("block_id")==0).head(1)]), "duplicada"),
            (pl.concat([original,original.filter(pl.col("block_id").is_null()).head(1)]), "duplicada"),
            (original.with_columns(pl.lit(9).alias("scenario_id")), "difere"),
            (original.with_columns(pl.lit(None,dtype=pl.Int64).alias("hydro_id")), "nulo"),
            (original.filter(pl.col("block_id").is_not_null()), "difere entre blocos"),
        ]
        for dados, motivo in casos:
            with self.subTest(motivo=motivo):
                dados.write_parquet(self.hydros/"scenario_id=0000"/"data.parquet")
                with self.assertRaisesRegex(ValueError,motivo):
                    self.gerar()
                self.assertFalse(self.saida.exists())

    def test_aceita_arquivo_anterior_com_lags(self):
        self.gerar()
        anterior = self.pasta/"anterior.parquet"
        pl.read_parquet(self.saida).with_columns(pl.lit(3.).alias("lag_1_m3s"),
                                                pl.lit(2.).alias("lag_12_m3s")).write_parquet(anterior)
        self.assertEqual(validar_parquet_consolidado(anterior)["lags"],["lag_1_m3s","lag_12_m3s"])



if __name__ == "__main__":
    unittest.main()
