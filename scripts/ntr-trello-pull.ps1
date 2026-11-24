<#
.SYNOPSIS
  Refreshes roadmap/backlog.json (the Trello snapshot) from the live Trello board.

.DESCRIPTION
  Needs two environment variables: TRELLO_KEY and TRELLO_TOKEN (read access to the board).
  Without them the script prints a message, leaves the snapshot untouched and exits 0.
  The token is sent in the Authorization header and is never printed.

  What is taken from Trello:  open lists and cards, card title, list (-> status), last activity,
                              checklist progress, card id (shortLink, used for matching next time).
  What is kept from the file: cell / stage (manual mapping), area, prio and owner of a card that
                              was already in the snapshot (matched by Trello id, then by title).
  owner: the "---XX" suffix of the card title through the "owners" map; else the previous owner.
  prio:  a label named 1..3 / P1..P3; else the previous value; else 2.
  New cards get cell: null, stage: null - map them by hand, the mapping survives the next pull.

  "lists" in backlog.json maps board list names to a status
  (queue | in-progress | review | ready | help | skip). Unknown lists are added with a guess -
  correct the guess in the file once, it is kept. Cards of "skip" lists are left out.

  Usage:
    $env:TRELLO_KEY = '...'; $env:TRELLO_TOKEN = '...'
    powershell -ExecutionPolicy Bypass -File scripts\ntr-trello-pull.ps1
  Offline check of the conversion (no network, no credentials):
    ... scripts\ntr-trello-pull.ps1 -FromFile lists.json -OutFile out.json
    lists.json = saved answer of GET /1/boards/<id>/lists?cards=open
#>
param(
  [string]$BoardId = '',
  [string]$FromFile = '',
  [string]$OutFile = ''
)
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$backlogPath = Join-Path $repo 'roadmap\backlog.json'
if (-not $OutFile) { $OutFile = $backlogPath }
$enc = [Text.Encoding]::UTF8
$utf8 = New-Object Text.UTF8Encoding $false

$old = [IO.File]::ReadAllText($backlogPath, $enc) | ConvertFrom-Json
if (-not $BoardId -and ([string]$old.source) -match '^trello:(.+)$') { $BoardId = $Matches[1] }

# ---- fetch ----------------------------------------------------------------------------------
if ($FromFile) {
  $text = [IO.File]::ReadAllText($FromFile, $enc)
} else {
  $key = $env:TRELLO_KEY; $token = $env:TRELLO_TOKEN
  if (-not $key -or -not $token) {
    Write-Output "trello: TRELLO_KEY / TRELLO_TOKEN are not set - snapshot of $($old.snapshot) left untouched"
    exit 0
  }
  if (-not $BoardId) { Write-Output 'trello: board id is unknown (no "source": "trello:<id>" in backlog.json) - snapshot left untouched'; exit 1 }
  [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
  $uri = "https://api.trello.com/1/boards/$BoardId/lists?filter=open&fields=name,pos&cards=open&card_fields=name,labels,dateLastActivity,badges,shortLink,pos"
  $headers = @{ Authorization = ('OAuth oauth_consumer_key="{0}", oauth_token="{1}"' -f $key, $token) }
  try {
    $resp = Invoke-WebRequest -Uri $uri -Headers $headers -UseBasicParsing -TimeoutSec 60
    $text = $enc.GetString($resp.RawContentStream.ToArray())      # PS 5.1 would mis-decode Cyrillic otherwise
  } catch {
    $code = ''
    if ($_.Exception.Response) { $code = " (HTTP $([int]$_.Exception.Response.StatusCode))" }
    Write-Output "trello: request failed$code - snapshot of $($old.snapshot) left untouched"
    exit 1
  }
}
$lists = $text | ConvertFrom-Json
$lists = @($lists) | Sort-Object { [double]$_.pos }

# ---- convert ----------------------------------------------------------------------------------
function Get-StatusGuess([string]$name) {
  $n = $name.ToLower()
  if ($n -match 'помощ|help|блок') { return 'help' }
  if ($n -match 'провер|review|тест|ревью') { return 'review' }
  if ($n -match 'обзор|правил|шаблон') { return 'skip' }
  if ($n -match 'в работе|в разработке|progress|делаю|doing') { return 'in-progress' }
  if ($n -match 'готов|done|ready|принят|сделан') { return 'ready' }
  return 'queue'
}
function Get-TitleKey([string]$t) { return (($t -replace '\s*-{2,}\s*[^\s-]{1,3}\s*$', '') -replace '\s+', ' ').Trim().ToLower() }

$owners = [ordered]@{}
if ($old.owners) { foreach ($p in $old.owners.PSObject.Properties) { $owners[$p.Name] = $p.Value } }
$listMap = [ordered]@{}
if ($old.lists) { foreach ($p in $old.lists.PSObject.Properties) { $listMap[$p.Name] = $p.Value } }

$oldItems = @($old.items)
$byId = @{}; $byTitle = @{}
foreach ($o in $oldItems) {
  if ($o.id) { $byId[[string]$o.id] = $o }
  $k = Get-TitleKey ([string]$o.title)
  if (-not $byTitle.ContainsKey($k)) { $byTitle[$k] = $o }
}

$items = @(); $n = 0; $new = 0
foreach ($list in $lists) {
  if (-not $listMap.Contains($list.name)) { $listMap[$list.name] = Get-StatusGuess $list.name }
  $status = [string]$listMap[$list.name]
  if ($status -eq 'skip') { continue }
  foreach ($card in @($list.cards) | Sort-Object { [double]$_.pos }) {
    if (-not $card) { continue }
    $name = [string]$card.name
    $title = $name; $code = $null
    if ($name -match '^(.*?)\s*-{1,}\s*([^\s-]{1,3})\s*$' -and $owners.Contains($Matches[2])) { $title = $Matches[1].Trim(); $code = $Matches[2] }
    # board convention: "<emoji> P1 · AREA · title"
    $tPrio = $null; $tArea = $null
    if ($title -match '^\S+\s*P([123])\s*·\s*(.+?)\s*·\s*(.+)$') { $tPrio = [int]$Matches[1]; $tArea = $Matches[2].Trim().ToUpper(); $title = $Matches[3].Trim() }
    $prev = $null
    if ($card.shortLink -and $byId.ContainsKey([string]$card.shortLink)) { $prev = $byId[[string]$card.shortLink] }
    else { $k = Get-TitleKey $title; if ($byTitle.ContainsKey($k)) { $prev = $byTitle[$k]; $byTitle.Remove($k) } }
    if (-not $prev) { $new++ }

    $owner = $null
    if ($code -and $owners.Contains($code)) { $owner = $owners[$code] } elseif ($prev) { $owner = $prev.owner }
    $prio = $null; $area = $null
    foreach ($lb in @($card.labels)) {
      $ln = ([string]$lb.name).Trim()
      if (-not $ln) { continue }
      if ($ln -match '^(?:P|П|prio\w*\s*|приоритет\s*)?([123])$') { $prio = [int]$Matches[1] } elseif (-not $area) { $area = $ln.ToUpper() }
    }
    if ($tArea) { $area = $tArea } elseif ($prev -and $prev.area) { $area = $prev.area }
    if ($tPrio) { $prio = $tPrio }
    if (-not $prio) { $prio = if ($prev -and $prev.prio) { [int]$prev.prio } else { 2 } }
    $upd = $card.dateLastActivity
    $upd = if ($upd -is [datetime]) { $upd.ToUniversalTime().ToString('yyyy-MM-dd') } elseif ($upd) { ([string]$upd).Substring(0, 10) } else { $null }
    $total = 0; $checked = 0
    if ($card.badges) { $total = [int]$card.badges.checkItems; $checked = [int]$card.badges.checkItemsChecked }

    $items += [ordered]@{
      n = $n; id = $card.shortLink; status = $status; prio = $prio; area = [string]$area; title = $title; owner = $owner
      upd = $upd; check = "$checked/$total"
      cell = if ($prev) { $prev.cell } else { $null }
      stage = if ($prev) { $prev.stage } else { $null }
    }
    $n++
  }
}
if (-not $items.Count) { Write-Output "trello: the board answered with 0 open cards - snapshot of $($old.snapshot) left untouched"; exit 1 }

# ---- write (same schema, one card per line) ---------------------------------------------------------
$today = (Get-Date).ToUniversalTime().ToString('yyyy-MM-dd')
$unmapped = @($items | Where-Object { -not $_.cell }).Count
$comment = "Снимок доски Trello на $today ($($items.Count) открытых карточек), получен scripts/ntr-trello-pull.ps1 - руками править только cell/stage и lists. owner - из суффикса названия (см. owners); cell/stage сопоставляются вручную и сохраняются при следующем обновлении (по id карточки, затем по названию); у новых карточек cell/stage = null. lists - колонка доски -> статус: queue | in-progress | review | ready | help | skip."
function J($v) { return (ConvertTo-Json $v -Compress -Depth 4) }
$sb = New-Object System.Text.StringBuilder
[void]$sb.Append("{`n")
[void]$sb.Append("  ""_comment"": $(J $comment),`n")
[void]$sb.Append("  ""source"": $(J "trello:$BoardId"),`n")
[void]$sb.Append("  ""snapshot"": $(J $today),`n")
[void]$sb.Append("  ""owners"": $(J $owners),`n")
[void]$sb.Append("  ""lists"": $(J $listMap),`n")
[void]$sb.Append("  ""items"": [`n")
for ($i = 0; $i -lt $items.Count; $i++) {
  $sep = if ($i -lt $items.Count - 1) { ',' } else { '' }
  [void]$sb.Append("    $(J $items[$i])$sep`n")
}
[void]$sb.Append("  ]`n}`n")
[IO.File]::WriteAllText($OutFile, $sb.ToString(), $utf8)
Write-Output "trello: $($items.Count) cards from $(@($lists).Count) lists -> $OutFile (snapshot $today; new $new, without cell/stage $unmapped)"
