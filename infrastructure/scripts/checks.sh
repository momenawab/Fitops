#!/usr/bin/env bash
set -u
set -o pipefail

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
BACKEND_DIR="$REPO_ROOT/backend"
FRONTEND_DIR="$REPO_ROOT/frontend"

GATE_LABEL=()
GATE_STATUS=()

die() {
    printf 'checks.sh: error: %s\n' "$*" >&2
    exit 1
}

record_gate() {
    GATE_LABEL+=("$1")
    GATE_STATUS+=("$2")
}

print_gate_output() {
    printf '%s\n' "$1" | sed 's/^/    /'
}

resolve_python() {
    if [ -n "${FITOPS_PYTHON:-}" ]; then
        [ -x "$FITOPS_PYTHON" ] || die "FITOPS_PYTHON is not an executable: $FITOPS_PYTHON"
        PYTHON="$FITOPS_PYTHON"
    elif [ -x "$REPO_ROOT/.venv/bin/python" ]; then
        PYTHON="$REPO_ROOT/.venv/bin/python"
    elif command -v python3 >/dev/null 2>&1; then
        PYTHON="$(command -v python3)"
    elif command -v python >/dev/null 2>&1; then
        PYTHON="$(command -v python)"
    else
        die "no Python interpreter found: no $REPO_ROOT/.venv, no python3/python on PATH. Set FITOPS_PYTHON to override."
    fi
}

resolve_ruff() {
    local python_bin
    python_bin=$(dirname "$PYTHON")
    if [ -x "$python_bin/ruff" ]; then
        RUFF="$python_bin/ruff"
    elif command -v ruff >/dev/null 2>&1; then
        RUFF="$(command -v ruff)"
    else
        die "ruff not found next to the Python interpreter ($python_bin) and not on PATH"
    fi
}

run_gate() {
    local label="$1"
    local dir="$2"
    shift 2
    local output status
    printf '\n==> %s\n' "$label"
    output=$(cd "$dir" && "$@" 2>&1)
    status=$?
    if [ "$status" -eq 0 ]; then
        printf '    PASS\n'
        record_gate "$label" PASS
    else
        printf '    FAIL (exit status %s)\n' "$status"
        print_gate_output "$output"
        record_gate "$label" FAIL
    fi
}

fail_tool_gate() {
    printf '\n==> %s\n' "$1"
    printf '    FAIL (%s not found on PATH)\n' "$2"
    record_gate "$1" FAIL
}

run_django_tests_gate() {
    local label="backend: django tests"
    local output status found count
    printf '\n==> %s\n' "$label"
    output=$(cd "$BACKEND_DIR" && "$PYTHON" manage.py test 2>&1)
    status=$?
    if [ "$status" -ne 0 ]; then
        printf '    FAIL (exit status %s)\n' "$status"
        print_gate_output "$output"
        record_gate "$label" FAIL
        return
    fi
    if printf '%s\n' "$output" | grep 'NO TESTS RAN' >/dev/null; then
        printf '    FAIL: Django collected 0 tests. Exit status 0 is NOT accepted as a pass for this gate.\n'
        print_gate_output "$output"
        record_gate "$label" FAIL
        return
    fi
    found=$(printf '%s\n' "$output" | grep -Eo 'Found [0-9]+ test' | sed -n '1p')
    count=${found#Found }
    count=${count% test}
    case "$count" in
        [1-9]*)
            printf '    PASS (%s test(s) collected)\n' "$count"
            record_gate "$label" PASS
            ;;
        *)
            printf '    FAIL: could not confirm that any test was collected (no usable "Found N test(s)" line in output). Exit status 0 is NOT accepted as a pass for this gate.\n'
            print_gate_output "$output"
            record_gate "$label" FAIL
            ;;
    esac
}

[ -d "$BACKEND_DIR" ] || die "backend directory not found at $BACKEND_DIR"
[ -d "$FRONTEND_DIR" ] || die "frontend directory not found at $FRONTEND_DIR"

resolve_python
resolve_ruff

NPM=""
if command -v npm >/dev/null 2>&1; then
    NPM="$(command -v npm)"
fi

printf 'FitOps local checks\n'
printf '  repo root: %s\n' "$REPO_ROOT"
printf '  python:    %s\n' "$PYTHON"
printf '  ruff:      %s\n' "$RUFF"
if [ -n "$NPM" ]; then
    printf '  npm:       %s\n' "$NPM"
else
    printf '  npm:       not found on PATH (frontend gates will fail)\n'
fi

run_gate "backend: ruff check" "$BACKEND_DIR" "$RUFF" check .
run_gate "backend: ruff format --check" "$BACKEND_DIR" "$RUFF" format --check .
run_django_tests_gate

if [ -n "$NPM" ]; then
    run_gate "frontend: npm run lint" "$FRONTEND_DIR" "$NPM" run lint
    run_gate "frontend: npm run typecheck" "$FRONTEND_DIR" "$NPM" run typecheck
    run_gate "frontend: npm test" "$FRONTEND_DIR" "$NPM" test
    run_gate "frontend: npm run format:check" "$FRONTEND_DIR" "$NPM" run format:check
else
    fail_tool_gate "frontend: npm run lint" npm
    fail_tool_gate "frontend: npm run typecheck" npm
    fail_tool_gate "frontend: npm test" npm
    fail_tool_gate "frontend: npm run format:check" npm
fi

[ "${#GATE_STATUS[@]}" -eq 7 ] || die "internal error: expected 7 gate results, recorded ${#GATE_STATUS[@]}"

printf '\nSummary\n'
printf -- '-------\n'
failed=0
for ((i = 0; i < ${#GATE_STATUS[@]}; i++)); do
    printf '  %-4s  %s\n' "${GATE_STATUS[$i]}" "${GATE_LABEL[$i]}"
    if [ "${GATE_STATUS[$i]}" != "PASS" ]; then
        failed=$((failed + 1))
    fi
done

if [ "$failed" -eq 0 ]; then
    printf '\nAll 7 gates passed.\n'
    exit 0
fi

printf '\n%s of 7 gates FAILED.\n' "$failed"
exit 1
