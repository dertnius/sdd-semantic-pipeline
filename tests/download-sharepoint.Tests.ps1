<#
    Pester unit tests for gitlab/ci-component/scripts/download-sharepoint.ps1.

    Dot-sources the script (its main-guard prevents the download from running) and tests the
    pure helpers in isolation — no network, no SharePoint tenant. The PnP connect path is
    exercised against a local stub of Connect-PnPOnline so the auth-branch selection is
    verified without the PnP.PowerShell module.

    Run:  pwsh -NoProfile -Command "Invoke-Pester -Path tests -CI"
    (Read-SharePointManifest tests need the powershell-yaml module; they self-skip if absent.)
#>

# Computed at DISCOVERY time so the -Skip below sees it (BeforeAll runs later, at run time).
$HasYaml = $null -ne (Get-Module -ListAvailable -Name powershell-yaml)

BeforeAll {
    $script:ScriptPath = (Resolve-Path (Join-Path $PSScriptRoot '..' 'gitlab' 'ci-component' 'scripts' 'download-sharepoint.ps1')).Path
    . $script:ScriptPath          # main-guard => functions only, no execution
}

Describe 'Get-LocalTargetPath' {
    It 'strips the web root and joins under the destination root' {
        $p = Get-LocalTargetPath -DestRoot '/inbox/sp' -WebRoot '/sites/Arch' -ServerUrl '/sites/Arch/Shared Documents/SAD/a.docx'
        $expected = (Join-Path '/inbox/sp' (Join-Path 'Shared Documents' (Join-Path 'SAD' 'a.docx')))
        $p | Should -Be $expected
    }

    It 'is case-insensitive about the web root prefix' {
        $p = Get-LocalTargetPath -DestRoot '/inbox/sp' -WebRoot '/sites/Arch' -ServerUrl '/SITES/ARCH/x.txt'
        $p | Should -Be (Join-Path '/inbox/sp' 'x.txt')
    }

    It 'refuses path traversal in the server URL' {
        { Get-LocalTargetPath -DestRoot '/inbox/sp' -WebRoot '/sites/Arch' -ServerUrl '/sites/Arch/../evil/x' } |
            Should -Throw -ExpectedMessage '*traversal*'
    }
}

Describe 'Test-IncludedExtension' {
    It 'includes everything when no filter is given' {
        Test-IncludedExtension -FileName 'a.png' -Include @() | Should -BeTrue
        Test-IncludedExtension -FileName 'a.png' -Include $null | Should -BeTrue
    }
    It 'includes only matching extensions when a filter is given' {
        Test-IncludedExtension -FileName 'a.docx' -Include @('docx', 'pdf') | Should -BeTrue
        Test-IncludedExtension -FileName 'a.png'  -Include @('docx', 'pdf') | Should -BeFalse
    }
    It 'tolerates a leading dot in the filter' {
        Test-IncludedExtension -FileName 'a.pdf' -Include @('.pdf') | Should -BeTrue
    }
}

Describe 'New-DownloadReport' {
    It 'counts ok and error records' {
        $results = @(
            [pscustomobject]@{ status = 'ok' }, [pscustomobject]@{ status = 'ok' },
            [pscustomobject]@{ status = 'error' }
        )
        $r = New-DownloadReport -Results $results -AuthMode 'secret' -DryRun $false
        $r.total | Should -Be 3
        $r.ok | Should -Be 2
        $r.errors | Should -Be 1
        $r.auth_mode | Should -Be 'secret'
    }
}

Describe 'Read-SharePointManifest' -Skip:(-not $HasYaml) {
    BeforeAll {
        Import-Module powershell-yaml -ErrorAction SilentlyContinue   # Read-SharePointManifest calls ConvertFrom-Yaml
        $script:tmp = Join-Path ([IO.Path]::GetTempPath()) ("spm-" + [Guid]::NewGuid().ToString('N') + ".yaml")
    }
    AfterEach { if (Test-Path $script:tmp) { Remove-Item $script:tmp -Force } }

    It 'parses entries and applies recurse/dest defaults' {
        @'
entries:
  - site: "https://t.sharepoint.com/sites/A"
    folder: "Shared Documents/SAD"
  - site: "https://t.sharepoint.com/sites/B"
    folder: "Docs/ADRs"
    dest: "sharepoint/custom"
    recurse: false
'@ | Set-Content -LiteralPath $script:tmp -Encoding utf8
        $e = Read-SharePointManifest -Path $script:tmp
        $e.Count | Should -Be 2
        $e[0].dest | Should -Be 'sharepoint/SAD'
        $e[0].recurse | Should -BeTrue
        $e[1].dest | Should -Be 'sharepoint/custom'
        $e[1].recurse | Should -BeFalse
    }

    It 'throws when an entry is missing site or folder' {
        "entries:`n  - site: `"https://t/sites/A`"`n" | Set-Content -LiteralPath $script:tmp -Encoding utf8
        { Read-SharePointManifest -Path $script:tmp } | Should -Throw
    }

    It 'throws when the manifest file is missing' {
        { Read-SharePointManifest -Path (Join-Path ([IO.Path]::GetTempPath()) 'does-not-exist.yaml') } | Should -Throw
    }
}

Describe 'Connect-ToSite (auth-branch selection, stubbed PnP)' {
    BeforeAll {
        # Stub Connect-PnPOnline so we can assert which parameters each mode passes.
        function Connect-PnPOnline {
            param(
                [string]$Url, [string]$ClientId, [string]$ClientSecret, [string]$Tenant,
                [string]$CertificateBase64Encoded, $CertificatePassword,
                [switch]$ManagedIdentity, [string]$UserAssignedManagedIdentityClientId, $ErrorAction
            )
            $script:LastConnect = $PSBoundParameters
        }
    }
    AfterEach {
        Remove-Item Env:SHAREPOINT_CLIENT_SECRET -ErrorAction SilentlyContinue
        Remove-Item Env:SHAREPOINT_CERT_BASE64 -ErrorAction SilentlyContinue
        $script:LastConnect = $null
    }

    It 'secret mode passes -ClientSecret from the environment' {
        $env:SHAREPOINT_CLIENT_SECRET = 'topsecret'
        Connect-ToSite -Site 'https://t/sites/A' -AuthMode 'secret' -ClientId 'cid'
        $script:LastConnect.ClientSecret | Should -Be 'topsecret'
        $script:LastConnect.ContainsKey('Tenant') | Should -BeFalse
    }

    It 'secret mode throws when the secret env var is absent' {
        { Connect-ToSite -Site 'https://t/sites/A' -AuthMode 'secret' -ClientId 'cid' } |
            Should -Throw -ExpectedMessage '*SHAREPOINT_CLIENT_SECRET*'
    }

    It 'certificate mode requires -Tenant' {
        $env:SHAREPOINT_CERT_BASE64 = 'YmFzZTY0'
        { Connect-ToSite -Site 'https://t/sites/A' -AuthMode 'certificate' -ClientId 'cid' } |
            Should -Throw -ExpectedMessage '*Tenant*'
    }

    It 'managedidentity mode passes -ManagedIdentity with the UAMI client id' {
        Connect-ToSite -Site 'https://t/sites/A' -AuthMode 'managedidentity' -UamiClientId 'uami-cid'
        $script:LastConnect.ManagedIdentity | Should -BeTrue
        $script:LastConnect.UserAssignedManagedIdentityClientId | Should -Be 'uami-cid'
    }
}
