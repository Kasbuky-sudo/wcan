# 发 GitHub Release：建 Release（必须带 target_commitish）→ 上传 exe zip、源码更新包、version.json
# 没显式给 -Token 时，自动用 git 凭据管理器里那份（也就是 git push 用的同一个），无需另外配置
param(
    [Parameter(Mandatory=$true)][string]$Version,
    [Parameter(Mandatory=$true)][string]$ZipPath,
    [string]$PkgPath = '',
    [string]$Token = ''
)
$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

if (-not $Token) {
    $line = (("protocol=https`nhost=github.com`n`n" | git credential fill) |
             Select-String -Pattern '^password=' | Select-Object -First 1)
    if ($line) { $Token = ($line.Line -replace '^password=', '') }
}
if (-not $Token) {
    Write-Host "  [错误] 没有 GitHub 令牌：设置 GITHUB_TOKEN，或先让 git 记住 github.com 的凭据"
    exit 1
}

$Owner = 'Kasbuky-sudo'; $Repo = 'wcan'
$Api = "https://api.github.com/repos/$Owner/$Repo"
$H = @{}
$H['Authorization'] = "Bearer $Token"
$H['Accept'] = 'application/vnd.github+json'
$H['User-Agent'] = 'WCAN-Releaser'

$tag = "v$Version"
$sha = (git rev-parse HEAD).Trim()

# 1) 建 Release（同名已存在就复用）
$payload = @{
    tag_name         = $tag
    name             = "编舟文心 v$Version"
    body             = "更新内容见仓库 templates/changelog.html 或应用内「更新日志」。"
    target_commitish = $sha
    draft            = $false
    prerelease       = $false
} | ConvertTo-Json

try {
    # 必须按 UTF-8 字节发，否则中文标题/说明会变成 ????
    $r = Invoke-RestMethod -Method Post -Uri "$Api/releases" -Headers $H `
         -Body ([Text.Encoding]::UTF8.GetBytes($payload)) -ContentType 'application/json; charset=utf-8'
    $releaseId = $r.id
    Write-Host "  Release 已创建: $($r.tag_name)"
} catch {
    try {
        $r = Invoke-RestMethod -Method Get -Uri "$Api/releases/tags/$tag" -Headers $H
        $releaseId = $r.id
        Write-Host "  Release 已存在，复用: $($r.tag_name)"
    } catch {
        Write-Host "  [错误] 建 Release 失败: $_"
        exit 1
    }
}

# 2) 上传附件
function Send-GhAsset {
    param([string]$Path, [string]$ContentType)
    if (-not $Path -or -not (Test-Path $Path)) {
        Write-Host "  [跳过] 文件不存在: $Path"
        return
    }
    $file = Resolve-Path $Path
    $name = [IO.Path]::GetFileName($file)
    $uri = "https://uploads.github.com/repos/$Owner/$Repo/releases/$releaseId/assets?name=$([Uri]::EscapeDataString($name))"
    try {
        Invoke-RestMethod -Method Post -Uri $uri -Headers $H -ContentType $ContentType -InFile $file | Out-Null
        Write-Host "  附件已上传: $name"
    } catch {
        Write-Host "  [错误] 附件上传失败: $name -> $_"
        exit 1
    }
}

Send-GhAsset -Path $ZipPath -ContentType 'application/zip'
if ($PkgPath) { Send-GhAsset -Path $PkgPath -ContentType 'application/zip' }
Send-GhAsset -Path (Join-Path $PSScriptRoot 'version.json') -ContentType 'application/json'
exit 0
