<#
sync_task.ps1 — 증분 수집(handbook-sync)을 Windows 작업 스케줄러에서 운영 DB로 한 번 돌리는 감싸개.

저장소 사본 안내: 팀장 PC 작업 스케줄러 작업 `provena-handbook-sync`(매일 02:14 KST, `-Trigger schedule`)가 실행하는
원본(<사용자 폴더>\provena_sync\sync_task.ps1, 2026-11-16 01:49 KST 수정본)에서 GCP 프로젝트 id, Secret Manager 이름,
알림 받는 주소, 개인 경로를 환경 변수로 바꾼 사본이다. 동작(준비 확인, 비밀값 처리, 동기화 호출, 실패·보류 메일)은 원본과 같다.
필요한 환경 변수(값은 저장소에 두지 않는다):
    PROVENA_GCP_PROJECT            GCP 프로젝트 id(필수)
    PROVENA_DB_SECRET_NAME         DATABASE_URL을 담은 Secret Manager 이름(필수)
    PROVENA_VOYAGE_SECRET_NAME     VOYAGE_API_KEY를 담은 Secret Manager 이름(필수)
    PROVENA_VOYAGE_SECRET_VERSION  그 판(없으면 latest)
    PROVENA_GMAIL_SECRET_NAME      Gmail 앱 비밀번호를 담은 Secret Manager 이름(없으면 실패 메일을 보내지 못하고 로그에만 남김)
    PROVENA_SYNC_ALERT_TO          실패 알림 받는 주소(없으면 운영 서비스의 GMAIL_SMTP_USER)
    PROVENA_REPO                   저장소 경로(없으면 이 파일 기준 두 단계 위)
    PROVENA_GCP_REGION, PROVENA_RUN_SERVICE  운영 Cloud Run 지역·서비스 이름(없으면 asia-northeast3, provena-api)
작업 스케줄러 등록 예(값은 자리 표시):
    powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File "<저장소>\scripts\ops\sync_task.ps1" -Trigger schedule
    트리거: 매일 02:14(현지 시각), 작업 폴더: 이 파일이 있는 폴더

- 진입점은 workflow(.github/workflows/handbook-sync.yml)와 같은 `python -m backend.rag.ingest.schedule --once`.
- 비밀값은 디스크에 두지 않는다. 실행할 때 GCP Secret Manager에서 `gcloud secrets versions access`로 받아
  이 프로세스 환경 변수(또는 자식 프로세스 환경)에만 두고, 끝나면 지운다. 값은 화면·로그·파일 어디에도 쓰지 않는다
  (파이썬 출력도 비밀값과 접속 주소 조각을 가린 뒤 로그에 쓴다).
- 이 작업이 쓰는 값(schedule.py, embed.py, workflow 대조):
    DATABASE_URL    <- Secret Manager $env:PROVENA_DB_SECRET_NAME (latest) = Supabase session pooler(포트 5432).
                       직접 연결 호스트는 이 PC에서 이름 풀이가 안 되어 session mode를 쓴다(transaction pooler 아님).
    VOYAGE_API_KEY  <- Secret Manager $env:PROVENA_VOYAGE_SECRET_NAME (판 $env:PROVENA_VOYAGE_SECRET_VERSION, 운영 Cloud Run과 같은 판). 새 글이 있는 날 임베딩에 쓴다
    EMBED_MODEL     <- 운영 Cloud Run(provena-api) 환경 변수(비밀 아님). 없으면 코드 기본값 voyage-4. 색인 장부와 다르면 schedule.py가 index_mismatch로 실패
  핸드북 원천은 공개 GitLab 저장소(git fetch, 토큰 없음), 캐시는 ~/.cache/provena/handbook.
  LLM·Langfuse·SERVICE_API_KEY·RECALL_WEBHOOK_SECRET은 쓰지 않는다(수집은 changed_articles 표에 pending으로 쌓기만 하고 리콜 처리는 API 쪽).
- 실패 알림(메일, Gmail SMTP): 동기화 종료 코드가 0이 아니거나, 준비 실패, 시간 초과면 메일 한 통을 보낸다.
    발송 설정은 backend/services/email_sender.py(GmailSMTPEmailSender)와 같다: smtp.gmail.com:587, STARTTLS, 앱 비밀번호 로그인.
    앱 비밀번호   <- Secret Manager $env:PROVENA_GMAIL_SECRET_NAME (latest), 보낼 때만 받는다
    로그인 계정   <- 운영 Cloud Run 환경 변수 GMAIL_SMTP_USER(비밀 아님), 보내는 주소 <- EMAIL_FROM(없으면 GMAIL_SMTP_USER)
    받는 주소     <- -AlertTo(기본 $env:PROVENA_SYNC_ALERT_TO), 없으면 GMAIL_SMTP_USER
    값은 메일을 보내는 자식 파이썬 프로세스의 환경에만 넣고(이 프로세스 환경에는 넣지 않음) 끝나면 버린다.
    로그에는 받는 주소도 가려서(첫 글자***@도메인) 쓴다.
- trigger: 작업 스케줄러 등록은 -Trigger schedule 로 부른다 → 슬롯 = 그날 UTC 날짜, sync_runs.trigger = schedule.
  손으로 돌릴 때 기본값은 manual → --slot manual-<UTC 시각> 이라 그날 정시 슬롯을 차지하지 않는다.
- -DryRun: 동기화도 메일도 보내지 않는다. 로컬 도구, gcloud 로그인, 비밀값 "이름"의 존재(gcloud secrets describe, 값은 받지 않음),
  운영 Cloud Run의 비밀 연결 이름과 EMBED_MODEL·메일 설정, 파이썬 모듈 import만 확인한다.
- -TestAlert: 동기화는 부르지 않고 시험 메일 한 통만 보낸다(실제 Gmail로 나간다).

종료 코드: 0 성공(noop·중복 슬롯 포함, TestAlert 발송 성공), 1 동기화 실패(schedule.py), 2 준비 실패(비밀값·도구, TestAlert 발송 실패), 124 시간 초과.
PowerShell 5.1 / 7 겸용. UTF-8(BOM)으로 저장.
#>
[CmdletBinding()]
param(
    [ValidateSet('schedule', 'manual')][string]$Trigger = 'manual',
    [switch]$DryRun,
    [switch]$TestAlert,
    [string]$Repo = $env:PROVENA_REPO,
    [string]$LogDir = (Join-Path $env:USERPROFILE 'provena_sync_logs'),
    [string]$TaskName = 'provena-handbook-sync',
    [string]$Project = $env:PROVENA_GCP_PROJECT,
    [string]$Region = $(if ($env:PROVENA_GCP_REGION) { $env:PROVENA_GCP_REGION } else { 'asia-northeast3' }),
    [string]$Service = $(if ($env:PROVENA_RUN_SERVICE) { $env:PROVENA_RUN_SERVICE } else { 'provena-api' }),
    [string]$DbSecret = $env:PROVENA_DB_SECRET_NAME,
    [string]$DbSecretVersion = 'latest',
    [string]$VoyageSecret = $env:PROVENA_VOYAGE_SECRET_NAME,
    [string]$VoyageSecretVersion = $(if ($env:PROVENA_VOYAGE_SECRET_VERSION) { $env:PROVENA_VOYAGE_SECRET_VERSION } else { 'latest' }),
    [string]$GmailSecret = $env:PROVENA_GMAIL_SECRET_NAME,
    [string]$AlertTo = $env:PROVENA_SYNC_ALERT_TO,
    [string]$AlertFrom = '',
    [int]$TimeoutMinutes = 30
)

$ErrorActionPreference = 'Stop'
if (-not $Repo) { $Repo = [IO.Path]::GetFullPath((Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) '..\..')) }   # 저장소 사본 기본값: scripts\ops 두 단계 위
try { [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12 } catch { }

$script:Redact = New-Object System.Collections.Generic.List[string]
$script:SecretEnv = @('DATABASE_URL', 'VOYAGE_API_KEY')
$script:RunCfg = $null
$script:Gcloud = ''
$utf8 = New-Object System.Text.UTF8Encoding($false)
$started = Get-Date
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$LogPath = Join-Path $LogDir ('sync_{0}.log' -f $started.ToString('yyyyMMdd_HHmmss'))

# 메일을 보내는 자식 파이썬(-I, 표준 라이브러리만). 설정은 환경 변수로만 받는다. 비밀번호·응답 내용은 찍지 않는다.
# PROVENA_ALERT_SMTP_HOST/PORT는 오프라인 시험 전용(루프백 주소만 허용, 평문 SMTP, STARTTLS 생략).
$script:MailPy = @'
import os, smtplib, ssl, sys
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
e = os.environ
user = e.get("PROVENA_ALERT_USER", "").strip()
pw = e.get("PROVENA_ALERT_PASS", "")
sender = e.get("PROVENA_ALERT_FROM", "").strip() or user
to = e.get("PROVENA_ALERT_TO", "").strip()
if not (user and pw and sender and to):
    print("mail not sent: missing settings")
    sys.exit(3)
msg = EmailMessage()
msg["From"] = sender
msg["To"] = to
msg["Subject"] = e.get("PROVENA_ALERT_SUBJECT", "[provena] alert")
msg["Date"] = formatdate(localtime=True)
msg["Message-ID"] = make_msgid(domain="provena.local")
msg.set_content(e.get("PROVENA_ALERT_BODY", ""))
test_host = e.get("PROVENA_ALERT_SMTP_HOST", "").strip()
if test_host and test_host not in ("127.0.0.1", "localhost", "::1"):
    print("mail not sent: test SMTP host must be loopback")
    sys.exit(3)
host = test_host or "smtp.gmail.com"
port = int(e.get("PROVENA_ALERT_SMTP_PORT", "25") or 25) if test_host else 587
try:
    with smtplib.SMTP(host, port, timeout=10) as smtp:
        smtp.ehlo()
        if not test_host:
            smtp.starttls(context=ssl.create_default_context())
            smtp.ehlo()
        smtp.login(user, pw)
        smtp.send_message(msg)
except Exception as ex:
    code = getattr(ex, "smtp_code", "")
    print(("mail not sent: %s %s" % (type(ex).__name__, code)).strip())
    sys.exit(1)
print("mail sent" + (" (test SMTP %s:%d)" % (host, port) if test_host else ""))
'@

function Protect-Text([string]$Text) {
    if ([string]::IsNullOrEmpty($Text)) { return $Text }
    $out = $Text
    foreach ($s in ($script:Redact | Sort-Object Length -Descending)) {
        if ($s.Length -ge 4) { $out = $out.Replace($s, '[가림]') }
    }
    return $out
}

function Write-Log([string]$Message) {
    $line = '{0} {1}' -f (Get-Date).ToString('yyyy-MM-dd HH:mm:ss'), (Protect-Text $Message)
    [System.IO.File]::AppendAllText($LogPath, $line + [Environment]::NewLine, $utf8)
    Write-Host $line
}

function Add-Redaction([string]$Value) {
    if ([string]::IsNullOrEmpty($Value)) { return }
    $script:Redact.Add($Value)
    # 접속 주소면 사용자·비밀번호·호스트와 그 긴 조각(프로젝트 식별자)도 가린다
    $m = [regex]::Match($Value, '^[A-Za-z0-9+.-]+://(?<user>[^:@/]+)(:(?<pw>[^@]*))?@(?<host>[^:/?]+)')
    if ($m.Success) {
        foreach ($k in 'user', 'pw', 'host') {
            $v = $m.Groups[$k].Value
            if ($v) {
                $script:Redact.Add($v)
                try { $script:Redact.Add([Uri]::UnescapeDataString($v)) } catch { }
                foreach ($seg in ($v -split '[.:]')) { if ($seg.Length -ge 10) { $script:Redact.Add($seg) } }
            }
        }
    }
}

function Format-MaskedEmail([string]$Addr) {
    $m = [regex]::Match([string]$Addr, '(?<l>[^\s<>@"]+)@(?<d>[^\s<>"]+)')
    if (-not $m.Success) { return '[가림]' }
    return '{0}***@{1}' -f $m.Groups['l'].Value.Substring(0, 1), $m.Groups['d'].Value
}

function Format-Times([datetime]$When) {
    $utc = $When.ToUniversalTime()
    try { $kst = [TimeZoneInfo]::ConvertTimeFromUtc($utc, [TimeZoneInfo]::FindSystemTimeZoneById('Korea Standard Time')) }
    catch { $kst = $utc.AddHours(9) }
    return '{0} KST (UTC {1})' -f $kst.ToString('yyyy-MM-dd HH:mm:ss'), $utc.ToString('yyyy-MM-dd HH:mm:ss')
}

function Invoke-Captured {
    param([string]$FilePath, [string]$Arguments, [string]$WorkDir = '', [int]$TimeoutSec = 120, [string]$StdIn = $null, [hashtable]$ExtraEnv = @{})
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $FilePath
    $psi.Arguments = $Arguments
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.RedirectStandardInput = ($null -ne $StdIn)
    $psi.StandardOutputEncoding = $utf8
    $psi.StandardErrorEncoding = $utf8
    if ($WorkDir) { $psi.WorkingDirectory = $WorkDir }
    foreach ($k in @($ExtraEnv.Keys)) { $psi.EnvironmentVariables[$k] = [string]$ExtraEnv[$k] }   # 자식 프로세스에만
    $p = [System.Diagnostics.Process]::Start($psi)
    $o = $p.StandardOutput.ReadToEndAsync()
    $e = $p.StandardError.ReadToEndAsync()
    if ($null -ne $StdIn) { $p.StandardInput.Write($StdIn); $p.StandardInput.Close() }
    $timedOut = $false
    if (-not $p.WaitForExit($TimeoutSec * 1000)) {
        $timedOut = $true
        try { Start-Process -FilePath "$env:SystemRoot\System32\taskkill.exe" -ArgumentList '/PID', $p.Id, '/T', '/F' -WindowStyle Hidden -Wait } catch { }
    }
    $p.WaitForExit()
    $code = if ($timedOut) { 124 } else { $p.ExitCode }
    return [pscustomobject]@{ Code = $code; Out = $o.Result; Err = $e.Result; TimedOut = $timedOut }
}

function Invoke-Gcloud([string]$Arguments, [int]$TimeoutSec = 120) {
    # gcloud.cmd는 cmd.exe로 부른다(경로에 공백). 출력은 받기만 하고 여기서 찍지 않는다.
    return Invoke-Captured -FilePath $env:ComSpec -Arguments ('/d /s /c ""{0}" {1}"' -f $script:Gcloud, $Arguments) -TimeoutSec $TimeoutSec
}

function Get-Secret([string]$Name, [string]$Version) {
    $r = Invoke-Gcloud ('secrets versions access {0} --secret={1} --project={2}' -f $Version, $Name, $Project)
    $v = if ($r.Out) { $r.Out.TrimEnd("`r", "`n") } else { '' }
    if ($r.Code -ne 0 -or -not $v) {
        $why = if ($r.Err) { ($r.Err.Trim() -split "`n")[-1] } else { '' }
        throw ('비밀값 {0}({1})을 받지 못함: 종료 코드 {2} {3}' -f $Name, $Version, $r.Code, $why)
    }
    Add-Redaction $v
    return $v
}

function Test-SecretName([string]$Name, [string]$Version) {
    $r = Invoke-Gcloud ('secrets describe {0} --project={1} --format="value(name)"' -f $Name, $Project)
    if ($r.Code -ne 0 -or -not $r.Out.Trim()) { Write-Log ("  [없음] 비밀 이름 {0}" -f $Name); return $false }
    if ($Version -ne 'latest') {
        $s = Invoke-Gcloud ('secrets versions describe {0} --secret={1} --project={2} --format="value(state)"' -f $Version, $Name, $Project)
        $state = if ($s.Out) { $s.Out.Trim() } else { '' }
        if ($s.Code -ne 0 -or $state -ne 'ENABLED') { Write-Log ("  [문제] {0} 판 {1} 상태 '{2}'" -f $Name, $Version, $state); return $false }
        Write-Log ("  [있음] {0} (판 {1} ENABLED)" -f $Name, $Version)
    }
    else { Write-Log ("  [있음] {0} (latest)" -f $Name) }
    return $true
}

function Get-RunConfig {
    # 운영 Cloud Run의 비밀 아닌 환경 변수(EMBED_MODEL, GMAIL_SMTP_USER, EMAIL_FROM)와 비밀 연결 이름만 읽는다. 값이 비밀인 항목은 이름만.
    $r = Invoke-Gcloud ('run services describe {0} --project={1} --region={2} --format=json' -f $Service, $Project, $Region) 180
    if ($r.Code -ne 0 -or -not $r.Out) { return $null }
    $j = $r.Out | ConvertFrom-Json
    $plain = @{}; $refs = @{}
    foreach ($c in @($j.spec.template.spec.containers)) {
        foreach ($ev in @($c.env)) {
            if ($null -eq $ev) { continue }
            $names = @($ev.PSObject.Properties.Name)
            if ($names -contains 'valueFrom' -and $ev.valueFrom -and (@($ev.valueFrom.PSObject.Properties.Name) -contains 'secretKeyRef')) {
                $refs[$ev.name] = '{0}:{1}' -f $ev.valueFrom.secretKeyRef.name, $ev.valueFrom.secretKeyRef.key
            }
            elseif ($names -contains 'value') { $plain[$ev.name] = [string]$ev.value }
        }
    }
    return [pscustomobject]@{ Plain = $plain; Refs = $refs }
}

function Get-MailConfig {
    # 로그인 계정·보내는 주소는 운영 Cloud Run의 비밀 아닌 값, 받는 주소는 -AlertTo 또는 로그인 계정. 주소는 로그에서 가린다.
    if ($null -eq $script:RunCfg -and $script:Gcloud) { try { $script:RunCfg = Get-RunConfig } catch { $script:RunCfg = $null } }
    $user = ''; $from = ''
    if ($script:RunCfg) {
        if ($script:RunCfg.Plain.ContainsKey('GMAIL_SMTP_USER')) { $user = ([string]$script:RunCfg.Plain['GMAIL_SMTP_USER']).Trim() }
        if ($script:RunCfg.Plain.ContainsKey('EMAIL_FROM')) { $from = ([string]$script:RunCfg.Plain['EMAIL_FROM']).Trim() }
    }
    if (-not $from) { $from = $user }
    if ($AlertFrom) { $user = $AlertFrom.Trim(); $from = $user }   # 알림 전용 발송 계정(앱 비밀번호는 -GmailSecret)
    $to =if ($AlertTo) { $AlertTo.Trim() } else { $user }
    foreach ($v in @($user, $from, $to)) { if ($v -and $v.Length -ge 4) { $script:Redact.Add($v) } }
    return [pscustomobject]@{ User = $user; From = $from; To = $to }
}

function New-AlertBody([datetime]$End, [int]$ExitCode, [string]$Kind, [string]$Detail) {
    $tail = @()
    if (Test-Path -LiteralPath $LogPath) { $tail = @(Get-Content -LiteralPath $LogPath -Tail 30 -Encoding UTF8) }
    $lines = New-Object System.Collections.Generic.List[string]
    $lines.Add(('작업: {0} (trigger={1})' -f $TaskName, $Trigger))
    $lines.Add('컴퓨터: {0}' -f $env:COMPUTERNAME)
    $lines.Add('시작: {0}' -f (Format-Times $started))
    $lines.Add('끝: {0}' -f (Format-Times $End))
    $lines.Add('종료 코드: {0}' -f $ExitCode)
    $lines.Add('오류 종류: {0}' -f $Kind)
    if ($Detail) { $lines.Add('오류 내용: {0}' -f $Detail) }
    $lines.Add('로그 파일: {0}' -f $LogPath)
    $lines.Add('')
    $lines.Add('--- 로그 마지막 {0}줄(비밀값 가림) ---' -f $tail.Count)
    foreach ($l in $tail) {
        $t = Protect-Text $l
        if ($t.Length -gt 400) { $t = $t.Substring(0, 400) + ' …' }
        $lines.Add($t)
    }
    $body = Protect-Text ($lines -join "`n")
    if ($body.Length -gt 24000) { $body = $body.Substring(0, 24000) + "`n…(잘림)" }
    return $body
}

function Send-AlertMail([string]$Subject, [string]$Body, [string]$Label) {
    # 앱 비밀번호는 보낼 때만 받고, 자식 파이썬의 환경에만 넣는다. 이 프로세스 환경 변수에는 넣지 않는다.
    $mailEnv = $null; $pw = $null
    try {
        if (-not $script:Gcloud) { throw 'gcloud 없음' }
        if (-not $GmailSecret) { throw 'PROVENA_GMAIL_SECRET_NAME 없음' }
        if (-not (Test-Path -LiteralPath $python)) { throw ('파이썬 없음: ' + $python) }
        $mc = Get-MailConfig
        if (-not $mc.User) { throw ('운영 서비스 {0}에서 GMAIL_SMTP_USER를 읽지 못함' -f $Service) }
        if (-not $mc.To) { throw '받는 주소 없음' }
        $pw = Get-Secret $GmailSecret 'latest'
        $mailEnv = @{
            PROVENA_ALERT_USER = $mc.User; PROVENA_ALERT_PASS = $pw; PROVENA_ALERT_FROM = $mc.From; PROVENA_ALERT_TO = $mc.To
            PROVENA_ALERT_SUBJECT = $Subject; PROVENA_ALERT_BODY = $Body
        }
        $r = Invoke-Captured -FilePath $python -Arguments '-I -' -TimeoutSec 60 -StdIn $script:MailPy -ExtraEnv $mailEnv
        $last = (($r.Out + "`n" + $r.Err).Trim() -split "`r?`n")[-1]
        if ($r.Code -eq 0) { Write-Log ('{0} 보냄: 메일({1}) {2}' -f $Label, (Format-MaskedEmail $mc.To), $last); return $true }
        Write-Log ('{0} 메일 전송 실패: 종료 코드 {1} {2}' -f $Label, $r.Code, $last)
        return $false
    }
    catch { Write-Log ('{0} 메일 전송 실패: {1}' -f $Label, $_.Exception.Message); return $false }
    finally { $pw = $null; if ($mailEnv) { $mailEnv.Clear() }; $mailEnv = $null }
}

function Clear-Secrets {
    foreach ($n in $script:SecretEnv) { Remove-Item "Env:$n" -ErrorAction SilentlyContinue }
}

# ───────────────────────── 본 실행 ─────────────────────────
$code = 2
$syncRan = $false
$summary = $null
$prepError = ''
$failLine = ''
$syncTimedOut = $false
$python = Join-Path $Repo '.venv\Scripts\python.exe'
$utcNow = $started.ToUniversalTime()
$mode = if ($DryRun) { 'DryRun' } elseif ($TestAlert) { 'TestAlert' } else { '실행' }
try {
    Write-Log ('시작 {0} (UTC {1}) 모드={2} trigger={3} 컴퓨터={4} PS={5}' -f $started.ToString('yyyy-MM-dd HH:mm:ss zzz'),
        $utcNow.ToString('yyyy-MM-dd HH:mm:ss'), $mode, $Trigger, $env:COMPUTERNAME, $PSVersionTable.PSVersion)
    Write-Log ('로그 {0}' -f $LogPath)

    # 1. 로컬 준비
    $ok = $true
    $gc = Get-Command gcloud.cmd -ErrorAction SilentlyContinue
    $script:Gcloud = if ($gc) { $gc.Source } else { '' }
    $git = Get-Command git -ErrorAction SilentlyContinue
    $cache = if ($env:HANDBOOK_CACHE) { $env:HANDBOOK_CACHE } else { Join-Path $env:USERPROFILE '.cache\provena\handbook' }
    $checks = [ordered]@{
        ('저장소 ' + $Repo)              = (Test-Path -LiteralPath (Join-Path $Repo 'backend\rag\ingest\schedule.py'))
        ('파이썬 ' + $python)            = (Test-Path -LiteralPath $python)
        'git'                             = [bool]$git
        'gcloud'                          = [bool]$script:Gcloud
    }
    foreach ($k in $checks.Keys) { Write-Log ('  [{0}] {1}' -f $(if ($checks[$k]) { '있음' } else { '없음' }), $k); if (-not $checks[$k]) { $ok = $false } }
    Write-Log ('  [{0}] 핸드북 캐시 {1}' -f $(if (Test-Path -LiteralPath (Join-Path $cache '.git')) { '있음' } else { '없음(첫 실행에서 새로 받음)' }), $cache)
    if (-not $ok) { throw '로컬 준비 실패(위 [없음] 항목)' }
    $missing = @(@{ PROVENA_GCP_PROJECT = $Project; PROVENA_DB_SECRET_NAME = $DbSecret; PROVENA_VOYAGE_SECRET_NAME = $VoyageSecret }.GetEnumerator() | Where-Object { -not $_.Value } | ForEach-Object { $_.Key })
    if ($missing.Count -gt 0) { throw ('설정 없음: ' + ($missing -join ', ') + ' (저장소 사본은 환경 변수로 받는다)') }
    $head = Invoke-Captured -FilePath $git.Source -Arguments 'rev-parse --short HEAD' -WorkDir $Repo
    $branch = Invoke-Captured -FilePath $git.Source -Arguments 'rev-parse --abbrev-ref HEAD' -WorkDir $Repo
    Write-Log ('저장소 커밋 {0} ({1})' -f $head.Out.Trim(), $branch.Out.Trim())

    $auth = Invoke-Gcloud 'auth list --filter=status:ACTIVE --format="value(account)"'
    if ($auth.Code -ne 0 -or -not $auth.Out.Trim()) { throw 'gcloud 로그인 계정 없음(gcloud auth login 필요)' }
    foreach ($a in ($auth.Out -split "`r?`n")) { if ($a.Trim().Length -ge 4) { $script:Redact.Add($a.Trim()) } }   # 계정 주소도 로그·메일에서 가린다
    Write-Log 'gcloud 활성 계정 있음'

    # 2. 운영 Cloud Run의 비밀 아닌 설정
    $script:RunCfg = Get-RunConfig
    $cfg = $script:RunCfg
    if ($null -eq $cfg) { Write-Log ('운영 서비스 설정을 읽지 못함({0}) — EMBED_MODEL은 코드 기본값(voyage-4), 색인 장부와 다르면 schedule.py가 실패로 막는다' -f $Service) }
    else {
        foreach ($n in 'DATABASE_URL', 'DATABASE_DIRECT_URL', 'VOYAGE_API_KEY', 'GMAIL_APP_PASSWORD') {
            if ($cfg.Refs.ContainsKey($n)) { Write-Log ('  운영 연결 {0} <- {1}' -f $n, $cfg.Refs[$n]) }
        }
        if ($cfg.Plain.ContainsKey('EMBED_MODEL') -and $cfg.Plain['EMBED_MODEL']) {
            $env:EMBED_MODEL = $cfg.Plain['EMBED_MODEL']
            Write-Log ('  EMBED_MODEL={0} (운영 서비스 값)' -f $env:EMBED_MODEL)
        }
        else { Remove-Item Env:EMBED_MODEL -ErrorAction SilentlyContinue; Write-Log '  EMBED_MODEL 운영 서비스에 없음 → 코드 기본값 voyage-4' }
    }

    if ($DryRun) {
        # 3D. 비밀값은 이름(과 고정 판 상태)만 확인한다. 값은 받지 않는다. 메일도 보내지 않는다.
        Write-Log '비밀 이름 확인(값은 받지 않음)'
        $okS = (Test-SecretName $DbSecret $DbSecretVersion)
        $okS = (Test-SecretName $VoyageSecret $VoyageSecretVersion) -and $okS
        $okS = (Test-SecretName $GmailSecret 'latest') -and $okS
        $mc = Get-MailConfig
        if ($mc.User -and $mc.To) {
            Write-Log ('실패 알림: 메일({0}) 보내는 주소 {1}, smtp.gmail.com:587 STARTTLS' -f (Format-MaskedEmail $mc.To), (Format-MaskedEmail $mc.From))
        }
        else { Write-Log ('  [문제] 운영 서비스 {0}에 GMAIL_SMTP_USER 없음 → 실패 알림 메일을 보낼 수 없음' -f $Service); $okS = $false }
        $imp = Invoke-Captured -FilePath $python -Arguments "-c ""import backend.rag.ingest.schedule, psycopg, pgvector.psycopg, smtplib, ssl; print('import ok')""" -WorkDir $Repo -TimeoutSec 180
        Write-Log ('파이썬 import: 종료 코드 {0} {1}' -f $imp.Code, (($imp.Out + $imp.Err).Trim() -split "`n")[-1])
        $code = if ($okS -and $imp.Code -eq 0) { 0 } else { 2 }
        Write-Log ('DryRun 결과: {0} (동기화와 메일은 부르지 않았다)' -f $(if ($code -eq 0) { '준비됨' } else { '문제 있음' }))
    }
    elseif ($TestAlert) {
        # 3T. 시험 메일 한 통. 동기화는 부르지 않는다.
        Write-Log '시험 메일: 동기화는 부르지 않는다'
        $subj = '[provena] 증분 수집 알림 시험 {0}' -f $started.ToString('yyyy-MM-dd')
        $body = New-AlertBody (Get-Date) 0 '시험(TestAlert, 실패 아님)' '실패 알림 메일 경로 확인용 시험 메일이다.'
        $code = if (Send-AlertMail $subj $body '시험 알림') { 0 } else { 2 }
    }
    else {
    # 3. 비밀값을 이 프로세스 환경 변수로만 받는다
    $env:DATABASE_URL = Get-Secret $DbSecret $DbSecretVersion
    $env:VOYAGE_API_KEY = Get-Secret $VoyageSecret $VoyageSecretVersion
    Write-Log ('비밀값 받음: DATABASE_URL<-{0}({1}), VOYAGE_API_KEY<-{2}({3}) (값은 기록하지 않음)' -f $DbSecret, $DbSecretVersion, $VoyageSecret, $VoyageSecretVersion)
    foreach ($n in 'GITHUB_EVENT_NAME', 'GITHUB_OUTPUT', 'LLM_RECORD', 'DEMO_MODE') { Remove-Item "Env:$n" -ErrorAction SilentlyContinue }
    $env:PYTHONIOENCODING = 'utf-8'
    $env:PYTHONUTF8 = '1'

    # 4. 동기화 한 번
    $pyArgs = '-m backend.rag.ingest.schedule --once'
    if ($Trigger -eq 'manual') { $pyArgs += (' --slot manual-{0}' -f $utcNow.ToString('yyyyMMddTHHmmss')) ; Write-Log '손 실행: 정시 슬롯을 쓰지 않는다(trigger=manual)' }
    else { Write-Log ('정시 실행: 슬롯 = UTC 날짜 {0} (trigger=schedule)' -f $utcNow.ToString('yyyy-MM-dd')) }
    Write-Log ('실행: python {0} (작업 폴더 저장소, 제한 {1}분)' -f $pyArgs, $TimeoutMinutes)
    $t0 = Get-Date
    $r = Invoke-Captured -FilePath $python -Arguments $pyArgs -WorkDir $Repo -TimeoutSec ($TimeoutMinutes * 60)
    $code = $r.Code
    $syncRan = $true
    $syncTimedOut = $r.TimedOut
    Write-Log ('--- 파이썬 출력(비밀 가림) ---')
    foreach ($ln in (($r.Out + "`n" + $r.Err) -split "`r?`n")) { if ($ln.Trim()) { Write-Log ('  ' + $ln) } }
    Write-Log ('--- 끝 (걸린 시간 {0:N1}초) ---' -f ((Get-Date) - $t0).TotalSeconds)
    if ($r.TimedOut) { Write-Log ('시간 초과({0}분)로 끊음 — sync_runs 행이 running으로 남을 수 있다' -f $TimeoutMinutes) }
    $fl = @((($r.Out + "`n" + $r.Err) -split "`r?`n") | Where-Object { $_ -match '실패: ' }) | Select-Object -Last 1
    if ($fl) { $failLine = Protect-Text $fl.Trim(); if ($failLine.Length -gt 300) { $failLine = $failLine.Substring(0, 300) } }

    $last = @(($r.Out -split "`r?`n") | Where-Object { $_.Trim().StartsWith('{') }) | Select-Object -Last 1
    if ($last) {
        try {
            $summary = $last | ConvertFrom-Json
            $props = @($summary.PSObject.Properties | ForEach-Object { '{0}={1}' -f $_.Name, ($(if ($_.Value -is [array]) { ($_.Value -join ',') } else { $_.Value })) })
            Write-Log ('sync_runs 요약: ' + ($props -join ' '))
        }
        catch { Write-Log 'sync_runs 요약: 마지막 JSON 줄을 읽지 못함' }
    }
    elseif ($code -eq 0) { Write-Log 'sync_runs 요약: 출력에 JSON 줄 없음' }
    elseif (($r.Out + $r.Err) -match '실패: ') { Write-Log 'sync_runs 요약: 실패(위 "실패:" 줄이 sync_runs.status=failed, error_kind/error_detail로 기록됨)' }
    else { Write-Log 'sync_runs 요약: 실패(슬롯을 차지하기 전에 끝나 sync_runs에 행이 없을 수 있다 — 접속·설정 오류)' }
    if ($summary -and $summary.PSObject.Properties.Name -contains 'reason' -and $summary.reason -eq 'paused') {
        Write-Log '주의: 변경 감시가 멈춰 있어(change_monitoring.status=paused) sync_runs에 행이 남지 않았다'
    }
    }
}
catch {
    if ($syncRan) { Write-Log ('기록 중 오류(동기화 종료 코드는 그대로): ' + $_.Exception.Message) }
    else { $prepError = $_.Exception.Message; Write-Log ('준비 실패: ' + $prepError); $code = 2 }
}
finally {
    Clear-Secrets
    $ended = Get-Date

    if (-not $DryRun -and -not $TestAlert) { try {
        $day = $started.ToString('yyyy-MM-dd')
        if ($code -ne 0) {
            if ($syncTimedOut -or $code -eq 124) { $kind = 'timeout(시간 초과 {0}분)' -f $TimeoutMinutes; $detail = $failLine }
            elseif ($syncRan) { $kind = 'sync_failed(동기화 실패, schedule.py 종료 코드 {0})' -f $code; $detail = $failLine }
            else { $kind = 'preparation(준비 실패, 동기화 전)'; $detail = $prepError }
            Write-Log ('실패 알림 메일을 보낸다: {0}' -f $kind)
            $body = New-AlertBody $ended $code $kind $detail
            [void](Send-AlertMail ('[provena] 증분 수집 정시 실행 실패 {0}' -f $day) $body '실패 알림')
        }
        elseif ($summary -and $summary.PSObject.Properties.Name -contains 'removed_held' -and [int]$summary.removed_held -gt 0) {
            $reasons = ''
            if ($summary.PSObject.Properties.Name -contains 'list_reasons') { $reasons = [regex]::Replace((@($summary.list_reasons) -join ', '), '[^\w:,. /-]', '') }
            if ($reasons.Length -gt 300) { $reasons = $reasons.Substring(0, 300) }
            $body = New-AlertBody $ended $code ('removed_held(삭제 보류 {0}쪽, 실패 아님)' -f $summary.removed_held) ('목록 불완전: {0} — 다음 실행에서 다시 확인' -f $reasons)
            [void](Send-AlertMail ('[provena] 증분 수집 삭제 보류 {0}' -f $day) $body '보류 알림')
        }
    } catch { Write-Log ('알림 처리 중 오류(종료 코드는 그대로): ' + $_.Exception.Message) } }
    Clear-Secrets
    Write-Log ('끝 {0} 종료 코드 {1} (걸린 시간 {2:N1}초)' -f $ended.ToString('yyyy-MM-dd HH:mm:ss zzz'), $code, ($ended - $started).TotalSeconds)
    $script:Redact.Clear()
}
exit $code
