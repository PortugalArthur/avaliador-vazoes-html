"""Escala dos coeficientes, calendário e integridade do Parquet NEWAVE completo."""

from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from geradores.parametros_par_newave import ler_parametros_parpvaz, conferir_caso_newave, associar_parametros_newave
from dados.validacao_dados_cobre import validar_parquet_consolidado
from geradores.converter_qincr_newave import converter_qincr, selecionar_pastas_newave
from testes.fixtures_parpvaz import escrever_parpvaz
from testes import test_qincr_newave as fixtures
import pyarrow as pa
import pyarrow.parquet as pq


class TestParametrosParNewave(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.pasta = Path(self.tmp.name)
        self.arquivo = self.pasta/"parpvaz.dat"
        escrever_parpvaz(self.arquivo)

    def tearDown(self):
        self.tmp.cleanup()

    def test_leitor_escalas_ordem_final_zero_e_estatisticas(self):
        r = ler_parametros_parpvaz(self.arquivo,6)
        self.assertEqual(len(r.parametros),24)
        self.assertEqual(r.configuracao,72)
        self.assertEqual(r.historicos[101],(2000,2002))
        p = r.parametros[101,2]
        self.assertEqual(p["ar_order"],2)  # Original era 3.
        self.assertEqual(p["ar_coefficient_lag_1"],.2)
        self.assertEqual(p["ar_coefficient_lag_2"],-.02)
        self.assertEqual(p["annual_coefficient"],-.212)
        self.assertEqual(p["seasonal_mean_m3s"],23.)
        self.assertEqual(p["annual_mean_m3s"],22.5)
        self.assertNotEqual(p["annual_std_m3s"],p["seasonal_std_m3s"])
        self.assertNotIn(9.99,p.values())
        self.assertIsNone(r.parametros[101,11]["ar_coefficient_lag_1"])
        self.assertEqual(r.parametros[101,12]["ar_coefficient_lag_1"],0.)
        self.assertEqual(r.parametros[101,11]["ar_order"],0)
        self.assertEqual(r.parametros[101,11]["annual_coefficient"],.11)

    def test_nao_assume_codigo_menos_um_nem_posto_e_repete_por_mes(self):
        r = ler_parametros_parpvaz(self.arquivo,6)
        mapa = [dict(codigo_usina_arquivo="101",nome_usina_arquivo="São-José",hydro_id=42,arquivo_origem="qincruh101.out")]
        associado = associar_parametros_newave(r,mapa,[date(2027,2,1),date(2028,2,1),date(2028,11,1)])
        self.assertEqual(set(associado),{(42,2),(42,11)})
        self.assertEqual(associado[42,2],r.parametros[101,2])
        mapa[0]["codigo_usina_arquivo"] = "701"  # Posto, não NUM.
        with self.assertRaisesRegex(ValueError,"código/nome"):
            associar_parametros_newave(r,mapa,[date(2027,1,1)])

    def test_rejeita_bloco_incompleto_nao_finito_duplicado_e_limite(self):
        original = self.arquivo.read_text(encoding="utf-8")
        casos = [
            (original.replace("2.000E-01 -2.000E-02","nan -2.000E-02",1),"não finito"),
            (original.replace("2.000E-01 -2.000E-02","2.000E-01",1),"esperados 2"),
            (original.replace("ORDEM FINAL DO MODELO","ORDEM INDISPONIVEL DO MODELO",1),"ordem final"),
            (original.replace("CONFIGURACAO No. 72", "CONFIGURACAO No. 73",1),"Múltiplas configurações"),
            (original.replace("PERIODO: DEZ/POS", "PERIODO: JAN/POS",1),"ajuste duplicado"),
            (original.replace("POS 1 2 1", "POS 1 1 1",1),"divergentes"),
            (original.replace("\n-.212E+00\n", "\n\n",1),"terceira linha"),
        ]
        for texto,motivo in casos:
            with self.subTest(motivo=motivo):
                self.arquivo.write_text(texto,encoding="utf-8")
                with self.assertRaisesRegex(ValueError,motivo):
                    ler_parametros_parpvaz(self.arquivo,6)
        self.arquivo.write_text(original,encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"limite de lags"):
            ler_parametros_parpvaz(self.arquivo,1)

    def test_companheiros_confirmam_e_rejeitam_horizonte_agregacao_e_historico(self):
        r = ler_parametros_parpvaz(self.arquivo,6)
        periodos = [date(2027,11,1),date(2028,2,1)]
        self.assertEqual(conferir_caso_newave(self.arquivo,r,periodos),[])
        (self.pasta/"dger.dat").write_text("MES INICIO DO ESTUDO    1\nANO INICIO DO ESTUDO 2027\nNo. DE ANOS DO EST      1\nNo. DE ANOS POS FINAL   1\n")
        (self.pasta/"ree.dat").write_text("NUM NOME SUB MES ANO\n1 SUDESTE 1 1 2029\n999\n")
        (self.pasta/"confhd.dat").write_text("101 SAO JOSE 701 2000 2002\n305 ITIQUIRA II 905 2000 2002\n")
        (self.pasta/"pmo.dat").write_text("Afluencias:...............2000 - 2002\n")
        self.assertEqual(len(conferir_caso_newave(self.arquivo,r,periodos)),4)
        with self.assertRaisesRegex(ValueError,"Horizonte QINCR"):
            conferir_caso_newave(self.arquivo,r,[date(2030,1,1)])
        (self.pasta/"ree.dat").write_text("1 SUDESTE 1 1 2028\n999\n")
        with self.assertRaisesRegex(ValueError,"agregada"):
            conferir_caso_newave(self.arquivo,r,periodos)
        (self.pasta/"ree.dat").unlink()
        (self.pasta/"confhd.dat").write_text("101 SAO JOSE 701 2000 2003\n305 ITIQUIRA II 905 2000 2002\n")
        with self.assertRaisesRegex(ValueError,"Limites históricos"):
            conferir_caso_newave(self.arquivo,r,periodos)

    def test_validador_rejeita_parametros_incoerentes_e_variacao_entre_cenarios(self):
        # Reutiliza o caso de conversão para testar dados gravados, não a implementação do parser.
        caso = fixtures.TestQINCRNewave()
        caso.setUp()
        try:
            caso.converter()
            original = pq.read_table(caso.saida)
            destino = caso.pasta/"alterado.parquet"
            for campo,valor in [("ar_order",9),("annual_std_m3s",-1.),
                                 ("annual_coefficient",float('nan')),("inflow_nonnegativity_slack_m3s",0.),
                                 ("ar_coefficient_lag_1",0.)]:
                with self.subTest(campo=campo):
                    indice = original.schema.get_field_index(campo)
                    valores = original[campo].to_pylist()
                    valores[0] = valor
                    pq.write_table(original.set_column(indice,original.schema.field(campo),pa.array(valores,type=original.schema.field(campo).type)),destino)
                    with self.assertRaisesRegex(ValueError,"Parâmetros NEWAVE inválidos"):
                        validar_parquet_consolidado(destino)
            valores = original["annual_coefficient"].to_pylist()
            valores[0] += 1.
            pq.write_table(original.set_column(original.schema.get_field_index("annual_coefficient"),"annual_coefficient",pa.array(valores)),destino)
            with self.assertRaisesRegex(ValueError,"variam entre cenários"):
                validar_parquet_consolidado(destino)
            metadata = dict(original.schema.metadata)
            metadata[b"coefficient_basis"] = b"original_units"
            pq.write_table(original.replace_schema_metadata(metadata),destino)
            with self.assertRaisesRegex(ValueError,"Metadados do ajuste"):
                validar_parquet_consolidado(destino)
            with self.assertRaisesRegex(ValueError,"Informe o arquivo parpvaz"):
                converter_qincr(caso.qincr,caso.deck,caso.saida)
        finally:
            caso.tearDown()

    def test_cancelamento_na_segunda_e_terceira_selecao(self):
        for etapa in [2,3]:
            with self.subTest(etapa=etapa), \
                 patch("geradores.converter_qincr_newave.encontrar_arquivos_qincr"), \
                 patch("geradores.converter_qincr_newave.filedialog.askdirectory",side_effect=[str(self.pasta),""]), \
                 patch("geradores.converter_qincr_newave.filedialog.askopenfilename",return_value="" if etapa==2 else str(self.arquivo)), \
                 patch("geradores.converter_qincr_newave.messagebox.showinfo"):
                self.assertIsNone(selecionar_pastas_newave(None))


if __name__ == "__main__":
    unittest.main()
