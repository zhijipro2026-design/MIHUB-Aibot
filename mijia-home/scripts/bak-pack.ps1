# 米家自动化极客版备份文件打包工具
# 格式：[4字节小端 uint32 解压后长度] + [raw DEFLATE 压缩的 JSON] + [SHA-256(前两段)]
# 用法：.\bak-pack.ps1 -JsonPath <规则.json> [-OutPath <输出.bak>]
param(
    [Parameter(Mandatory = $true)][string]$JsonPath,   # 输入的规则 JSON 文件路径
    [string]$OutPath                                   # 输出 .bak 路径，缺省为同名 .bak
)

if (-not (Test-Path $JsonPath)) { throw "文件不存在: $JsonPath" }
if (-not $OutPath) { $OutPath = [System.IO.Path]::ChangeExtension($JsonPath, '.bak') }

# 校验 JSON 合法性，并压缩为单行（与官方导出格式一致）
$jsonText = Get-Content $JsonPath -Raw -Encoding UTF8
$jsonText = ($jsonText | ConvertFrom-Json) | ConvertTo-Json -Depth 50 -Compress

$payload = [System.Text.Encoding]::UTF8.GetBytes($jsonText)
$ms = New-Object System.IO.MemoryStream
$ds = New-Object System.IO.Compression.DeflateStream($ms, [System.IO.Compression.CompressionLevel]::Optimal, $true)
$ds.Write($payload, 0, $payload.Length)
$ds.Dispose()
$compressed = $ms.ToArray()

# 拼装：4 字节小端长度头 + 压缩体
$header = [BitConverter]::GetBytes([uint32]$payload.Length)
$body = New-Object byte[] ($header.Length + $compressed.Length)
$header.CopyTo($body, 0)
$compressed.CopyTo($body, 4)

# 追加 SHA-256(长度头 + 压缩体) 作为完整性校验尾（缺失则网关导入时无响应）
$sha = [System.Security.Cryptography.SHA256]::Create()
$digest = $sha.ComputeHash($body)
$outBytes = New-Object byte[] ($body.Length + 32)
$body.CopyTo($outBytes, 0)
$digest.CopyTo($outBytes, $body.Length)

[System.IO.File]::WriteAllBytes($OutPath, $outBytes)
Write-Output "打包完成: $OutPath (JSON $($payload.Length) 字节 -> bak $($outBytes.Length) 字节, 含SHA-256校验尾)"
