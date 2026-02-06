import json
import time
import re
import requests
from playwright.sync_api import sync_playwright, TimeoutError
 
# =====================
# CONFIG
# =====================
LIST_URL = "https://autos.mercadolibre.com.ar/usados"
MAX_AUTOS = 5              # 👈 para pruebas rápidas
MAX_CHARS = 1200           # 👈 evita truncados en Ollama
 
OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "llama3:latest"   # o el que tengas
 
# =====================
# HELPERS
# =====================
 
def parse_price(card):
    currency = "ARS"
    raw = ""
 
    symbol = card.query_selector("span.andes-money-amount__currency-symbol")
    fraction = card.query_selector("span.andes-money-amount__fraction")
 
    if symbol:
        raw += symbol.inner_text()
        if "US" in raw:
            currency = "USD"
 
    if fraction:
        raw += "\n" + fraction.inner_text()
 
    value = None
    if fraction:
        try:
            value = int(fraction.inner_text().replace(".", ""))
        except:
            pass
 
    return {
        "value": value,
        "currency": currency,
        "raw": raw.strip()
    }
 
 
def try_fix_json(text):
    text = text.strip()
 
    if text.startswith("{") and not text.endswith("}"):
        text += "}"
 
    try:
        return json.loads(text)
    except:
        return None
 
 
def parse_ollama_response(text):
    match = re.search(r"\{[\s\S]*", text)
    if not match:
        return None
 
    return try_fix_json(match.group(0))
 
 
# =====================
# SCRAPER
# =====================
 
def scrape_list(page):
    page.goto(LIST_URL, wait_until="domcontentloaded", timeout=90000)
 
    try:
        page.get_by_role("button", name=re.compile("Aceptar", re.I)).click(timeout=4000)
        print("🍪 Cookies aceptadas")
    except:
        pass
 
    page.wait_for_selector("li.ui-search-layout__item", timeout=60000)
    cards = page.query_selector_all("li.ui-search-layout__item")
 
    autos = []
 
    for card in cards[:MAX_AUTOS]:
        title_el = card.query_selector("h2, h3")
        link_el = card.query_selector("a")
 
        if not title_el or not link_el:
            continue
 
        autos.append({
            "title": title_el.inner_text().strip(),
            "link": link_el.get_attribute("href"),
            "price": parse_price(card)
        })
 
    return autos
 
 
def scrape_details(page, auto):
    try:
        page.goto(auto["link"], wait_until="domcontentloaded", timeout=60000)
    except TimeoutError:
        print("⚠️ Timeout detalle")
        return auto
 
    time.sleep(2)
 
    def grab(selector):
        el = page.query_selector(selector)
        return el.inner_text().strip() if el else ""
 
    header = grab("div.ui-pdp-header")
 
    auto["raw_text"] = "=== HEADER ===\n" + header if header else ""
    return auto
 
 
# =====================
# OLLAMA CLEANING
# =====================
 
def clean_with_ollama(auto):
    text = auto["raw_text"][:MAX_CHARS]
 
    prompt = f"""
Extraé información estructurada del siguiente aviso de auto.
Respondé SOLO con JSON válido, sin texto adicional.
 
Campos:
brand, model, version, year, km, is_new, posted_days_ago, segment
 
Texto:
{text}
"""
 
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "temperature": 0,
        "num_predict": 300,
        "stop": ["\n\n"]
    }
 
    try:
        r = requests.post(OLLAMA_URL, json=payload, timeout=60)
        r.raise_for_status()
        response_text = r.json().get("response", "")
    except Exception as e:
        print("❌ Ollama error:", e)
        auto["clean"] = None
        return auto
 
    parsed = parse_ollama_response(response_text)
 
    if not parsed:
        print("⚠️ No se pudo extraer JSON:", response_text[:120])
        auto["clean"] = None
    else:
        auto["clean"] = parsed
 
    return auto
 
 
# =====================
# MAIN
# =====================
 
def main():
    results = []
 
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(locale="es-AR")
        page = context.new_page()
 
        print("🌐 Abriendo MercadoLibre Autos (usados)...")
        autos = scrape_list(page)
        print(f"🚗 Autos encontrados: {len(autos)}")
 
        for auto in autos:
            detail_page = context.new_page()
            auto = scrape_details(detail_page, auto)
            detail_page.close()
 
            auto = clean_with_ollama(auto)
            results.append(auto)
 
        browser.close()
 
    with open("autos_final.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
 
    print("💾 autos_final.json generado")
 
 
if __name__ == "__main__":
    main()