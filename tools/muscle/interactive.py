"""
Interactive Mode - Human-in-the-loop control for MUSCLE.

Architecture Decision Record (ADR):
- ENABLED by default for better UX
- Pause points: before iteration, on failure, on success
- Rich UI with buttons/choices
- User can provide hints when stuck
"""

from enum import Enum


class InteractiveChoice(Enum):
    CONTINUE = "c"
    MODIFY = "m"
    SKIP = "s"
    ABORT = "a"
    VIEW = "v"


class InteractiveHandler:
    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self._history: list[str] = []

    def pause_before_iteration(
        self,
        iteration: int,
        task: str,
        evolved_strategy: str | None,
    ) -> InteractiveChoice:
        """Pause before an iteration. Returns user's choice."""
        if not self.enabled:
            return InteractiveChoice.CONTINUE

        print(f"\n{'=' * 60}")
        print(f"ITERATION {iteration}")
        print(f"{'=' * 60}")
        print(f"Task: {task[:100]}...")
        if evolved_strategy:
            print(f"Strategy: {evolved_strategy[:100]}...")
        print(f"{'=' * 60}")
        print("[c]ontinue - Accept current approach")
        print("[m]odify  - Provide a hint or modification")
        print("[s]kip    - Skip this iteration")
        print("[a]bort   - End session")
        print("[v]iew    - View previous iterations")
        print(f"{'=' * 60}")

        while True:
            try:
                choice = input("Your choice (c/m/s/a/v): ").strip().lower()
                if choice in ["c", "continue"]:
                    return InteractiveChoice.CONTINUE
                elif choice in ["m", "modify"]:
                    return InteractiveChoice.MODIFY
                elif choice in ["s", "skip"]:
                    return InteractiveChoice.SKIP
                elif choice in ["a", "abort"]:
                    return InteractiveChoice.ABORT
                elif choice in ["v", "view"]:
                    self._view_history()
                    print(f"\n{'=' * 60}")
                    print(f"ITERATION {iteration}")
                    print(f"{'=' * 60}")
                else:
                    print("Invalid choice. Try again.")
            except (KeyboardInterrupt, EOFError):
                return InteractiveChoice.CONTINUE

    def pause_on_failure(
        self,
        iteration: int,
        errors: list[str],
    ) -> tuple[InteractiveChoice, str | None]:
        """Pause when iteration fails. Returns (choice, hint_if_any)."""
        if not self.enabled:
            return InteractiveChoice.CONTINUE, None

        print(f"\n{'=' * 60}")
        print(f"ITERATION {iteration} FAILED")
        print(f"{'=' * 60}")
        for err in errors[:5]:
            print(f"  - {err}")
        if len(errors) > 5:
            print(f"  ... and {len(errors) - 5} more errors")
        print(f"{'=' * 60}")
        print("[c]ontinue - Proceed with evolved strategy")
        print("[m]odify  - Provide a hint to guide next attempt")
        print("[a]bort   - End session")
        print(f"{'=' * 60}")

        while True:
            try:
                choice = input("Your choice (c/m/a): ").strip().lower()
                if choice in ["c", "continue"]:
                    return InteractiveChoice.CONTINUE, None
                elif choice in ["m", "modify"]:
                    hint = input("Enter your hint: ").strip()
                    return InteractiveChoice.MODIFY, hint if hint else None
                elif choice in ["a", "abort"]:
                    return InteractiveChoice.ABORT, None
                else:
                    print("Invalid choice. Try again.")
            except (KeyboardInterrupt, EOFError):
                return InteractiveChoice.CONTINUE, None

    def pause_on_success(
        self,
        iteration: int,
        files: list[str],
    ) -> InteractiveChoice:
        """Pause when iteration succeeds. Returns user's choice."""
        if not self.enabled:
            return InteractiveChoice.CONTINUE

        print(f"\n{'=' * 60}")
        print(f"ITERATION {iteration} SUCCEEDED!")
        print(f"{'=' * 60}")
        print(f"Generated {len(files)} files:")
        for f in files[:10]:
            print(f"  - {f}")
        if len(files) > 10:
            print(f"  ... and {len(files) - 10} more")
        print(f"{'=' * 60}")
        print("[c]ontinue - Accept and finish")
        print("[v]iew    - View generated code")
        print("[a]bort   - Continue improving (don't finish)")
        print(f"{'=' * 60}")

        while True:
            try:
                choice = input("Your choice (c/v/a): ").strip().lower()
                if choice in ["c", "continue"]:
                    return InteractiveChoice.CONTINUE
                elif choice in ["v", "view"]:
                    for f in files:
                        try:
                            with open(f) as fp:
                                print(f"\n--- {f} ---")
                                print(fp.read()[:500])
                        except Exception:
                            pass
                    print(f"\n{'=' * 60}")
                elif choice in ["a", "abort"]:
                    return InteractiveChoice.ABORT
                else:
                    print("Invalid choice. Try again.")
            except (KeyboardInterrupt, EOFError):
                return InteractiveChoice.CONTINUE

    def add_to_history(self, text: str) -> None:
        self._history.append(text)

    def _view_history(self) -> None:
        if not self._history:
            print("No previous iterations yet.")
            return
        print(f"\n{'=' * 60}")
        print("ITERATION HISTORY")
        print(f"{'=' * 60}")
        for i, h in enumerate(self._history[-5:], 1):
            print(f"\n[Iteration {len(self._history) - 5 + i}]")
            print(h[:300])
        print(f"{'=' * 60}")
