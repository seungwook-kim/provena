# GitLab public API counts (GET only, no auth). Run date recorded in output.
# Usage: pwsh -File count_gitlab.ps1
$ErrorActionPreference = 'Continue'
$out = Join-Path $PSScriptRoot 'raw_counts.json'
$H = @{'User-Agent'='research-readonly-count'}
$proj = 42817607   # gitlab-com/content-sites/handbook
$grp  = 6543       # gitlab-com group
$script:calls = 0
function Get-Resp($u) {
  Start-Sleep -Milliseconds 700   # rate limit: ~1.4 req/s, far below 500/min
  $script:calls++
  try { return Invoke-WebRequest -Uri $u -UseBasicParsing -Headers $H } catch { Write-Host "ERR $u $($_.Exception.Message)"; return $null }
}
function Total($u) { $r = Get-Resp $u; if ($r) { return [int](@($r.Headers['X-Total'])[0]) } else { return $null } }
function CountCommits($path, $since, $until) {
  $n = 0; $page = 1
  while ($true) {
    $u = "https://gitlab.com/api/v4/projects/$proj/repository/commits?path=$([uri]::EscapeDataString($path))&since=$since&until=$until&per_page=100&page=$page"
    $r = Get-Resp $u; if (-not $r) { return $null }
    $arr = $r.Content | ConvertFrom-Json
    $n += @($arr).Count
    if (@($arr).Count -lt 100) { break }
    $page++
  }
  return $n
}
# month windows: 2025-11 .. 2026-10 (12 full months) UTC
$months = @()
for ($i = 0; $i -lt 12; $i++) {
  $s = [datetime]::new(2025,11,1,0,0,0,[DateTimeKind]::Utc).AddMonths($i)
  $e = $s.AddMonths(1)
  $months += [pscustomobject]@{ label = $s.ToString('yyyy-MM'); s = $s.ToString('yyyy-MM-ddTHH:mm:ssZ'); e = $e.ToString('yyyy-MM-ddTHH:mm:ssZ'); weekdays = (0..([int]($e-$s).TotalDays-1) | ? { $d = $s.AddDays($_).DayOfWeek; $d -ne 'Saturday' -and $d -ne 'Sunday' }).Count }
}
$res = [ordered]@{ run_at_utc = (Get-Date).ToUniversalTime().ToString('o'); project = 'gitlab-com/content-sites/handbook (id 42817607)'; months = @() }
foreach ($m in $months) {
  $row = [ordered]@{ month = $m.label; weekdays = $m.weekdays }
  $row.merged_mrs = Total "https://gitlab.com/api/v4/projects/$proj/merge_requests?state=merged&merged_after=$($m.s)&merged_before=$($m.e)&per_page=1"
  $row.opened_mrs = Total "https://gitlab.com/api/v4/projects/$proj/merge_requests?state=all&created_after=$($m.s)&created_before=$($m.e)&per_page=1"
  $row.commits_security = CountCommits 'content/handbook/security' $m.s $m.e
  $row.commits_finance  = CountCommits 'content/handbook/finance' $m.s $m.e
  $row.commits_people_policies = CountCommits 'content/handbook/people-policies' $m.s $m.e
  $row.commits_legal = CountCommits 'content/handbook/legal' $m.s $m.e
  $row.commits_it_eta = (CountCommits 'content/handbook/it' $m.s $m.e) + (CountCommits 'content/handbook/eta' $m.s $m.e)
  $row.group_public_issues_title_access_request = Total "https://gitlab.com/api/v4/groups/$grp/issues?search=access%20request&in=title&state=all&created_after=$($m.s)&created_before=$($m.e)&per_page=1"
  $res.months += [pscustomobject]$row
  Write-Host ($row | ConvertTo-Json -Compress)
}
# Access-requests tracker visibility
$vis = @{}
foreach ($u in @('https://gitlab.com/api/v4/projects/gitlab-com%2Fteam-member-epics%2Faccess-requests','https://gitlab.com/gitlab-com/team-member-epics/access-requests/-/issues')) {
  Start-Sleep -Milliseconds 700
  try { $r = Invoke-WebRequest -Uri $u -UseBasicParsing -Headers $H; $vis[$u] = [int]$r.StatusCode } catch { $vis[$u] = [int]$_.Exception.Response.StatusCode }
}
$res.access_requests_tracker_http_status = $vis
$res.total_http_calls = $script:calls
$res | ConvertTo-Json -Depth 6 | Set-Content -Path $out -Encoding UTF8
Write-Host "saved $out"
