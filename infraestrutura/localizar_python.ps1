# Return only the full path of a usable interpreter to the batch launcher.
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$candidatos = @(
    Join-Path $PWD.Path '.venv\Scripts\python.exe'
    foreach ($nome in 'python.exe', 'python3.exe') {
        Get-Command $nome -All -CommandType Application -ErrorAction SilentlyContinue |
            Where-Object { $_.Source -notlike '*\Microsoft\WindowsApps\*' } |
            Select-Object -ExpandProperty Source
    }
    foreach ($launcher in (Get-Command py.exe -All -CommandType Application -ErrorAction SilentlyContinue)) {
        foreach ($linha in (& $launcher.Source -0p 2>$null)) {
            if ($linha -match '((?:[a-z]:\\|\\\\).+?\.exe)"?\s*$') {
                $Matches[1]
            }
        }
    }
    foreach ($raiz in 'HKCU:\Software\Python', 'HKLM:\Software\Python') {
        foreach ($origem in (Get-ChildItem -LiteralPath $raiz -ErrorAction SilentlyContinue)) {
            foreach ($versao in (Get-ChildItem -LiteralPath $origem.PSPath -ErrorAction SilentlyContinue)) {
                $instalacao = Get-Item -LiteralPath "$($versao.PSPath)\InstallPath" -ErrorAction SilentlyContinue
                if ($instalacao) {
                    $executavel = $instalacao.GetValue('ExecutablePath')
                    if ($executavel) {
                        $executavel
                    } elseif ($instalacao.GetValue('')) {
                        Join-Path $instalacao.GetValue('') 'python.exe'
                    }
                }
            }
        }
    }
)

foreach ($candidato in ($candidatos | Select-Object -Unique)) {
    if ($candidato -and (Test-Path -LiteralPath $candidato -PathType Leaf)) {
        try {
            $resultado = & $candidato -E -s -c "import struct, sys, tkinter; sys.exit(sys.version_info < (3, 10) or struct.calcsize('P') != 8)" 2>$null
            if ($LASTEXITCODE -eq 0) {
                Write-Output $candidato
                exit 0
            }
        } catch {
            continue
        }
    }
}
exit 1
