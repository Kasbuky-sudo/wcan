# 发 Gitee Release：先上传附件，再创建 Release 指向它（Gitee 的附件接口挂在 Release 下，两步走）
param(
    [Parameter(Mandatory=$true)][string]$Version,
    [Parameter(Mandatory=$true)][string]$ZipPath,
    [Parameter(Mandatory=$true)][string]$Token,
    [string]$PkgPath = ''
)
$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$Owner = 'AZSongguo'; $Repo = 'wcan'
$Api = "https://gitee.com/api/v5/repos/$Owner/$Repo"
$H = @{}; $H['Authorization'] = "Bearer $Token"   # requests 风格; gitee 亦接受 access_token 参数

# 1) 创建 Release（不带附件）
$tag = "v$Version"
$sha = (git rev-parse HEAD).Trim()   # Gitee 建 Release 必须要 target_commitish
$body = @{
    tag_name         = $tag
    name             = "编舟文心 v$Version"
    body             = "更新内容见仓库 templates/changelog.html 或应用内「更新日志」。"
    target_commitish = $sha
    prerelease       = $false
} | ConvertTo-Json
try {
    # 必须显式用 UTF-8 字节发，否则 PS 5.1 会按 ANSI 编码，中文全变成 ????
    $r = Invoke-RestMethod -Method Post -Uri "$Api/releases" -Headers $H -Body ([Text.Encoding]::UTF8.GetBytes($body)) -ContentType 'application/json; charset=utf-8'
    Write-Host "  Release 已创建: $($r.tag_name)"
} catch {
    # 已存在同名 Release 则复用
    $existing = Invoke-RestMethod -Method Get -Uri "$Api/releases/tags/$tag" -Headers $H
    $r = $existing
    Write-Host "  Release 已存在，复用: $($r.tag_name)"
}
$releaseId = $r.id

# 2) 上传附件：zip 给用户下载，version.json 给应用内「检查更新」读版本号（缺了它在线更新会静默失效）
function Send-Attachment {
    param([string]$Path, [string]$ContentType)
    if (-not $Path -or -not (Test-Path $Path)) {
        Write-Host "  [跳过] 文件不存在: $Path"
        return
    }
    $file = Resolve-Path $Path
    # 附件接口只认 Authorization 头；用 ?token= 传凭据会回 40001 登录失效
    $uploadUri = "$Api/releases/$releaseId/attach_files"
    $boundary = [Guid]::NewGuid().ToString()
    $fileName = [IO.Path]::GetFileName($file)
    $bytes = [IO.File]::ReadAllBytes($file)
    $lf = "`r`n"
    $bodyParts = New-Object System.Text.StringBuilder
    [void]$bodyParts.Append("--$boundary$lf")
    [void]$bodyParts.Append("Content-Disposition: form-data; name=`"file`"; filename=`"$fileName`"$lf")
    [void]$bodyParts.Append("Content-Type: $ContentType$lf$lf")
    $headerBytes = [Text.Encoding]::UTF8.GetBytes($bodyParts.ToString())
    $tailBytes = [Text.Encoding]::UTF8.GetBytes("$lf--$boundary--$lf")
    $full = New-Object byte[] ($headerBytes.Length + $bytes.Length + $tailBytes.Length)
    [Array]::Copy($headerBytes,0,$full,0,$headerBytes.Length)
    [Array]::Copy($bytes,0,$full,$headerBytes.Length,$bytes.Length)
    [Array]::Copy($tailBytes,0,$full,$headerBytes.Length+$bytes.Length,$tailBytes.Length)
    $resp = Invoke-WebRequest -Method Post -Uri $uploadUri -Headers $H -ContentType "multipart/form-data; boundary=$boundary" -Body $full -UseBasicParsing
    if ($resp.StatusCode -in 200,201) {
        Write-Host "  附件已上传: $fileName"
    } else {
        Write-Host "  附件上传失败: $fileName ($($resp.StatusCode))"
        exit 1
    }
}

Send-Attachment -Path $ZipPath -ContentType 'application/zip'
if ($PkgPath) { Send-Attachment -Path $PkgPath -ContentType 'application/zip' }
Send-Attachment -Path (Join-Path $PSScriptRoot 'version.json') -ContentType 'application/json'
exit 0
