import os
import time
import secrets
import requests
from flask import Flask, request, redirect, url_for, session, render_template_string

app = Flask(__name__)

app.secret_key = os.environ.get(
    "FLASK_SECRET_KEY",
    "CHANGE_THIS_SECRET_KEY_IN_PRODUCTION"
)

TRENDYOL_ORDER_URL = "https://apigw.trendyol.com/integration/order/sellers"
TRENDYOL_PRODUCT_URL = "https://apigw.trendyol.com/integration/product/sellers"

REQUEST_TIMEOUT = 20
ORDER_PAGE_SIZE = 200
PRODUCT_BATCH_SIZE = 50
MAX_ORDER_PAGES = 50
SESSION_TTL = 3600

AKTIF_OTURUMLAR = {}


HTML_SABLONU = """
<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>FeedBackLoop</title>
<script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-gray-50 min-h-screen text-gray-800">

<nav class="bg-white border-b">
<div class="max-w-7xl mx-auto px-4 py-4 flex flex-wrap items-center gap-5">
<a href="/" class="font-bold text-blue-600">🏠 Panel</a>
<a href="/ayarlar" class="font-bold text-blue-600">⚙️ Ayarlar</a>
{% if oturum %}
<a href="/tarama" class="font-bold text-blue-600">🔍 Siparişleri Tara</a>
<a href="/cikis" class="font-bold text-red-600">Çıkış</a>
{% endif %}
</div>
</nav>

<main class="max-w-7xl mx-auto px-4 py-8">

{% if hata %}
<div class="bg-red-100 border border-red-300 text-red-700 p-4 rounded-lg mb-6">
<strong>Hata:</strong> {{ hata }}
</div>
{% endif %}

{% if basari %}
<div class="bg-green-100 border border-green-300 text-green-700 p-4 rounded-lg mb-6">
{{ basari }}
</div>
{% endif %}

{{ icerik|safe }}

</main>
</body>
</html>
"""


def sayfa(icerik, hata="", basari=""):
    return render_template_string(
        HTML_SABLONU,
        icerik=icerik,
        hata=hata,
        basari=basari,
        oturum=bool(session.get("oturum_token"))
    )


def html_escape(value):
    if value is None:
        return ""

    value = str(value)

    return (
        value
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#x27;")
    )


def aktif_baglanti():
    token = session.get("oturum_token")

    if not token:
        return None

    baglanti = AKTIF_OTURUMLAR.get(token)

    if not baglanti:
        return None

    if time.time() - baglanti["olusturma_zamani"] > SESSION_TTL:
        AKTIF_OTURUMLAR.pop(token, None)
        session.clear()
        return None

    return baglanti


def api_get(url, seller_id, api_key, api_secret, params=None):
    headers = {
        "User-Agent": f"{seller_id} - SelfIntegration",
        "Accept": "application/json"
    }

    try:
        response = requests.get(
            url,
            params=params or {},
            auth=(api_key, api_secret),
            headers=headers,
            timeout=REQUEST_TIMEOUT
        )
    except requests.exceptions.Timeout:
        raise RuntimeError("Trendyol API bağlantısı zaman aşımına uğradı.")
    except requests.exceptions.ConnectionError:
        raise RuntimeError("Trendyol API sunucusuna bağlantı kurulamadı.")
    except requests.exceptions.RequestException as exc:
        raise RuntimeError(f"API bağlantı hatası: {exc}")

    if response.status_code == 200:
        try:
            return response.json()
        except ValueError:
            raise RuntimeError("Trendyol API geçersiz JSON yanıtı döndürdü.")

    if response.status_code == 400:
        raise RuntimeError("Trendyol API isteğinde geçersiz parametre var.")

    if response.status_code == 401:
        raise RuntimeError("API Key veya API Secret hatalı.")

    if response.status_code == 403:
        raise RuntimeError("Trendyol API erişim yetkisi reddedildi.")

    if response.status_code == 404:
        raise RuntimeError("Satıcı ID veya API endpoint'i bulunamadı.")

    if response.status_code == 429:
        raise RuntimeError("Trendyol API hız limiti aşıldı. Lütfen tekrar deneyin.")

    if response.status_code >= 500:
        raise RuntimeError(
            f"Trendyol API geçici sunucu hatası verdi: HTTP {response.status_code}"
        )

    raise RuntimeError(
        f"Trendyol API beklenmeyen HTTP kodu döndürdü: {response.status_code}"
    )


def siparis_paketlerini_getir(baglanti):
    seller_id = baglanti["seller_id"]
    api_key = baglanti["api_key"]
    api_secret = baglanti["api_secret"]

    tum_paketler = []

    for page in range(MAX_ORDER_PAGES):

        url = f"{TRENDYOL_ORDER_URL}/{seller_id}/v2/orders"

        params = {
            "status": "Delivered",
            "page": page,
            "size": ORDER_PAGE_SIZE,
            "orderByField": "PackageLastModifiedDate",
            "orderByDirection": "DESC"
        }

        data = api_get(
            url,
            seller_id,
            api_key,
            api_secret,
            params
        )

        content = data.get("content", [])

        if not isinstance(content, list):
            raise RuntimeError("Trendyol sipariş listesi okunamadı.")

        tum_paketler.extend(content)

        total_pages = data.get("totalPages")

        if total_pages is not None:
            try:
                if page + 1 >= int(total_pages):
                    break
            except (TypeError, ValueError):
                pass

        if len(content) < ORDER_PAGE_SIZE:
            break

    return tum_paketler


def urun_desilerini_getir(baglanti, barkodlar):
    """
    Onaylı ürünleri V2 endpointinden 50'şer barkod halinde alır.

    Dönen yapı:
    {
        "barkod": {
            "dimensionalWeight": 2.0,
            "productName": "..."
        }
    }
    """

    if not barkodlar:
        return {}

    seller_id = baglanti["seller_id"]
    api_key = baglanti["api_key"]
    api_secret = baglanti["api_secret"]

    sonuc = {}

    benzersiz_barkodlar = []

    for barkod in barkodlar:
        if barkod is None:
            continue

        barkod = str(barkod).strip()

        if barkod and barkod not in benzersiz_barkodlar:
            benzersiz_barkodlar.append(barkod)

    for baslangic in range(
        0,
        len(benzersiz_barkodlar),
        PRODUCT_BATCH_SIZE
    ):

        batch = benzersiz_barkodlar[
            baslangic:baslangic + PRODUCT_BATCH_SIZE
        ]

        url = (
            f"{TRENDYOL_PRODUCT_URL}/"
            f"{seller_id}/products/approved"
        )

        params = {
            "barcodes": ",".join(batch),
            "size": PRODUCT_BATCH_SIZE
        }

        data = api_get(
            url,
            seller_id,
            api_key,
            api_secret,
            params
        )

        content = data.get("content", [])

        if not isinstance(content, list):
            continue

        for item in content:

            # V2 approved response'larında varyant bilgisi bulunabilir.
            variants = item.get("variants")

            if isinstance(variants, list):
                for variant in variants:
                    barcode = variant.get("barcode")

                    if barcode is None:
                        barcode = item.get("barcode")

                    if barcode is None:
                        continue

                    dimensional_weight = variant.get(
                        "dimensionalWeight"
                    )

                    if dimensional_weight is None:
                        dimensional_weight = item.get(
                            "dimensionalWeight"
                        )

                    sonuc[str(barcode)] = {
                        "dimensionalWeight": dimensional_weight,
                        "productName": (
                            variant.get("title")
                            or item.get("title")
                            or ""
                        )
                    }

            else:
                barcode = item.get("barcode")

                if barcode is None:
                    continue

                sonuc[str(barcode)] = {
                    "dimensionalWeight": item.get(
                        "dimensionalWeight"
                    ),
                    "productName": item.get(
                        "title",
                        ""
                    )
                }

    return sonuc


def sayisal_deger(value):
    if value is None:
        return None

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def paket_analiz_et(paket, urunler):
    """
    Paket için beklenen desiyi hesaplar.

    Beklenen desi =
        ürün dimensionalWeight × quantity

    Karşılaştırma:
        cargoDeci > beklenen desi -> POTANSİYEL FAZLA DESİ
        cargoDeci < beklenen desi -> düşük değer
        eşitse -> UYUMLU

    Ürün desisi eksikse HESAPLANAMADI döner.
    """

    cargo_deci = sayisal_deger(
        paket.get("cargoDeci")
    )

    if cargo_deci is None:
        return {
            "durum": "HESAPLANAMADI",
            "cargo_deci": None,
            "beklenen_desi": None,
            "fark": None,
            "urunler": []
        }

    toplam_beklenen = 0.0
    eksik_urun = False
    urun_detaylari = []

    lines = paket.get("lines", [])

    if not isinstance(lines, list) or not lines:
        return {
            "durum": "HESAPLANAMADI",
            "cargo_deci": cargo_deci,
            "beklenen_desi": None,
            "fark": None,
            "urunler": []
        }

    for line in lines:

        stock_code = line.get("stockCode")

        # Sipariş line'ında barkod farklı isimlerle gelebilir.
        barcode = (
            line.get("barcode")
            or line.get("merchantSku")
            or line.get("productCode")
            or stock_code
        )

        quantity = line.get("quantity", 1)

        try:
            quantity = float(quantity)
        except (TypeError, ValueError):
            quantity = 1.0

        product = urunler.get(
            str(barcode)
        ) if barcode is not None else None

        dimensional_weight = None

        if product:
            dimensional_weight = sayisal_deger(
                product.get("dimensionalWeight")
            )

        if dimensional_weight is None:
            eksik_urun = True

        else:
            toplam_beklenen += (
                dimensional_weight * quantity
            )

        urun_detaylari.append({
            "barcode": barcode,
            "stock_code": stock_code,
            "product_name": line.get(
                "productName",
                ""
            ),
            "quantity": quantity,
            "dimensional_weight": dimensional_weight
        })

    if eksik_urun:
        return {
            "durum": "HESAPLANAMADI",
            "cargo_deci": cargo_deci,
            "beklenen_desi": toplam_beklenen if toplam_beklenen > 0 else None,
            "fark": None,
            "urunler": urun_detaylari
        }

    fark = cargo_deci - toplam_beklenen

    # Float hassasiyetinden kaynaklanan küçük farkları yok say.
    if abs(fark) < 0.01:
        durum = "UYUMLU"
    elif fark > 0:
        durum = "FAZLA_DESİ"
    else:
        durum = "DÜŞÜK_DESİ"

    return {
        "durum": durum,
        "cargo_deci": cargo_deci,
        "beklenen_desi": toplam_beklenen,
        "fark": fark,
        "urunler": urun_detaylari
    }


def para_desi(value):
    if value is None:
        return "-"

    return f"{value:.2f}".rstrip("0").rstrip(".")


@app.route("/")
def ana_sayfa():

    baglanti = aktif_baglanti()

    hata = session.pop("hata_mesaji", "")
    basari = session.pop("basari_mesaji", "")

    if not baglanti:

        icerik = """
        <div class="bg-white p-8 rounded-xl border">
            <h1 class="text-2xl font-bold mb-3">
                FeedBackLoop
            </h1>

            <p class="text-gray-600 mb-6">
                Trendyol mağazanızı bağlayarak siparişlerdeki
                kargo desi farklılıklarını kontrol edin.
            </p>

            <a href="/ayarlar"
               class="inline-block bg-blue-600 text-white px-6 py-3 rounded-lg font-semibold">
                Trendyol Mağazasını Bağla
            </a>
        </div>
        """

        return sayfa(
            icerik,
            hata=hata,
            basari=basari
        )

    magaza = html_escape(
        baglanti["magaza_adi"]
    )

    icerik = f"""
    <div class="bg-white p-8 rounded-xl border">

        <h1 class="text-2xl font-bold mb-2">
            FeedBackLoop
        </h1>

        <p class="text-gray-500 mb-6">
            Bağlı mağaza:
            <strong>{magaza}</strong>
        </p>

        <div class="grid md:grid-cols-3 gap-4 mb-6">

            <div class="border rounded-lg p-5">
                <div class="text-sm text-gray-500">
                    Bağlantı
                </div>
                <div class="text-xl font-bold text-green-600">
                    Aktif
                </div>
            </div>

            <div class="border rounded-lg p-5">
                <div class="text-sm text-gray-500">
                    Siparişler
                </div>
                <div class="text-xl font-bold">
                    Hazır
                </div>
            </div>

            <div class="border rounded-lg p-5">
                <div class="text-sm text-gray-500">
                    Desi Kontrolü
                </div>
                <div class="text-xl font-bold">
                    Aktif
                </div>
            </div>

        </div>

        <a href="/tarama"
           class="inline-block bg-blue-600 text-white px-6 py-3 rounded-lg font-semibold">
            Siparişleri Tara
        </a>

    </div>
    """

    return sayfa(
        icerik,
        hata=hata,
        basari=basari
    )


@app.route("/ayarlar", methods=["GET", "POST"])
def ayarlar_sayfasi():

    if request.method == "POST":

        magaza_adi = request.form.get(
            "magaza_adi",
            ""
        ).strip()

        seller_id = request.form.get(
            "satici_id",
            ""
        ).strip()

        api_key = request.form.get(
            "api_key",
            ""
        ).strip()

        api_secret = request.form.get(
            "api_secret",
            ""
        ).strip()

        if not magaza_adi:
            return sayfa(
                ayarlar_formu(),
                hata="Mağaza adı zorunludur."
            )

        if not seller_id:
            return sayfa(
                ayarlar_formu(),
                hata="Satıcı ID zorunludur."
            )

        if not seller_id.isdigit():
            return sayfa(
                ayarlar_formu(),
                hata="Satıcı ID yalnızca rakamlardan oluşmalıdır."
            )

        if not api_key:
            return sayfa(
                ayarlar_formu(),
                hata="API Key zorunludur."
            )

        if not api_secret:
            return sayfa(
                ayarlar_formu(),
                hata="API Secret zorunludur."
            )

        try:

            # Gerçek bağlantı testi.
            api_get(
                f"{TRENDYOL_ORDER_URL}/{seller_id}/v2/orders",
                seller_id,
                api_key,
                api_secret,
                {
                    "status": "Delivered",
                    "page": 0,
                    "size": 1
                }
            )

        except RuntimeError as exc:

            return sayfa(
                ayarlar_formu(),
                hata=str(exc)
            )

        token = secrets.token_urlsafe(32)

        AKTIF_OTURUMLAR[token] = {
            "magaza_adi": magaza_adi,
            "seller_id": seller_id,
            "api_key": api_key,
            "api_secret": api_secret,
            "olusturma_zamani": time.time()
        }

        session.clear()
        session["oturum_token"] = token
        session["basari_mesaji"] = (
            "Trendyol mağazası başarıyla bağlandı."
        )

        return redirect(
            url_for("ana_sayfa")
        )

    return sayfa(
        ayarlar_formu()
    )


def ayarlar_formu():

    return """
    <div class="max-w-xl">

    <div class="bg-white p-6 rounded-xl border">

    <h1 class="text-2xl font-bold mb-2">
        Trendyol Mağaza Bağlantısı
    </h1>

    <p class="text-gray-500 mb-6">
        API bilgilerinizi girerek mağazanızı bağlayın.
    </p>

    <form method="POST" class="space-y-4">

        <div>
            <label class="block text-sm font-semibold mb-1">
                Mağaza Adı
            </label>

            <input
                type="text"
                name="magaza_adi"
                required
                autocomplete="organization"
                class="w-full p-3 border rounded-lg"
                placeholder="Mağazam"
            >
        </div>

        <div>
            <label class="block text-sm font-semibold mb-1">
                Satıcı ID
            </label>

            <input
                type="text"
                name="satici_id"
                required
                inputmode="numeric"
                autocomplete="off"
                class="w-full p-3 border rounded-lg"
                placeholder="123456"
            >
        </div>

        <div>
            <label class="block text-sm font-semibold mb-1">
                API Key
            </label>

            <input
                type="text"
                name="api_key"
                required
                autocomplete="off"
                class="w-full p-3 border rounded-lg"
                placeholder="API Key"
            >
        </div>

        <div>
            <label class="block text-sm font-semibold mb-1">
                API Secret
            </label>

            <input
                type="password"
                name="api_secret"
                required
                autocomplete="new-password"
                class="w-full p-3 border rounded-lg"
                placeholder="API Secret"
            >
        </div>

        <button
            type="submit"
            class="w-full bg-blue-600 hover:bg-blue-700 text-white p-3 rounded-lg font-semibold">
            Bağlantıyı Test Et
        </button>

    </form>

    </div>
    </div>
    """


@app.route("/tarama")
def tarama():

    baglanti = aktif_baglanti()

    if not baglanti:

        session["hata_mesaji"] = (
            "Önce Trendyol mağazanızı bağlamalısınız."
        )

        return redirect(
            url_for("ayarlar_sayfasi")
        )

    try:

        # 1. Delivered paketleri çek.
        paketler = siparis_paketlerini_getir(
            baglanti
        )

        # 2. Siparişlerde kullanılan barkodları çıkar.
        barkodlar = []

        for paket in paketler:

            lines = paket.get(
                "lines",
                []
            )

            if not isinstance(lines, list):
                continue

            for line in lines:

                barcode = (
                    line.get("barcode")
                    or line.get("merchantSku")
                    or line.get("productCode")
                    or line.get("stockCode")
                )

                if barcode:
                    barkodlar.append(
                        str(barcode)
                    )

        # 3. Ürünlerin tanımlı desilerini getir.
        urunler = urun_desilerini_getir(
            baglanti,
            barkodlar
        )

        # 4. Her paketi analiz et.
        analizler = []

        for paket in paketler:

            analiz = paket_analiz_et(
                paket,
                urunler
            )

            analizler.append(
                (paket, analiz)
            )

    except RuntimeError as exc:

        return sayfa(
            """
            <div class="bg-white p-8 rounded-xl border">
                <h1 class="text-2xl font-bold mb-3">
                    Tarama Başarısız
                </h1>

                <a href="/tarama"
                   class="inline-block bg-blue-600 text-white px-5 py-3 rounded-lg">
                    Tekrar Dene
                </a>
            </div>
            """,
            hata=str(exc)
        )

    toplam = len(analizler)

    fazla = sum(
        1
        for _, analiz in analizler
        if analiz["durum"] == "FAZLA_DESİ"
    )

    uyumlu = sum(
        1
        for _, analiz in analizler
        if analiz["durum"] == "UYUMLU"
    )

    hesaplanamadi = sum(
        1
        for _, analiz in analizler
        if analiz["durum"] == "HESAPLANAMADI"
    )

    dusuk = sum(
        1
        for _, analiz in analizler
        if analiz["durum"] == "DÜŞÜK_DESİ"
    )

    satirlar = []

    for paket, analiz in analizler:

        package_id = html_escape(
            paket.get(
                "shipmentPackageId",
                "-"
            )
        )

        order_number = html_escape(
            paket.get(
                "orderNumber",
                "-"
            )
        )

        shipment_number = html_escape(
            paket.get(
                "shipmentNumber",
                paket.get(
                    "cargoTrackingNumber",
                    "-"
                )
            )
        )

        cargo_provider = html_escape(
            paket.get(
                "cargoProviderName",
                "-"
            )
        )

        cargo_deci = analiz["cargo_deci"]

        beklenen = analiz["beklenen_desi"]

        fark = analiz["fark"]

        if analiz["durum"] == "FAZLA_DESİ":

            durum_html = """
            <span class="inline-block px-2 py-1 rounded bg-red-100 text-red-700 font-semibold">
                FAZLA DESİ
            </span>
            """

        elif analiz["durum"] == "UYUMLU":

            durum_html = """
            <span class="inline-block px-2 py-1 rounded bg-green-100 text-green-700 font-semibold">
                UYUMLU
            </span>
            """

        elif analiz["durum"] == "DÜŞÜK_DESİ":

            durum_html = """
            <span class="inline-block px-2 py-1 rounded bg-yellow-100 text-yellow-700 font-semibold">
                DÜŞÜK DESİ
            </span>
            """

        else:

            durum_html = """
            <span class="inline-block px-2 py-1 rounded bg-gray-100 text-gray-700 font-semibold">
                HESAPLANAMADI
            </span>
            """

        satirlar.append(
            f"""
            <tr class="border-b hover:bg-gray-50">

                <td class="p-3">
                    {package_id}
                </td>

                <td class="p-3">
                    {order_number}
                </td>

                <td class="p-3">
                    {shipment_number}
                </td>

                <td class="p-3">
                    {cargo_provider}
                </td>

                <td class="p-3 font-semibold">
                    {para_desi(cargo_deci)}
                </td>

                <td class="p-3">
                    {para_desi(beklenen)}
                </td>

                <td class="p-3">
                    {para_desi(fark)}
                </td>

                <td class="p-3">
                    {durum_html}
                </td>

            </tr>
            """
        )

    if not satirlar:

        tablo = """
        <div class="bg-white p-8 rounded-xl border">
            <h2 class="text-xl font-bold mb-2">
                Sipariş bulunamadı
            </h2>

            <p class="text-gray-500">
                Delivered durumunda paket bulunamadı.
            </p>
        </div>
        """

    else:

        tablo = f"""
        <div class="bg-white rounded-xl border overflow-hidden">

        <div class="p-5 border-b">
            <h2 class="text-lg font-bold">
                Desi Mutabakat Sonuçları
            </h2>

            <p class="text-sm text-gray-500 mt-1">
                Ürün tanımlı desisi ile paket cargoDeci değeri karşılaştırıldı.
            </p>
        </div>

        <div class="overflow-x-auto">

        <table class="w-full text-left text-sm">

        <thead class="bg-gray-50">
        <tr>
            <th class="p-3">Paket ID</th>
            <th class="p-3">Sipariş No</th>
            <th class="p-3">Kargo No</th>
            <th class="p-3">Kargo</th>
            <th class="p-3">Cargo Desi</th>
            <th class="p-3">Beklenen</th>
            <th class="p-3">Fark</th>
            <th class="p-3">Sonuç</th>
        </tr>
        </thead>

        <tbody>
        {"".join(satirlar)}
        </tbody>

        </table>

        </div>
        </div>
        """

    icerik = f"""
    <div class="mb-6">

        <h1 class="text-2xl font-bold">
            Sipariş Tarama
        </h1>

        <p class="text-gray-500 mt-1">
            Delivered siparişleri desi açısından kontrol edildi.
        </p>

    </div>

    <div class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">

        <div class="bg-white p-5 rounded-xl border">
            <div class="text-sm text-gray-500">
                Toplam Paket
            </div>
            <div class="text-2xl font-bold">
                {toplam}
            </div>
        </div>

        <div class="bg-white p-5 rounded-xl border">
            <div class="text-sm text-gray-500">
                Fazla Desi
            </div>
            <div class="text-2xl font-bold text-red-600">
                {fazla}
            </div>
        </div>

        <div class="bg-white p-5 rounded-xl border">
            <div class="text-sm text-gray-500">
                Uyumlu
            </div>
            <div class="text-2xl font-bold text-green-600">
                {uyumlu}
            </div>
        </div>

        <div class="bg-white p-5 rounded-xl border">
            <div class="text-sm text-gray-500">
                Hesaplanamadı
            </div>
            <div class="text-2xl font-bold">
                {hesaplanamadi}
            </div>
        </div>

    </div>

    {tablo}

    <div class="mt-6">

        <a href="/tarama"
           class="inline-block bg-blue-600 text-white px-5 py-3 rounded-lg font-semibold">
            Yeniden Tara
        </a>

    </div>
    """

    return sayfa(
        icerik
    )


@app.route("/cikis")
def exodus_yap():

    token = session.get(
        "oturum_token"
    )

    if token:
        AKTIF_OTURUMLAR.pop(
            token,
            None
        )

    session.clear()

    return redirect(
        url_for("ana_sayfa")
    )


@app.errorhandler(404)
def sayfa_bulunamadi(error):

    return sayfa(
        """
        <div class="bg-white p-8 rounded-xl border text-center">

            <h1 class="text-3xl font-bold mb-3">
                404
            </h1>

            <p class="text-gray-500 mb-6">
                Sayfa bulunamadı.
            </p>

            <a href="/"
               class="inline-block bg-blue-600 text-white px-5 py-3 rounded-lg">
                Ana Sayfaya Dön
            </a>

        </div>
        """
    ), 404


@app.errorhandler(500)
def sunucu_hatasi(error):

    return sayfa(
        """
        <div class="bg-white p-8 rounded-xl border text-center">

            <h1 class="text-3xl font-bold mb-3">
                Sunucu Hatası
            </h1>

            <p class="text-gray-500">
                Beklenmeyen bir hata oluştu.
            </p>

        </div>
        """,
        hata="Sunucu tarafında beklenmeyen bir hata oluştu."
    ), 500


if __name__ == "__main__":

    port = int(
        os.environ.get(
            "PORT",
            10000
        )
    )

    debug = (
        os.environ.get(
            "FLASK_DEBUG",
            "0"
        ) == "1"
    )

    app.run(
        host="0.0.0.0",
        port=port,
        debug=debug
    )
