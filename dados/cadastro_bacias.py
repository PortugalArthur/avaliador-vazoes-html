"""Lista interna de bacias transcrita do diagrama ONS de maio de 2026."""

import json
from pathlib import Path

import pandas as pd

from dados.metadados_vazoes import normalizar_nome_usina


CAMINHO_CADASTRO = Path(__file__).with_name("cadastro_bacias_ons_maio_2026.json")


def assinatura_cadastro_bacias():
    stat = CAMINHO_CADASTRO.stat()
    return str(CAMINHO_CADASTRO), stat.st_size, stat.st_mtime_ns


def ler_cadastro_bacias(caminho=None):
    """Lê somente o JSON distribuído com o programa; não necessita do PDF."""
    arquivo = Path(caminho) if caminho is not None else CAMINHO_CADASTRO
    try:
        documento = json.loads(arquivo.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError) as erro:
        raise ValueError("A lista interna de bacias não contém um JSON válido.") from erro
    if not isinstance(documento, dict) or not documento.get("versao") or not isinstance(documento.get("bacias"), list):
        raise ValueError("Formato inválido da lista interna de bacias.")
    ids, nomes, aliases = set(), set(), {}
    ids_subdivisoes, nomes_subdivisoes = set(), set()
    linhas = []
    for bacia in documento["bacias"]:
        if (not isinstance(bacia, dict) or not isinstance(bacia.get("id"), int)
                or isinstance(bacia["id"], bool) or bacia["id"] <= 0
                or not isinstance(bacia.get("nome"), str) or not bacia["nome"].strip()
                or not isinstance(bacia.get("usinas"), list)):
            raise ValueError("Bacia inválida na lista interna.")
        codigo, nome = bacia["id"], bacia["nome"].strip()
        if codigo in ids or normalizar_nome_usina(nome) in nomes:
            raise ValueError("Código ou nome de bacia repetido na lista interna.")
        ids.add(codigo)
        nomes.add(normalizar_nome_usina(nome))
        subdivisoes = {}
        itens_subdivisoes = bacia.get("subdivisoes", [])
        if not isinstance(itens_subdivisoes, list):
            raise ValueError("Subdivisões inválidas na lista interna de bacias.")
        for sub in itens_subdivisoes:
            if (not isinstance(sub, dict) or not isinstance(sub.get("id"), int)
                    or isinstance(sub["id"], bool) or sub["id"] <= 0
                    or not isinstance(sub.get("nome"), str) or not sub["nome"].strip()):
                raise ValueError("Subdivisão inválida na lista interna de bacias.")
            chave_nome = normalizar_nome_usina(sub["nome"])
            if sub["id"] in ids_subdivisoes or chave_nome in nomes_subdivisoes:
                raise ValueError("Código ou nome de subdivisão repetido na lista interna.")
            ids_subdivisoes.add(sub["id"])
            nomes_subdivisoes.add(chave_nome)
            subdivisoes[sub["id"]] = sub["nome"].strip()
        for usina in bacia["usinas"]:
            if (not isinstance(usina, dict) or not isinstance(usina.get("nome_pdf"), str)
                    or not usina["nome_pdf"].strip() or not isinstance(usina.get("aliases"), list)
                    or not all(isinstance(a, str) and a.strip() for a in usina["aliases"])
                    or not isinstance(usina.get("rio"), str) or not usina["rio"].strip()):
                raise ValueError("Usina inválida na lista interna de bacias.")
            indice = len(linhas)
            subdivisao_id = usina.get("subdivisao_id")
            if subdivisao_id is not None and (
                not isinstance(subdivisao_id, int) or isinstance(subdivisao_id, bool)
                or subdivisao_id not in subdivisoes
            ):
                raise ValueError(f"Subdivisão incompatível com a bacia de {usina['nome_pdf']}.")
            chaves = {normalizar_nome_usina(n) for n in [usina["nome_pdf"], *usina["aliases"]]}
            for chave in chaves:
                if not chave or chave in aliases:
                    raise ValueError(f"Nome ou alias ambíguo na lista interna: {usina['nome_pdf']}.")
                aliases[chave] = indice
            linhas.append({"nome_pdf": usina["nome_pdf"], "aliases": list(usina["aliases"]),
                           "bacia_id": codigo, "Bacia": nome, "Rio": usina["rio"],
                           "subdivisao_id": subdivisao_id,
                           "Subdivisão": subdivisoes.get(subdivisao_id),
                           "Tem subdivisões": bool(subdivisoes)})
    if not linhas:
        raise ValueError("A lista interna de bacias está vazia.")
    if ids.intersection(ids_subdivisoes):
        raise ValueError("Bacias e subdivisões não podem usar o mesmo código interno.")
    cadastro = pd.DataFrame(linhas)
    cadastro.attrs["versao"] = documento["versao"]
    cadastro.attrs["fonte"] = documento.get("fonte", {})
    return cadastro


def associar_usinas_bacias(nomes, cadastro):
    """Associa por nome normalizado ou alias explícito, sem aproximações."""
    por_nome = {}
    for linha in cadastro.to_dict("records"):
        for nome in {normalizar_nome_usina(n) for n in [linha["nome_pdf"], *linha["aliases"]]}:
            if nome in por_nome:
                raise ValueError(f"Nome ambíguo no cadastro interno: {nome}.")
            por_nome[nome] = linha
    normalizados = set()
    linhas = []
    for hydro_id, nome in nomes.items():
        chave = normalizar_nome_usina(nome)
        if not chave or chave in normalizados:
            raise ValueError(f"Cadastro do estudo com nome de usina inválido ou ambíguo: {nome}.")
        normalizados.add(chave)
        registro = por_nome.get(chave, {})
        linhas.append({"hydro_id": int(hydro_id), "Usina": nome,
                       "Nome no diagrama": registro.get("nome_pdf"), "Rio": registro.get("Rio"),
                       "bacia_id": registro.get("bacia_id"), "Bacia": registro.get("Bacia"),
                       "subdivisao_id": registro.get("subdivisao_id"),
                       "Subdivisão": registro.get("Subdivisão"),
                       "Tem subdivisões": registro.get("Tem subdivisões", False)})
    resultado = pd.DataFrame(linhas, columns=["hydro_id", "Usina", "Nome no diagrama", "Rio", "bacia_id", "Bacia",
                                               "subdivisao_id", "Subdivisão", "Tem subdivisões"])
    for coluna in ("bacia_id", "subdivisao_id"):
        resultado[coluna] = resultado[coluna].astype("Int64")
    return resultado


def organizar_agrupamento_bacias(cadastro, incluir_subdivisoes=False):
    """Mantém uma única classificação por UHE em cada modo de visualização."""
    resultado = cadastro.copy(deep=True)
    resultado["Bacia principal"] = resultado["Bacia"]
    if incluir_subdivisoes:
        subdivididas = resultado.subdivisao_id.notna()
        demais = resultado["Tem subdivisões"].eq(True) & ~subdivididas
        resultado.loc[demais, "Bacia"] = resultado.loc[demais, "Bacia"] + " — demais trechos"
        resultado.loc[subdivididas, "bacia_id"] = resultado.loc[subdivididas, "subdivisao_id"]
        resultado.loc[subdivididas, "Bacia"] = resultado.loc[subdivididas, "Subdivisão"]
    return resultado
