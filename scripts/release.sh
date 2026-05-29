#!/usr/bin/env bash
set -euo pipefail

# Preflight checks
branch=$(git branch --show-current)
if [[ "$branch" != "main" ]]; then
    echo "❌ Must be on main branch (currently on '$branch')"
    exit 1
fi

if [[ -n "$(git status --porcelain)" ]]; then
    echo "❌ Working directory is not clean. Commit or stash changes first."
    exit 1
fi

if ! gh auth status &>/dev/null; then
    echo "❌ GitHub CLI not authenticated. Run: gh auth login"
    exit 1
fi

git fetch origin --tags --quiet
git fetch origin main --quiet

if [[ "$(git rev-parse main)" != "$(git rev-parse origin/main)" ]]; then
    echo "❌ Local main is out of sync with origin/main. Run: git pull"
    exit 1
fi

current=$(python3 -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])")
echo "📦 Current version: $current"

# Calculate next patch version as suggestion
IFS='.' read -r major minor patch <<< "$current"
suggested="$major.$minor.$((patch + 1))"

read -p "🔖 New version [$suggested]: " version
version="${version:-$suggested}"

# Validate format
if [[ ! "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "❌ Invalid version format. Use semver (e.g. 1.2.3)"
    exit 1
fi

if git tag -l "v$version" | grep -q .; then
    echo "❌ Tag v$version already exists"
    exit 1
fi

echo ""
echo "This will:"
echo "  1. Update pyproject.toml to $version"
echo "  2. Commit and push to main (admin bypass)"
echo "  3. Tag v$version and create a GitHub release"
echo ""
read -p "Continue? [Y/n] " confirm
if [[ "${confirm:-Y}" =~ ^[Nn] ]]; then
    exit 0
fi

# Bump version (portable — works on macOS and Linux)
python3 -c "
import re, pathlib
p = pathlib.Path('pyproject.toml')
p.write_text(re.sub(r'^version = \".*\"', 'version = \"$version\"', p.read_text(), count=1, flags=re.MULTILINE))
"

git add pyproject.toml
git commit -m "Bump version to $version"
git push origin main

git tag "v$version"
git push origin "v$version"
gh release create "v$version" --title "v$version" --generate-notes

echo ""
echo "✅ Released v$version"
