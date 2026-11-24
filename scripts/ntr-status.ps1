<#
.SYNOPSIS
  Builds the NTR status report from repo data: STATUS.md, status/data.json, status/dashboard.html.
  Generated files - do not edit by hand.

.DESCRIPTION
  Sources:
    team.md                    people (id, name, Trello code, shown in report)
    roadmap/pipeline.json      products, cells, stages, shares, focus, target
    roadmap/backlog.json       Trello snapshot: tasks, priorities, owners, mapped to cells/stages
                               (refreshed by scripts/ntr-trello-pull.ps1 when Trello keys are set)
    registry/tools/*.md        tool / contract cards (front matter)
    registry/tests/*.md        cross-test reports (front matter)
    journal/<date>/<user>.md   daily journals from scripts/ntr-daily.ps1 (branch 'journal')
    sessions/<date>_<user>_<slug>.md   one record per work session (front matter), written by the agent
    team.aliases.json          branch / session user names that differ from team.md ids

  sessions/, registry/tools/ and registry/tests/ are read from the working tree AND from every
  origin/* branch (git ls-tree / git show, nothing is checked out), so work that lives only in a
  colleague's branch is visible. Cards: working tree and main win, branch-only cards get in_branch.
  Sessions: de-duplicated by path, newest commit wins. Remote work/<user>/... branches and pull
  requests (gh, optional) form the 'github' block. Run 'git fetch' first for fresh data; -NoGit
  skips all of this.

  Savings count only cards with status measured|cross-tested|accepted and time_source: measured.
  Per stage only the best tool counts (no double counting); its author gets the contribution.

  Usage (maintainer PC, nightly or before the weekly meeting):
    powershell -ExecutionPolicy Bypass -File scripts\ntr-status.ps1 [-JournalRoot ..\NTR_AI-journal\journal] [-Days 14] [-NoGit]
  With -OutDir <dir> everything (including STATUS.md) goes to <dir>; the repo is not modified.
#>
param(
  [string]$JournalRoot = '',
  [int]$Days = 14,
  [string]$OutDir = '',
  [string]$Label = '',
  [switch]$NoGit
)
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
if (-not $JournalRoot) {
  $wt = Join-Path (Split-Path -Parent $repo) 'NTR_AI-journal\journal'
  $JournalRoot = if (Test-Path $wt) { $wt } else { Join-Path $repo 'journal' }
}
if (-not $OutDir) { $OutDir = Join-Path $repo 'status' }
$utf8 = New-Object Text.UTF8Encoding $false
$enc = [Text.Encoding]::UTF8

function Read-FrontMatter([string]$path) { return ConvertFrom-FrontMatter ([IO.File]::ReadAllLines($path, $enc)) }
function ConvertFrom-FrontMatter([string[]]$lines) {
  $h = [ordered]@{}; $body = New-Object System.Collections.Generic.List[string]
  $in = $false; $done = $false
  foreach ($l in $lines) {
    if (-not $in) { $l = $l.TrimStart([char]0xFEFF) }
    if (-not $done -and $l.Trim() -eq '---') { if ($in) { $done = $true } else { $in = $true }; continue }
    if ($in -and -not $done) {
      $i = $l.IndexOf(':'); if ($i -gt 0) { $h[$l.Substring(0,$i).Trim()] = $l.Substring($i+1).Trim() }
    } elseif ($done) { $body.Add($l) }
  }
  $h['_body'] = ($body -join "`n").Trim()
  return $h
}
function Num($v) { $n = 0.0; if ([double]::TryParse([string]$v, [Globalization.NumberStyles]::Float, [Globalization.CultureInfo]::InvariantCulture, [ref]$n)) { return $n } return $null }
function R2($v) { return [math]::Round([double]$v, 2) }

$pipeline = [IO.File]::ReadAllText((Join-Path $repo 'roadmap\pipeline.json'), $enc) | ConvertFrom-Json
$backlogPath = Join-Path $repo 'roadmap\backlog.json'
$backlog = if (Test-Path $backlogPath) { [IO.File]::ReadAllText($backlogPath, $enc) | ConvertFrom-Json } else { $null }

# ---- team ------------------------------------------------------------------------------------
$team = [ordered]@{}; $people = @()
foreach ($l in [IO.File]::ReadAllLines((Join-Path $repo 'team.md'), $enc)) {
  if ($l -match '^\|\s*([a-z][a-z0-9-]+)\s*\|\s*([^|]+?)\s*\|') {
    $team[$Matches[1]] = $Matches[2]
    if ($l -match '\|\s*да\s*\|\s*$') { $people += $Matches[1] }
  }
}
# re-match ids for people (the second -match overwrote $Matches)
$people = @()
foreach ($l in [IO.File]::ReadAllLines((Join-Path $repo 'team.md'), $enc)) {
  if ($l -match '\|\s*да\s*\|\s*$' -and $l -match '^\|\s*([a-z][a-z0-9-]+)\s*\|') { $people += $Matches[1] }
}

# branch / session user names that are not team.md ids (work/roman-kasyan/... -> roman)
$aliases = @{}
$aliasPath = Join-Path $repo 'team.aliases.json'
if (Test-Path $aliasPath) {
  $aj = [IO.File]::ReadAllText($aliasPath, $enc) | ConvertFrom-Json
  foreach ($p in $aj.PSObject.Properties) { if ($p.Name -notlike '_*') { $aliases[$p.Name.ToLower()] = [string]$p.Value } }
}
function Resolve-User([string]$raw) {
  if (-not $raw) { return $null }
  $k = $raw.Trim().ToLower()
  if ($team.Contains($k)) { return $k }
  if ($aliases.ContainsKey($k)) { return $aliases[$k] }
  return $raw.Trim()
}
$weekAgo = (Get-Date).Date.AddDays(-6).ToString('yyyy-MM-dd')
$twoWeeksAgo = (Get-Date).Date.AddDays(-13).ToString('yyyy-MM-dd')

# ---- git: remote branches, files that live only in branches ------------------------------------
$useGit = -not $NoGit
try { [Console]::OutputEncoding = $enc } catch { }
function Invoke-Git { $ErrorActionPreference = 'Continue'; & git.exe -C $repo -c core.quotepath=false @args 2>$null }
if ($useGit) {
  if (-not (Get-Command git.exe -ErrorAction SilentlyContinue)) { $useGit = $false }
  else { $null = Invoke-Git rev-parse --git-dir; if ($LASTEXITCODE -ne 0) { $useGit = $false } }
}
$refs = @(); $mainRef = $null; $repoUrl = $null
$cand = @{}                                              # repo path -> candidates (ref, blob)
$dirty = New-Object System.Collections.Generic.HashSet[string]
if ($useGit) {
  foreach ($l in @(Invoke-Git for-each-ref '--sort=-committerdate' '--format=%(refname:short)%09%(committerdate:iso-strict)%09%(objectname)%09%(subject)' refs/remotes/origin)) {
    $p = $l -split "`t", 4
    if ($p.Count -lt 4 -or $p[0] -notlike 'origin/*' -or $p[0] -eq 'origin/HEAD' -or $p[0] -eq 'origin/gh-pages') { continue }
    $refs += [pscustomobject]@{ ref=$p[0]; branch=$p[0].Substring(7); date=$p[1]; sha=$p[2]; subject=$p[3] }
  }
  foreach ($m in 'origin/main','origin/master') { if (-not $mainRef -and @($refs | Where-Object { $_.ref -eq $m }).Count) { $mainRef = $m } }
  $url = [string](Invoke-Git remote get-url origin)
  if ($url -match 'github\.com[:/]([\w.-]+/[\w.-]+?)(\.git)?/?$') { $repoUrl = "https://github.com/$($Matches[1])" }
  foreach ($l in @(Invoke-Git status --porcelain -- sessions)) { if ($l.Length -gt 3) { [void]$dirty.Add($l.Substring(3).Trim('"')) } }
  # HEAD first, then main, then the rest (newest first); identical tips are scanned once
  $scan = @([pscustomobject]@{ ref='HEAD'; sha=[string](Invoke-Git rev-parse HEAD) })
  $scan += @($refs | Where-Object { $_.ref -eq $mainRef }) + @($refs | Where-Object { $_.ref -ne $mainRef })
  $seenTip = @{}
  foreach ($r in $scan) {
    if (-not $r.sha -or $seenTip.ContainsKey($r.sha)) { continue }
    $seenTip[$r.sha] = $true
    foreach ($l in @(Invoke-Git ls-tree -r $r.ref -- sessions registry/tools registry/tests)) {
      if ($l -notmatch '^\d+ blob ([0-9a-f]+)\t(.+\.md)$') { continue }
      $path = $Matches[2]
      if (-not $cand.ContainsKey($path)) { $cand[$path] = New-Object System.Collections.ArrayList }
      [void]$cand[$path].Add([pscustomobject]@{ ref=$r.ref; blob=$Matches[1] })
    }
  }
}
# Front matter of every <dir>/*.md, from the working tree and from branches.
#   $localWins = $true  (cards):    working tree, then main, then the newest branch copy
#   $localWins = $false (sessions): uncommitted local file, else the copy with the newest commit
# in_branch = branch name when the chosen copy is neither in the working tree / HEAD nor in main.
function Get-RepoDocs([string]$dir, [bool]$localWins) {
  $paths = New-Object System.Collections.Generic.SortedSet[string]
  foreach ($f in Get-ChildItem (Join-Path $repo $dir) -Filter *.md -File -ErrorAction SilentlyContinue) { [void]$paths.Add("$dir/$($f.Name)") }
  foreach ($k in @($cand.Keys)) { if ($k.StartsWith("$dir/") -and $k.IndexOf('/', $dir.Length + 1) -lt 0) { [void]$paths.Add($k) } }
  $out = @()
  foreach ($p in $paths) {
    if ($p -like '*/README.md') { continue }
    $local = Join-Path $repo ($p -replace '/', '\')
    $c = if ($cand.ContainsKey($p)) { @($cand[$p]) } else { @() }
    $inBranch = $null
    if ((Test-Path -LiteralPath $local) -and ($localWins -or $c.Count -eq 0 -or $dirty.Contains($p))) {
      $fm = Read-FrontMatter $local
    } else {
      $pick = $null
      if ($localWins) { $pick = $c | Where-Object { $_.ref -eq $mainRef } | Select-Object -First 1 }
      if (-not $pick) {
        $blobs = @($c | Group-Object blob)
        if ($blobs.Count -eq 1) { $pick = $c[0] }
        else {
          $bestT = -1
          foreach ($g in $blobs) {
            $t = [int64]0; [void][int64]::TryParse([string](Invoke-Git log -1 '--format=%ct' $g.Group[0].ref -- $p), [ref]$t)
            if ($t -gt $bestT) { $bestT = $t; $pick = $g.Group[0] }
          }
        }
      }
      $fm = ConvertFrom-FrontMatter @(Invoke-Git show "$($pick.ref):$p")
      $merged = @($c | Where-Object { $_.blob -eq $pick.blob -and ($_.ref -eq 'HEAD' -or $_.ref -eq $mainRef) }).Count
      if (-not $merged) { $inBranch = $pick.ref -replace '^origin/', '' }
    }
    $out += [pscustomobject]@{ path=$p; fm=$fm; in_branch=$inBranch }
  }
  return $out
}

# ---- registry -------------------------------------------------------------------------------
$tests = @()
foreach ($d in Get-RepoDocs 'registry/tests' $true) {
  $t = $d.fm
  if ($t.tool) { $tests += [pscustomobject]@{ tool=$t.tool; tester=$t.tester; date=$t.date; project=$t.project; result=$t.result; in_branch=$d.in_branch } }
}
$measuredStatuses = @('measured','cross-tested','accepted')
$tools = @()
foreach ($d in @(Get-RepoDocs 'registry/tools' $true) | Sort-Object { [bool]$_.in_branch }) {
  $c = $d.fm
  if (-not $c.id -or @($tools | Where-Object { $_.id -eq $c.id }).Count) { continue }
  $mb = Num $c.minutes_before; $ma = Num $c.minutes_after
  $saving = $null
  if ($mb -and $ma -ne $null -and $mb -gt 0) { $saving = [math]::Round(($mb - $ma) / $mb, 3) }
  $counts = ($measuredStatuses -contains $c.status) -and $c.time_source -eq 'measured' -and $saving -ne $null
  $myTests = @($tests | Where-Object { $_.tool -eq $c.id })
  $tools += [pscustomobject]@{
    id=$c.id; title=$c.title; purpose=$c.purpose; trello=$c.trello; line=$c.line; author=$c.author
    cell=$c.cell; stage=$c.stage; dcc=$c.dcc; status=$c.status; where=$c.where
    minutes_before=$mb; minutes_after=$ma; time_source=$c.time_source
    saving=$saving; counts=$counts; contribution_pct=0.0; note=$c._body
    testers=@($myTests | ForEach-Object { $_.tester } | Sort-Object -Unique); tests=$myTests.Count
    in_branch=$d.in_branch
  }
}

# ---- pipeline savings, contributions ---------------------------------------------------------
$cells = @()
foreach ($cell in $pipeline.cells) {
  $stages = @(); $cellSaving = 0.0
  foreach ($st in @($cell.stages)) {
    $stTools = @($tools | Where-Object { $_.cell -eq $cell.id -and $_.stage -eq $st.id })
    $best = $stTools | Where-Object { $_.counts } | Sort-Object saving -Descending | Select-Object -First 1
    $s = if ($best) { [double]$best.saving } else { 0.0 }
    $estBest = $stTools | Where-Object { $_.saving -ne $null -and -not $_.counts } | Sort-Object saving -Descending | Select-Object -First 1
    $e = if ($estBest -and $estBest.saving -gt $s) { [double]$estBest.saving } else { 0.0 }
    $cellSaving += $st.share * $s
    $stTasks = if ($backlog) { @($backlog.items | Where-Object { $_.cell -eq $cell.id -and $_.stage -eq $st.id }) } else { @() }
    $stages += [pscustomobject]@{
      id=$st.id; title=$st.title; short=$st.short; share=$st.share; line=$st.line; saving=$s; est_saving=$e
      best= if ($best) { $best.id } else { $null }; est_tool= if ($e) { $estBest.id } else { $null }
      tools=@($stTools | ForEach-Object { $_.id }); baseline=$st.baseline
      tasks_open=@($stTasks | Where-Object { $_.status -ne 'ready' }).Count
      tasks_ready=@($stTasks | Where-Object { $_.status -eq 'ready' }).Count
      inFocus=(@($pipeline.focus.cells) -contains $cell.id -and @($pipeline.focus.stages) -contains $st.id)
    }
  }
  $cells += [pscustomobject]@{
    id=$cell.id; kind=$cell.kind; title=$cell.title; owner=$cell.owner
    saving_pct=[math]::Round($cellSaving, 1)
    stages=$stages; note=$cell.note
    tools=@($tools | Where-Object { $_.cell -eq $cell.id }).Count
    tasks=if ($backlog) { @($backlog.items | Where-Object { $_.cell -eq $cell.id }).Count } else { 0 }
  }
}
# products: hours before / after per stage segment; tool contribution in hours
$products = @()
foreach ($p in $pipeline.products) {
  $segs = @(); $saved = 0.0; $est = 0.0
  foreach ($part in $p.parts) {
    $c = $cells | Where-Object { $_.id -eq $part.cell }
    $cellH = [double]$p.hours * $part.share / 100
    foreach ($s in @($c.stages)) {
      $h = $cellH * $s.share / 100
      $sv = $h * $s.saving; $es = $h * [math]::Max(0.0, [double]$s.est_saving - [double]$s.saving)
      $saved += $sv; $est += $es
      if ($s.best) { $bt = $tools | Where-Object { $_.id -eq $s.best }; $bt.contribution_pct += $sv }
      $segs += [pscustomobject]@{ cell=$c.id; kind=$c.kind; stage=$s.id; short=$s.short; title=$s.title; line=$s.line
        hours=R2 $h; saved=R2 $sv; est=R2 $es; best=$s.best; est_tool=$s.est_tool; inFocus=$s.inFocus; tools=$s.tools; tasks_open=$s.tasks_open }
    }
  }
  $products += [pscustomobject]@{
    id=$p.id; title=$p.title; hours=[double]$p.hours; days=[double]$p.hours / $pipeline.hours_per_day; note=$p.note
    parts=$p.parts; segments=$segs
    saved_h=R2 $saved; est_h=R2 $est; after_h=R2 ([double]$p.hours - $saved)
    saving_pct=R2 ($saved / $p.hours * 100); est_pct=R2 ($est / $p.hours * 100)
    cells=@($p.parts | ForEach-Object { $_.cell }); described=@($p.parts).Count; total=@($p.parts).Count
  }
}
# contribution_pct now holds hours saved over one typical project of each product
foreach ($t in $tools) { $t.contribution_pct = R2 $t.contribution_pct }

# ---- backlog / top-10 ------------------------------------------------------------------------
$statusW = @{ 'help'=6; 'in-progress'=5; 'review'=4; 'queue'=2; 'ready'=0 }
$backlogOut = $null; $top = @()
if ($backlog) {
  $items = @()
  foreach ($b in $backlog.items) {
    $focus = (@($pipeline.focus.cells) -contains $b.cell) -and (@($pipeline.focus.stages) -contains $b.stage)
    $share = 0
    $cdef = $pipeline.cells | Where-Object { $_.id -eq $b.cell }
    if ($cdef) { $sdef = @($cdef.stages) | Where-Object { $_.id -eq $b.stage }; if ($sdef) { $share = $sdef.share } }
    $score = (4 - [int]$b.prio) * 10 + $statusW[[string]$b.status] + $(if ($focus) { 8 } else { 0 }) + [math]::Round($share / 5)
    $tool = $tools | Where-Object { $_.trello -and ($_.trello -split ';\s*') -contains $b.title } | Select-Object -First 1
    $items += [pscustomobject]@{
      n=$b.n; status=$b.status; prio=$b.prio; area=$b.area; title=$b.title; owner=$b.owner; upd=$b.upd; check=$b.check
      cell=$b.cell; stage=$b.stage; focus=$focus; stage_share=$share; score=$score; tool= if ($tool) { $tool.id } else { $null }
    }
  }
  # stations = cell x stage; Trello micro-tasks are grouped inside
  $stations = @()
  foreach ($g in ($items | Where-Object { $_.cell -and $_.cell -ne 'infra' } | Group-Object { "$($_.cell)/$($_.stage)" })) {
    $its = @($g.Group); $first = $its[0]
    $open = @($its | Where-Object { $_.status -ne 'ready' })
    $stTools = @($tools | Where-Object { $_.cell -eq $first.cell -and $_.stage -eq $first.stage })
    $owners = @($its | Where-Object { $_.owner } | Group-Object owner | Sort-Object Count -Descending | ForEach-Object { $_.Name })
    $cellObj = $cells | Where-Object { $_.id -eq $first.cell }
    $stObj = if ($cellObj) { @($cellObj.stages) | Where-Object { $_.id -eq $first.stage } } else { $null }
    $score = ($open | Measure-Object score -Maximum).Maximum + [math]::Min(6, $open.Count)
    $stations += [pscustomobject]@{
      key=$g.Name; cell=$first.cell; stage=$first.stage
      title= if ($stObj) { $stObj.title } else { $null }
      share=$first.stage_share; focus=$first.focus; saving= if ($stObj) { $stObj.saving } else { 0 }
      tasks=$its.Count; open=$open.Count
      in_progress=@($its | Where-Object { $_.status -eq 'in-progress' }).Count
      review=@($its | Where-Object { $_.status -eq 'review' }).Count
      ready=@($its | Where-Object { $_.status -eq 'ready' }).Count
      p1=@($open | Where-Object { $_.prio -eq 1 }).Count
      owners=$owners; tools=@($stTools | ForEach-Object { $_.id })
      score= if ($open.Count) { $score } else { 0 }
      items=@($its | Sort-Object score -Descending | ForEach-Object { [pscustomobject]@{ title=$_.title; status=$_.status; prio=$_.prio; owner=$_.owner } })
    }
  }
  $top = @($stations | Where-Object { $_.open -gt 0 } | Sort-Object score -Descending | Select-Object -First 10)
  $byList = [ordered]@{}; foreach ($s in 'help','in-progress','review','queue','ready') { $byList[$s] = @($items | Where-Object { $_.status -eq $s }).Count }
  $byOwner = [ordered]@{}
  foreach ($u in $people + @('unassigned')) {
    $mine = @($items | Where-Object { if ($u -eq 'unassigned') { -not $_.owner } else { $_.owner -eq $u } })
    $o = [ordered]@{}; foreach ($s in 'in-progress','review','queue','ready') { $o[$s] = @($mine | Where-Object { $_.status -eq $s }).Count }
    $byOwner[$u] = $o
  }
  $backlogOut = [ordered]@{ snapshot=$backlog.snapshot; source=$backlog.source; total=$items.Count; unmapped=@($items | Where-Object { -not $_.cell }).Count; stations=$stations.Count; by_status=$byList; by_owner=$byOwner; items=$items }
}

# ---- journals -----------------------------------------------------------------------------
$since = (Get-Date).Date.AddDays(-$Days + 1)
$activity = @(); $feed = @()
if (Test-Path $JournalRoot) {
  foreach ($f in Get-ChildItem $JournalRoot -Recurse -Filter *.md) {
    $j = Read-FrontMatter $f.FullName
    if (-not $j.date) { continue }
    $dt = [datetime]::ParseExact($j.date, 'yyyy-MM-dd', $null)
    if ($dt -lt $since) { continue }
    $modes = [ordered]@{}
    foreach ($p in ([string]$j.modes -split ',\s*')) { if ($p -match '^(\w+):(\d+)$') { $modes[$Matches[1]] = [int]$Matches[2] } }
    $activity += [pscustomobject]@{ date=$j.date; user=$j.user; sessions=[int]$j.sessions; tagged=[int]$j.tagged; minutes=[int]$j.minutes; tokens=[int64]$j.tokens; modes=$modes }
    foreach ($row in ($j._body -split "`n")) {
      if ($row -notmatch '^\| \d') { continue }
      $c = $row.Trim('|').Split('|') | ForEach-Object { $_.Trim() }
      if ($c.Count -lt 6) { continue }
      $feed += [pscustomobject]@{ date=$j.date; user=$j.user; time=$c[0]; minutes=[int]$c[1]; mode=$c[2]; cellstage=$c[3]; task=$c[4]; result=$c[5] }
    }
  }
}
$feed = @($feed | Where-Object { $_.mode -ne 'untagged' } | Sort-Object date, time -Descending | Select-Object -First 15)

# ---- sessions (sessions/<date>_<user>_<slug>.md) ------------------------------------------------
$sessions = @()
foreach ($d in Get-RepoDocs 'sessions' $false) {
  $s = $d.fm
  foreach ($k in @($s.Keys)) { if ($k -ne '_body') { $s[$k] = ([string]$s[$k]).Trim('"', "'") } }
  $date = $s.date; $rawUser = $s.user
  if ($d.path -match '/(\d{4}-\d{2}-\d{2})_([^_]+)_') { if (-not $date) { $date = $Matches[1] }; if (-not $rawUser) { $rawUser = $Matches[2] } }
  if ($date -notmatch '^\d{4}-\d{2}-\d{2}$') { continue }
  $mm = Num $s.minutes_manual; $mai = Num $s.minutes_ai
  $both = ($null -ne $mm) -and ($null -ne $mai)
  $sessions += [pscustomobject]@{
    id=$s.id; user=(Resolve-User $rawUser); date=$date; mode=$s.mode; cell=$s.cell; stage=$s.stage; dcc=$s.dcc
    task=$s.task; status=$s.status; scenario=$s.scenario; scenario_version=$s.scenario_version; based_on=$s.based_on
    minutes_manual=$mm; minutes_ai=$mai; time_source=$s.time_source; tool_needed=$s.tool_needed
    handovers=$s.handovers; updated=$s.updated
    minutes_saved= if ($both) { $mm - $mai } else { $null }
    measured=($both -and $s.time_source -eq 'measured')
    example=(([string]$s.id) -like 'example-*')
    in_branch=$d.in_branch; path=$d.path
  }
}
$sessions = @($sessions | Sort-Object date, updated -Descending | Select-Object -First 200)
$realSessions = @($sessions | Where-Object { -not $_.example })

# ---- github: work/<user>/... branches, pull requests, 7-day summary per person ------------------
$branches = @(); $prs = @(); $ghOk = $false
if ($useGit) {
  if (Get-Command gh -ErrorAction SilentlyContinue) {
    $raw = & { $ErrorActionPreference = 'Continue'; Push-Location $repo
      try { gh pr list --state all --limit 200 --json number,title,headRefName,state,isDraft,updatedAt,author 2>$null } finally { Pop-Location } }
    if ($LASTEXITCODE -eq 0 -and $raw) {
      try {
        $pj = ($raw -join "`n") | ConvertFrom-Json
        foreach ($p in @($pj)) {
          $u = if ($p.headRefName -like 'work/*/*') { Resolve-User ($p.headRefName.Split('/')[1]) } else { $null }
          $prs += [pscustomobject]@{ number=$p.number; title=$p.title; branch=$p.headRefName; state=$p.state; draft=[bool]$p.isDraft
            updated=([datetime]$p.updatedAt).ToUniversalTime().ToString('yyyy-MM-dd'); author=$p.author.login; user=$u }
        }
        $ghOk = $true
      } catch { $prs = @() }
    }
  }
  $notMain = if ($mainRef) { @('--not', $mainRef) } else { @() }
  foreach ($r in $refs | Where-Object { $_.branch -like 'work/*/*' }) {
    $seg = $r.branch.Split('/')
    $pr = $prs | Where-Object { $_.branch -eq $r.branch } | Sort-Object { $_.state -ne 'OPEN' }, { -$_.number } | Select-Object -First 1
    $branches += [pscustomobject]@{
      branch=$r.branch; user=(Resolve-User $seg[1]); user_raw=$seg[1]; topic=($seg[2..($seg.Count - 1)] -join '/')
      last_commit=$r.date; last_date=$r.date.Substring(0, 10); subject=$r.subject
      commits_7d=[int](Invoke-Git rev-list --count "--since=${weekAgo}T00:00:00" $r.ref @notMain)
      commits_14d=[int](Invoke-Git rev-list --count "--since=${twoWeeksAgo}T00:00:00" $r.ref @notMain)
      ahead=[int](Invoke-Git rev-list --count $r.ref @notMain)
      pr= if ($pr) { [pscustomobject]@{ number=$pr.number; state=$pr.state; draft=$pr.draft; title=$pr.title } } else { $null }
    }
  }
}
$people7 = @()
$seenUsers = @($people) + @($branches | ForEach-Object { $_.user }) + @($realSessions | ForEach-Object { $_.user }) | Where-Object { $_ } | Select-Object -Unique
foreach ($u in $seenUsers) {
  $mine = @($branches | Where-Object { $_.user -eq $u })
  $uploads = 0
  if ($mine.Count) { $ur = @($mine | ForEach-Object { "origin/$($_.branch)" }); $uploads = [int](Invoke-Git rev-list --count "--since=${weekAgo}T00:00:00" @ur @notMain) }
  $ses = @($realSessions | Where-Object { $_.user -eq $u -and $_.date -ge $weekAgo })
  $dates = @(@($mine | ForEach-Object { $_.last_date }) + @($realSessions | Where-Object { $_.user -eq $u } | ForEach-Object { $_.date }) | Sort-Object -Descending)
  $last = if ($dates.Count) { $dates[0] } else { $null }
  $people7 += [pscustomobject]@{
    user=$u; known=$team.Contains($u); sessions=$ses.Count; uploads=$uploads
    prs=@($prs | Where-Object { $_.user -eq $u -and $_.updated -ge $weekAgo }).Count
    prs_open=@($prs | Where-Object { $_.user -eq $u -and $_.state -eq 'OPEN' }).Count
    minutes_saved=[int](($ses | Where-Object { $_.measured } | Measure-Object minutes_saved -Sum).Sum)
    branches=$mine.Count; last_activity=$last
  }
}
$github = [ordered]@{
  available = $useGit; gh = $ghOk; repo = $repoUrl; main = $mainRef; refs_scanned = $refs.Count
  branches = $branches
  prs_open = @($prs | Where-Object { $_.state -eq 'OPEN' })
  people_7d = $people7
}
$live = [ordered]@{
  sessions_7d = @($realSessions | Where-Object { $_.date -ge $weekAgo }).Count
  sessions_total = $realSessions.Count
  examples = $sessions.Count - $realSessions.Count
  uploads_7d = [int](($people7 | Measure-Object uploads -Sum).Sum)
  active_people_7d = @($people7 | Where-Object { $_.sessions -gt 0 -or $_.uploads -gt 0 }).Count
  measurements = @($realSessions | Where-Object { $_.measured }).Count
  minutes_saved_7d = [int](($people7 | Measure-Object minutes_saved -Sum).Sum)
}

# ---- people contributions ------------------------------------------------------------------
$contrib = @()
foreach ($u in $people) {
  $mine = @($tools | Where-Object { $_.author -eq $u })
  $byS = [ordered]@{}; foreach ($s in 'not-in-repo','draft','measured','cross-tested','accepted') { $byS[$s] = @($mine | Where-Object { $_.status -eq $s }).Count }
  $act = @($activity | Where-Object { $_.user -eq $u })
  $contrib += [pscustomobject]@{
    user=$u
    saving_pct = R2 (($mine | Measure-Object contribution_pct -Sum).Sum)
    saving_contract = R2 ((@($mine | Where-Object { $_.line -eq 'contract' }) | Measure-Object contribution_pct -Sum).Sum)
    saving_tool = R2 ((@($mine | Where-Object { $_.line -eq 'tool' }) | Measure-Object contribution_pct -Sum).Sum)
    tools=$mine.Count; contracts=@($mine | Where-Object { $_.line -eq 'contract' }).Count; scripts=@($mine | Where-Object { $_.line -eq 'tool' }).Count
    by_status=$byS
    tests_done=@($tests | Where-Object { $_.tester -eq $u }).Count
    minutes_7d=[int](($act | Where-Object { $_.date -ge $weekAgo } | Measure-Object minutes -Sum).Sum)
    minutes_total=[int](($act | Measure-Object minutes -Sum).Sum)
  }
}

# ---- summary --------------------------------------------------------------------------------
$byStatus = [ordered]@{}
foreach ($s in 'not-in-repo','draft','measured','cross-tested','accepted') { $byStatus[$s] = @($tools | Where-Object { $_.status -eq $s }).Count }
$recentTests = @($tests | Where-Object { $_.date -ge $weekAgo })
$recentAct = @($activity | Where-Object { $_.date -ge $weekAgo })
$sumSessions = [int](($recentAct | Measure-Object sessions -Sum).Sum)
$sumTagged = [int](($recentAct | Measure-Object tagged -Sum).Sum)
$avgSaving = if ($products.Count) { R2 (($products | Measure-Object saving_pct -Average).Average) } else { 0 }

$data = [ordered]@{
  generated = (Get-Date -Format 'yyyy-MM-dd HH:mm')
  generated_utc = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
  label = $Label
  live = $live
  github = $github
  sessions = $sessions
  focus = $pipeline.focus
  target = $pipeline.target
  team = $team
  people = $people
  summary = [ordered]@{
    avg_product_saving_pct = $avgSaving
    tools_by_status = $byStatus
    contracts = @($tools | Where-Object { $_.line -eq 'contract' }).Count
    tools = @($tools | Where-Object { $_.line -eq 'tool' }).Count
    tests_7d = $recentTests.Count
    sessions_7d = $sumSessions
    tagged_7d = $sumTagged
    minutes_7d = [int](($recentAct | Measure-Object minutes -Sum).Sum)
    active_people_7d = @($recentAct | Where-Object { $_.sessions -gt 0 } | ForEach-Object { $_.user } | Sort-Object -Unique).Count
  }
  products = $products
  cells = $cells
  tools = $tools
  tests = $tests
  contributions = $contrib
  backlog = $backlogOut
  top = $top
  activity = $activity
  feed = $feed
}
New-Item -ItemType Directory -Force $OutDir | Out-Null
$json = $data | ConvertTo-Json -Depth 12
[IO.File]::WriteAllText((Join-Path $OutDir 'data.json'), $json, $utf8)

# ---- dashboard.html -----------------------------------------------------------------------
$tpl = [IO.File]::ReadAllText((Join-Path $repo 'status\dashboard.template.html'), $enc)
[IO.File]::WriteAllText((Join-Path $OutDir 'dashboard.html'), $tpl.Replace('/*__DATA__*/null', $json), $utf8)

# ---- STATUS.md ----------------------------------------------------------------------------
$st = [ordered]@{ 'not-in-repo'='нет в репо'; 'draft'='черновик'; 'measured'='замерен'; 'cross-tested'='проверен коллегой'; 'accepted'='принят' }
$sb = New-Object System.Text.StringBuilder
function L($s) { [void]$sb.AppendLine($s) }
function Who($id) { if ($id -and $team.Contains($id)) { $team[$id] } elseif ($id) { $id } else { '—' } }
L "# Статус NTR — ИИ в производстве"
L ""
L "_Сгенерировано $($data.generated) скриптом ``scripts/ntr-status.ps1``. Руками не править. Визуально: ``status/dashboard.html``._ $Label"
L ""
L "## Типовой проект: было → стало (только замеры)"
L "| Продукт | Было | Стало | Экономия | Ещё по оценкам |"
L "|---|---|---|---|---|"
foreach ($p in $products) { L "| $($p.title) | $($p.hours) ч | $($p.after_h) ч | **$($p.saving_pct)%** (−$($p.saved_h) ч) | −$($p.est_h) ч |" }
L ""
L "Цель: $($pipeline.target.project_saving_pct)% — $($pipeline.target.why)"
L ""
L "## Кто что внёс"
L "| Кто | Сэкономил часов (на 3 типовых проекта) | Контрактов / скриптов | Проверил чужих | Минут с агентом (7 дн) |"
L "|---|---|---|---|---|"
foreach ($c in $contrib) { L "| $(Who $c.user) | $($c.saving_pct) ч | $($c.contracts) / $($c.scripts) | $($c.tests_done) | $($c.minutes_7d) |" }
if ($top.Count) {
  L ""
  L "## Топ-10 станций (ячейка × этап; задачи Trello сгруппированы, снимок $($backlog.snapshot))"
  L "| # | Станция | Открыто задач | В работе / проверка | P1 | Кто | Инструменты |"
  L "|---|---|---|---|---|---|---|"
  $i = 0; foreach ($t in $top) { $i++; L "| $i | $($t.cell) / $($t.stage) | $($t.open) | $($t.in_progress) / $($t.review) | $($t.p1) | $((@($t.owners) | ForEach-Object { Who $_ }) -join ', ') | $(@($t.tools) -join ', ') |" }
}
L ""
L "## Инструменты"
foreach ($line in @(@('contract','Линия 1 — контракты для агента'), @('tool','Линия 2 — тулза NTR (Max / Blender)'), @('infra','Инфраструктура'))) {
  L ""
  L "### $($line[1])"
  L "| Инструмент | Для чего | Автор | Этап | Статус | Проверили |"
  L "|---|---|---|---|---|---|"
  foreach ($t in $tools | Where-Object { $_.line -eq $line[0] } | Sort-Object cell, stage) {
    $who = if ($t.testers.Count) { ($t.testers | ForEach-Object { Who $_ }) -join ', ' } else { '—' }
    L "| $($t.title) | $($t.purpose) | $(Who $t.author) | $($t.cell)/$($t.stage) | $($st[$t.status]) | $who |"
  }
}
$statusPath = if ($OutDir -eq (Join-Path $repo 'status')) { Join-Path $repo 'STATUS.md' } else { Join-Path $OutDir 'STATUS.md' }
[IO.File]::WriteAllText($statusPath, $sb.ToString(), $utf8)
Write-Output "status: $statusPath; $OutDir\dashboard.html ($($tools.Count) tools, $(@($tools | Where-Object { $_.in_branch }).Count) only in branches; $($sessions.Count) sessions, $($live.examples) example; $($branches.Count) work branches of $($refs.Count) remote, $(@($github.prs_open).Count) open PRs, gh=$ghOk; $($activity.Count) journal days, top $($top.Count))"
