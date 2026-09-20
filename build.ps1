$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path $PSScriptRoot).Path
$workPath = Join-Path $projectRoot ".pyinstaller-work"
$distPath = Join-Path $projectRoot "dist"

& .\venv\Scripts\python.exe -m PyInstaller `
    --noconfirm --clean --windowed `
    --workpath $workPath --distpath $distPath `
    --icon .\assets\clock.ico --add-data ".\assets;assets" `
    --add-data ".\README.md;." --add-data ".\CHANGELOG.md;." `
    --add-data ".\LICENSE;." --add-data ".\THIRD_PARTY_NOTICES.md;." `
    --name TTask run_ttask.py
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller 构建失败，退出码：$LASTEXITCODE"
}

# Qt6Core 在 Windows 上应使用系统自带的 ICU 接口。某些开发环境会把
# PATH 中其他软件（例如 Poppler）附带的不兼容 ICU DLL 误收集进发布目录，
# 进而造成 QtCore 加载时报 WinError 127（找不到指定的程序）。
$bundledRuntimePath = Join-Path $distPath "TTask\_internal"
foreach ($foreignIcuName in @("icuuc.dll", "icudt78.dll")) {
    $foreignIcuPath = Join-Path $bundledRuntimePath $foreignIcuName
    if (Test-Path -LiteralPath $foreignIcuPath) {
        Remove-Item -LiteralPath $foreignIcuPath -Force
    }
}

# PyInstaller 的工作目录内也会出现一个不可独立运行的临时 EXE。
# 构建成功后删除工作目录，避免误把它当成发布程序启动。
if (Test-Path -LiteralPath $workPath) {
    $resolvedWorkPath = (Resolve-Path -LiteralPath $workPath).Path
    if ((Split-Path -Parent $resolvedWorkPath) -ne $projectRoot) {
        throw "拒绝清理项目目录以外的工作路径：$resolvedWorkPath"
    }
    Remove-Item -LiteralPath $resolvedWorkPath -Recurse -Force
}

Write-Host "构建完成，请只运行：dist\TTask\TTask.exe"
