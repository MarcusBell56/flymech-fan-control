param(
    [string]$cmd = "OPERATING_OFFICE_MODE",
    [string]$topic = "Fan/Control"
)

try {
    $gcuDir = (Get-ChildItem -Path "C:\Program Files\OEM" -Filter "GCUService.exe" -Recurse | Select-Object -First 1).DirectoryName
    $m2mqtt = [System.IO.Path]::Combine($gcuDir, "M2Mqtt.Net.dll")
    if ([System.IO.File]::Exists($m2mqtt)) {
        [System.Reflection.Assembly]::LoadFile($m2mqtt) | Out-Null
    }

    $systray = "C:\Program Files\WindowsApps\ControlCenter3_4.17.47.13_x64__wrbgcf7aesyd8\Win32\SystrayComponent.exe"
    if (-not [System.IO.File]::Exists($systray)) {
        $systray = (Get-ChildItem -Path "C:\Program Files\WindowsApps" -Filter "SystrayComponent.exe" -Recurse | Select-Object -First 1).FullName
    }

    $asm = [System.Reflection.Assembly]::LoadFile($systray)
    $types = $asm.GetTypes()
    $mqttType = $types | Where-Object { $_.Name -eq "MQTTDatsService" }
    $instProp = $mqttType.GetProperty("Instance", [System.Reflection.BindingFlags]'Public,Static')
    $inst = $instProp.GetValue($null, $null)

    $connMethod = $mqttType.GetMethod("ClientConnection", [System.Reflection.BindingFlags]'Public,NonPublic,Instance')
    $connMethod.Invoke($inst, $null)

    # Wait for Connected == True
    $connField = $mqttType.GetField("Connected", [System.Reflection.BindingFlags]'Public,NonPublic,Instance')
    $timeout = 0
    while (-not $connField.GetValue($inst) -and $timeout -lt 30) {
        Start-Sleep -Milliseconds 100
        $timeout++
    }

    $pubMethod = $mqttType.GetMethod("PublishTopic", [System.Reflection.BindingFlags]'Public,NonPublic,Instance')
    $pubMethod.Invoke($inst, @($topic, $cmd, $false))
    Write-Host "OK:$cmd"
    Start-Sleep -Milliseconds 100
} catch {
    Write-Error $_.Exception.Message
    exit 1
}
