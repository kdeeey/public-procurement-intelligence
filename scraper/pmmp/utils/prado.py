"""
Shared PRADO form/postback plumbing for marchespublics.gov.ma.

The portal is a PRADO (PHP) application: every result listing is a *stateful
form*, not a set of addressable URLs. Paging or resizing a listing means
POSTing the entire form back — including the opaque PRADO_PAGESTATE returned by
the previous response — with PRADO_POSTBACK_TARGET naming the control that was
"clicked".

Portal behaviour established by reconnaissance:

  * `&page_courante=N` in the URL is IGNORED — every page returns page 1.
  * The advanced-search date filters (dateMiseEnLigneCalculeStart/End) and the
    `classification` filter are IGNORED server-side — a one-day window still
    returns the full result set. Filter client-side instead.
  * `annonceType` and `categorie` ARE honoured. `categorie` partitions the
    consultation universe exactly (36 496 + 26 994 + 37 051 = 100 541).
  * Consultations are NOT an `annonceType` value: they are a separate entry
    point (`&AllCons`). The `annonceType` select only lists annonce kinds
    (2=information, 4=résultat définitif, 5=extrait de PV, ...).
  * Result listings are sorted by *date limite de remise des plis*, descending
    and monotonic across pages — NOT by publication date.

This module is shared by the consultations spider and the PV downloader so the
postback logic exists in exactly one place.
"""

from __future__ import annotations

import re
from typing import Any, Callable
from urllib.parse import urljoin

from bs4 import BeautifulSoup

# PRADO control names, stable across the portal's search pages.
ADV_PREFIX = "ctl0$CONTENU_PAGE$AdvancedSearch$"
RES_PREFIX = "ctl0$CONTENU_PAGE$resultSearch$"
SEARCH_BUTTON = ADV_PREFIX + "lancerRecherche"
PAGE_SIZE_CTL = RES_PREFIX + "listePageSizeTop"
PAGER_NEXT = RES_PREFIX + "PagerTop$ctl2"   # ctl3 is "last page"
PAGER_LAST = RES_PREFIX + "PagerTop$ctl3"

_NB_RESULTS_RE = re.compile(r"[Nn]ombre de r.sultats\s*:?\s*([\d\s ]{1,12})")


def form_payload(html: str, current_url: str) -> tuple[dict[str, str], str]:
    """Every submittable field of the PRADO form, plus its absolute action URL.

    Checkboxes and radios are only included when checked, and submit buttons are
    left out, so the caller can add exactly the one control it is "clicking".
    """
    soup = BeautifulSoup(html, "html.parser")
    form = soup.find("form")
    if form is None:
        raise RuntimeError("no <form> on page — session probably expired")
    action = urljoin(current_url, form.get("action") or current_url)

    data: dict[str, str] = {}
    for inp in form.find_all("input"):
        name = inp.get("name")
        typ = (inp.get("type") or "text").lower()
        if not name:
            continue
        if typ in ("checkbox", "radio"):
            if inp.has_attr("checked"):
                data[name] = inp.get("value", "on")
        elif typ != "submit":
            data[name] = inp.get("value", "")
    for sel in form.find_all("select"):
        name = sel.get("name")
        if not name:
            continue
        opt = sel.find("option", selected=True) or sel.find("option")
        data[name] = opt.get("value", "") if opt else ""
    return data, action


class PradoSearch:
    """Walks a PRADO result listing page by page.

    Only the entry URL and the posted search fields differ between the
    consultations search and the extraits-de-PV search, so both reuse this.
    """

    def __init__(self, downloader: Any, entry_url: str, page_size: int = 500):
        self.dl = downloader
        self.entry_url = entry_url
        self.page_size = page_size
        self.html: str = ""
        self.url: str = entry_url

    # ------------------------------------------------------------------ #

    def load(self) -> str:
        """GET the entry point, which renders the (unsubmitted) search form."""
        self.html = self.dl.get(self.entry_url).text
        self.url = self.entry_url
        return self.html

    def _submit(self, mutate: Callable[[dict], None] | None = None,
                target: str | None = None) -> str:
        data, action = form_payload(self.html, self.url)
        if mutate is not None:
            mutate(data)
        if target is not None:
            data["PRADO_POSTBACK_TARGET"] = target
        resp = self.dl.post(action, data)
        self.html, self.url = resp.text, resp.url
        return self.html

    def start(self, fields: dict[str, str] | None = None,
              page_size: int | None = None) -> str:
        """Run the search. `fields` keys are bare names, e.g. {"categorie": "1"}."""
        if not self.html:
            self.load()

        def _apply(data: dict) -> None:
            for key, value in (fields or {}).items():
                data[ADV_PREFIX + key] = value
            data[SEARCH_BUTTON] = "Lancer la recherche"

        self._submit(_apply)
        size = page_size if page_size is not None else self.page_size
        if size:
            self.set_page_size(size)
        return self.html

    def set_page_size(self, n: int) -> str:
        """Widen the listing so one request covers many rows."""
        data, _ = form_payload(self.html, self.url)
        if PAGE_SIZE_CTL not in data:
            return self.html  # control absent on this listing — keep default
        self.page_size = n
        return self._submit(lambda d: d.__setitem__(PAGE_SIZE_CTL, str(n)),
                            target=PAGE_SIZE_CTL)

    def next_page(self) -> str:
        return self._submit(target=PAGER_NEXT)

    def last_page(self) -> str:
        return self._submit(target=PAGER_LAST)

    def total_results(self) -> int | None:
        text = BeautifulSoup(self.html, "html.parser").get_text(" ", strip=True)
        m = _NB_RESULTS_RE.search(text)
        if not m:
            return None
        digits = re.sub(r"\D", "", m.group(1))
        return int(digits) if digits else None
