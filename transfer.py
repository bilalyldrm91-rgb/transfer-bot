import json, os, re, requests, feedparser, socket
from datetime import datetime, timezone
from time import mktime

socket.setdefaulttimeout(20)

TOKEN = os.environ["TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]
API_KEY = os.environ["GROQ_API_KEY"]

DAKIKA = 60        # son 1 saat
MAX_MESAJ = 8
MIN_SKOR = 5       # bunun altindaki haberler gonderilmez

FEEDS = [
    ("TR", "https://news.google.com/rss/search?q=transfer+(anla%C5%9Fma+OR+imza+OR+bonservis+OR+resmen)+when:1d&hl=tr&gl=TR&ceid=TR:tr"),
    ("TR", "https://news.google.com/rss/search?q=(Galatasaray+OR+Fenerbah%C3%A7e+OR+Be%C5%9Fikta%C5%9F+OR+Trabzonspor)+transfer+when:1d&hl=tr&gl=TR&ceid=TR:tr"),
    ("EN", "https://news.google.com/rss/search?q=(transfer+OR+signing)+(agreement+OR+medical+OR+%22here+we+go%22+OR+%22done+deal%22)+when:1d&hl=en-GB&gl=GB&ceid=GB:en"),
    ("EN", "https://news.google.com/rss/search?q=(%22Fabrizio+Romano%22+OR+%22David+Ornstein%22+OR+%22Gianluca+Di+Marzio%22)+when:1d&hl=en-GB&gl=GB&ceid=GB:en"),
]

YASAK = ["iddaa", "bahis", "kupon", "banko", "tahmin", "canlı skor",
         "para transferi", "havale", "hangi kanalda", "şifresiz"]


def kacis(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def gonder(metin):
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": metin, "parse_mode": "HTML",
                  "disable_web_page_preview": True},
            timeout=15
        )
        if r.status_code != 200:
            print("TELEGRAM HATASI:", r.status_code, r.text[:250])
    except Exception as e:
        print("Telegram baglanti hatasi:", type(e).__name__, e)


def sadelestir(b):
    b = b.lower()
    b = re.sub(r"\s*-\s*[^-]+$", "", b)
    b = re.sub(r"[^a-zçğıöşü0-9 ]", "", b)
    b = re.sub(r"\s+", " ", b).strip()
    return " ".join(sorted(b.split()))


def temiz_baslik(b):
    return re.sub(r"\s*[-–|]\s*[^-–|]{2,40}$", "", b).strip()


def ai_analiz(haberler):
    liste = "\n".join(f"{i+1}. {h['baslik']}" for i, h in enumerate(haberler))
    prompt = f"""Asagida futbol transfer haberi basliklari var. Her biri icin JSON uret.

{liste}

Her haber icin su alanlar:
- "no": sira numarasi (integer)
- "oyuncu": transfer edilen oyuncunun adi. Yoksa null.
- "kulup": oyuncuyu alan veya ilgilenen kulup. Yoksa null.
- "eski_kulup": oyuncunun mevcut kulubu. Bilinmiyorsa null.
- "durum": "kesin" (resmen aciklandi/imzaladi), "yakin" (saglik kontrolu/anlasma saglandi), "soylenti" (ilgileniyor/gundeminde), "alakasiz" (transfer haberi degil)
- "skor": 1-10 onem. Resmi aciklama 9-10, saglik kontrolu 7-8, ciddi gorusme 5-6, dedikodu 2-4, alakasiz 1.

SADECE JSON dizisi dondur, baska hicbir sey yazma."""

    try:
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {API_KEY}",
                     "Content-Type": "application/json"},
            json={"model": "llama-3.3-70b-versatile",
                  "messages": [{"role": "user", "content": prompt}],
                  "temperature": 0.2,
                  "response_format": {"type": "json_object"}},
            timeout=60
        )
        if r.status_code != 200:
            print("AI HATASI:", r.status_code, r.text[:300])
            return {}

        metin = r.json()["choices"][0]["message"]["content"].strip()
        metin = re.sub(r"^```(?:json)?|```$", "", metin, flags=re.M).strip()
        veri = json.loads(metin)

        # json_object modu bazen {"haberler": [...]} sarmalar
        if isinstance(veri, dict):
            for v in veri.values():
                if isinstance(v, list):
                    veri = v
                    break
        if not isinstance(veri, list):
            print("AI beklenmedik format:", str(veri)[:200])
            return {}

        return {d["no"]: d for d in veri if isinstance(d, dict) and "no" in d}
    except Exception as e:
        print("AI parse hatasi:", type(e).__name__, e)
        return {}


ROZET = {"kesin": "🔴 RESMİ", "yakin": "🟠 SON AŞAMA", "soylenti": "🟡 SÖYLENTİ"}

DOSYA = "gorulen.json"
gorulen = set(json.load(open(DOSYA))) if os.path.exists(DOSYA) else set()

simdi = datetime.now(timezone.utc)
ham = []

for etiket, url in FEEDS:
    try:
        r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
        feed = feedparser.parse(r.content)
        print(f"[{etiket}] {len(feed.entries)} kayit")

        for e in feed.entries:
            baslik = e.get("title", "")
            link = e.get("link", "")
            if not baslik or not link:
                continue

            yayin = e.get("published_parsed")
            if not yayin:
                continue
            dk = (simdi - datetime.fromtimestamp(mktime(yayin), timezone.utc)).total_seconds() / 60
            if dk > DAKIKA:
                continue

            anahtar = sadelestir(baslik)
            if anahtar in gorulen:
                continue
            if any(y in baslik.lower() for y in YASAK):
                continue

            ham.append({
                "baslik": temiz_baslik(baslik),
                "link": link,
                "kaynak": e.get("source", {}).get("title", "Kaynak"),
                "etiket": etiket,
                "dk": int(dk),
            })
            gorulen.add(anahtar)
    except Exception as ex:
        print("Feed hatasi:", etiket, type(ex).__name__, ex)

print(f"Ham haber: {len(ham)}")

gonderilen = 0
if ham:
    ham = ham[:25]
    analiz = ai_analiz(ham)
    mesajlar = []

    for i, h in enumerate(ham):
        a = analiz.get(i + 1, {})
        durum = a.get("durum", "soylenti")
        skor = a.get("skor", 0)

        if durum == "alakasiz" or skor < MIN_SKOR:
            continue

        satir = [f"{ROZET.get(durum, '🟡 SÖYLENTİ')}  ·  {skor}/10"]

        oyuncu = a.get("oyuncu")
        kulup = a.get("kulup")
        eski = a.get("eski_kulup")

        if oyuncu:
            if kulup and eski:
                satir.append(f"⚽ <b>{kacis(str(oyuncu))}</b>   {kacis(str(eski))} → {kacis(str(kulup))}")
            elif kulup:
                satir.append(f"⚽ <b>{kacis(str(oyuncu))}</b> → {kacis(str(kulup))}")
            else:
                satir.append(f"⚽ <b>{kacis(str(oyuncu))}</b>")
        elif kulup:
            satir.append(f"🏟 <b>{kacis(str(kulup))}</b>")

        satir.append(kacis(h["baslik"]))
        satir.append(f'📰 <a href="{h["link"]}">{kacis(h["kaynak"])}</a>  ·  {h["dk"]} dk önce')
        mesajlar.append("\n".join(satir))

    mesajlar = mesajlar[:MAX_MESAJ]
    for i in range(0, len(mesajlar), 3):
        gonder("\n\n➖➖➖\n\n".join(mesajlar[i:i+3]))
    gonderilen = len(mesajlar)

json.dump(list(gorulen)[-3000:], open(DOSYA, "w"))
print(f"Gonderilen: {gonderilen}")
