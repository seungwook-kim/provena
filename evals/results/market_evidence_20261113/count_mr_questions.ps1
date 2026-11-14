$ErrorActionPreference='Continue'
$H=@{'User-Agent'='Mozilla/5.0 research-readonly-count'}; $p='https://gitlab.com/api/v4/projects/42817607'; $w='https://gitlab.com/gitlab-com/content-sites/handbook/-/merge_requests'
$s='2026-10-01T00:00:00Z'; $e='2026-11-01T00:00:00Z'
$script:calls=0;$script:errs=0
function W($u,$ms){ Start-Sleep -Milliseconds $ms; $script:calls++; try{ Invoke-WebRequest $u -Headers $H -UseBasicParsing -TimeoutSec 60 }catch{ Write-Host "ERR $u $($_.Exception.Message)"; $script:errs++; $null } }
$mrs=@();$pg=1
while($true){ $r=W "$p/merge_requests?state=merged&merged_after=$s&merged_before=$e&per_page=100&page=$pg" 700; $a=@($r.Content|ConvertFrom-Json|%{$_}); $mrs+=$a; if($a.Count -lt 100){break}; $pg++ }
$polre='^content/handbook/(security|finance|people-policies|legal|it|eta|people-group|total-rewards|business-technology)/'
$rows=@()
foreach($m in $mrs){
  $hn=0;$q=0;$qa=@{};$failed=$false
  if($m.user_notes_count -gt 0){
    $cursor=$null
    do{ $u="$w/$($m.iid)/discussions.json?per_page=100"; if($cursor){$u+="&cursor=$([uri]::EscapeDataString($cursor))"}
      $r=W $u 1200; if(-not $r){$failed=$true;break}
      foreach($d in @($r.Content|ConvertFrom-Json|%{$_})){ foreach($n in $d.notes){ $un=$n.author.username; if(-not $n.system -and $un -notmatch 'bot|^project_|^group_|duo|gitlab-qa|danger|^ghost'){ $hn++; $body=($n.note -replace '(?s)```.*?```','' -replace 'https?://\S+',''); if($body -match '\?(\s|$)'){ $q++; $qa[$un]=1 } } } }
      $cursor=@($r.Headers['X-Next-Page-Cursor'])[0]
    }while($cursor)
  }
  $pol=$null
  if($q -gt 0){ $r=W "$p/merge_requests/$($m.iid)/diffs?per_page=100" 700; if($r){ $pol=[bool](@($r.Content|ConvertFrom-Json|%{$_.new_path}) | ?{ $_ -match $polre }) } }
  $rows+=[pscustomobject]@{iid=$m.iid;notes_api=$m.user_notes_count;human_notes=$hn;q_notes=$q;q_authors=$qa.Count;policy_path=$pol;failed=$failed}
}
$res=[ordered]@{run_at_utc=(Get-Date).ToUniversalTime().ToString('o');window="$s..$e";merged_mrs=$mrs.Count;mrs_notes_gt0=@($rows|?{$_.notes_api -gt 0}).Count;mrs_fetch_failed=@($rows|?{$_.failed}).Count;mrs_with_human_notes=@($rows|?{$_.human_notes -gt 0}).Count;human_notes=($rows|measure human_notes -Sum).Sum;question_notes=($rows|measure q_notes -Sum).Sum;mrs_with_question=@($rows|?{$_.q_notes -gt 0}).Count;question_notes_policy_path=($rows|?{$_.policy_path}|measure q_notes -Sum).Sum;mrs_with_question_policy_path=@($rows|?{$_.policy_path}).Count;calls=$script:calls;errs=$script:errs}
$res|ConvertTo-Json
$rows|ConvertTo-Json -Compress|Set-Content (Join-Path $PSScriptRoot 'mr_question_rows.json') -Encoding UTF8
