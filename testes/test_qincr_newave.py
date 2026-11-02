"""QINCR por marcadores, IDs por cadastro/data, node nulo e cinco análises."""

from contextlib import redirect_stdout
from datetime import date
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from geradores.converter_qincr_newave import converter_qincr, ler_relatorio_qincr, selecionar_pastas_newave, COLUNAS_NEWAVE
from dados.validacao_dados_cobre import validar_parquet_consolidado, validar_stages_json, validar_hydros_json, validar_compatibilidade
from calculos.correlacao_espacial_cobre import gerar_correlacao_espacial
from dados.metadados_vazoes import colunas_newave_completo
from testes.fixtures_parpvaz import escrever_parpvaz
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq


def escrever_qincr(arquivo,nome,offset=0.,n=3):
    linhas = ["ESTUDO DE TESTE",f"VAZAO INCREMENTAL DA USINA (m3/s) USINA:{nome}",""]
    for ano,meses,inicio in [(2027,[11,12],0),(2028,[1,2],2)]:
        linhas += [f"ANO: {ano}"," ".join(map(str,meses))+" MEDIA"]
        for c in range(n,0,-1):  # A posição física da linha não define o cenário.
            valores = [offset+10*c+i+.25 for i in range(inicio,inicio+2)]
            linhas.append(str(c)+" "+" ".join(f"{v:.2f}" for v in valores)+" 9999.00")
        for resumo in ["MEDIA","DPADRAO","MIN","P5","P95","MAX"]:
            linhas.append(resumo+" "+" ".join(["0.00"]*(3 if resumo == "MEDIA" else 2)))
        linhas.append("")
    arquivo.write_text("\n".join(linhas),encoding="utf-8")


class TestQINCRNewave(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.pasta = Path(self.tmp.name)
        self.qincr,self.deck = self.pasta/"QINCR",self.pasta/"referencia"
        self.qincr.mkdir()
        (self.deck/"system").mkdir(parents=True)
        self.a,self.b = self.qincr/"qincruh101.out",self.qincr/"qincruh305.out"
        escrever_qincr(self.a,"SAO JOSE")
        escrever_qincr(self.b,"ITIQUIRA II",100.)
        self.saida = self.pasta/"inflows_newave.parquet"
        self.parpvaz = self.pasta/"parpvaz.dat"
        escrever_parpvaz(self.parpvaz)
        (self.deck/"config.json").write_text(json.dumps({"estimation":{"max_order":6}}),encoding="utf-8")
        nomes = {"hydros":[{"id":42,"name":"São-José"},{"id":7,"name":"ITIQUIRA II"}]}
        (self.deck/"system"/"hydros.json").write_text(json.dumps(nomes),encoding="utf-8")
        stages = {"stages":[dict(id=i,start_date=str(p.start_time.date()),end_date=str((p+1).start_time.date()))
                            for i,p in zip([88,30,4,99,17,2],pd.period_range("2027-10",periods=6,freq="M"))]}
        (self.deck/"stages.json").write_text(json.dumps(stages),encoding="utf-8")
        self.calendario = validar_stages_json(self.deck/"stages.json")
        self.nomes = validar_hydros_json(self.deck/"system"/"hydros.json")

    def tearDown(self):
        self.tmp.cleanup()

    def converter(self):
        with redirect_stdout(StringIO()):
            return converter_qincr(self.qincr,self.deck,self.saida,arquivo_parpvaz=self.parpvaz)

    def test_parser_ignora_media_e_resumos_e_reconstroi_trajectoria(self):
        r = ler_relatorio_qincr(self.a)
        self.assertEqual(r.nome,"SAO JOSE")
        self.assertEqual(r.cenarios.tolist(),[1,2,3])
        self.assertEqual(r.periodos,(date(2027,11,1),date(2027,12,1),date(2028,1,1),date(2028,2,1)))
        self.assertEqual(r.valores.shape,(3,4))
        np.testing.assert_array_equal(r.valores[0],[10.25,11.25,12.25,13.25])
        self.assertFalse(np.any(r.valores == 9999))

    def test_formato_completo_mapeado_por_nome_mes_e_no_nulo(self):
        self.saida = self.pasta/"parquet gerado newave"/"inflows_newave.parquet"
        with patch("geradores.converter_qincr_newave.PASTA_PROJETO",self.pasta), redirect_stdout(StringIO()):
            self.assertEqual(converter_qincr(self.qincr,self.deck,arquivo_parpvaz=self.parpvaz),self.saida)
        tabela = pq.read_table(self.saida)
        self.assertEqual(tabela.column_names,colunas_newave_completo(6))
        self.assertEqual(tabela.num_rows,24)
        self.assertEqual(tabela["node_id"].null_count,24)
        self.assertTrue(pa.types.is_integer(tabela.schema.field("node_id").type))
        self.assertEqual(tabela.schema.metadata[b"source_model"],b"NEWAVE")
        dados = tabela.to_pandas()
        linha = dados.loc[dados.hydro_id.eq(42) & dados.scenario_id.eq(0)].set_index("stage_id")
        self.assertEqual(linha.loc[30,"incremental_inflow_m3s"],10.25)
        self.assertEqual(linha.loc[99,"incremental_inflow_m3s"],12.25)
        self.assertEqual(linha.loc[30,"ar_order"],0)  # Novembro, sem usar stage_id % 12.
        self.assertEqual(linha.loc[4,"ar_order"],2)
        self.assertEqual(linha.loc[4,"ar_coefficient_lag_1"],0.)
        self.assertAlmostEqual(linha.loc[99,"ar_coefficient_lag_1"],.1)
        self.assertAlmostEqual(linha.loc[17,"annual_coefficient"],-.212)
        self.assertTrue(tabela["inflow_nonnegativity_slack_m3s"].null_count==24)
        self.assertTrue(linha.filter(like="ar_coefficient").loc[30].isna().all())
        meta = validar_parquet_consolidado(self.saida)
        self.assertEqual(meta["modelo_origem"],"NEWAVE")
        self.assertEqual(meta["cenarios"],3)
        self.assertEqual(meta["usinas"],[7,42])
        self.assertEqual(set(meta["ids_estagios"]),{30,4,99,17})
        self.assertEqual(validar_compatibilidade(meta,self.nomes,self.calendario),[])

    def test_somente_newave_identificado_pode_ter_no_nulo(self):
        self.converter()
        tabela = pq.read_table(self.saida)
        outro = self.pasta/"sem_metadados.parquet"
        pq.write_table(tabela.replace_schema_metadata(None),outro)
        with self.assertRaisesRegex(ValueError,"identificadores nulos"):
            validar_parquet_consolidado(outro)
        errado = tabela.set_column(2,"node_id",pa.array([0]*len(tabela),type=pa.int64()))
        pq.write_table(errado,outro)
        with self.assertRaisesRegex(ValueError,"node_id nulo"):
            validar_parquet_consolidado(outro)
        duplicado = pa.concat_tables([tabela,tabela.slice(0,1)])
        pq.write_table(duplicado,outro)
        with self.assertRaisesRegex(ValueError,"repetidas"):
            validar_parquet_consolidado(outro)

    def test_referencia_incompativel_nao_e_aceita(self):
        self.converter()
        meta = validar_parquet_consolidado(self.saida)
        nomes = dict(self.nomes,**{})
        nomes[42] = "Outra usina"
        self.assertTrue(any("nome incompatível" in e for e in validar_compatibilidade(meta,nomes,self.calendario)))
        calendario = {i:dict(v) for i,v in self.calendario.items()}
        calendario[30]["inicio"] = date(2020,1,1)
        self.assertTrue(any("datas incompatíveis" in e for e in validar_compatibilidade(meta,self.nomes,calendario)))

    def test_parser_rejeita_lacunas_repeticoes_e_nao_finitos(self):
        original = self.a.read_text(encoding="utf-8")
        casos = [(original.replace("P5 0.00 0.00\n","",1),"resumos"),
                 (original.replace("3 30.25", "1 30.25",1),"sem lacunas"),
                 (original.replace("30.25","nan",1),"não finito"),
                 (original.replace("ANO: 2028","ANO: 2029"),"lacuna")]
        for texto,motivo in casos:
            with self.subTest(caso=motivo):
                self.a.write_text(texto,encoding="utf-8")
                with self.assertRaisesRegex(ValueError,motivo):
                    ler_relatorio_qincr(self.a)

    def test_falha_tardia_preserva_arquivo_e_zeros_sao_dados(self):
        self.converter()
        anterior = self.saida.read_bytes()
        escrever_qincr(self.b,"ITIQUIRA II",100.,n=2)
        with self.assertRaisesRegex(ValueError,"cenários incompatíveis"):
            self.converter()
        self.assertEqual(self.saida.read_bytes(),anterior)
        self.assertFalse(self.saida.with_name(self.saida.name+".tmp.parquet").exists())
        escrever_qincr(self.b,"ITIQUIRA II",100.)
        texto = self.b.read_text(encoding="utf-8")
        for v in [110.25,111.25,112.25,113.25,120.25,121.25,122.25,123.25,130.25,131.25,132.25,133.25]:
            texto = texto.replace(f"{v:.2f}","0.00")
        self.b.write_text(texto,encoding="utf-8")
        self.converter()
        dados = pq.read_table(self.saida).to_pandas()
        self.assertTrue(dados.loc[dados.hydro_id.eq(7),"incremental_inflow_m3s"].eq(0).all())

    def test_sem_correspondencia_ou_mes_nao_inventa_ids(self):
        escrever_qincr(self.b,"NOME SEM CADASTRO")
        with self.assertRaisesRegex(ValueError,"sem correspondência"):
            self.converter()
        self.assertFalse(self.saida.exists())
        escrever_qincr(self.b,"ITIQUIRA II")
        stages = json.loads((self.deck/"stages.json").read_text())
        stages["stages"] = stages["stages"][:2]
        (self.deck/"stages.json").write_text(json.dumps(stages),encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"Meses do QINCR ausentes"):
            self.converter()

    def test_seletores_corrigem_e_cancelam(self):
        with patch("geradores.converter_qincr_newave.filedialog.askdirectory",side_effect=[str(self.deck),str(self.qincr),str(self.deck)]), \
             patch("geradores.converter_qincr_newave.filedialog.askopenfilename",side_effect=[str(self.a),str(self.parpvaz)]), \
             patch("geradores.converter_qincr_newave.messagebox.showinfo"), \
             patch("geradores.converter_qincr_newave.messagebox.showerror") as erro:
            self.assertEqual(selecionar_pastas_newave(None),(self.qincr,self.parpvaz,self.deck))
            self.assertEqual(erro.call_count,2)
        with patch("geradores.converter_qincr_newave.filedialog.askdirectory",return_value=""), \
             patch("geradores.converter_qincr_newave.messagebox.showinfo"):
            self.assertIsNone(selecionar_pastas_newave(None))

    def test_correlacao_espacial_e_formato_legado_com_no_nulo(self):
        self.converter()
        espacial = gerar_correlacao_espacial(str(self.saida),self.nomes,self.calendario)
        self.assertEqual(set(espacial.stage_ids),{30,4,99,17})
        self.assertAlmostEqual(espacial.correlacoes[0,0,1],1.)
        # O formato antigo de cinco colunas continua funcionando nas cinco abas.
        tabela = pq.read_table(self.saida)
        metadata = {k:v for k,v in tabela.schema.metadata.items() if k in
                    [b"source_model",b"node_id_semantics",b"scenario_id_transform",b"hydro_mapping",b"stage_mapping"]}
        legado = self.pasta/"legado.parquet"
        pq.write_table(tabela.select(COLUNAS_NEWAVE).replace_schema_metadata(metadata),legado)
        self.assertFalse(validar_parquet_consolidado(legado)["parametros_par_newave"])




if __name__ == "__main__":
    unittest.main()
