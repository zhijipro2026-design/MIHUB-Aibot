# 米家自动化极客版备份文件解包工具
# 格式：[4字节小端 uint32 解压后长度] + [raw DEFLATE 压缩的 JSON] + [SHA-256(前两段)]
# 用法：.\bak-unpack.ps1 -BakPath <备份.bak> [-OutPath <输出.json>] [-Pretty]
param(
    [Parameter(Mandatory = $true)][string]$BakPath,    # 输入的 .bak 备份文件路径
    [string]$OutPath,                                  # 输出 JSON 路径，缺省为同名 .json
    [switch]$Pretty                                    # 是否格式化输出 JSON（便于人工阅读）
)

if (-not (Test-Path $BakPath)) { throw "文件不存在: $BakPath" }
if (-not $OutPath) { $OutPath = [System.IO.Path]::ChangeExtension($BakPath, '.json') }

$bytes = [System.IO.File]::ReadAllBytes($BakPath)
if ($bytes.Length -lt 37) { throw ".bak 文件过短，缺少长度头、压缩数据或 SHA-256 校验尾" }
$declaredLength = [BitConverter]::ToUInt32($bytes, 0)

# 校验尾部 32 字节 SHA-256（对长度头+压缩体计算）；失败立即停止
$bodyLength = $bytes.Length - 32
$body = New-Object byte[] $bodyLength
[Array]::Copy($bytes, 0, $body, 0, $bodyLength)
$tail = New-Object byte[] 32
[Array]::Copy($bytes, $bodyLength, $tail, 0, 32)
$sha = [System.Security.Cryptography.SHA256]::Create()
$digest = $sha.ComputeHash($body)
$tailHex = ($tail | ForEach-Object { $_.ToString('X2') }) -join ''
$digestHex = ($digest | ForEach-Object { $_.ToString('X2') }) -join ''
if ($tailHex -ne $digestHex) { throw "SHA-256 校验失败；拒绝解包" }

# 跳过 4 字节头部，对压缩体做 raw DEFLATE 解压
$compLength = $bodyLength - 4
$comp = New-Object byte[] $compLength
[Array]::Copy($bytes, 4, $comp, 0, $compLength)
$ms = New-Object System.IO.MemoryStream(, $comp)
$ds = New-Object System.IO.Compression.DeflateStream($ms, [System.IO.Compression.CompressionMode]::Decompress)
$out = New-Object System.IO.MemoryStream
$ds.CopyTo($out)
$ds.Dispose()

if ($out.Length -ne $declaredLength) { throw "解压长度 $($out.Length) 与头部声明 $declaredLength 不一致；拒绝输出" }

$json = [System.Text.Encoding]::UTF8.GetString($out.ToArray())
if ($Pretty) { $json = ($json | ConvertFrom-Json) | ConvertTo-Json -Depth 50 }

[System.IO.File]::WriteAllText($OutPath, $json, (New-Object System.Text.UTF8Encoding($false)))
Write-Output "解包完成: $OutPath (JSON $($out.Length) 字节, SHA-256校验通过: $($tailHex -eq $digestHex))"
