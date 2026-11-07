<#
.SYNOPSIS
  NTR daily journal: summarise today's Codex sessions that ran inside the NTR repo
  into journal/<date>/<user>.md. Works even if the person forgot to commit or push.

.DESCRIPTION
  Reads %USERPROFILE%\.codex\sessions\YYYY\MM\DD\*.jsonl, keeps top-level sessions whose
  working folder path contains the repo folder name (also Codex worktrees), and extracts:
  start/end time, number of prompts, tokens, first prompt, NTR-SESSION / NTR-RESULT tags.
  Raw chat text is NOT copied - only a short summary.

  Run every evening on each PC (Codex automation or Windows Task Scheduler):
    powershell -ExecutionPolicy Bypass -File scripts\ntr-daily.ps1 -Push

.PARAMETER Date      Day to summarise (yyyy-MM-dd). Default: today.
.PARAMETER User      Team id. Default: contents of .ntr-user in repo root.
.PARAMETER RepoName  Folder name used to recognise repo sessions. Default: NTR_AI.
.PARAMETER Push      Commit and push the journal file to branch 'journal' via a separate worktree.
#>
param(
  [string]$Date = (Get-Date -Format 'yyyy-MM-dd'),
  [string]$User = '',
  [string]$RepoName = 'NTR_AI',
  [string]$SessionsRoot = (Join-Path $env:USERPROFILE '.codex\sessions'),
  [string]$OutRoot = '',
  [switch]$Push
)
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
if (-not $User) {
  $f = Join-Path $repo '.ntr-user'
  if (Test-Path $f) { $User = (Get-Content $f -Raw).Trim() } else { $User = 'unknown' }
}
$machine = $env:COMPUTERNAME
$d = [datetime]::ParseExact($Date, 'yyyy-MM-dd', $null)
$dayDir = Join-Path $SessionsRoot ('{0:yyyy}\{0:MM}\{0:dd}' -f $d)

function Get-Texts($payload) {
  $out = @()
  foreach ($c in @($payload.content)) { if ($c.text) { $out += [string]$c.text } }
  return $out
}
function Parse-Tag([string]$line) {
  $h = @{}
  foreach ($m in [regex]::Matches($line, '(\w+)=("([^"]*)"|\S+)')) {
    $v = if ($m.Groups[3].Success) { $m.Groups[3].Value } else { $m.Groups[2].Value }
    $h[$m.Groups[1].Value] = $v
  }
  return $h
}

$sessions = @()
if (Test-Path $dayDir) {
  foreach ($file in Get-ChildItem $dayDir -Filter *.jsonl) {
    $meta = $null; $first = $null; $last = $null; $prompts = 0; $firstPrompt = ''
    $tokens = 0; $tags = @(); $results = @()
    foreach ($line in [IO.File]::ReadLines($file.FullName)) {
      if (-not $line) { continue }
      try { $o = $line | ConvertFrom-Json } catch { continue }
      if ($o.timestamp) {
        $ts = [datetime]::Parse($o.timestamp).ToLocalTime()
        if (-not $first) { $first = $ts }; $last = $ts
      }
      if ($o.type -eq 'session_meta') { $meta = $o.payload; continue }
      if ($o.type -eq 'event_msg' -and $o.payload.type -eq 'token_count' -and $o.payload.info) {
        $tokens = [int64]$o.payload.info.total_token_usage.total_tokens; continue
      }
      if ($o.type -ne 'response_item' -or $o.payload.type -ne 'message') { continue }
      $role = $o.payload.role
      foreach ($t in Get-Texts $o.payload) {
        if ($role -eq 'user') {
          $tt = $t.Trim()
          if ($tt.StartsWith('#') -or $tt.StartsWith('<')) { continue }  # injected AGENTS.md / env context
          $prompts++
          if (-not $firstPrompt) { $firstPrompt = $tt }
        } elseif ($role -eq 'assistant') {
          foreach ($m in [regex]::Matches($t, 'NTR-SESSION[^\r\n`]*')) { $tags += ,(Parse-Tag $m.Value) }
          foreach ($m in [regex]::Matches($t, 'NTR-RESULT[^\r\n`]*'))  { $results += ,(Parse-Tag $m.Value) }
        }
      }
    }
    if (-not $meta) { continue }
    # only top-level threads (sub-agent threads carry a different parent id)
    if ($meta.parent_thread_id -and $meta.parent_thread_id -ne $meta.id) { continue }
    $segments = ([string]$meta.cwd) -split '[\\/]'
    if ($segments -notcontains $RepoName) { continue }
    if ($prompts -eq 0) { continue }
    $tag = if ($tags.Count) { $tags[0] } else { @{} }
    $sessions += [pscustomobject]@{
      start   = $first; end = $last
      minutes = [math]::Round(($last - $first).TotalMinutes)
      prompts = $prompts; tokens = $tokens
      mode    = if ($tag.mode) { $tag.mode } else { 'untagged' }
      cell    = $tag.cell; stage = $tag.stage; task = $tag.task
      tagUser = $tag.user
      result  = if ($results.Count) { $results[-1] } else { $null }
      first   = if ($firstPrompt.Length -gt 120) { $firstPrompt.Substring(0,120) + '...' } else { $firstPrompt }
    }
  }
}

# ---- write journal file --------------------------------------------------------------
if (-not $OutRoot) { $OutRoot = Join-Path $repo 'journal' }
$outDir = Join-Path $OutRoot $Date
New-Item -ItemType Directory -Force $outDir | Out-Null
$outFile = Join-Path $outDir "$User.md"

$totalMin = ($sessions | Measure-Object minutes -Sum).Sum; if (-not $totalMin) { $totalMin = 0 }
$totalTok = ($sessions | Measure-Object tokens -Sum).Sum; if (-not $totalTok) { $totalTok = 0 }
$modes = ($sessions | Group-Object mode | ForEach-Object { "$($_.Name):$($_.Count)" }) -join ', '
$tagged = @($sessions | Where-Object { $_.mode -ne 'untagged' }).Count

$sb = New-Object System.Text.StringBuilder
[void]$sb.AppendLine('---')
[void]$sb.AppendLine("user: $User")
[void]$sb.AppendLine("machine: $machine")
[void]$sb.AppendLine("date: $Date")
[void]$sb.AppendLine("sessions: $($sessions.Count)")
[void]$sb.AppendLine("tagged: $tagged")
[void]$sb.AppendLine("minutes: $totalMin")
[void]$sb.AppendLine("tokens: $totalTok")
[void]$sb.AppendLine("modes: $modes")
[void]$sb.AppendLine('generated: scripts/ntr-daily.ps1')
[void]$sb.AppendLine('---')
[void]$sb.AppendLine('')
[void]$sb.AppendLine("# $Date - $User")
[void]$sb.AppendLine('')
if ($sessions.Count -eq 0) {
  [void]$sb.AppendLine('Sessions in the repo: none.')
} else {
  [void]$sb.AppendLine('| Time | Min | Mode | Cell / stage | Task | Result |')
  [void]$sb.AppendLine('|---|---|---|---|---|---|')
  foreach ($s in $sessions | Sort-Object start) {
    $res = '-'
    if ($s.result) { $res = "$($s.result.status) $($s.result.item)".Trim()
      if ($s.result.minutes_before -and $s.result.minutes_before -ne '-') { $res += " ($($s.result.minutes_before)->$($s.result.minutes_after) min)" } }
    $task = if ($s.task) { $s.task } else { $s.first }
    $task = ($task -replace '\|', '/' -replace '\r?\n', ' ')
    $cs = if ($s.cell) { "$($s.cell) / $($s.stage)" } else { '-' }
    [void]$sb.AppendLine(("| {0:HH:mm}-{1:HH:mm} | {2} | {3} | {4} | {5} | {6} |" -f $s.start, $s.end, $s.minutes, $s.mode, $cs, $task, $res))
  }
}
[IO.File]::WriteAllText($outFile, $sb.ToString(), (New-Object Text.UTF8Encoding $false))
Write-Output "journal: $outFile ($($sessions.Count) sessions, $totalMin min, tagged $tagged)"

# ---- optional publish to branch 'journal' ------------------------------------------------
if ($Push) {
  $wt = Join-Path (Split-Path -Parent $repo) "$RepoName-journal"
  Push-Location $repo
  try {
    if (-not (Test-Path $wt)) {
      git fetch origin journal 2>$null
      if ($LASTEXITCODE -eq 0) { git worktree add $wt journal } else { git worktree add --orphan -b journal $wt }
    }
  } finally { Pop-Location }
  Push-Location $wt
  try {
    git pull --rebase origin journal 2>$null
    $dst = Join-Path $wt "journal\$Date"
    New-Item -ItemType Directory -Force $dst | Out-Null
    Copy-Item $outFile (Join-Path $dst "$User.md") -Force
    git add -- "journal/$Date/$User.md"
    git commit -m "journal: $Date $User" 2>$null
    git push origin journal
  } finally { Pop-Location }
}
