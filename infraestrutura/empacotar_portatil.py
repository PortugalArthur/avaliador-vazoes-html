"""Gera e verifica o ZIP portátil Windows x64 a partir de um commit do Git."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import sysconfig
from tempfile import TemporaryDirectory
import zipfile


PROGRAMA = Path(__file__).resolve().parents[1]
RAIZ = PROGRAMA.parent if PROGRAMA.name == "programa" else PROGRAMA
NOME_PACOTE = "AVALIADOR_VAZOES_HTML_WINDOWS_X64"
ATALHOS = (
    "GERAR_RELATORIO_HTML.bat",
    "GERAR_PARQUET_NOVO_MODELO.bat",
    "GERAR_PARQUET_NEWAVE.bat",
    "EXPORTAR_PARQUET_EXCEL.bat",
    "EXPORTAR_HISTORICO_EXCEL.bat",
)


def copiar_python(runtime: Path, requisitos: Path) -> None:
    origem = Path(sys.base_prefix)
    if not all((origem / nome).exists() for nome in ("python.exe", "DLLs", "Lib", "tcl", "LICENSE.txt")):
        raise RuntimeError("Use uma instalação completa do CPython para Windows com Tcl/Tk e pip.")

    runtime.mkdir()
    shutil.copy2(origem / "python.exe", runtime)
    shutil.copy2(origem / "LICENSE.txt", runtime)
    for dll in origem.glob("*.dll"):
        shutil.copy2(dll, runtime)
    ignorar_cache = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo")
    for pasta in ("DLLs", "tcl"):
        shutil.copytree(origem / pasta, runtime / pasta, ignore=ignorar_cache)
    shutil.copytree(
        origem / "Lib",
        runtime / "Lib",
        ignore=shutil.ignore_patterns(
            "site-packages", "__pycache__", "*.pyc", "*.pyo", "test", "tests",
            "idlelib", "turtledemo", "ensurepip",
        ),
    )
    site = runtime / "Lib" / "site-packages"
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "--disable-pip-version-check",
         "--only-binary=:all:", "--target", str(site), "-r", str(requisitos)],
        check=True,
    )
    versao = f"{sys.version_info.major}{sys.version_info.minor}"
    (runtime / f"python{versao}._pth").write_text(
        "DLLs\nLib\nLib/site-packages\nimport site\n", encoding="ascii",
    )


def verificar_pacote(pacote: Path, programa: Path) -> dict:
    ambiente = dict(
        os.environ,
        PATH=str(Path(os.environ["SystemRoot"]) / "System32"),
        PYTHONPATH="IGNORAR", PYTHONHOME="IGNORAR", PIP_NO_INDEX="1",
        TCL_LIBRARY="IGNORAR", TK_LIBRARY="IGNORAR",
    )
    cmd = Path(ambiente["PATH"]) / "cmd.exe"
    for atalho in ATALHOS:
        subprocess.run(
            [str(cmd), "/d", "/c", atalho, "--verificar-ambiente"],
            cwd=pacote, env=ambiente, stdin=subprocess.DEVNULL, check=True, timeout=60,
        )

    verificar = """
import importlib
from importlib.metadata import distributions
import json
import sys

for modulo in (
    'duckdb', 'numpy', 'pandas', 'scipy', 'pyarrow', 'plotly',
    'polars', 'openpyxl', 'xlsxwriter', 'tzdata',
):
    importlib.import_module(modulo)
print(json.dumps({
    'python': sys.version.split()[0],
    'bibliotecas': {d.metadata['Name']: d.version for d in distributions()},
}))
"""
    resultado = subprocess.check_output(
        [str(pacote / "_python" / "python.exe"), "-X", "utf8", "-c", verificar],
        cwd=programa, env=ambiente, text=True, encoding="utf-8", timeout=60,
    )
    return json.loads(resultado)


def preparar(destino: Path, ref: str) -> Path:
    if sysconfig.get_platform() != "win-amd64":
        raise RuntimeError("Prepare o ZIP com CPython x64 no Windows.")
    if sys.implementation.name != "cpython" or sys.version_info < (3, 10):
        raise RuntimeError("Use CPython 3.10 ou mais recente.")

    commit = subprocess.check_output(
        ["git", "rev-parse", "--verify", f"{ref}^{{commit}}"],
        cwd=RAIZ, text=True,
    ).strip()
    destino = destino.resolve()
    destino.mkdir(parents=True, exist_ok=True)
    saida = destino / f"{NOME_PACOTE}.zip"
    checksum = destino / f"{NOME_PACOTE}.sha256"
    if saida.exists() or checksum.exists():
        raise FileExistsError(f"Escolha um destino sem um pacote anterior: {destino}")

    with TemporaryDirectory(prefix="build-avaliador-", dir=destino) as temporario:
        pasta = Path(temporario)
        pacote = pasta / "Avaliador de Vazões HTML"
        fontes = pasta / "fontes.zip"
        subprocess.run(
            ["git", "archive", "--format=zip", "-o", str(fontes), commit],
            cwd=RAIZ, check=True,
        )
        with zipfile.ZipFile(fontes) as arquivo:
            arquivo.extractall(pacote)
        for atalho in pacote.glob("*.bat"):
            texto = atalho.read_text(encoding="ascii")
            atalho.write_bytes(texto.replace("\n", "\r\n").encode("ascii"))

        programa = pacote / "programa" if (pacote / "programa" / "requirements.txt").is_file() else pacote
        copiar_python(pacote / "_python", programa / "requirements.txt")
        versoes = verificar_pacote(pacote, programa)
        manifesto = {"plataforma": "Windows x64", "commit": commit, **versoes}
        (pacote / "VERSOES_PORTATIL.json").write_text(
            json.dumps(manifesto, indent=2, sort_keys=True) + "\n", encoding="utf-8",
        )
        (pacote / "LEIA_PRIMEIRO.txt").write_text(
            "Extraia todo o ZIP para uma pasta gravável.\n"
            "Mantenha a pasta _python junto aos atalhos e abra GERAR_RELATORIO_HTML.bat.\n"
            "O programa funciona sem instalar Python e sem internet.\n"
            "Selecione separadamente o deck e os Parquets do estudo.\n",
            encoding="utf-8-sig",
        )

        zip_temporario = pasta / saida.name
        with zipfile.ZipFile(zip_temporario, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as arquivo:
            for caminho in sorted(pacote.rglob("*")):
                if caminho.is_file() and "__pycache__" not in caminho.parts and caminho.suffix != ".pyc":
                    arquivo.write(caminho, caminho.relative_to(pasta))
        with zip_temporario.open("rb") as arquivo:
            sha256 = calcular_sha256(arquivo)
        zip_temporario.rename(saida)
        checksum.write_text(f"{sha256}  {saida.name}\n", encoding="ascii")
    return saida


def calcular_sha256(arquivo) -> str:
    digest = hashlib.sha256()
    for bloco in iter(lambda: arquivo.read(1024 * 1024), b""):
        digest.update(bloco)
    return digest.hexdigest()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destino", type=Path, required=True, help="Pasta de saída do ZIP e do SHA-256")
    parser.add_argument("--ref", default="HEAD", help="Commit ou tag a empacotar (padrão: HEAD)")
    argumentos = parser.parse_args()
    print(preparar(argumentos.destino, argumentos.ref))
