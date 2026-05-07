$ErrorActionPreference = "Stop"

$EsHome = "D:\AI-App-Development\elastic\elasticsearch-9.4.0"
$EsBin = Join-Path $EsHome "bin\elasticsearch.bat"

if (!(Test-Path $EsBin)) {
    throw "Elasticsearch was not found at $EsBin"
}

Start-Process -FilePath $EsBin -WorkingDirectory $EsHome -WindowStyle Hidden

$deadline = (Get-Date).AddMinutes(3)
do {
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri "http://localhost:9200" -TimeoutSec 5
        $response.Content
        exit 0
    }
    catch {
        Start-Sleep -Seconds 5
    }
} while ((Get-Date) -lt $deadline)

throw "Elasticsearch did not respond on http://localhost:9200 within 3 minutes."
