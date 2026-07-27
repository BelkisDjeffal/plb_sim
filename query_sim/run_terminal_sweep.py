from pathlib import Path
import re
import shutil
import subprocess
import sys

SCENARIO = Path("scenario.py")
OUT = Path("outputs_query/no_fault_3_classes")
SWEEP = Path("outputs_query/terminal_sweep/no_fault_3_classes")

TERMINAL_LEVELS = [60, 120, 240, 300, 360, 400, 480, 600, 800, 1000, 1200, 1500, 1800, 2400, 3000]

def class_counts(total):
    base = total // 3
    rem = total % 3
    enterprise = base + (1 if rem > 0 else 0)
    premium = base + (1 if rem > 1 else 0)
    freemium = base
    return [enterprise, premium, freemium]

def patch_scenario(text, total):
    counts = class_counts(total)

    text = re.sub(
        r'"total_workers"\s*:\s*\d+',
        f'"total_workers": {total}',
        text,
    )

    text = re.sub(
        r'"class_counts"\s*:\s*\[[^\]]+\]',
        f'"class_counts": {counts}',
        text,
    )

    return text, counts

original = SCENARIO.read_text()
backup = SCENARIO.with_suffix(".py.before_terminal_sweep")
backup.write_text(original)

SWEEP.mkdir(parents=True, exist_ok=True)

try:
    for total in TERMINAL_LEVELS:
        patched, counts = patch_scenario(original, total)
        SCENARIO.write_text(patched)

        if OUT.exists():
            shutil.rmtree(OUT)

        print()
        print("=" * 80)
        print(f"Running terminal-equivalent level T={total}, class_counts={counts}")
        print("=" * 80)

        subprocess.run(
            [sys.executable, "query_sim/run_all_query_simulations.py"],
            check=True,
            env={**dict(), **{"PYTHONPATH": "."}},
        )

        target = SWEEP / f"T{total}"
        if target.exists():
            shutil.rmtree(target)

        shutil.copytree(OUT, target)
        (target / "terminal_equivalent.txt").write_text(str(total) + "\n")
        (target / "class_counts.txt").write_text(str(counts) + "\n")

finally:
    SCENARIO.write_text(original)
    print()
    print(f"Restored {SCENARIO}")
    print(f"Backup kept at {backup}")

print()
print(f"Wrote sweep outputs to {SWEEP}")
