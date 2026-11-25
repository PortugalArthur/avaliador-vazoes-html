"""Ponto de entrada comum para os atalhos Windows."""

import os
from pathlib import Path
import runpy
import sys

MODULOS = {
    "aplicacao.executar",
    "aplicacao.exportar_csv",
    "aplicacao.exportar_historico_csv",
    "geradores.consolidar_vazoes_incrementais_e_lags",
    "geradores.converter_qincr_newave",
}


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in MODULOS:
        raise SystemExit("Abra um dos cinco atalhos do Avaliador de Vazões.")

    programa = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(programa))
    from infraestrutura.preparar_ambiente import PYTHON_PORTATIL

    if PYTHON_PORTATIL:
        pasta_tcl = Path(sys.executable).parent / "tcl"
        for variavel, arquivo in (("TCL_LIBRARY", "init.tcl"), ("TK_LIBRARY", "tk.tcl")):
            biblioteca = next(pasta_tcl.glob(f"*/{arquivo}"), None)
            if biblioteca is None:
                raise SystemExit("A pasta _python está incompleta. Extraia novamente todo o ZIP portátil.")
            os.environ[variavel] = str(biblioteca.parent)

    modulo = sys.argv.pop(1)
    if sys.argv[1:] == ["--verificar-ambiente"]:
        import importlib
        import tkinter

        janela = tkinter.Tk()
        janela.withdraw()
        janela.destroy()
        importlib.import_module(modulo)
        print(f"{modulo}: Python {sys.version.split()[0]} e Tcl/Tk disponíveis")
        return

    runpy.run_module(modulo, run_name="__main__", alter_sys=True)


if __name__ == "__main__":
    main()
