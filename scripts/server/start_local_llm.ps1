param(
    [ValidateSet('gpu4k', 'cpu8k', 'gpu8k')][string]$Profile = 'gpu4k',
    [string]$RuntimeDirectory = 'D:\models\runtime\llama.cpp\b11900-cuda12.4',
    [string]$ModelPath = 'D:\models\gemma-4-12b\gemma-4-12b-it-Q4_K_M.gguf'
)
$ErrorActionPreference = 'Stop'
$profileSettings = if ($Profile -eq 'gpu4k') {
    @{ Port = 1234; Context = 4096; Layers = 99 }
} elseif ($Profile -eq 'gpu8k') {
    @{ Port = 1234; Context = 8192; Layers = 99 }
} else {
    @{ Port = 1235; Context = 8192; Layers = 0 }
}
$executable = Join-Path $RuntimeDirectory 'llama-server.exe'
if (!(Test-Path -LiteralPath $executable -PathType Leaf) -or !(Test-Path -LiteralPath $ModelPath -PathType Leaf)) {
    throw '실행 파일과 GGUF 경로를 확인하세요. 이 도구는 다운로드하지 않습니다.'
}
$port = $profileSettings.Port
$url = "http://127.0.0.1:$port"
$listener = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
if ($listener) {
    try {
        $props = Invoke-RestMethod "$url/props" -TimeoutSec 5
        $models = Invoke-RestMethod "$url/v1/models" -TimeoutSec 5
        if ($props.default_generation_settings.n_ctx -ne $profileSettings.Context -or
            'gemma-4-12b-q4' -notin @($models.data.id)) {
            throw '프로필 불일치'
        }
        Write-Output "기존 서버 재사용: $Profile / $url/v1 / gemma-4-12b-q4"
        return
    } catch {
        throw "포트 $port 사용 중입니다. 기존 서버를 자동 종료하거나 바꾸지 않습니다."
    }
}
$stateDirectory = Join-Path (Split-Path $PSScriptRoot -Parent) '.local_llm'
New-Item -ItemType Directory -Path $stateDirectory -Force | Out-Null
$serverArgs = @('-m', ('"' + $ModelPath + '"'), '--alias', 'gemma-4-12b-q4',
    '--ctx-size', $profileSettings.Context, '--gpu-layers', $profileSettings.Layers,
    '--parallel', '1', '--host', '127.0.0.1', '--port', $port,
    '--no-webui', '--no-context-shift', '--jinja', '--reasoning', 'off', '--threads', '8')
if ($Profile -in @('gpu4k', 'gpu8k')) {
    $serverArgs += @('--flash-attn', 'on', '--cache-type-k', 'q8_0', '--cache-type-v', 'q8_0')
}
$process = Start-Process -FilePath $executable -ArgumentList $serverArgs -WorkingDirectory $RuntimeDirectory -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput (Join-Path $stateDirectory "$Profile.stdout.log") `
    -RedirectStandardError (Join-Path $stateDirectory "$Profile.stderr.log")
@{ pid = $process.Id; profile = $Profile; model = $ModelPath; url = "$url/v1"; arguments = $serverArgs } |
    ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $stateDirectory "$Profile.json") -Encoding UTF8
Write-Output "모델 서버 시작 요청: $Profile / PID $($process.Id) / $url/v1"
Write-Output '로딩 완료 후 앱을 직접 실행하세요. 앱과 브라우저는 이 도구가 실행하지 않습니다.'
Write-Output '종료는 작업 관리자에서 해당 PID를 확인해 수행하세요. 다른 프로세스를 자동 종료하지 않습니다.'
