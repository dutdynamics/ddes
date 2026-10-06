# DLADE Seminar Report LaTeX Template

This archive contains a portable, one-page XeLaTeX seminar report template. A slim DLADE brand bar sits above two aligned identity rows: the university mark and school address, followed by seminar logistics and the QR code. The QR code is bottom-aligned with the final date-and-time line. The talk content uses an unnumbered academic layout without decorative section dividers.

## Compile

Run the following command twice if hyperlinks or references are changed:

```text
xelatex main.tex
```

No `--shell-escape` option is required.

## Files

- `main.tex`: editable report source.
- `DUT_symbol.pdf`: Dalian University of Technology logo supplied with the project.
- `QR.pdf`: seminar QR code supplied with the project.
- `dlade-favicon.svg`: original DLADE icon supplied with the project.
- `dlade-favicon.pdf`: portable vector version used by `main.tex`.
- `dlade-icon-conversion.tex`: reproducible TikZ conversion source for the icon.
- `DLADE_Seminar_Report.pdf`: compiled one-page preview.

Edit the commands under `EDITABLE SEMINAR DETAILS` near the top of `main.tex` to update the title, speaker, venue, time, and links.
