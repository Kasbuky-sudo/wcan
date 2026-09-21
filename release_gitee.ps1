# 发 Gitee Release：先上传附件，再创建 Release 指向它（Gitee 的附件接口挂在 Release 下，两步走）
param(
    [Parameter(Mandatory=$true)][string]$Version,
    [Parameter(Mandatory=$true)][string]$ZipPath,
    [Parameter(Mandatory=$true)][string]$Token
)
$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$Owner = 'AZSongguo'; $Repo = 'wcan'
$Api = "https://gitee.com/api/v5/repos/$Owner/$Repo"
$H = @{}; $H['Authorization'] = "Bearer $Token"   # requests 风格; gitee 亦接受 access_token 参数

# 1) 创建 Release（不带附件）
$tag = "v$Version"
$body = @{
    tag_name    = $tag
    name        = "编舟文心 v$Version"
    body        = "更新内容见仓库 templates/changelog.html 或应用内「更新日志」。"
    prerelease  = $false
} | ConvertTo-Json
try {
    $r = Invoke-RestMethod -Method Post -Uri "$Api/releases" -Headers $H -Body $body -ContentType 'application/json'
    Write-Host "  Release 已创建: $($r.tag_name)"
} catch {
    # 已存在同名 Release 则复用
    $existing = Invoke-RestMethod -Method Get -Uri "$Api/releases/tags/$tag" -Headers $H
    $r = $existing
    Write-Host "  Release 已存在，复用: $($r.tag_name)"
}
$releaseId = $r.id

# 2) 上传 zip 附件
$zipFile = Resolve-Path $ZipPath
$uploadUri = "$Api/releases/$releaseId/attach_files?token=$Token"
$boundary = [Guid]::NewGuid().ToString()
$fileName = [IO.Path]::GetFileName($zipFile)
$bytes = [IO.File]::ReadAllBytes($zipFile)
$lf = "`r`n"
$bodyParts = New-Object System.Text.StringBuilder
[void]$bodyParts.Append("--$boundary$lf")
[void]$bodyParts.Append("Content-Disposition: form-data; name=`"file`"; filename=`"$fileName`"$lf")
[void]$bodyParts.Append("Content-Type: application/zip$lf$lf")
$headerBytes = [Text.Encoding]::UTF8.GetBytes($bodyParts.ToString())
$tailBytes = [Text.Encoding]::UTF8.GetBytes("$lf--$boundary--$lf")
$full = New-Object byte[] ($headerBytes.Length + $bytes.Length + $tailBytes.Length)
[Array]::Copy($headerBytes,0,$full,0,$headerBytes.Length)
[Array]::Copy($bytes,0,$full,$headerBytes.Length,$bytes.Length)
[Array]::Copy($tailBytes,0,$full,$headerBytes.Length+$bytes.Length,$tailBytes.Length)
$resp = Invoke-WebRequest -Method Post -Uri $uploadUri -ContentType "multipart/form-data; boundary=$boundary" -Body $full -UseBasicParsing
if ($resp.StatusCode -in 200,201) {
    Write-Host "  附件已上传: $fileName"
} else {
    Write-Host "  附件上传失败: $($resp.StatusCode)"
    exit 1
}
exit 0
