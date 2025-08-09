C64 BASIC → RC2014 MS BASIC (CP/M) SID converter

Overview
- Converts SID sound POKEs from C64 BASIC to RC2014 MS BASIC OUT instructions for the SID‑Ulator module.
- Rewrites POKE 54272+N,V or POKE B+N,V (where B was set to 54272) into:
  - OUT REG,N : OUT DAT,V
- Adds an initialization header that sets B=0 and REG/DAT ports (default 212/213).
- Keeps other code intact, including expressions and colon-separated statements.

Install
- Requires Python 3.8+.

Usage
- Basic conversion:
  python3 sidconv.py input.bas output.bas

- Configure ports (REG/DAT):
  python3 sidconv.py input.bas output.bas --reg 212 --dat 213

- Warn on offsets outside SID register range 0–24:
  python3 sidconv.py input.bas output.bas --warn-out-of-range

- Naive delay scaling for simple FOR..NEXT loops (increase RC2014 delays):
  python3 sidconv.py input.bas output.bas --scale-for 5

  By default, this scales patterns like:
    FOR T=1 TO 200 : ... : NEXT T
  You can set which variables count as delay counters (comma-separated):
    --scale-for-vars T,W,DELAY,D

- Screen/ANSI mappings for PETSCII controls:
  python3 sidconv.py input.bas output.bas --screen-profile ansi

  This rewrites CHR$(n) for common C64 controls to ANSI sequences (e.g., CHR$(147) clear screen -> ESC[2J ESC[H, cursor moves -> ESC[A/B/C/D, and a color subset).

  Helper variables mode (cleaner output):
  python3 sidconv.py input.bas output.bas --screen-profile ansi-helpers --inject-ansi-helpers

  This replaces CHR$(n) control codes with variables like CLS$, HOME$, CUU$/CUD$/CUL$/CUR$, and COL_*$, and injects their definitions near the header.

- Keyboard GET to INKEY$ (optional):
  python3 sidconv.py input.bas output.bas --map-get-to-inkey

  Rewrites simple GET X$ to X$=INKEY$ for Microsoft BASIC-style key polling.

- Unknown PETSCII handling:
  python3 sidconv.py input.bas output.bas --unknown-petscii strip

  Policies: leave (default), strip (remove non-printable CHR$), warn (planned; no-op for now but reserved).

Example
Input (C64 BASIC):
  5 B=54272
  30 POKE B+1,0
  40 POKE B+0,0
  50 POKE B+5,9
  60 POKE B+6,240
  70 POKE B+4,17
  80 POKE B+0,169:POKE B+1,44

Output (RC2014 MS BASIC):
  0 B=0:REG=212:DAT=213
  5 B=0
  30 OUT REG,1:OUT DAT,0
  40 OUT REG,0:OUT DAT,0
  50 OUT REG,5:OUT DAT,9
  60 OUT REG,6:OUT DAT,240
  70 OUT REG,4:OUT DAT,17
  80 OUT REG,0:OUT DAT,169:OUT REG,1:OUT DAT,44

Notes
- Only SID POKEs are translated. Other POKEs (VIC, screen RAM, KERNAL) are not.
- Screen control codes in CHR$(n) can be mapped to ANSI with --screen-profile ansi. If your terminal doesn’t support ANSI, use --screen-profile none. For cleaner output with reusable controls, use --screen-profile ansi-helpers with --inject-ansi-helpers.
- GET mapping requires INKEY$ support on your MS BASIC. If absent, leave it off.
- Reads and exotic features (SYS, DATA-driven ML) are out of scope.
- If the first program line number is small, the header is inserted as line 0 to precede it.
- If your hardware ports differ (e.g., A4/A5 or others), pass --reg/--dat accordingly.

License
- MIT
