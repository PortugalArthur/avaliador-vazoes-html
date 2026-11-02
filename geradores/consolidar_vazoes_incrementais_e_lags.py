"""Consolida vazões, folgas e parâmetros PAR do deck COBRE selecionado."""

from pathlib import Path  # Permite trabalhar com pastas e arquivos sem fixar caminhos no código.
import os  # Permite substituir o arquivo final somente depois de concluir a escrita.
import sys  # Permite sinalizar erro quando o programa é executado diretamente.
import tkinter as tk  # Cria a janela básica usada pelos seletores de pastas.
from tkinter import filedialog, messagebox  # Abre os seletores e mostra mensagens ao usuário.

# Permite executar o gerador diretamente pelo editor ou como módulo.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from infraestrutura.preparar_ambiente import PASTA_PROJETO, garantir_dependencias  # Prepara automaticamente as bibliotecas ausentes na primeira execução.

garantir_dependencias(  # Permite iniciar pelo botão Run sem executar previamente um comando de instalação.
    {
        "polars": "polars>=0.20",
        "pyarrow": "pyarrow>=14",
    }
)

import polars as pl  # Lê, verifica, transforma e junta as tabelas de cada cenário.
import pyarrow.parquet as pq  # Grava vários cenários em um único arquivo Parquet.
from geradores.parametros_par_consolidado import carregar_parametros_par, validar_pasta_deck, validar_pasta_saida


CHAVE = ["scenario_id", "stage_id", "node_id", "hydro_id"]  # Define os quatro identificadores que impedem misturas entre registros.
COLUNA_SLACK = "inflow_nonnegativity_slack_m3s"  # Identifica a folga de não negatividade copiada diretamente da saída hydros.
COLUNAS_HYDROS = CHAVE + ["block_id", "incremental_inflow_m3s", COLUNA_SLACK]  # Lê apenas os campos necessários do arquivo hydros.
COLUNAS_SAIDA = CHAVE + ["incremental_inflow_m3s", COLUNA_SLACK]  # Define as seis colunas básicas preservadas no consolidado enriquecido.


def encontrar_cenarios(pasta: Path, nome_fonte: str) -> dict[int, Path]:  # Localiza os arquivos de cada cenário de uma fonte.
    if not pasta.is_dir():  # Verifica se a pasta principal existe e é um diretório.
        raise ValueError(f"A pasta {nome_fonte} não existe: {pasta}")  # Explica qual pasta selecionada está incorreta.

    cenarios = {}  # Guarda cada caminho pelo número do cenário, sem depender da ordem dos arquivos.
    for subpasta in pasta.glob("scenario_id=*"):  # Procura somente as entradas com o nome esperado.
        if not subpasta.is_dir():  # Verifica se a entrada encontrada é realmente uma pasta.
            raise ValueError(f"Entrada de cenário não é uma pasta: {subpasta}")  # Rejeita uma estrutura inesperada.
        identificador = subpasta.name.removeprefix("scenario_id=")  # Extrai o identificador escrito no nome da pasta.
        if not identificador.isdecimal():  # Exige um identificador numérico para associar os cenários com segurança.
            raise ValueError(f"Identificador de cenário inválido: {subpasta}")  # Mostra a pasta com nome inválido.
        numero = int(identificador)  # Converte o identificador para comparar pastas com diferentes quantidades de zeros.
        if numero in cenarios:  # Detecta duas pastas que representam o mesmo cenário numérico.
            raise ValueError(f"Cenário {numero} repetido em {nome_fonte}: {subpasta}")  # Impede uma associação ambígua.
        arquivo = subpasta / "data.parquet"  # Monta o caminho do Parquet esperado dentro da pasta do cenário.
        if not arquivo.is_file():  # Confirma que o Parquet correspondente existe.
            raise ValueError(f"Arquivo ausente em {nome_fonte}: {arquivo}")  # Informa precisamente o arquivo faltante.
        cenarios[numero] = arquivo  # Associa o número do cenário ao respectivo Parquet.

    if not cenarios:  # Verifica se a pasta selecionada continha pelo menos um cenário.
        raise ValueError(f"Nenhuma pasta scenario_id=* encontrada em {nome_fonte}: {pasta}")  # Informa a estrutura esperada.
    return cenarios  # Entrega o mapa de cenários para a associação entre as fontes.


def verificar_cenario(tabela: pl.DataFrame, numero: int, fonte: str) -> None:  # Confere o identificador armazenado no próprio Parquet.
    if tabela.is_empty():  # Rejeita um cenário sem linhas, que não produziria informações úteis.
        raise ValueError(f"{fonte}, cenário {numero}: o Parquet está vazio")  # Explica qual arquivo precisa de atenção.
    if tabela.select(pl.col("scenario_id").is_null().any()).item():  # Procura identificadores de cenário ausentes.
        raise ValueError(f"{fonte}, cenário {numero}: scenario_id nulo")  # Evita associar uma linha sem cenário definido.
    if tabela.filter(pl.col("scenario_id") != numero).height:  # Compara cada linha com o identificador da pasta.
        raise ValueError(f"{fonte}, cenário {numero}: scenario_id do arquivo difere do nome da pasta")  # Evita misturar cenários.
    for coluna in CHAVE:  # Examina cada identificador necessário à junção.
        if tabela.select(pl.col(coluna).is_null().any()).item():  # Procura valores ausentes na chave.
            raise ValueError(f"{fonte}, cenário {numero}: {coluna} nulo")  # Informa qual identificador está incompleto.


def verificar_chave_unica(tabela: pl.DataFrame, colunas: list[str], fonte: str, numero: int) -> None:  # Detecta linhas repetidas sem agregá-las.
    repetidas = tabela.group_by(colunas).agg(pl.len().alias("quantidade"))  # Conta quantas linhas existem por chave.
    repetidas = repetidas.filter(pl.col("quantidade") > 1)  # Mantém apenas as chaves que aparecem mais de uma vez.
    if not repetidas.is_empty():  # Interrompe o processamento diante de qualquer duplicidade.
        exemplo = repetidas.row(0, named=True)  # Guarda uma chave repetida para a mensagem de erro.
        raise ValueError(f"{fonte}, cenário {numero}: chave duplicada {exemplo}")  # Mostra a chave problemática sem escolher uma linha.


def selecionar_vazao_atual(tabela: pl.DataFrame, numero: int) -> pl.DataFrame:  # Obtém uma única vazão atual por estágio e usina.
    verificar_cenario(tabela, numero, "hydros")  # Confere as chaves e o cenário dentro do arquivo hydros.
    registros_de_estagio = tabela.filter(pl.col("block_id").is_null())  # Procura o registro de estágio indicado pelo COBRE atual.
    total_chaves = tabela.select(CHAVE).unique().height  # Conta as combinações de cenário, estágio, nó e usina.
    bloco_zero = tabela.filter(pl.col("block_id") == 0)  # Separa o bloco escolhido explicitamente para copiar o slack.
    verificar_chave_unica(bloco_zero, CHAVE, "hydros com block_id=0", numero)  # Exige uma só cópia do bloco 0 por chave.
    if bloco_zero.height != total_chaves:  # Confirma que o slack do bloco 0 existe para todas as combinações.
        raise ValueError(f"hydros, cenário {numero}: falta block_id=0 para alguma chave")  # Não substitui o slack por outro bloco.
    slack_bloco_zero = bloco_zero.select(CHAVE + [COLUNA_SLACK])  # Guarda o slack do bloco 0 sem comparar seu valor com os demais blocos.

    if not registros_de_estagio.is_empty():  # Prioriza os registros de estágio quando block_id é nulo.
        verificar_chave_unica(registros_de_estagio, CHAVE, "hydros com block_id nulo", numero)  # Exige uma só linha de estágio por chave.
        if registros_de_estagio.height != total_chaves:  # Confirma que todas as chaves possuem registro de estágio.
            raise ValueError(f"hydros, cenário {numero}: nem todas as chaves têm block_id nulo")  # Evita perder usinas ou estágios.
        vazoes = registros_de_estagio.select(CHAVE + ["incremental_inflow_m3s"])  # Usa a vazão de estágio, mantendo o slack separado no bloco 0.
    else:  # Trata versões em que a vazão incremental é repetida em todos os blocos.
        valores_por_chave = tabela.group_by(CHAVE).agg(  # Conta somente os valores distintos da vazão incremental entre os blocos.
            pl.col("incremental_inflow_m3s").n_unique().alias("quantidade_vazao"),  # Verifica a repetição segura da vazão entre patamares.
        )
        divergentes = valores_por_chave.filter(pl.col("quantidade_vazao") != 1)  # Identifica somente vazões incrementais diferentes entre blocos.
        if not divergentes.is_empty():  # Rejeita a escolha de um bloco quando os valores divergem.
            exemplo = divergentes.row(0, named=True)  # Guarda uma chave com valores conflitantes.
            raise ValueError(f"hydros, cenário {numero}: vazão incremental difere entre blocos em {exemplo}")  # Explica a ambiguidade restante.
        vazoes = bloco_zero.select(CHAVE + ["incremental_inflow_m3s"])  # Usa a vazão repetida do bloco 0 após validar somente essa variável.

    vazoes = vazoes.join(slack_bloco_zero, on=CHAVE, how="left", validate="1:1")  # Acrescenta sempre o slack vindo do bloco 0.
    return vazoes.select(CHAVE + ["incremental_inflow_m3s", COLUNA_SLACK])  # Entrega uma linha por chave sem manter block_id.


def consolidar(pasta_hydros: Path, arquivo_saida: Path | None = None, *,
               pasta_deck: Path | None = None, pasta_stochastic: Path | None = None) -> Path:
    """Gera seis colunas básicas; com ambas as fontes do ajuste, acrescenta os parâmetros PAR."""
    pasta_hydros = Path(pasta_hydros)  # Aceita um caminho Path ou texto sem depender do diretório de execução.
    if arquivo_saida is None:  # Define o local padrão quando o usuário não especifica outro local.
        arquivo_saida = PASTA_PROJETO / "parquet gerado novo modelo" / "inflows_with_lags.parquet"
        arquivo_saida.parent.mkdir(parents=True, exist_ok=True)  # Cria a pasta padrão do novo modelo (COBRE).
    arquivo_saida = Path(arquivo_saida)  # Garante que a saída pode ser manipulada como caminho de arquivo.
    if not arquivo_saida.parent.is_dir():  # Confere que o diretório de saída já existe.
        raise ValueError(f"Pasta de saída inexistente: {arquivo_saida.parent}")  # Evita iniciar o processamento sem destino válido.

    hydros = encontrar_cenarios(pasta_hydros, "hydros")  # A pasta inflow_lags não é necessária para o novo formato.
    print(f"Cenários encontrados em hydros: {len(hydros)}", flush=True)  # Mostra a quantidade identificada, sem fixar 2000.
    if (pasta_deck is None) != (pasta_stochastic is None):
        raise ValueError("Informe conjuntamente a pasta do deck de entrada e a pasta stochastic.")
    parametros, colunas_parametros = None, []
    if pasta_deck is not None:
        print("Validando calendário, ordens e parâmetros estocásticos...", flush=True)
        parametros, colunas_parametros = carregar_parametros_par(pasta_deck, pasta_stochastic)
    colunas_saida = COLUNAS_SAIDA + colunas_parametros
    print(f"Colunas do consolidado: {len(colunas_saida)}", flush=True)

    temporario = arquivo_saida.with_name(arquivo_saida.name + ".tmp")  # Define um arquivo temporário ao lado da saída final.
    if temporario.exists():  # Evita misturar uma execução anterior incompleta com a execução atual.
        temporario.unlink()  # Remove somente o temporário desta rotina.
    escritor = None  # Guarda o gravador único, iniciado após o primeiro cenário válido.
    esquema = None  # Guarda o esquema de colunas e tipos do primeiro cenário.
    estagios = set()  # Acumula os identificadores de estágio observados.
    usinas = set()  # Acumula os identificadores de usina observados.
    total_linhas = 0  # Conta as linhas escritas no Parquet final.

    try:  # Garante que uma falha feche o gravador e remova a saída temporária.
        for posicao, numero in enumerate(sorted(hydros), start=1):  # Processa os cenários em ordem numérica crescente.
            if posicao == 1 or posicao % 50 == 0 or posicao == len(hydros):  # Limita as mensagens de progresso para manter o terminal legível.
                print(f"Processando cenário {numero:04d} ({posicao}/{len(hydros)})...", flush=True)  # Informa o cenário atual.

            colunas_disponiveis = pq.read_schema(hydros[numero]).names  # Verifica o esquema antes de tentar ler a nova variável.
            faltantes = [coluna for coluna in COLUNAS_HYDROS if coluna not in colunas_disponiveis]  # Valida todo o esquema de entrada.
            if faltantes:  # Impede criar uma saída parcial ou inventar valores ausentes.
                raise ValueError(  # Informa precisamente o cenário, o arquivo e a coluna ausente.
                    f"Colunas ausentes em hydros do cenário {numero:04d}: {', '.join(faltantes)}. Arquivo: {hydros[numero]}"
                )
            dados_hydros = pl.read_parquet(hydros[numero], columns=COLUNAS_HYDROS)  # Lê vazão e slack diretamente do mesmo arquivo hydros.
            vazoes = selecionar_vazao_atual(dados_hydros, numero)  # Obtém uma vazão incremental por estágio, nó e usina.
            resultado = vazoes
            if parametros is not None:
                # Parâmetros não variam por cenário/nó. A relação m:1 preserva
                # todas as vazões e impede multiplicar linhas pelos lags AR.
                ajuste = parametros.with_columns(
                    pl.col("hydro_id").cast(vazoes.schema["hydro_id"], strict=True),
                    pl.col("stage_id").cast(vazoes.schema["stage_id"], strict=True))
                resultado = vazoes.join(ajuste, on=["hydro_id", "stage_id"], how="left", validate="m:1")
                sem_parametros = resultado.filter(pl.col("ar_order").is_null())
                if not sem_parametros.is_empty():
                    exemplo = sem_parametros.select(CHAVE).row(0, named=True)
                    raise ValueError(f"Cenário {numero}: UHE/estágio sem parâmetros do ajuste selecionado: {exemplo}")
                if resultado.height != vazoes.height:
                    raise ValueError(f"Cenário {numero}: a associação dos parâmetros alterou a quantidade de vazões.")
            resultado = resultado.select(colunas_saida).sort(CHAVE)  # Mantém as seis colunas iniciais e acrescenta o ajuste, sem vazões de lags.
            estagios.update(resultado.get_column("stage_id").unique().to_list())  # Registra os estágios encontrados no cenário.
            usinas.update(resultado.get_column("hydro_id").unique().to_list())  # Registra as usinas encontradas no cenário.
            tabela_arrow = resultado.to_arrow()  # Converte apenas o cenário atual para a tabela usada pelo gravador Parquet.

            if escritor is None:  # Cria o único gravador quando a primeira tabela estiver pronta.
                esquema = tabela_arrow.schema  # Preserva os tipos das colunas observados no primeiro cenário.
                escritor = pq.ParquetWriter(temporario, esquema, compression="zstd")  # Abre um único arquivo Parquet temporário.
            tabela_arrow = tabela_arrow.cast(esquema, safe=True)  # Exige o mesmo esquema sem converter valores de forma insegura.
            escritor.write_table(tabela_arrow)  # Acrescenta as linhas do cenário ao mesmo arquivo Parquet.
            total_linhas += resultado.height  # Atualiza a quantidade total de registros consolidados.

        escritor.close()  # Fecha o arquivo temporário após escrever todos os cenários.
        escritor = None  # Marca o gravador como fechado para não tentar fechá-lo novamente.
        os.replace(temporario, arquivo_saida)  # Publica a saída única somente depois de concluir todas as verificações.
    except Exception:  # Trata qualquer falha de leitura, validação ou escrita.
        if escritor is not None:  # Verifica se o gravador ainda precisa ser fechado.
            escritor.close()  # Libera o arquivo temporário antes de removê-lo.
        if temporario.exists():  # Confere se foi criado algum arquivo intermediário.
            temporario.unlink()  # Remove o arquivo incompleto e preserva eventual saída anterior.
        raise  # Repassa a falha com sua mensagem original para o usuário.

    print(f"Estágios encontrados: {len(estagios)}", flush=True)  # Mostra quantos estágios distintos aparecem na saída.
    print(f"Usinas encontradas: {len(usinas)}", flush=True)  # Mostra quantas usinas distintas aparecem na saída.
    print(f"Linhas consolidadas: {total_linhas}", flush=True)  # Mostra o total de combinações consolidadas.
    print(f"Dataset salvo em: {arquivo_saida}", flush=True)  # Informa o caminho do único arquivo final.
    return arquivo_saida  # Permite que outra rotina também use o resultado produzido.


def selecionar_pastas(janela):
    """Orienta as duas seleções e permite corrigir a pasta sem reiniciar o gerador."""
    messagebox.showinfo("Etapa 1 de 2 — deck de entrada",
                        "Selecione a pasta raiz do DECK DE ENTRADA.\n\n"
                        "Ela deve conter:\nconfig.json\nstages.json\nsystem/hydros.json\n\n"
                        "Escolha a pasta do estudo, não a pasta system ou uma pasta de cenário.", parent=janela)
    while True:
        escolhido = filedialog.askdirectory(title="1/2 — DECK DE ENTRADA (config.json, stages.json e system)",
                                             mustexist=True, parent=janela)
        if not escolhido:
            return None
        try:
            deck = validar_pasta_deck(escolhido)
            break
        except ValueError as erro:
            messagebox.showerror("Pasta de entrada incorreta", str(erro), parent=janela)
    messagebox.showinfo("Etapa 2 de 2 — saída extraída",
                        "Extraia o output.zip do mesmo estudo. Depois selecione a pasta que contém:\n\n"
                        "simulation/hydros/scenario_id=.../data.parquet\n"
                        "stochastic/inflow_ar_coefficients.parquet\n"
                        "stochastic/fitting_report.json\n"
                        "stochastic/inflow_annual_component.parquet\n"
                        "stochastic/inflow_seasonal_stats.parquet\n\n"
                        "Escolha a pasta que contém simulation e stochastic, independentemente do nome dela.", parent=janela)
    while True:
        escolhido = filedialog.askdirectory(title="2/2 — SAÍDA EXTRAÍDA (pastas simulation e stochastic)",
                                             initialdir=str(deck), mustexist=True, parent=janela)
        if not escolhido:
            return None
        try:
            hydros, stochastic = validar_pasta_saida(escolhido)
            return deck, hydros, stochastic
        except ValueError as erro:
            messagebox.showerror("Pasta de saída incorreta", str(erro), parent=janela)


def main() -> None:  # Solicita as raízes do deck de entrada e da saída extraída.
    janela = tk.Tk()  # Inicializa a janela necessária aos diálogos nativos do sistema.
    janela.withdraw()  # Esconde a janela vazia e deixa apenas os diálogos visíveis.
    try:  # Garante que a janela seja encerrada mesmo se o usuário cancelar ou ocorrer um erro.
        pastas = selecionar_pastas(janela)
        if pastas is None:
            messagebox.showinfo("Seleção cancelada", "Nenhum Parquet foi gerado. O arquivo existente foi preservado.", parent=janela)
            return
        pasta_deck, pasta_hydros, pasta_stochastic = pastas
        try:  # Mostra qualquer problema estrutural encontrado durante a consolidação.
            saida = consolidar(pasta_hydros, pasta_deck=pasta_deck, pasta_stochastic=pasta_stochastic)
        except Exception as erro:  # Captura a explicação da falha sem ocultá-la.
            messagebox.showerror("Falha na consolidação", str(erro), parent=janela)  # Exibe o problema em uma janela legível.
            raise  # Mantém a falha visível também no terminal, quando houver.
        messagebox.showinfo("Consolidação concluída", f"Dataset salvo em:\n{saida}", parent=janela)  # Mostra o caminho do resultado.
    finally:  # Executa a limpeza tanto em sucesso quanto em cancelamento ou erro.
        janela.destroy()  # Fecha a janela de suporte aos diálogos.


if __name__ == "__main__":  # Executa a interface somente quando este arquivo Python é aberto diretamente.
    try:  # Converte uma falha não tratada em um código de saída compreensível.
        main()  # Inicia a seleção visual e a consolidação.
    except Exception as erro:  # Recebe qualquer erro já informado pela interface.
        print(f"Erro: {erro}", file=sys.stderr)  # Repete a causa no terminal, quando ele estiver aberto.
        sys.exit(1)  # Encerra com código de erro para indicar que não houve saída nova válida.
