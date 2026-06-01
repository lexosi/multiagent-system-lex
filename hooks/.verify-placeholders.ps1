Get-ChildItem $env:USERPROFILE\.claude\agents\*.md | ForEach-Object {
    $count = ([regex]::Matches((Get-Content $_.FullName -Raw), '\{\{paths\.[a-zA-Z_.-]+\}\}')).Count
    "$($_.Name): $count placeholders"
}
