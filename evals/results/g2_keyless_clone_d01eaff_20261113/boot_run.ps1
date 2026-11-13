param([string]$Project,[string]$Tag,[switch]$NoCacheBuild)
$ErrorActionPreference="Continue"
$clone="C:\Users\Wook\AppData\Local\Temp\claude\9519414f725d5b3e\c618f6be-6202-4257-bc5c-31e5f539d45a\scratchpad\fix1113\a5_clone\proj3-c"
$out="C:\Users\Wook\AppData\Local\Temp\claude\9519414f725d5b3e\c618f6be-6202-4257-bc5c-31e5f539d45a\scratchpad\fix1113\a5_clone"
Set-Location $clone
if (Test-Path .env) { throw ".env exists" }
$env:API_PORT="18000"
$sw=[Diagnostics.Stopwatch]::StartNew()
$tl="$out\timeline_$Tag.txt"
"start $(Get-Date -Format o)" | Out-File $tl -Encoding utf8
if ($NoCacheBuild) {
  docker compose -p $Project build --no-cache *> "$out\log_${Tag}_build.txt"
  "build_done {0:N1}s" -f $sw.Elapsed.TotalSeconds | Add-Content $tl
}
docker compose -p $Project up -d *> "$out\log_${Tag}_up.txt"
"up_cmd_returned {0:N1}s" -f $sw.Elapsed.TotalSeconds | Add-Content $tl
$ok=$false
while ($sw.Elapsed.TotalSeconds -lt 900) {
  try { $r=Invoke-WebRequest -Uri "http://localhost:18000/health" -UseBasicParsing -TimeoutSec 2; if ($r.StatusCode -eq 200) { $ok=$true; break } } catch {}
  Start-Sleep -Seconds 1
}
"health_200 {0:N1}s ok={1}" -f $sw.Elapsed.TotalSeconds,$ok | Add-Content $tl
docker compose -p $Project ps -a *> "$out\log_${Tag}_ps.txt"
docker compose -p $Project logs loader *> "$out\log_${Tag}_loader.txt"
docker compose -p $Project logs api *> "$out\log_${Tag}_api.txt"
"logs_saved {0:N1}s" -f $sw.Elapsed.TotalSeconds | Add-Content $tl
