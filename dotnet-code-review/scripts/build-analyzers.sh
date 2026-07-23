#!/usr/bin/env bash
# Build all Roslyn analyzers so engine.py can run them as DLLs (fast path)
# instead of `dotnet run` (which re-JITs on every call).
# Run from the skill root:  bash scripts/build-analyzers.sh
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
for name in csharp-ast-analyzer csharp-semantic-analyzer csharp-project-analyzer; do
    proj="$ROOT/$name/$name.csproj"
    echo -n "Building $name... "
    if dotnet build "$proj" -c Debug --nologo -v q >/dev/null 2>&1; then
        echo "OK"
    else
        echo "FAILED"
        exit 1
    fi
done
echo "All analyzers built. engine.py will use the DLL fast path."
