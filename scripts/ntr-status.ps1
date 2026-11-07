<#
.SYNOPSIS
  Builds the NTR status report from repo data: STATUS.md, status/data.json, status/dashboard.html.
  Generated files - do not edit by hand.

.DESCRIPTION
  Sources:
    team.md                    people (id, name, Trello code, shown in report)
    roadmap/pipeline.json      products, cells, stages, shares, focus, target
    roadmap/backlog.json       Trello snapshot: tasks, priorities, owners, mapped to cells/stages
    registry/tools/*.md        tool / contract cards (front matter)
    registry/tests/*.md        cross-test reports (front matter)
    journal/<date>/<user>.md   daily journals from scripts/ntr-daily.ps1 (branch 'journal')

  Savings count only cards with status measured|cross-tested|accepted and time_source: measured.
  Per stage only the best tool counts (no double counting); its author gets the contribution.

  Usage (maintainer PC, nightly or before the weekly meeting):
    powershell -ExecutionPolicy Bypass -File scripts\ntr-status.ps1 [-JournalRoot ..\NTR_AI-journal\journal] [-Days 14]
#>
param(
  [string]$JournalRoot = '',
  [int]$Days = 14,
  [string]$OutDir = '',
  [string]$Label = ''
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

function Read-FrontMatter([string]$path) {
  $h = [ordered]@{}; $body = New-Object System.Collections.Generic.List[string]
  $in = $false; $done = $false
  foreach ($l in [IO.File]::ReadAllLines($path, $enc)) {
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

# ---- registry -------------------------------------------------------------------------------
$tests = @()
foreach ($f in Get-ChildItem (Join-Path $repo 'registry\tests') -Filter *.md -ErrorAction SilentlyContinue) {
  $t = Read-FrontMatter $f.FullName
  if ($t.tool) { $tests += [pscustomobject]@{ tool=$t.tool; tester=$t.tester; date=$t.date; project=$t.project; result=$t.result } }
}
$measuredStatuses = @('measured','cross-tested','accepted')
$tools = @()
foreach ($f in Get-ChildItem (Join-Path $repo 'registry\tools') -Filter *.md) {
  $c = Read-FrontMatter $f.FullName
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
  foreach ($g in ($items | Where-Object { $_.cell -ne 'infra' } | Group-Object { "$($_.cell)/$($_.stage)" })) {
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
  $backlogOut = [ordered]@{ snapshot=$backlog.snapshot; source=$backlog.source; total=$items.Count; stations=$stations.Count; by_status=$byList; by_owner=$byOwner; items=$items }
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

# ---- people contributions ------------------------------------------------------------------
$weekAgo = (Get-Date).Date.AddDays(-6).ToString('yyyy-MM-dd')
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
  label = $Label
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
Write-Output "status: $statusPath; $OutDir\dashboard.html ($($tools.Count) tools, $($activity.Count) journal days, top $($top.Count))"
