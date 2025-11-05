<# 
  run_demo.ps1 — one-click launcher for the RAG demo

  What it does:
    1) Starts FastAPI backend (uvicorn) on port 7861
    2) Starts Streamlit UI on port 7862
    3) (Optional) Configures ngrok authtoken (if provided) and exposes the UI publicly
    4) Opens each piece in its own PowerShell window

  Usage examples:
    .\run_demo.ps1
    .\run_demo.ps1 -NgrokExe "C:\Tools\ngrok.exe" -NgrokToken "YOUR_REAL_TOKEN"

  Notes:
    - Keep all windows open while colleagues are testing.
    - The public URL appears in the ngrok window after a few seconds.
#>

param(
  # Paths and ports
  [string]$ProjectDir = "C:\Users\lan396\Dev\chat-with-report",
  [int]$BackendPort = 7861,
  [int]$UiPort = 7862,

  # Optional ngrok settings
  [string]$NgrokExe = "ngrok",     # or full path like "C:\Tools\ngrok.exe"
  [string]$NgrokToken = ""         # paste your real token here (NOT the 'cr_' one)
)

# --- helpers --------------------------------------------------------------

function Start-NewWindow {
  param(
    [Parameter(Mandatory=$true)][string]$Title,
    [Parameter(Mandatory=$true)][string]$Command
  )
  Start-Process -FilePath "powershell.exe" -ArgumentList @(
    "-NoExit",
    "-ExecutionPolicy","Bypass",
    "-Command", $Command
  ) -WindowStyle Normal
  Write-Host "Started: $Title"
}

function Ensure-Project {
  param([string]$Dir)
  if (-not (Test-Path $Dir)) { throw "ProjectDir not found: $Dir" }
}

# --- go -------------------------------------------------------------------

$ErrorActionPreference = "Stop"
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force

Ensure-Project -Dir $ProjectDir

# Check venv
$venvActivate = Join-Path $ProjectDir ".venv\Scripts\Activate.ps1"
if (-not (Test-Path $venvActivate)) {
  throw "Virtual env not found at $venvActivate. Create it first (python -m venv .venv) and install deps."
}

# Backend window (uvicorn)
$BackendCmd = @"
Set-Location '$ProjectDir';
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass;
& '$venvActivate';
uvicorn app:app --reload --port $BackendPort
"@
Start-NewWindow -Title "RAG Backend (Uvicorn $BackendPort)" -Command $BackendCmd

Start-Sleep -Seconds 2

# UI window (Streamlit)
# Tell UI where to find the backend via env var RAG_API_URL
$ApiUrl = "http://127.0.0.1:$BackendPort/ask"
$UiCmd = @"
Set-Location '$ProjectDir';
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass;
& '$venvActivate';
`$env:RAG_API_URL = '$ApiUrl';
streamlit run ui_streamlit.py --server.port $UiPort --server.address 0.0.0.0
"@
Start-NewWindow -Title "RAG UI (Streamlit $UiPort)" -Command $UiCmd

Start-Sleep -Seconds 2

# ngrok window (optional)
try {
  if ($NgrokToken -and $NgrokToken.Trim().Length -gt 10) {
    $NgrokCmd = @"
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass;
`"$NgrokExe`" config add-authtoken $NgrokToken;
`"$NgrokExe`" http $UiPort
"@
  } else {
    # no token provided; still try to run ngrok (might work if token already configured)
    $NgrokCmd = @"
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass;
`"$NgrokExe`" http $UiPort
"@
  }
  Start-NewWindow -Title "ngrok → UI $UiPort" -Command $NgrokCmd
  Write-Host "`nWhen ngrok starts, copy the public HTTPS link it prints (Forwarding → https://...).`n"
} catch {
  Write-Warning "ngrok could not be started automatically. Install it and/or set -NgrokExe and -NgrokToken, then run again."
}

Write-Host "All set. Keep these windows open while people test."
Write-Host "Local UI: http://localhost:$UiPort"
Write-Host "Backend:  http://localhost:$BackendPort/ask"
