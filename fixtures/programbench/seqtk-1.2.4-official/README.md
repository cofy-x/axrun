# Seqtk locked qualification case

This is a second explicit ProgramBench 1.2.4 case, not a new execution backend. The resolver locks source, metadata, test blobs and evaluator helpers; the existing multi-Run verifier owns compile, rootfs result consumption, fresh branches and cleanup.

The native qualification uses an unmodified upstream-source reference-build fixture with a disclosed compile wrapper, an unchanged public model partial archive, and a separately labeled synthetic compile-failure fixture. Neither local fixture is represented as an officially supplied candidate or baseline. See the [selection and evidence record](../../../docs/validation/2026-09-22-programbench-deterministic-selection.md).

The evaluator dependency lock and compile helper are byte-identical to the already qualified 1.2.4 evaluator. The branch helper moves only the two exact pip-install lines to image construction; it retains the official timeout-method adaptation, rerun policy, test bodies and result semantics. No TUI patch, tolerance change or best-of-run selection is included. The native baseline retains offline setup commands, which find all requirements preinstalled; SDK branch execution removes those redundant commands and verifies the same installed lock before testing.

Hidden tests and candidates are not vendored or exposed to inference. Build the dependency-closed image before executing episodes; runtime networking remains deny-all.
