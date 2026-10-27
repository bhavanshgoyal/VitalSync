"""Derive the IEEE Transactions (journal) manuscript from the conference source.

The professor supplied IEEE's official Transactions bundle (IEEEtran.cls v1.8b
plus New_IEEEtran_how-to), which specifies the journal format. The body text,
figures and tables are identical to the conference version; only the front
matter, the class options and the end matter differ.

Doing this as a transform rather than a second hand-maintained .tex means the
two versions cannot drift: regenerate after any edit to vitalsync_ieee.tex.

Run:  python paper/make_transactions.py
"""

from __future__ import annotations

import io
import re
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "vitalsync_ieee.tex"
OUT_DIR = HERE / "ieee-transactions"
OUT = OUT_DIR / "vitalsync_transactions.tex"

BS = chr(92)

# --------------------------------------------------------------- front matter
# Journal format per New_IEEEtran_how-to.pdf sections "How to Create Common
# Front Matter" and the bare_jrnl_new_sample4.tex sample.
PREAMBLE = r"""%% VitalSync -- IEEE Transactions (journal) manuscript
%%
%% GENERATED FILE -- do not edit by hand.
%% Produced by paper/make_transactions.py from paper/vitalsync_ieee.tex so the
%% conference and journal versions cannot drift apart. Edit the source, then
%% regenerate.
%%
%% Format follows the IEEE Transactions template bundle supplied for this
%% submission: IEEEtran.cls v1.8b (2015/08/26), lettersize + journal options,
%% as described in New_IEEEtran_how-to.pdf.
%%
%% Build (TeX Live, from this directory):
%%   pdflatex vitalsync_transactions
%%   pdflatex vitalsync_transactions
%%   pdflatex vitalsync_transactions
%% (three passes: references, then IEEEtran's biography/float placement)

\documentclass[lettersize,journal]{IEEEtran}

\usepackage{cite}
\usepackage{amsmath,amssymb,amsfonts}
\usepackage{algorithmic}
\usepackage{array}
\usepackage{graphicx}
\usepackage{textcomp}
\usepackage{xcolor}
\usepackage{booktabs}
\usepackage{stfloats}
\usepackage{tikz}
\usetikzlibrary{arrows.meta, positioning, shapes.geometric, calc, fit,
                backgrounds}
\usepackage{url}
\usepackage[hidelinks]{hyperref}

\hyphenation{op-tical net-works semi-conduc-tor tele-metry
             summa-ri-za-tion faith-ful-ness}

\begin{document}

\title{VitalSync: A Decoupled IoMT Architecture for Risk Triage and
Resilient Clinical Summarization}

\author{Bhavansh~Goyal%
\thanks{Manuscript prepared October~2026. \emph{(Corresponding author:
Bhavansh Goyal.)}}%
\thanks{B. Goyal is with the Department of [Department], [Institution],
[City], [Country] (e-mail: [e-mail address]).}%
\thanks{This work is a research prototype. The system described is not a
medical device and has not been evaluated for clinical use. All cohorts are
simulated; no patient data was used.}}

% Running heads: journal/volume information, then author et al. and short title.
\markboth{IEEE Transactions on [Journal Name],~Vol.~XX, No.~X, Month~2026}%
{Goyal: VitalSync: A Decoupled IoMT Architecture for Risk Triage and Resilient Clinical Summarization}

\maketitle

"""

# A journal paper closes with author biographies (how-to section "Biographies
# and Author Photos"). No photo is supplied, so the nophoto form is used.
END_MATTER = r"""
\begin{IEEEbiographynophoto}{Bhavansh Goyal}
received the [degree] degree in [field] from [institution], [city], [country],
in [year]. His research interests include the Internet of Medical Things,
fault-tolerant system architecture, clinical decision support, and the
evaluation of machine learning systems under realistic sensor noise. The
present work was carried out as an undergraduate research project.
\end{IEEEbiographynophoto}

\end{document}
"""


def convert(src_text: str) -> str:
    """Rewrite the conference body for the journal class."""
    body_start = src_text.index(BS + "begin{abstract}")
    body_end = src_text.index(BS + "end{document}")
    body = src_text[body_start:body_end]

    # 1. Initial drop cap. Journal style opens the Introduction with
    #    \IEEEPARstart; the conference class does not use it.
    marker = BS + "section{Introduction}\n\n"
    assert marker in body, "could not locate the Introduction"
    after = body.index(marker) + len(marker)
    first_para_end = body.index("\n\n", after)
    first_para = body[after:first_para_end]

    m = re.match(r"^([A-Za-z])([A-Za-z]*)", first_para.lstrip())
    assert m, "first paragraph does not begin with a word"
    first, rest_of_word = m.group(1), m.group(2)
    dropped = (BS + "IEEEPARstart{" + first + "}{" + rest_of_word + "}"
               + first_para.lstrip()[len(first) + len(rest_of_word):])
    body = body[:after] + dropped + body[first_para_end:]

    # 2. The acknowledgment is a starred section in this source; IEEEtran
    #    journal style numbers it, so keep it unnumbered but use the class's
    #    own heading to match the template.
    body = body.replace(
        BS + "section*{Acknowledgment}",
        BS + "section*{Acknowledgment}")

    # 3. Wide floats: conference and journal both honour figure*/table*, but
    #    stfloats is loaded so bottom-of-page wide floats are permitted.
    return body


def main() -> int:
    src = io.open(SRC, encoding="utf-8").read()
    body = convert(src)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    io.open(OUT, "w", encoding="utf-8").write(PREAMBLE + body + END_MATTER)

    # Keep the package self-contained: assets travel with the .tex.
    for sub in ("figures", "tables"):
        (OUT_DIR / sub).mkdir(exist_ok=True)
        for f in (HERE / sub).iterdir():
            if f.suffix in {".pdf", ".tex", ".png"}:
                shutil.copy2(f, OUT_DIR / sub / f.name)

    print(f"wrote {OUT}")
    print(f"  {len(body.splitlines())} body lines, assets refreshed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
