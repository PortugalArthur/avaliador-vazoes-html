"""Exportação de dados originais: filtros, calendário, nulos e precisão float64."""
from datetime import date
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path
import re
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from xml.etree import ElementTree as ET
import zipfile

from aplicacao.exportar_csv import (inspecionar,Filtros,previa,exportar,exportar_excel,
                                  formatar_valor,FORMATO_DECIMAL_EXCEL,FORMATO_CIENTIFICO_EXCEL)
import pyarrow as pa
import pyarrow.parquet as pq


class TestExportarCSV(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.p=Path(self.tmp.name)
        self.deck=self.p/'deck';(self.deck/'system').mkdir(parents=True)
        self.etapas=[{'id':7,'start_date':'2026-01-01','end_date':'2026-02-01'},
                     {'id':4,'start_date':'2026-02-01','end_date':'2026-03-01'},
                     {'id':100,'start_date':'2027-01-01','end_date':'2027-02-01'}]
        (self.deck/'system/hydros.json').write_text(json.dumps({'hydros':[{'id':0,'name':'CAMARGOS'},{'id':5,'name':'FURNAS'}]}))
        (self.deck/'stages.json').write_text(json.dumps({'stages':self.etapas}))
        self.schema=pa.schema([('scenario_id',pa.int64()),('stage_id',pa.int64()),('node_id',pa.int64()),
                              ('hydro_id',pa.int64()),('incremental_inflow_m3s',pa.float64()),('annual_mean_m3s',pa.float64())])
        self.rows=[dict(scenario_id=c,stage_id=s,node_id=c,hydro_id=u,
            incremental_inflow_m3s=1.2345678901234567+s+u+c,annual_mean_m3s=None if c==10 else 0.)
            for u in [5,0] for s in [100,4,7] for c in [40,30,20,10]]
        self.rows[-1]['incremental_inflow_m3s']=0.
        self.src=self.p/'novo.parquet';pq.write_table(pa.Table.from_pylist(self.rows,schema=self.schema),self.src)

    def planilha(self,p):
        folhas=self.xlsx(p);cols=[c[1] for c in folhas[0][1][0].values()]
        return [{col:row.get(chr(65+i),('',''))[1] for i,col in enumerate(cols)}
                for _,rows in folhas for row in rows[1:]]

    def test_exportacao_todas_colunas_preserva_dados_e_fonte(self):
        before=hashlib.sha256(self.src.read_bytes()).hexdigest();info=inspecionar(self.src,self.deck)
        n,path=exportar(info,Filtros(),self.p/'dados.xlsx');rows=self.planilha(path)
        self.assertEqual(n,24);self.assertEqual(len(rows),24)
        esperado={(r['hydro_id'],r['stage_id'],r['scenario_id']):r for r in self.rows}
        for r in rows:
            original=esperado[int(r['hydro_id']),int(r['stage_id']),int(r['scenario_id'])]
            self.assertTrue(math.isclose(float(r['incremental_inflow_m3s']),original['incremental_inflow_m3s'],rel_tol=5e-16))
            self.assertEqual(r['annual_mean_m3s'],'' if original['annual_mean_m3s'] is None else '0')
        self.assertEqual(hashlib.sha256(self.src.read_bytes()).hexdigest(),before)
        self.assertTrue(zipfile.is_zipfile(path))
        self.assertEqual(list(rows[0]),list(self.schema.names))

    def test_filtros_usina_estagio_mes_cenario_com_calendario_nao_numerico(self):
        info=inspecionar(self.src,self.deck);self.assertEqual(info.estagios,(7,4,100))
        f=Filtros(usinas=[0],estagio_inicio=7,estagio_fim=100,mes=1,cenario_inicio=20,cenario_fim=30,
                  colunas=['stage_id','scenario_id','incremental_inflow_m3s'],incluir_cadastro=True)
        n,cols,rows=previa(info,f)
        self.assertEqual(n,4);self.assertEqual([r[0] for r in rows],[7,7,100,100])
        self.assertEqual([r[1] for r in rows],[20,30,20,30])
        self.assertEqual(cols[-3:],['nome_usina','inicio_estagio','fim_estagio'])
        self.assertTrue(all(r[3]=='CAMARGOS' for r in rows))
        nn,path=exportar(info,f,self.p/'filtrado.xlsx');self.assertEqual(nn,4)
        self.assertEqual([r['inicio_estagio'] for r in self.planilha(path)],['2026-01-01']*2+['2027-01-01']*2)

    def test_sem_deck_exporta_por_id_e_nao_inventa_mes(self):
        info=inspecionar(self.src)
        n,_,_=previa(info,Filtros(usinas=[5],estagio_inicio=4,estagio_fim=4,cenario_inicio=10,cenario_fim=10))
        self.assertEqual(n,1)
        with self.assertRaisesRegex(ValueError,'calendário'):previa(info,Filtros(mes=1))
        with self.assertRaisesRegex(ValueError,'cadastro'):previa(info,Filtros(incluir_cadastro=True))

    def test_newave_usa_metadados_nos_nulos_e_colunas_variaveis(self):
        data=[dict(r,hydro_id=r['hydro_id']+100,node_id=None) for r in self.rows]
        meta={b'source_model':b'NEWAVE',b'hydro_mapping':json.dumps([{'hydro_id':100,'nome_usina_cadastro':'CAMARGOS'},{'hydro_id':105,'nome_usina_cadastro':'FURNAS'}]).encode(),
              b'stage_mapping':json.dumps([{'stage_id':e['id'],'start_date':e['start_date'],'end_date':e['end_date']} for e in self.etapas]).encode()}
        src=self.p/'newave.parquet';pq.write_table(pa.Table.from_pylist(data,schema=self.schema).replace_schema_metadata(meta),src)
        info=inspecionar(src);self.assertEqual(info.modelo,'NEWAVE');self.assertEqual(info.nomes[100],'CAMARGOS')
        n,path=exportar(info,Filtros(usinas=[100],mes=2),self.p/'nw.xlsx')
        self.assertEqual(n,4);self.assertTrue(all(r['node_id']=='' for r in self.planilha(path)))

    def test_historico_filtra_anos_e_mes_sem_media_ou_sobreposicao(self):
        rows=[{'hydro_id':0,'start_date':date(y,m,1),'end_date':date(y,m+1,1),'value_m3s':v}
              for y,m,v in [(2022,1,8.),(2023,1,13.),(2023,2,99.),(2024,1,27.)]]
        src=self.p/'hist.parquet';pq.write_table(pa.Table.from_pylist(rows),src)
        info=inspecionar(src,self.deck,apenas_historico=True);self.assertEqual(info.tipo,'historico')
        n,path=exportar(info,Filtros(periodo_inicio='2023-01',periodo_fim='2024-01',mes=1),self.p/'hist.xlsx')
        result=self.planilha(path);self.assertEqual(n,2)
        self.assertEqual([float(r['value_m3s']) for r in result],[13.,27.])
        self.assertEqual([r['start_date'] for r in result],['2023-01-01','2024-01-01'])

    def test_modo_historico_rejeita_parquet_de_cenarios(self):
        with self.assertRaisesRegex(ValueError,'inflow_history.parquet'):
            inspecionar(self.src,self.deck,apenas_historico=True)

    def test_previa_limitada_nao_limita_exportacao(self):
        info=inspecionar(self.src)
        n,_,rows=previa(info,Filtros(),limite=2);self.assertEqual(n,24);self.assertEqual(len(rows),2)
        n,_=exportar(info,Filtros(),self.p/'total.xlsx');self.assertEqual(n,24)

    def test_intervalos_invalidos_ou_colunas_ausentes_bloqueiam(self):
        info=inspecionar(self.src,self.deck)
        for f in [Filtros(usinas=[]),Filtros(usinas=[999]),Filtros(colunas=[]),Filtros(colunas=['inexistente']),
                  Filtros(estagio_inicio=100,estagio_fim=7),Filtros(cenario_inicio=30,cenario_fim=20),Filtros(mes=13)]:
            with self.subTest(f=f),self.assertRaises(ValueError):previa(info,f)

    def test_fonte_alterada_e_saida_existente_sao_preservadas(self):
        info=inspecionar(self.src);dest=self.p/'antigo.xlsx';dest.write_text('anterior')
        with self.assertRaisesRegex(ValueError,'já existe'):exportar(info,Filtros(),dest)
        def mudar(_):
            with self.src.open('ab') as f:f.write(b'alteracao_teste')
        with self.assertRaisesRegex(ValueError,'mudou durante'):
            exportar(info,Filtros(),dest,sobrescrever=True,progresso=mudar)
        self.assertEqual(dest.read_text(),'anterior');self.assertFalse(list(self.p.glob('*.tmp')))

    def test_formatacao_nao_arredonda_e_distingue_nulo_zero_e_decimal(self):
        for q in [1.2345678901234567,1e-200,-0.,-3.141592653589793]:
            self.assertEqual(float(formatar_valor(q).replace(',','.')),q)
        self.assertEqual(formatar_valor(None),'');self.assertEqual(formatar_valor(0.),'0,0')
        self.assertEqual(formatar_valor(Decimal('1.2300')),'1,2300')

    def test_numeros_grandes_nao_recebem_separador_de_milhar(self):
        for valor,esperado in [(1234567,'1234567'),(1234567.89,'1234567,89'),
                               (-1234567.89,'-1234567,89'),(Decimal('1234567.8900'),'1234567,8900')]:
            with self.subTest(valor=valor):
                texto=formatar_valor(valor)
                self.assertEqual(texto,esperado)
                self.assertLessEqual(texto.count(','),1)
                self.assertNotIn('.',texto);self.assertNotIn(' ',texto)


    def xlsx(self,path):
        ns={'x':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
        with zipfile.ZipFile(path) as z:
            estilos=ET.fromstring(z.read('xl/styles.xml'))
            formatos={int(f.attrib['numFmtId']):f.attrib['formatCode'] for f in estilos.findall('x:numFmts/x:numFmt',ns)}
            estilos_celula=[int(f.attrib['numFmtId']) for f in estilos.findall('x:cellXfs/x:xf',ns)]
            folhas=[]
            for nome in sorted(n for n in z.namelist() if n.startswith('xl/worksheets/sheet') and n.endswith('.xml')):
                raiz=ET.fromstring(z.read(nome));linhas=[]
                for row in raiz.findall('x:sheetData/x:row',ns):
                    celulas={}
                    for c in row.findall('x:c',ns):
                        texto=''.join(t.text or '' for t in c.findall('.//x:t',ns)) if c.attrib.get('t')=='inlineStr' else c.findtext('x:v',default='',namespaces=ns)
                        estilo=estilos_celula[int(c.attrib.get('s',0))]
                        celulas[re.sub(r'\d','',c.attrib['r'])]=(c.attrib.get('t','n'),texto,formatos.get(estilo,str(estilo)))
                    linhas.append(celulas)
                folhas.append((raiz,linhas))
        return folhas

    def test_excel_numero_do_caso_real_nao_depende_do_separador_decimal(self):
        alvo=45.64170226738804
        src=self.p/'valor.parquet'
        pq.write_table(pa.Table.from_pylist([dict(self.rows[0],incremental_inflow_m3s=alvo)]),src)
        info=inspecionar(src)
        n,path=exportar_excel(info,Filtros(colunas=['incremental_inflow_m3s']),self.p/'valor.xlsx')
        tipo,valor,formato=self.xlsx(path)[0][1][1]['A']
        self.assertEqual(n,1);self.assertEqual(tipo,'n')
        self.assertEqual(float(valor),alvo)
        self.assertNotIn(',',valor);self.assertNotIn(',',formato)
        self.assertEqual(formato,FORMATO_DECIMAL_EXCEL)

    def test_excel_mesmos_filtros_valores_nulos_zero_e_sem_formulas(self):
        data=[dict(r) for r in self.rows];data[-1]['incremental_inflow_m3s']=0.
        self.deck.joinpath('system/hydros.json').write_text(json.dumps({'hydros':[{'id':0,'name':'=1+2'},{'id':5,'name':'FURNAS'}]}))
        pq.write_table(pa.Table.from_pylist(data,schema=self.schema),self.src)
        before=hashlib.sha256(self.src.read_bytes()).hexdigest();info=inspecionar(self.src,self.deck)
        f=Filtros(usinas=[0],estagio_inicio=7,estagio_fim=7,colunas=['scenario_id','incremental_inflow_m3s','annual_mean_m3s'],incluir_cadastro=True)
        total,cols,expected=previa(info,f)
        n,path=exportar_excel(info,f,self.p/'filtrado.xlsx');raiz,rows=self.xlsx(path)[0]
        self.assertEqual(n,total);self.assertEqual(n,4)
        self.assertEqual([v[1] for v in rows[0].values()],cols)
        for row,original in zip(rows[1:],expected,strict=True):
            for j,(col,v) in enumerate(zip(cols,original,strict=True)):
                celula=chr(65+j)
                if v is None:self.assertNotIn(celula,row)
                elif isinstance(v,(int,float)):
                    self.assertEqual(row[celula][0],'n')
                    self.assertTrue(math.isclose(float(row[celula][1]),v,rel_tol=3e-16,abs_tol=0))
                    self.assertNotIn(',',row[celula][2])
                else:self.assertEqual(row[celula][:2],('inlineStr',str(v)))
        self.assertEqual(hashlib.sha256(self.src.read_bytes()).hexdigest(),before)
        self.assertFalse(raiz.findall('.//{*}f'))

    def test_excel_divide_em_abas_sem_perder_linhas(self):
        info=inspecionar(self.src)
        with patch('aplicacao.exportar_csv.MAX_LINHAS_EXCEL',3):
            n,path=exportar_excel(info,Filtros(usinas=[0],estagio_inicio=4,estagio_fim=4),self.p/'abas.xlsx')
        folhas=self.xlsx(path)
        self.assertEqual(n,4);self.assertEqual(len(folhas),2)
        self.assertEqual([len(rows)-1 for _,rows in folhas],[2,2])
        self.assertEqual(sorted(int(r['A'][1]) for _,rows in folhas for r in rows[1:]),[10,20,30,40])

    def test_excel_tiny_values_e_identificadores_grandes_nao_viram_zero(self):
        data=[dict(self.rows[0],scenario_id=1234567890123456789,incremental_inflow_m3s=1e-200)]
        pq.write_table(pa.Table.from_pylist(data,schema=self.schema),self.src)
        n,path=exportar_excel(inspecionar(self.src),Filtros(colunas=['scenario_id','incremental_inflow_m3s']),self.p/'tiny.xlsx')
        r=self.xlsx(path)[0][1][1]
        self.assertEqual(r['A'][:2],('inlineStr','1234567890123456789'))
        self.assertEqual(float(r['B'][1]),1e-200)
        self.assertIn('E+00',r['B'][2]);self.assertNotIn(',',r['B'][2])

    def test_excel_falha_preserva_saida_anterior(self):
        info=inspecionar(self.src);dest=self.p/'anterior.xlsx';dest.write_bytes(b'anterior')
        with self.assertRaisesRegex(ValueError,'já existe'):exportar_excel(info,Filtros(),dest)
        def mudar(_):
            with self.src.open('ab') as f:f.write(b'alteracao_teste')
        with self.assertRaisesRegex(ValueError,'mudou durante'):
            exportar_excel(info,Filtros(),dest,sobrescrever=True,progresso=mudar)
        self.assertEqual(dest.read_bytes(),b'anterior');self.assertFalse(list(self.p.glob('*.tmp')))


    def test_csv_rejeitado_sem_criar_ou_sobrescrever_arquivo(self):
        info=inspecionar(self.src);dest=self.p/'antigo.csv';dest.write_bytes(b'anterior')
        with self.assertRaisesRegex(ValueError,'xlsx'):
            exportar(info,Filtros(),dest,sobrescrever=True)
        self.assertEqual(dest.read_bytes(),b'anterior')
        self.assertFalse(list(self.p.glob('*.tmp')))

    def test_precisao_sem_arredondamento_adicional_na_exportacao(self):
        valores=[1.2345678901234567,45.64170226738804,0.00000012345678901234567,
                 -3.141592653589793,1.2345678901234567e-200,1234567890.1234567]
        data=[dict(self.rows[0],scenario_id=i,incremental_inflow_m3s=v) for i,v in enumerate(valores)]
        pq.write_table(pa.Table.from_pylist(data,schema=self.schema),self.src)
        _,path=exportar(inspecionar(self.src),Filtros(colunas=['incremental_inflow_m3s']),self.p/'precisao.xlsx')
        for (_,raw,formato),v in zip((r['A'] for r in self.xlsx(path)[0][1][1:]),valores,strict=True):
            # O serializador numérico do XLSX usa 16 algarismos significativos.
            # Esse é o único limite aplicado: não reduzimos decimais na consulta.
            self.assertEqual(float(raw),float(format(v,'.16g')))
            self.assertIn(formato,[FORMATO_DECIMAL_EXCEL,FORMATO_CIENTIFICO_EXCEL])
            self.assertNotIn(',',formato)


if __name__=='__main__':unittest.main()
