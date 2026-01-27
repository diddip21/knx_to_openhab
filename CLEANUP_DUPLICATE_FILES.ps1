#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Clean up duplicate files and directories that were copied to src/ during migration
    
.DESCRIPTION
    This script removes files that were copied during the package restructuring:
    - Python modules (config, utils, ets_helpers, ets_to_openhab → generator, knxproject_to_openhab → knxproject)
    - Template files (items.template, things.template, sitemap.template)
    - Web UI directory
    - Optional files (cli.py, gunicorn_conf.py if they exist)
    
    The src/ versions are the source of truth and contain more recent/fixed versions.
    
.PARAMETER Force
    Skip confirmation prompt and delete immediately
    
.EXAMPLE
    .\\CLEANUP_DUPLICATE_FILES.ps1
    
#>

param(
    [switch]$Force
)

# Color codes for output
$GREEN = "`e[32m"
$YELLOW = "`e[33m"
$RED = "`e[31m"
$BLUE = "`e[34m"
$NC = "`e[0m"  # No Color

Write-Host "$BLUE╔════════════════════════════════════════════════════════════════╗$NC"
Write-Host "$BLUE║                  CLEANUP DUPLICATE FILES - PHASE 7              ║$NC"
Write-Host "$BLUE║                  Remove copied root files                       ║$NC"
Write-Host "$BLUE╚════════════════════════════════════════════════════════════════╝$NC"
Write-Host ""

# Check if we're in the right repository
if (-not (Test-Path ".git" -Type Container)) {
    Write-Host "$RED✗ Error: This doesn't appear to be a Git repository$NC"
    Write-Host "$RED  Please run this script from the repository root directory$NC"
    exit 1
}

# Check current branch
$currentBranch = git rev-parse --abbrev-ref HEAD 2>$null
if ($currentBranch -ne "feature/professional-restructuring") {
    Write-Host "$YELLOW⚠ Warning: You're not on the correct branch!$NC"
    Write-Host "  Current branch: $YELLOW$currentBranch$NC"
    Write-Host "  Expected: feature/professional-restructuring"
    Write-Host ""
    Write-Host "Switch to correct branch first:"
    Write-Host "  git checkout feature/professional-restructuring"
    Write-Host ""
    
    if (-not $Force) {
        $response = Read-Host "Continue anyway? (Y/N)"
        if ($response -ne "Y" -and $response -ne "y") {
            exit 1
        }
    }
}

Write-Host "$BLUE→ Step 1: Pull latest changes from origin$NC"
try {
    git pull origin feature/professional-restructuring 2>&1 | Out-Null
    Write-Host "$GREEN✓ Pulled latest changes$NC"
}
catch {
    Write-Host "$RED✗ Failed to pull changes: $_$NC"
    exit 1
}

Write-Host ""
Write-Host "$BLUE→ Step 2: Identify files to delete$NC"

# Define files and directories to delete
$filesToDelete = @(
    # Python modules (Phase 1)
    'config.py',
    'utils.py',
    'ets_helpers.py',
    
    # Main generator and project module (Phase 2-3)
    'ets_to_openhab.py',                    # Renamed to generator.py in src/
    'knxproject_to_openhab.py',             # Renamed to knxproject.py in src/
    
    # Template files (Phase 2) - IMPORTANT!
    'items.template',
    'things.template',
    'sitemap.template',
    
    # CLI and gunicorn (Phase 5) - if they exist
    'cli.py',
    'gunicorn_conf.py'
)

$directoriesDelete = @(
    'web_ui'                                # Complete directory moved to src/
)

# Check which files actually exist
$existingFiles = @()
$missingFiles = @()

foreach ($file in $filesToDelete) {
    if (Test-Path $file -Type Leaf) {
        $existingFiles += $file
        $size = (Get-Item $file).Length
        Write-Host "$GREEN✓ Found: $file$NC ($size bytes)"
    } else {
        $missingFiles += $file
    }
}

Write-Host ""
Write-Host "$BLUE→ Step 3: Check directories$NC"

$existingDirs = @()
foreach ($dir in $directoriesDelete) {
    if (Test-Path $dir -Type Container) {
        $existingDirs += $dir
        $itemCount = (Get-ChildItem $dir -Recurse | Measure-Object).Count
        Write-Host "$GREEN✓ Found: $dir/$NC ($itemCount items)"
    }
}

Write-Host ""
Write-Host "$YELLOW╔════════════════════════════════════════════════════════════════╗$NC"
Write-Host "$YELLOW║                    FILES TO DELETE                             ║$NC"
Write-Host "$YELLOW╚════════════════════════════════════════════════════════════════╝$NC"
Write-Host ""
Write-Host "Python Modules:"
foreach ($file in @('config.py', 'utils.py', 'ets_helpers.py', 'ets_to_openhab.py', 'knxproject_to_openhab.py')) {
    if ($existingFiles -contains $file) {
        Write-Host "  $GREEN✓$NC $file"
    } else {
        Write-Host "  $YELLOW·$NC $file (not found)"
    }
}

Write-Host ""
Write-Host "Template Files:"
foreach ($file in @('items.template', 'things.template', 'sitemap.template')) {
    if ($existingFiles -contains $file) {
        Write-Host "  $GREEN✓$NC $file"
    } else {
        Write-Host "  $YELLOW·$NC $file (not found)"
    }
}

Write-Host ""
Write-Host "Optional Files:"
foreach ($file in @('cli.py', 'gunicorn_conf.py')) {
    if ($existingFiles -contains $file) {
        Write-Host "  $GREEN✓$NC $file"
    } else {
        Write-Host "  $YELLOW·$NC $file (not found)"
    }
}

Write-Host ""
Write-Host "Directories:"
foreach ($dir in $directoriesDelete) {
    if ($existingDirs -contains $dir) {
        Write-Host "  $GREEN✓$NC $dir/"
    } else {
        Write-Host "  $YELLOW·$NC $dir/ (not found)"
    }
}

Write-Host ""
Write-Host "Summary:"
Write-Host "  Files to delete: $($existingFiles.Count) found, $($missingFiles.Count) not found"
Write-Host "  Directories to delete: $($existingDirs.Count) found"
Write-Host ""

# Confirmation
if (-not $Force) {
    Write-Host "$YELLOW━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━$NC"
    Write-Host ""
    Write-Host "$YELLOW⚠ This will DELETE the above files and directories!$NC"
    Write-Host "$YELLOW⚠ These files are duplicates - the real versions are in src/$NC"
    Write-Host ""
    Write-Host "The changes will be:"
    Write-Host "  1. Delete $($existingFiles.Count + $existingDirs.Count) items from root"
    Write-Host "  2. Stage all changes: git add -A"
    Write-Host "  3. Create commit: 'cleanup: Remove duplicate files from root'"
    Write-Host "  4. Push to origin: git push origin feature/professional-restructuring"
    Write-Host ""
    Write-Host "$YELLOW━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━$NC"
    Write-Host ""
    
    $response = Read-Host "Continue with cleanup? (Type 'Y' to confirm)"
    if ($response -ne "Y" -and $response -ne "y") {
        Write-Host "$YELLOW✗ Cleanup cancelled$NC"
        exit 0
    }
}

Write-Host ""
Write-Host "$BLUE→ Step 4: Delete files and directories$NC"

# Delete files
$deletedCount = 0
foreach ($file in $existingFiles) {
    try {
        Remove-Item $file -Force -ErrorAction Stop
        Write-Host "$GREEN✓$NC Deleted: $file"
        $deletedCount++
    }
    catch {
        Write-Host "$RED✗$NC Failed to delete $file : $_"
    }
}

# Delete directories
foreach ($dir in $existingDirs) {
    try {
        Remove-Item $dir -Recurse -Force -ErrorAction Stop
        Write-Host "$GREEN✓$NC Deleted: $dir/"
        $deletedCount++
    }
    catch {
        Write-Host "$RED✗$NC Failed to delete $dir : $_"
    }
}

Write-Host ""
Write-Host "$GREEN✓ Deleted $deletedCount items$NC"

Write-Host ""
Write-Host "$BLUE→ Step 5: Stage all changes$NC"
try {
    git add -A 2>&1 | Out-Null
    Write-Host "$GREEN✓ Staged all changes$NC"
}
catch {
    Write-Host "$RED✗ Failed to stage changes: $_$NC"
    exit 1
}

Write-Host ""
Write-Host "$BLUE→ Step 6: Create commit$NC"
try {
    git commit -m "cleanup: Remove duplicate files from root that were migrated to src/ in phases 1-3

- Remove Python modules: config.py, utils.py, ets_helpers.py
- Remove renamed modules: ets_to_openhab.py → generator.py, knxproject_to_openhab.py → knxproject.py
- Remove template files: items.template, things.template, sitemap.template
- Remove web_ui/ directory (now in src/knx_to_openhab/web_ui/)
- Keep root copies: setup.py, config.json, MANIFEST.in, etc.

All source-of-truth files are now in src/knx_to_openhab/
Phase 6 verified all files are correctly migrated with proper imports.
Ready for Phase 7 testing and v2.0.0 release." 2>&1 | Out-Null
    Write-Host "$GREEN✓ Created commit$NC"
}
catch {
    Write-Host "$RED✗ Failed to create commit: $_$NC"
    exit 1
}

Write-Host ""
Write-Host "$BLUE→ Step 7: Push to origin$NC"
try {
    git push origin feature/professional-restructuring 2>&1 | Out-Null
    Write-Host "$GREEN✓ Pushed to origin$NC"
}
catch {
    Write-Host "$RED✗ Failed to push to origin: $_$NC"
    exit 1
}

Write-Host ""
Write-Host "$BLUE→ Step 8: Verify cleanup$NC"

# Verify files are gone
$verifyFailed = $false
foreach ($file in $existingFiles) {
    if (Test-Path $file -Type Leaf) {
        Write-Host "$RED✗$NC File still exists: $file"
        $verifyFailed = $true
    }
}

foreach ($dir in $existingDirs) {
    if (Test-Path $dir -Type Container) {
        Write-Host "$RED✗$NC Directory still exists: $dir"
        $verifyFailed = $true
    }
}

if ($verifyFailed) {
    Write-Host "$RED✗ Verification failed!$NC"
    exit 1
}

Write-Host "$GREEN✓ All files successfully deleted$NC"
Write-Host "$GREEN✓ All directories successfully deleted$NC"

Write-Host ""
Write-Host "$GREEN╔════════════════════════════════════════════════════════════════╗$NC"
Write-Host "$GREEN║               ✓ CLEANUP COMPLETED SUCCESSFULLY                ║$NC"
Write-Host "$GREEN╚════════════════════════════════════════════════════════════════╝$NC"
Write-Host ""
Write-Host "Next steps:"
Write-Host "  1. Verify on GitHub that the commit was pushed"
Write-Host "  2. Run Phase 7 testing:"
Write-Host "     .\\PHASE_7_EXECUTION.ps1"
Write-Host ""
Write-Host "Status:"
Write-Host "  ✓ Duplicate files removed from root"
Write-Host "  ✓ All changes committed and pushed"
Write-Host "  ✓ src/ is now the single source of truth"
Write-Host "  ✓ Ready for Phase 7 execution"
Write-Host ""

exit 0
