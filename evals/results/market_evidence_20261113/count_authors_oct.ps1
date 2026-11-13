# Oct 2026 merged MRs in gitlab-com/content-sites/handbook: distinct authors, bot share. GET only.
$H = @{'User-Agent'='research-readonly-count'}
$out = Join-Path $PSScriptRoot 'raw_authors_oct2026.json'
$all = @(); $page = 1
while ($true) {
  Start-Sleep -Milliseconds 800
  $u = "https://gitlab.com/api/v4/projects/42817607/merge_requests?state=merged&merged_after=2026-10-01T00:00:00Z&merged_before=2026-11-01T00:00:00Z&per_page=100&page=$page"
  $arr = Invoke-RestMethod -Uri $u -Headers $H
  $all += $arr | % { [pscustomobject]@{ iid=$_.iid; author=$_.author.username; merged_at=$_.merged_at; title=$_.title } }
  if (@($arr).Count -lt 100) { break }
  $page++
}
$bots = $all | ? { $_.author -match 'bot|^gitlab-' -or $_.author -match 'project_\d+_bot' }
$res = [ordered]@{
  run_at_utc = (Get-Date).ToUniversalTime().ToString('o')
  merged_mrs = $all.Count
  distinct_authors = ($all | group author).Count
  bot_like_author_mrs = @($bots).Count
  bot_like_authors = (@($bots) | group author | % { "$($_.Name)=$($_.Count)" })
  top_authors = ($all | group author | sort Count -desc | select -First 10 | % { "$($_.Name)=$($_.Count)" })
  mrs_by_weekday_of_merge = ($all | group { ([datetime]$_.merged_at).DayOfWeek } | % { "$($_.Name)=$($_.Count)" })
}
$res | ConvertTo-Json -Depth 4 | Set-Content $out -Encoding UTF8
$res | ConvertTo-Json -Depth 4
