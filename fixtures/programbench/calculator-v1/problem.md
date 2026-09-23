Rebuild the program in `/workspace` from behavioral observation.

The execute-only reference program is `./executable`. You may run it with ordinary command-line
arguments, but you must not read, copy, trace, disassemble, or otherwise inspect it. Do not use a
package-manager implementation or delegate to another installed calculator.

Create an original implementation and an executable `./compile.sh`. A fresh offline environment
will remove the provided `./executable`, run `./compile.sh`, and then invoke the new `./executable`.
The submitted project must therefore contain everything needed to rebuild the program without
network access.
