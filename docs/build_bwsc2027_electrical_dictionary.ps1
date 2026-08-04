$ErrorActionPreference = 'Stop'

$DocsDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $DocsDir
$Pandoc = Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Packages\JohnMacFarlane.Pandoc_Microsoft.Winget.Source_8wekyb3d8bbwe\pandoc-3.10\pandoc.exe'
$Source = Join-Path $DocsDir 'bwsc2027_electrical_dictionary_book.md'
$PdfOut = Join-Path $DocsDir 'bwsc2027_electrical_dictionary_book.pdf'
$DocxOut = Join-Path $DocsDir 'bwsc2027_electrical_dictionary_book.docx'
$PreviewDir = Join-Path $DocsDir 'pdf_check_electrical_dictionary'

if (-not (Test-Path $Pandoc)) {
    throw "pandoc not found: $Pandoc"
}

Push-Location $DocsDir
try {
    python (Join-Path $DocsDir 'generate_bwsc2027_electrical_dictionary_assets.py')
    python (Join-Path $DocsDir 'generate_bwsc2027_electrical_dictionary_markdown.py')

    & $Pandoc $Source `
        --standalone `
        --from markdown+tex_math_dollars+tex_math_single_backslash `
        --toc `
        --toc-depth=2 `
        --resource-path "$DocsDir;$RepoRoot" `
        --pdf-engine=xelatex `
        --pdf-engine-opt=-interaction=nonstopmode `
        -o $PdfOut
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $PdfOut)) {
        throw "pandoc PDF build failed"
    }

    & $Pandoc $Source `
        --standalone `
        --from markdown+tex_math_dollars+tex_math_single_backslash `
        --toc `
        --toc-depth=2 `
        --resource-path "$DocsDir;$RepoRoot" `
        -o $DocxOut
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $DocxOut)) {
        throw "pandoc DOCX build failed"
    }

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
        --pages 1 3 5 10 20 30 40 50 60 70 80 90

    Write-Output "PDF : $PdfOut"
    Write-Output "DOCX: $DocxOut"
    Write-Output "Preview PNGs: $PreviewDir"
} finally {
    Pop-Location
}
