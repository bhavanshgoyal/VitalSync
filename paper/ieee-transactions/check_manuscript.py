"""Pre-submission checks for the Transactions manuscript.

Covers the "A Final Checklist" items in New_IEEEtran_how-to.pdf: every
reference cited, every cited key defined, all graphics present, plus the
journal front matter the template requires. Also reports layout overflow,
which a successful compile does not catch.

Run from this directory:  python check_manuscript.py
"""

from __future__ import annotations

import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEX = HERE / "vitalsync_transactions.tex"
LOG = HERE / "vitalsync_transactions.log"

BS = chr(92)
problems: list[str] = []
notes: list[str] = []


def strip_comments(text: str) -> str:
    """Remove LaTeX comments so commented-out markup is not treated as live.

    Without this, a deliberately disabled line such as the reserved
    `% \\input{tables/table_llm}` is reported as a missing file.
    """
    out = []
    for line in text.splitlines():
        cut = None
        for i, ch in enumerate(line):
            if ch == "%" and (i == 0 or line[i - 1] != BS):
                cut = i
                break
        out.append(line if cut is None else line[:cut])
    return "\n".join(out)


def load_expanded() -> str:
    """Main file with \\input files spliced in, so checks see the whole paper."""
    text = strip_comments(TEX.read_text(encoding="utf-8"))
    for rel in re.findall(re.escape(BS) + r"input\{([^}]+)\}", text):
        p = HERE / (rel if rel.endswith(".tex") else rel + ".tex")
        if p.exists():
            text += "\n" + strip_comments(p.read_text(encoding="utf-8"))
    return text


def main() -> int:
    tex = load_expanded()
    main_only = strip_comments(TEX.read_text(encoding="utf-8"))

    # --- references -------------------------------------------------------
    items = re.findall(re.escape(BS) + r"bibitem\{([^}]+)\}", tex)
    cited: set[str] = set()
    for group in re.findall(re.escape(BS) + r"cite\{([^}]+)\}", tex):
        cited.update(c.strip() for c in group.split(","))

    uncited = [i for i in items if i not in cited]
    undefined = sorted(c for c in cited if c not in items)
    dupes = sorted({i for i in items if items.count(i) > 1})

    notes.append(f"references defined: {len(items)}; distinct keys cited: {len(cited)}")
    if undefined:
        problems.append(f"cited but not defined: {undefined}")
    if uncited:
        problems.append(f"defined but never cited (IEEE requires all be cited): {uncited}")
    if dupes:
        problems.append(f"duplicate bibitem keys: {dupes}")

    # --- reference completeness ------------------------------------------
    # IEEE entries need an author, a venue and locator details. An entry that
    # opens straight into a quoted title, with no volume or pages, is either
    # incomplete or not a real paper; both must be resolved before submission.
    bib = tex[tex.index(BS + "begin{thebibliography}"):] if (
        BS + "begin{thebibliography}") in tex else ""
    thin = []
    for chunk in re.split(re.escape(BS) + r"bibitem\{", bib)[1:]:
        key = chunk.split("}", 1)[0]
        text = " ".join(chunk.split("}", 1)[1].split())
        no_author = text.lstrip().startswith("``")
        no_locator = not re.search(r"vol\.|pp\.|arXiv|doi|DOI|" + re.escape(BS) + "url", text)
        if no_author and no_locator:
            thin.append(key)
    if thin:
        problems.append(
            f"{len(thin)} reference(s) have no author and no volume/pages/DOI, so they "
            f"cannot be verified: {thin}")

    # --- graphics and inputs ---------------------------------------------
    missing = []
    for g in re.findall(re.escape(BS) + r"includegraphics(?:\[[^\]]*\])?\{([^}]+)\}", tex):
        if not any((HERE / c).exists() for c in (g, g + ".pdf", g + ".png")):
            missing.append(g)
    notes.append(
        f"graphics referenced: {len(re.findall(re.escape(BS) + r'includegraphics', tex))}")
    if missing:
        problems.append(f"missing graphics files: {missing}")

    for rel in re.findall(re.escape(BS) + r"input\{([^}]+)\}", main_only):
        p = HERE / (rel if rel.endswith(".tex") else rel + ".tex")
        if not p.exists():
            problems.append(f"missing input file: {rel}")

    # --- labels and cross-references --------------------------------------
    labels = set(re.findall(re.escape(BS) + r"label\{([^}]+)\}", tex))
    refs = set(re.findall(re.escape(BS) + r"ref\{([^}]+)\}", tex))
    dangling = sorted(r for r in refs if r not in labels)
    if dangling:
        problems.append(f"reference to undefined label: {dangling}")
    notes.append(f"labels: {len(labels)}; cross-references: {len(refs)}")

    # --- journal front matter required by the supplied template ----------
    required = [
        (r"documentclass\[lettersize,journal\]\{IEEEtran\}", "journal class options"),
        (r"markboth\{", "running heads"),
        (r"IEEEPARstart\{", "initial drop cap"),
        (r"begin\{IEEEkeywords\}", "index terms"),
        (r"begin\{IEEEbiograph", "author biography"),
        (r"thanks\{", "manuscript/affiliation footnote"),
    ]
    for pattern, why in required:
        if not re.search(re.escape(BS) + pattern, tex):
            problems.append(f"journal front matter missing: {why}")

    # --- layout, from the compile log -------------------------------------
    if LOG.exists():
        log = LOG.read_text(encoding="utf-8", errors="replace")
        undef_warn = len(re.findall(r"Warning.*undefined", log))
        if undef_warn:
            problems.append(f"{undef_warn} undefined reference warning(s) in log")
        over = [float(m) for m in
                re.findall(r"Overfull .hbox \(([0-9.]+)pt too wide\)", log)]
        severe = [b for b in over if b > 20]
        notes.append(f"overfull hboxes: {len(over)} total, {len(severe)} over 20pt")
        if severe:
            problems.append(
                f"severe overfull hbox(es) over 20pt: {[round(b, 1) for b in severe]} "
                f"- content is reaching into the margin")
        pages = re.search(r"Output written on \S+ \((\d+) pages", log)
        if pages:
            notes.append(f"pages: {pages.group(1)}")

    # --- placeholders the author must still fill --------------------------
    ph = sorted(set(re.findall(
        r"\[(?:Journal Name|Department|Institution|City|Country|e-mail address|"
        r"degree|field|institution|city|country|year)\]", tex)))
    if ph:
        notes.append(f"placeholders to fill before submission: {', '.join(ph)}")

    print("=" * 66)
    for n in notes:
        print(f"  {n}")
    print("=" * 66)
    if problems:
        print(f"{len(problems)} PROBLEM(S):")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("  all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
