# Agent Guidelines for D^it

Before proposing or making architectural changes, consult the project brain:
- [brain/system-overview.md](brain/system-overview.md): System capabilities and concept.
- [brain/architecture.md](brain/architecture.md): Component interactions.
- [brain/landmines.md](brain/landmines.md): Known failure modes, pitfalls, and the WHY.
- [brain/operations.md](brain/operations.md): How to run and test.

When modifying code:
- Maintain instrumentation: preserve stage timing logs.
- Fail loud: do not silently swallow exceptions in audio capture or model initialization.
- Test with real runtime execution (`python main.py --test`), not just syntax check.

