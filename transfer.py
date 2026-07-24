import json, os, re, requests, feedparser, socket
from datetime import datetime, timezone
from time import mktime

socket.setdefaulttimeout(20)

TOKEN = os.environ["TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]
DAKIKA = 75          # son kaç dakikaya bak (15 dk job + pay)
MAX_MESAJ = 10       # tek turda en fazla kaç bildirim

# ---------------- KAYNAKLAR ----------------
FEEDS = [
    # Türkçe — genel transfer
    ("TR", "https://news.google.com/rss/search?q=transfer+(anla%C5%9Fma+OR+imza+OR+bonservis+OR+resmen)+when:1d&hl=tr&gl=TR&ceid=TR:tr"),
    # Türkçe — büyük kulüpler
    ("TR", "https://news.google.com/rss/search?q=(Galatasaray+OR+Fenerbah%C3%A7e+OR+Be%C5%9Fikta%C5%9F+OR+Trabzonspor)+transfer+when:1d&hl=tr&gl=TR&ceid=TR:tr"),
    # İngilizce — dünya transfer
    ("EN", "https://news.google.com/rss/search?q=(transfer+OR+signing)+(agreement+OR+medical+OR+%22here+we+go%22+OR+%22done+deal%22)+when:1d&hl=en-GB&gl=GB&ceid=GB:en"),
    # İngilizce — muhabir odaklı (X'te attıklarını haberleştirenler)
    ("EN", "https://news.google.com/rss/search?q=(%22Fabrizio+Romano%22+OR+%22David+Ornstein%22+OR+%22Gianluca+Di+Marzio%22)+when:1d&hl=en-GB&gl=GB&ceid=GB:en"),
]

# ---------------- FİLTRE ----------------
# Başlıkta bunlardan EN AZ BİRİ olmalı
TETIK = [
    "transfer", "imza", "imzayı", "anlaşma", "anlaştı", "bonservis", "resmen",
    "kadroya kattı", "sözleşme", "teklif", "görüşme", "sağlık kontrolü",
    "ayrılıyor", "geliyor", "gündemde", "resmi teklif", "ön protokol",
    "signing", "signs", "agreement", "medical", "here we go", "done deal",
    "bid", "offer", "deal", "joins", "completed", "agreed", "verbal",
]

# Bunlardan biri geçerse ELE (spam/alakasız)
YASAK = [
    "iddaa", "bahis", "kupon", "banko", "tahmin", "canlı skor",
    "e-transfer", "para transferi", "havale", "transfer ücreti banka",
    "basketbol transfer dedikodu", "hangi kanalda", "şifresiz",
]

def gonder(metin):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": metin,
                  "parse_mode": "HTML", "disable_web_page_preview": True},
            timeout=15
        )
    except Exception as e:
        print("Telegram hatası:", e)

def sadelestir(b):
    """Aynı haberi farklı sitelerden ayırt etmek için normalize et"""
    b = b.lower()
    b = re.sub(r"\s*-\s*[^-]+$", "", b)          # sondaki "- Site Adı" kısmını at
    b = re.sub(r"[^a-zçğıöşü0-9 ]", "", b)
    b = re.sub(r"\s+", " ", b).strip()
    return " ".join(sorted(b.split()))            # kelime sırası farkını yok say

def onem(baslik):
    """Kesinleşmiş haber mi, söylenti mi"""
    b = baslik.lower()
    if any(k in b for k in ["resmen", "imzaladı", "here we go", "done deal",
                            "completed", "official", "açıklandı", "duyurdu"]):
        return "🔴 KESİN"
    if any(k in b for k in ["sağlık kontrolü", "medical", "anlaşma sağlandı",
                            "agreed", "el sıkıştı", "imza için"]):
        return "🟠 SON AŞAMA"
    return "🟡 SÖYLENTİ"

# ---------------- ÇALIŞMA ----------------
DOSYA = "gorulen.json"
gorulen = set(json.load(open(DOSYA))) if os.path.exists(DOSYA) else set()

simdi = datetime.now(timezone.utc)
bulunanlar = []

for etiket, url in FEEDS:
    try:
        r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
        feed = feedparser.parse(r.content)
        print(f"[{etiket}] {len(feed.entries)} kayıt")

        for e in feed.entries:
            baslik = e.get("title", "")
            link = e.get("link", "")
            if not baslik or not link:
                continue

            # yaş kontrolü
            yayin = e.get("published_parsed")
            if yayin:
                dakika = (simdi - datetime.fromtimestamp(mktime(yayin), timezone.utc)).total_seconds() / 60
                if dakika > DAKIKA:
                    continue

            anahtar = sadelestir(baslik)
            if anahtar in gorulen:
                continue

            b = baslik.lower()
            if any(y in b for y in YASAK):
                continue
            if not any(t in b for t in TETIK):
                continue

            kaynak = e.get("source", {}).get("title", "")
            bulunanlar.append(
                f"{onem(baslik)} · {etiket}\n<b>{baslik}</b>\n"
                + (f"<i>{kaynak}</i>\n" if kaynak else "")
                + link
            )
            gorulen.add(anahtar)

    except Exception as ex:
        print("Feed hatası:", etiket, type(ex).__name__, ex)

# kesin haberler üstte
oncelik = {"🔴": 0, "🟠": 1, "🟡": 2}
bulunanlar.sort(key=lambda x: oncelik.get(x[:2], 9))
bulunanlar = bulunanlar[:MAX_MESAJ]

for i in range(0, len(bulunanlar), 4):
    gonder("⚽ <b>Transfer</b>\n\n" + "\n\n".join(bulunanlar[i:i+4]))

json.dump(list(gorulen)[-3000:], open(DOSYA, "w"))
print(f"Gönderilen: {len(bulunanlar)}")
