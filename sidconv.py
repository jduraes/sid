#!/usr/bin/env python3
"""
C64 BASIC → RC2014 MS BASIC (CP/M) SID POKE-to-OUT converter

Core rules implemented:
- Detects SID base set to 54272 (decimal) either via literal or variable assignment.
- Rewrites POKE base+offset, value into OUT REG,offset : OUT DAT,value.
- Handles colon-separated statements and variable expressions on either side of the comma.
- Inserts a header line setting B=0 and REG/DAT ports (default 212/213) at the top.
- Optionally warns for offsets beyond 0–24 and appends a REM comment.

Limitations:
- Designed for typical SID-only POKE usage. Other POKEs (VIC, screen, KERNAL, etc.) are not translated.
- Basic handling of line-numbered programs. If the first line number is very small, the header is inserted as line 0.
- Delay scaling is optional and conservative; it only scales simple FOR var=1 TO <const> : ... : NEXT var patterns when enabled.

Usage:
  python3 sidconv.py input.bas output.bas [--reg 212] [--dat 213]
                                        [--warn-out-of-range]
                                        [--scale-for FACTOR]
                                        [--scale-for-vars T,W,DELAY]
"""
from __future__ import annotations
import argparse
import re
from typing import List, Tuple, Optional, Set

# BASIC-friendly variable names; keep letters, avoid symbols for CP/M environments.
DEFAULT_REG = 212
DEFAULT_DAT = 213

# Simple regexes for parsing
LINE_NUM_RE = re.compile(r"^\s*(\d+)\s*(.*)$")
ASSIGN_BASE_RE = re.compile(r"^\s*(?:LET\s+)?([A-Z][A-Z0-9]?)\s*=\s*54272\s*$", re.IGNORECASE)
POKE_STMT_RE = re.compile(r"^\s*POKE\s+(.+?)\s*,\s*(.+?)\s*$", re.IGNORECASE)
# FOR..NEXT simple loop recognizer for optional delay scaling
FOR_RE = re.compile(r"^\s*FOR\s+([A-Z][A-Z0-9]?)\s*=\s*1\s+TO\s*(\d+)\s*$", re.IGNORECASE)
NEXT_RE = re.compile(r"^\s*NEXT\s+([A-Z][A-Z0-9]?)\s*$", re.IGNORECASE)


def split_colon_statements(s: str) -> List[str]:
    parts = []
    buf = []
    i = 0
    while i < len(s):
        c = s[i]
        if c == ':':
            parts.append(''.join(buf).strip())
            buf = []
        else:
            buf.append(c)
        i += 1
    tail = ''.join(buf).strip()
    if tail:
        parts.append(tail)
    return parts


def rewrite_poke(arg_addr: str, arg_val: str, base_vars: Set[str], warn_out_of_range: bool) -> Tuple[Optional[str], Optional[str]]:
    """Return (out_reg_stmt, out_dat_stmt) or (None, None) if not a SID poke."""
    addr_expr = arg_addr.strip()
    val_expr = arg_val.strip()

    # Normalize spacing
    addr_expr_no_sp = re.sub(r"\s+", "", addr_expr)

    # Match forms:
    # - 54272+X
    # - B+X where B in base_vars
    # - 54272 (offset 0)
    # - B (offset 0)
    offset_expr = None
    # Literal base
    if addr_expr_no_sp.startswith("54272+"):
        offset_expr = addr_expr_no_sp[len("54272+"):]
    elif addr_expr_no_sp == "54272":
        offset_expr = "0"
    else:
        # Variable base
        m = re.match(r"^([A-Z][A-Z0-9]?)(\+(.+))?$", addr_expr_no_sp, re.IGNORECASE)
        if m and m.group(1).upper() in base_vars:
            offset_expr = m.group(3) if m.group(3) is not None else "0"

    if offset_expr is None:
        return None, None

    # Try to detect constant offset to optionally warn about range
    rem = ""
    if warn_out_of_range:
        try:
            off_eval = int(offset_expr, 10)
            if off_eval < 0 or off_eval > 24:
                rem = f" : REM WARN: SID reg {off_eval} out of 0-24"
        except ValueError:
            # Non-constant; cannot check
            pass

    return f"OUT REG,{offset_expr}", f"OUT DAT,{val_expr}{rem}"


ANSI_SEQ = "\x1b"

# Minimal PETSCII -> ANSI mappings (best-effort)
ANSI_CHR_MAP = {
    147: f"{ANSI_SEQ}[2J{ANSI_SEQ}[H",   # Clear screen + home
    19:  f"{ANSI_SEQ}[H",                # Home cursor
    17:  f"{ANSI_SEQ}[B",                # Cursor down
    145: f"{ANSI_SEQ}[A",                # Cursor up
    157: f"{ANSI_SEQ}[D",                # Cursor left
    29:  f"{ANSI_SEQ}[C",                # Cursor right
    # Basic colors (approximate):
    5:   f"{ANSI_SEQ}[37m",              # White
    28:  f"{ANSI_SEQ}[31m",              # Red
    30:  f"{ANSI_SEQ}[32m",              # Green
    31:  f"{ANSI_SEQ}[34m",              # Blue
    144: f"{ANSI_SEQ}[30m",              # Black
    # Reset color (use 0m)
    18:  f"{ANSI_SEQ}[0m",               # Reverse off (approx as reset)
}

CHR_CALL_RE = re.compile(r"CHR\$\(\s*(\d+)\s*\)", re.IGNORECASE)


def map_chr_calls_to_profile(stmt: str, screen_profile: str) -> str:
    if screen_profile != "ansi":
        return stmt

    def repl(m: re.Match) -> str:
        n = int(m.group(1))
        if n in ANSI_CHR_MAP:
            esc = ANSI_CHR_MAP[n]
            # Return as a quoted string literal suitable for BASIC
            # Double quotes inside are not present, so safe
            return f'"{esc}"'
        return m.group(0)

    return CHR_CALL_RE.sub(repl, stmt)


def process_line_body(body: str, base_vars: Set[str], warn_out_of_range: bool,
                      scale_for: Optional[int], scale_for_vars: Set[str],
                      screen_profile: str, map_get_to_inkey: bool) -> str:
    # Split by ':' and process each sub-statement
    stmts = split_colon_statements(body)

    # Optional simple FOR..NEXT scaling state machine
    scaled_stmts = []
    i = 0
    while i < len(stmts):
        s = stmts[i].strip()
        if scale_for and scale_for > 1:
            fm = FOR_RE.match(s)
            if fm and fm.group(1).upper() in scale_for_vars:
                var = fm.group(1)
                bound = int(fm.group(2))
                new_bound = bound * scale_for
                scaled_stmts.append(f"FOR {var}=1 TO {new_bound}")
                i += 1
                continue
        # Default path
        scaled_stmts.append(s)
        i += 1

    out_parts: List[str] = []
    for s in scaled_stmts:
        # Optional: map GET var$ -> var$=INKEY$
        if map_get_to_inkey:
            mg = re.match(r"^\s*GET\s+([A-Z][A-Z0-9]?)\$?\s*$", s, re.IGNORECASE)
            if mg:
                var = mg.group(1).upper() + "$"
                out_parts.append(f"{var}=INKEY$")
                continue

        # Try a POKE rewrite
        pm = POKE_STMT_RE.match(s)
        if pm:
            addr, val = pm.group(1), pm.group(2)
            out_reg, out_dat = rewrite_poke(addr, val, base_vars, warn_out_of_range)
            if out_reg and out_dat:
                out_parts.append(out_reg)
                out_parts.append(out_dat)
                continue
        # Screen/profile mapping for CHR$ controls
        s2 = map_chr_calls_to_profile(s, screen_profile)
        out_parts.append(s2)
    return ':'.join(out_parts)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Convert C64 BASIC SID POKEs to RC2014 MS BASIC OUTs and improve screen I/O compatibility")
    p.add_argument("input", help="Input .BAS file (C64 BASIC)")
    p.add_argument("output", help="Output .BAS file (RC2014 MS BASIC)")
    p.add_argument("--reg", type=int, default=DEFAULT_REG, help="SID-Ulator REG port (default 212)")
    p.add_argument("--dat", type=int, default=DEFAULT_DAT, help="SID-Ulator DAT port (default 213)")
    p.add_argument("--warn-out-of-range", action="store_true", help="Append REM warning when register offset is outside 0-24")
    p.add_argument("--scale-for", type=int, default=0, help="Scale simple FOR var=1 TO N loops by this factor (0 disables)")
    p.add_argument("--scale-for-vars", type=str, default="T,W,DELAY,D", help="Comma-separated variable names for delay loop scaling")
    p.add_argument("--screen-profile", choices=["ansi","none"], default="ansi", help="Map common C64 PETSCII CHR$() controls to terminal sequences (default ansi)")
    p.add_argument("--map-get-to-inkey", action="store_true", help="Replace GET X$ with X$=INKEY$ for keypress handling")
    return p.parse_args()


def main():
    args = parse_args()
    scale_for_vars = {v.strip().upper() for v in args.scale_for_vars.split(',') if v.strip()}

    with open(args.input, 'r', encoding='utf-8', errors='ignore') as f:
        lines = f.read().splitlines()

    # First pass: detect base variable names and first line number
    base_vars: Set[str] = set()
    first_line_num: Optional[int] = None
    parsed_lines: List[Tuple[Optional[int], str]] = []

    for raw in lines:
        m = LINE_NUM_RE.match(raw)
        if m:
            ln = int(m.group(1))
            body = m.group(2).strip()
            if first_line_num is None:
                first_line_num = ln
            # Also scan each colon-separated stmt for base assigns
            for stmt in split_colon_statements(body):
                am = ASSIGN_BASE_RE.match(stmt)
                if am:
                    base_vars.add(am.group(1).upper())
            parsed_lines.append((ln, body))
        else:
            # Non-numbered line (keep as-is)
            parsed_lines.append((None, raw.rstrip()))

    # If no explicit base var found, we still translate literal 54272 POKEs

    # Prepare header line number and text
    header_ln: Optional[int] = None
    if first_line_num is not None:
        header_ln = max(0, first_line_num - 5)
    header_text = f"B=0:REG={args.reg}:DAT={args.dat}"

    # Second pass: rewrite
    output_lines: List[str] = []

    # Insert header first (numbered if possible)
    if header_ln is not None:
        output_lines.append(f"{header_ln} {header_text}")
    else:
        output_lines.append(f"5 {header_text}")

    for ln, body in parsed_lines:
        if ln is None:
            # Carry through any non-numbered lines untouched
            output_lines.append(body)
            continue
        new_body = process_line_body(body, base_vars, args.warn_out_of_range,
                                      args.scale_for if args.scale_for > 0 else None, scale_for_vars,
                                      args.screen_profile, args.map_get_to_inkey)

        # If the line contains an assignment of a known base var, rewrite it to BASE=0 on RC2014
        # This keeps program semantics aligned to REG/DAT addressing model.
        # Replace only exact "<base>=54272" with "<base>=0" when encountered.
        replaced = False
        stmts = split_colon_statements(new_body)
        for i, s in enumerate(stmts):
            am = ASSIGN_BASE_RE.match(s)
            if am and am.group(1).upper() in base_vars:
                stmts[i] = f"{am.group(1).upper()}=0"
                replaced = True
        if replaced:
            new_body = ':'.join(stmts)

        if new_body.strip() == '':
            output_lines.append(f"{ln}")
        else:
            output_lines.append(f"{ln} {new_body}")

    with open(args.output, 'w', encoding='utf-8') as f:
        f.write('\n'.join(output_lines) + '\n')


if __name__ == "__main__":
    main()
