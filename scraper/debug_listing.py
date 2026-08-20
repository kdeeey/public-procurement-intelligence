"""Debug: fetch AllCons listing and inspect results structure."""
import sys, re
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import requests
from bs4 import BeautifulSoup

BASE = "https://www.marchespublics.gov.ma/index.php"
HEADERS = {"User-Agent": "public-procurement-intelligence-bot (academic project)"}

# AllCons = all consultations listing (not just current)
URL = f"{BASE}?page=entreprise.EntrepriseAdvancedSearch&AllCons&searchAnnCons&page_courante=1"

resp = requests.get(URL, headers=HEADERS, timeout=30)
print(f"Status: {resp.status_code}  Final: {resp.url}\n")

soup = BeautifulSoup(resp.text, "html.parser")
Path("data/raw/debug_allcons.html").write_text(resp.text, encoding="utf-8")
print("Saved → data/raw/debug_allcons.html\n")

# Look for result rows — typically each consultation is a <tr> or <div> with a link
print("=== LINKS WITH 'DetailConsultation' or 'AnnonsesResultats' or similar ===")
for a in soup.find_all("a", href=True):
    href = a["href"]
    text = a.get_text(strip=True)[:80]
    if any(k in href for k in ["Detail", "detail", "Annons", "annons", "Result", "result", "ref=", "id="]):
        print(f"  [{text[:60]}] -> {href}")

print("\n=== ALL LINKS ON PAGE ===")
for a in soup.find_all("a", href=True):
    text = a.get_text(strip=True)[:60]
    href = a["href"]
    if href not in ("#", "") and "domaineActivite" not in href:
        print(f"  [{text}] -> {href}")

print("\n=== DATES ===")
dates = re.findall(r'\d{2}/\d{2}/\d{4}', resp.text)
print(f"  {len(dates)} date strings found: {dates[:15]}")

print("\n=== TABLES ===")
for i, tbl in enumerate(soup.find_all("table")):
    rows = tbl.find_all("tr")
    if len(rows) > 1:
        print(f"\n  Table {i} ({len(rows)} rows):")
        for row in rows[:4]:
            print(f"    {row.get_text(separator=' | ', strip=True)[:150]}")
