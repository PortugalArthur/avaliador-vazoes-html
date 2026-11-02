"""Converte QINCR e ajuste PAR(p)-A do NEWAVE no esquema comum do avaliador."""

from dataclasses import dataclass
from datetime import date
import json
import math
import os
from pathlib import Path
import re
import sys
import tkinter as tk
from tkinter import filedialog, messagebox

# Permite executar o gerador diretamente pelo editor ou como módulo.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from infraestrutura.preparar_ambiente import PASTA_PROJETO, garantir_dependencias
garantir_dependencias({"numpy": "numpy>=1.24", "pyarrow": "pyarrow>=14"})
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from dados.metadados_vazoes import normalizar_nome_usina, COLUNAS_BASE_NEWAVE, colunas_newave_completo
from dados.validacao_dados_cobre import validar_hydros_json, validar_stages_json, validar_parquet_consolidado
from geradores.parametros_par_newave import (
    validar_arquivo_parpvaz, ler_parametros_parpvaz, conferir_caso_newave, associar_parametros_newave,
)


COLUNAS_NEWAVE = COLUNAS_BASE_NEWAVE  # Esquema legado, ainda aceito pelo dashboard.
RESUMOS = {"MEDIA", "DPADRAO", "MIN", "P5", "P95", "MAX"}


@dataclass
class RelatorioQINCR:
    nome: str
    cenarios: np.ndarray
    periodos: tuple[date, ...]
    valores: np.ndarray


def encontrar_arquivos_qincr(pasta):
    pasta = Path(pasta).resolve()
    if not pasta.is_dir():
        raise ValueError(f"Pasta QINCR inexistente: {pasta}")
    arquivos, codigos = [], set()
    for arquivo in sorted(pasta.iterdir()):
        if not arquivo.is_file() or not arquivo.name.lower().startswith("qincruh") or arquivo.suffix.lower() != ".out":
            continue
        match = re.fullmatch(r"qincruh(\d+)\.out", arquivo.name, re.I)
        if not match or int(match[1]) in codigos:
            raise ValueError(f"Nome ou código de usina inválido/duplicado: {arquivo.name}")
        codigos.add(int(match[1]))
        arquivos.append(arquivo)
    if not arquivos:
        raise ValueError("Selecione a pasta QINCR que contém diretamente os arquivos qincruhNNN.out.")
    return arquivos


def validar_referencia_cobre(pasta):
    pasta = Path(pasta).resolve()
    faltantes = [n for n in ("config.json", "stages.json", "system/hydros.json") if not (pasta/n).is_file()]
    if faltantes:
        raise ValueError(f"Selecione a pasta do deck de referência COBRE. Arquivos ausentes: {', '.join(faltantes)}")
    ler_limite_lags(pasta)
    return pasta


def ler_limite_lags(pasta):
    try:
        config = json.loads((Path(pasta)/"config.json").read_text(encoding="utf-8-sig"))
        max_order = config["estimation"]["max_order"]
    except (ValueError, OSError, KeyError, TypeError) as erro:
        raise ValueError("O deck de referência deve informar estimation.max_order em config.json.") from erro
    if isinstance(max_order,bool) or not isinstance(max_order,int) or max_order < 0:
        raise ValueError("estimation.max_order deve ser inteiro não negativo.")
    return max_order


def ler_nome_qincr(arquivo):
    try:
        with Path(arquivo).open(encoding="utf-8-sig") as f:
            f.readline()
            linha = f.readline()
    except (UnicodeError, OSError) as erro:
        raise ValueError(f"Não foi possível ler o cabeçalho de {arquivo}.") from erro
    match = re.search(r"USINA\s*:\s*(.+?)\s*$", linha, re.I)
    if not match or "VAZAOINCREMENTAL" not in normalizar_nome_usina(linha) or "m3/s" not in linha.lower():
        raise ValueError(f"{Path(arquivo).name}: cabeçalho de vazão incremental em m3/s ou nome da usina ausente.")
    return match[1].strip()


def mapear_usinas(arquivos, nomes):
    por_nome = {}
    for hydro_id, nome in nomes.items():
        por_nome.setdefault(normalizar_nome_usina(nome), []).append(hydro_id)
    mapa, usados, pendencias = [], set(), []
    for arquivo in arquivos:
        nome = ler_nome_qincr(arquivo)
        candidatos = por_nome.get(normalizar_nome_usina(nome), [])
        if len(candidatos) != 1:
            pendencias.append(f"{arquivo.name}: '{nome}' — " + ("sem correspondência" if not candidatos else f"nome ambíguo: IDs {candidatos}"))
            continue
        hydro_id = candidatos[0]
        if hydro_id in usados:
            pendencias.append(f"Mais de um arquivo corresponde à UHE {hydro_id} ({nome}).")
            continue
        usados.add(hydro_id)
        mapa.append(dict(arquivo_origem=arquivo.name, codigo_usina_arquivo=re.fullmatch(r"qincruh(\d+)\.out",arquivo.name,re.I)[1],
                         nome_usina_arquivo=nome, hydro_id=hydro_id, nome_usina_cadastro=nomes[hydro_id]))
    if pendencias:
        raise ValueError("Correspondências de usinas pendentes; nenhum ID foi presumido:\n"+"\n".join(pendencias))
    return mapa


def ler_relatorio_qincr(arquivo):
    """Lê os marcadores do relatório, sem fixar anos, cenários ou linhas físicas."""
    nome = ler_nome_qincr(arquivo)
    blocos = []
    bloco = None

    def falha(linha, mensagem):
        raise ValueError(f"{Path(arquivo).name}, linha {linha}: {mensagem}")

    def concluir(linha):
        if bloco is None:
            return
        if not bloco["meses"] or not bloco["ids"]:
            falha(linha,"bloco anual sem cabeçalho mensal ou sem cenários")
        if bloco["resumos"] != RESUMOS:
            falha(linha,f"resumos anuais ausentes: {sorted(RESUMOS-bloco['resumos'])}")
        if sorted(bloco["ids"]) != list(range(1,len(bloco["ids"])+1)):
            falha(linha,"os cenários devem formar a sequência de 1 a N, sem lacunas ou repetições")
        ordem = np.argsort(bloco["ids"])
        blocos.append((bloco["ano"],bloco["meses"],np.asarray(bloco["ids"],dtype=np.int64)[ordem],
                       np.asarray(bloco["valores"],dtype=np.float64)[ordem]))

    try:
        with Path(arquivo).open(encoding="utf-8-sig") as f:
            for numero, texto in enumerate(f,1):
                linha = texto.strip()
                if not linha or numero <= 2:
                    continue
                ano = re.fullmatch(r"ANO\s*:\s*(\d{4})",linha,re.I)
                if ano:
                    concluir(numero)
                    if any(b[0] == int(ano[1]) for b in blocos):
                        falha(numero,"ano duplicado")
                    bloco = dict(ano=int(ano[1]),meses=None,ids=[],valores=[],resumos=set())
                    continue
                if bloco is None:
                    falha(numero,"conteúdo inesperado antes do primeiro ANO:")
                campos = linha.split()
                if campos[-1].upper() == "MEDIA" and all(c.isdecimal() for c in campos[:-1]):
                    meses = [int(c) for c in campos[:-1]]
                    if bloco["meses"] is not None or not meses or not all(1<=m<=12 for m in meses) or meses != list(range(meses[0],meses[-1]+1)):
                        falha(numero,"cabeçalho mensal inválido ou duplicado")
                    bloco["meses"] = meses
                    continue
                if bloco["meses"] is None:
                    falha(numero,"cabeçalho dos meses ausente")
                rotulo = campos[0].rstrip(":").upper()
                cenario = campos[0].isdecimal()
                if not cenario and rotulo not in RESUMOS:
                    falha(numero,f"linha de dados ou resumo não reconhecida: {campos[0]}")
                extras = 1 if cenario or rotulo == "MEDIA" else 0
                if len(campos) != 1+len(bloco["meses"])+extras:
                    falha(numero,"quantidade de valores incompatível com os meses e a coluna MEDIA")
                try:
                    valores = [float(v) for v in campos[1:]]
                except ValueError:
                    falha(numero,"valor de vazão/resumo não numérico")
                if not all(math.isfinite(v) for v in valores):
                    falha(numero,"valor de vazão/resumo não finito")
                if cenario:
                    if bloco["resumos"]:
                        falha(numero,"cenário encontrado depois dos resumos anuais")
                    bloco["ids"].append(int(campos[0]))
                    # MEDIA é apenas um resumo; preservar somente as vazões mensais.
                    bloco["valores"].append(valores[:-1])
                else:
                    if rotulo in bloco["resumos"]:
                        falha(numero,f"resumo {rotulo} duplicado")
                    bloco["resumos"].add(rotulo)
        concluir(numero if 'numero' in locals() else 0)
    except (UnicodeError, OSError) as erro:
        raise ValueError(f"Falha ao ler {arquivo}: {erro}") from erro
    if not blocos:
        raise ValueError(f"{Path(arquivo).name}: nenhum bloco ANO: encontrado.")
    cenarios = blocos[0][2]
    if any(not np.array_equal(b[2],cenarios) for b in blocos):
        raise ValueError(f"{Path(arquivo).name}: cenários inconsistentes entre os anos.")
    periodos = tuple(date(ano,m,1) for ano,meses,_,_ in blocos for m in meses)
    ordinais = [p.year*12+p.month for p in periodos]
    if any(b != a+1 for a,b in zip(ordinais,ordinais[1:])):
        raise ValueError(f"{Path(arquivo).name}: lacuna, repetição ou inversão nos meses do horizonte.")
    return RelatorioQINCR(nome,cenarios,periodos,np.concatenate([b[3] for b in blocos],axis=1))


def converter_qincr(pasta_qincr,pasta_referencia,arquivo_saida=None,*,arquivo_parpvaz=None):
    if arquivo_parpvaz is None:
        raise ValueError("Informe o arquivo parpvaz.dat do mesmo caso hidrológico do QINCR.")
    arquivos = encontrar_arquivos_qincr(pasta_qincr)
    referencia = validar_referencia_cobre(pasta_referencia)
    nomes = validar_hydros_json(referencia/"system"/"hydros.json")
    calendario = validar_stages_json(referencia/"stages.json")
    mapa = mapear_usinas(arquivos,nomes)
    primeiro = ler_relatorio_qincr(arquivos[0])
    por_data = {etapa["inicio"]:i for i,etapa in calendario.items()}
    faltantes = [str(d) for d in primeiro.periodos if d not in por_data]
    if faltantes:
        raise ValueError("Meses do QINCR ausentes no calendário de referência: "+", ".join(faltantes))
    ids_estagios = np.array([por_data[d] for d in primeiro.periodos],dtype=np.int64)
    max_order = ler_limite_lags(referencia)
    relatorio = ler_parametros_parpvaz(arquivo_parpvaz,max_order)
    conferidos = conferir_caso_newave(arquivo_parpvaz,relatorio,primeiro.periodos)
    parametros = associar_parametros_newave(relatorio,mapa,primeiro.periodos)
    colunas = colunas_newave_completo(max_order)
    mapa_estagios = [dict(stage_id=int(i),start_date=str(calendario[int(i)]["inicio"]),end_date=str(calendario[int(i)]["fim"])) for i in ids_estagios]
    metadata = {b"source_model":b"NEWAVE",b"node_id_semantics":b"unavailable",
                b"scenario_id_transform":b"original_minus_one",b"reported_decimal_places":b"2",
                b"hydro_mapping":json.dumps(mapa,ensure_ascii=False).encode("utf-8"),
                b"stage_mapping":json.dumps(mapa_estagios).encode("utf-8")}
    metadata.update({b"newave_schema_version":b"2",b"coefficient_basis":b"seasonal_standardized",
                     b"ar_max_order":str(max_order).encode(),b"slack_semantics":b"unavailable",
                     b"parpvaz_sha256":relatorio.sha256.encode(),
                     b"parpvaz_configuration":str(relatorio.configuracao).encode(),
                     b"parpvaz_history_periods":json.dumps(sorted(set(relatorio.historicos.values()))).encode(),
                     b"parpvaz_companions_checked":json.dumps(conferidos).encode()})
    schema = pa.schema([pa.field(c,pa.int64() if c in COLUNAS_NEWAVE[:4] else
                                pa.int32() if c == "ar_order" else pa.float64(),
                                nullable=(c in ("node_id","inflow_nonnegativity_slack_m3s")
                                          or c.startswith("ar_coefficient_lag_"))) for c in colunas],metadata=metadata)
    if arquivo_saida is None:
        saida = PASTA_PROJETO/"parquet gerado newave"/"inflows_newave.parquet"
        saida.parent.mkdir(parents=True,exist_ok=True)
    else:
        saida = Path(arquivo_saida)
    if not saida.parent.is_dir():
        raise ValueError(f"Pasta de saída inexistente: {saida.parent}")
    temporario = saida.with_name(saida.name+".tmp.parquet")
    escritor = None
    linhas = 0
    try:
        escritor = pq.ParquetWriter(temporario,schema,compression="zstd")
        for posicao,(arquivo,usina) in enumerate(zip(arquivos,mapa),1):
            r = primeiro if posicao == 1 else ler_relatorio_qincr(arquivo)
            if r.periodos != primeiro.periodos or not np.array_equal(r.cenarios,primeiro.cenarios):
                raise ValueError(f"{arquivo.name}: horizonte ou cenários incompatíveis com os demais relatórios.")
            if r.nome != usina["nome_usina_arquivo"]:
                raise ValueError(f"{arquivo.name}: cabeçalho mudou durante a leitura.")
            n,h = r.valores.shape
            quantidade = n*h
            arrays = [
                pa.array(np.repeat(r.cenarios-1,h)),pa.array(np.tile(ids_estagios,n)),
                pa.nulls(quantidade,type=pa.int64()),pa.array(np.full(quantidade,usina["hydro_id"],dtype=np.int64)),
                pa.array(r.valores.ravel()),pa.nulls(quantidade,type=pa.float64())]
            # O mês vem da data real, sem aritmética com o ID do estágio.
            por_mes = [parametros[usina["hydro_id"],p.month] for p in r.periodos]
            for campo in colunas[6:]:
                valores = [p[campo] for p in por_mes] * n
                arrays.append(pa.array(valores,type=schema.field(campo).type))
            tabela = pa.Table.from_arrays(arrays,schema=schema)
            escritor.write_table(tabela)
            linhas += quantidade
            if posicao == 1 or posicao % 10 == 0 or posicao == len(arquivos):
                print(f"QINCR: {posicao}/{len(arquivos)} usinas; {linhas} vazões mensais.",flush=True)
        escritor.close()
        escritor = None
        meta = validar_parquet_consolidado(temporario)
        if meta["registros"] != len(arquivos)*len(primeiro.cenarios)*len(primeiro.periodos):
            raise ValueError("A associação dos parâmetros alterou a quantidade de observações.")
        os.replace(temporario,saida)
    except Exception:
        if escritor is not None:
            escritor.close()
        if temporario.exists():
            temporario.unlink()
        raise
    print(f"NEWAVE: {len(arquivos)} usinas, {len(primeiro.cenarios)} cenários, {len(primeiro.periodos)} meses. Salvo em {saida}",flush=True)
    return saida


def selecionar_pastas_newave(janela):
    selecoes = []
    for titulo,texto,validador,arquivo in [
        ("1/3 — Pasta QINCR do NEWAVE","Selecione a pasta que contém diretamente os arquivos qincruhNNN.out.",encontrar_arquivos_qincr,False),
        ("2/3 — Ajuste PAR(p)-A do NEWAVE","Selecione o parpvaz.dat do mesmo caso hidrológico que gerou o QINCR.\n\n"
         "Será usado o ajuste mensal da configuração final para o horizonte completamente individualizado.",validar_arquivo_parpvaz,True),
        ("3/3 — Deck do novo modelo de referência","Selecione a pasta que contém config.json, stages.json e system/hydros.json.\n\n"
         "O cadastro fornece os IDs, o calendário fornece as datas e estimation.max_order define o limite de lags.",validar_referencia_cobre,False)]:
        messagebox.showinfo(titulo,texto,parent=janela)
        while True:
            pasta = (filedialog.askopenfilename(title=titulo,filetypes=[("Relatório NEWAVE","*.dat"),("Todos os arquivos","*.*")],parent=janela)
                     if arquivo else filedialog.askdirectory(title=titulo,mustexist=True,parent=janela))
            if not pasta:
                return None
            try:
                validador(pasta)
                selecoes.append(Path(pasta))
                break
            except ValueError as erro:
                messagebox.showerror("Pasta incorreta",str(erro),parent=janela)
    return tuple(selecoes)  # QINCR, parpvaz.dat, deck de referência.


def main():
    janela = tk.Tk()
    janela.withdraw()
    try:
        pastas = selecionar_pastas_newave(janela)
        if pastas is None:
            messagebox.showinfo("Seleção cancelada","Nenhum arquivo foi gerado.",parent=janela)
            return
        try:
            qincr,parpvaz,referencia = pastas
            saida = converter_qincr(qincr,referencia,arquivo_parpvaz=parpvaz)
        except Exception as erro:
            messagebox.showerror("Falha na conversão QINCR",str(erro),parent=janela)
            raise
        messagebox.showinfo("Conversão concluída",f"Parquet NEWAVE salvo em:\n{saida}\n\n"
                            "No dashboard, selecione esse arquivo e a pasta do deck do novo modelo de referência, que contém também o histórico.",parent=janela)
    finally:
        janela.destroy()


if __name__ == "__main__":
    try:
        main()
    except Exception as erro:
        print(f"Erro: {erro}",file=sys.stderr)
        sys.exit(1)
