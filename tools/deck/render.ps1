# Render a .pptx to PNG slides (and optionally PDF) through PowerPoint.
#   powershell -File tools/deck/render.ps1 -Pptx deck.pptx -OutDir out [-Pdf deck.pdf]
param([string]$Pptx, [string]$OutDir, [string]$Pdf = "")
$ErrorActionPreference = "Stop"
$pp = New-Object -ComObject PowerPoint.Application
try {
    $full = (Resolve-Path $Pptx).Path
    $pres = $pp.Presentations.Open($full, $true, $false, $false)   # read-only, no window
    New-Item -ItemType Directory -Force $OutDir | Out-Null
    $out = (Resolve-Path $OutDir).Path
    $i = 1
    foreach ($s in $pres.Slides) {
        $s.Export((Join-Path $out ("slide{0}.png" -f $i)), "PNG", 1600, 900)
        $i++
    }
    if ($Pdf) {
        $pdfFull = [System.IO.Path]::GetFullPath($Pdf)
        $pres.SaveAs($pdfFull, 32)   # ppSaveAsPDF
    }
    $pres.Close()
} finally {
    $pp.Quit()
}
