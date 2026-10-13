# Opponent-count regression harness

This is supporting validation for [1dot13/source PR #705](https://github.com/1dot13/source/pull/705). The PR itself contains the four-file engine fix; this branch makes the local harness available for review.

Run with Python 3 and clang++ from a source checkout that contains both commits:

```sh
# Unpatched base: expected exit code 1, 103 checks and 26 failures.
python3 validation/test_opponent_counts.py . --ref 7f333f3950504262d4b8497b8cb83a70bd886b53

# PR commit: expected exit code 0, 103 checks and no failures.
python3 validation/test_opponent_counts.py . --ref 95002295765cc8fdc3635d81beccec58cce4963d
```

The harness compiles source functions in C++17 with ASan/UBSan. It reads the affected functions, neutrality macro, scalar types, SoldierID, body/status enums and range constants from the selected Git commit. The fixture supplies minimal soldier records and stub engine dependencies. It checks callback invocation but does not execute the real AI decisions or automatic combatant discovery. Temporary build files are removed after each run.

This is focused logic coverage. Gameplay and multiplayer testing remain separate checks. The Windows/MSVC build for the exact PR commit is available in [the fork Actions run](https://github.com/anton-vinogradov/source/actions/runs/38439821629).
