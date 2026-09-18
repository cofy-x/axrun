#!/usr/bin/env bash
set -euo pipefail

root=/opt/claude-code
. /tmp/architecture.env
loader=/__claude_code/l
canonical_rpath="/__claude_code/opt/claude-code/lib:/__claude_code/lib/$DEB_LIB_ARCH:/__claude_code/lib64:/__claude_code/usr/lib/$DEB_LIB_ARCH:/__claude_code/usr/lib"
elf_list=/tmp/claude-elfs.txt
executable_list=/tmp/claude-dynamic-executables.txt
in_place_list=/tmp/claude-in-place-elfs.txt
: > "$elf_list"
: > "$executable_list"
: > "$in_place_list"

while IFS= read -r -d '' path; do
  if ! file -b -- "$path" | grep -q '^ELF'; then
    continue
  fi
  relative_path="${path#/}"
  printf '%s\n' "$relative_path" >> "$elf_list"
  case "$path" in
    /opt/claude-code/bin/claude-native | */"$CLAUDE_NATIVE_PACKAGE"/claude)
      size_before="$(stat -c %s "$path")"
      python3 /opt/axrun-build/scripts/patch-bun-interp.py "$path" "$SOURCE_INTERP"
      test "$(stat -c %s "$path")" = "$size_before"
      test "$(patchelf --print-interpreter "$path")" = "$loader"
      printf '%s\n' "$relative_path" >> "$executable_list"
      printf '%s\n' "$relative_path" >> "$in_place_list"
      continue
      ;;
  esac
  old_rpath="$(patchelf --print-rpath "$path" 2>/dev/null || true)"
  if [[ -n "$old_rpath" ]]; then
    patchelf --force-rpath --set-rpath "${old_rpath}:${canonical_rpath}" "$path"
  else
    patchelf --force-rpath --set-rpath "$canonical_rpath" "$path"
  fi
  interpreter="$(patchelf --print-interpreter "$path" 2>/dev/null || true)"
  if [[ -n "$interpreter" ]]; then
    patchelf --set-interpreter "$loader" "$path"
    printf '%s\n' "$relative_path" >> "$executable_list"
    test "$(patchelf --print-interpreter "$path")" = "$loader"
  fi
  patchelf --print-rpath "$path" | grep -Fq '/__claude_code/'
done < <(find "$root" -type f -print0)

sort -u -o "$elf_list" "$elf_list"
sort -u -o "$executable_list" "$executable_list"
sort -u -o "$in_place_list" "$in_place_list"
test -s "$elf_list"
test -s "$executable_list"
test -s "$in_place_list"
