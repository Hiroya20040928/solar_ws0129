$ErrorActionPreference = 'Stop'

$DocsDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $DocsDir
$Pandoc = Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Packages\JohnMacFarlane.Pandoc_Microsoft.Winget.Source_8wekyb3d8bbwe\pandoc-3.10\pandoc.exe'
$Source = Join-Path $DocsDir 'bwsc2027_solarcar_master_guide.md'
$PdfOut = Join-Path $DocsDir 'bwsc2027_solarcar_master_guide.pdf'
$DocxOut = Join-Path $DocsDir 'bwsc2027_solarcar_master_guide.docx'
$PreviewDir = Join-Path $DocsDir 'pdf_check_master'

if (-not (Test-Path $Pandoc)) {
    throw "pandoc not found: $Pandoc"
}

Push-Location $DocsDir
try {
    python (Join-Path $DocsDir 'generate_bwsc2027_master_assets.py')

    & $Pandoc $Source `
        --standalone `
        --from markdown+tex_math_dollars+tex_math_single_backslash `
        --toc `
        --toc-depth=3 `
        --number-sections `
        --resource-path "$DocsDir;$RepoRoot" `
        --pdf-engine=xelatex `
        --pdf-engine-opt=-interaction=nonstopmode `
        -o $PdfOut

    & $Pandoc $Source `
        --standalone `
        --from markdown+tex_math_dollars+tex_math_single_backslash `
        --toc `
        --toc-depth=3 `
        --number-sections `
        --resource-path "$DocsDir;$RepoRoot" `
        -o $DocxOut

    $word = New-Object -ComObject Word.Application
    $word.Visible = $false
    try {
        $doc = $word.Documents.Open($DocxOut)
        foreach ($toc in @($doc.TablesOfContents)) {
            $toc.Update()
        }
        $doc.Fields.Update() | Out-Null
        $doc.Save()
        $doc.Close()
    } finally {
        $word.Quit()
    }

    python (Join-Path $DocsDir 'render_pdf_preview.py') `
        --pdf $PdfOut `
        --outdir $PreviewDir `
        --pages 1 4 8 12 16 20 24

    Write-Output "PDF : $PdfOut"
    Write-Output "DOCX: $DocxOut"
    Write-Output "Preview PNGs: $PreviewDir"
} finally {
    Pop-Location
}
