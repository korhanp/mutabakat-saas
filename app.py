import os
import time
import secrets
import requests
from flask import Flask, request, redirect, url_for, session, render_template_string

app = Flask(__name__)

# Production'da mutlaka environment variable kullanın.
app.secret_key = os.environ.get(
    "FLASK_SECRET_KEY",
    "development-only-change-this-secret-key"
)

TRENDYOL_BASE_URL = "https://apigw.trendyol.com/integration/order/sellers"
REQUEST_TIMEOUT = 15
PAGE_SIZE = 200
MAX_PAGES = 50

# Basit MVP için sunucu belleğinde tutulur.
# Flask'ın imzalı session cookie'sine API Secret yazılmaz.
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

<nav class="bg-white border-b px-4 py-4">
    <div class="max-w-6xl mx-auto flex flex-wrap items-center gap-4">
        <a href="/" class="font-bold text-blue-600">🏠 Panel</a>
        <a href="/ayarlar" class="font-bold text-blue-600">⚙️ Giriş</a>

        {% if oturum %}
            <a href="/tarama" class="font-bold text-blue-600">🔍 Siparişleri Tara</a>
            <a href="/cikis" class="font-bold text-red-600">Çıkış</a>
        {% endif %}
    </div>
</nav>

<main class="max-w-6xl mx-auto px-4 py-8">

    {% if hata %}
        <div class="bg-red-100 border border-red-300 text-red-700 p-4 rounded mb-6">
            {{ hata }}
        </div>
    {% endif %}

    {% if basari %}
        <div class="bg-green-100 border border-green-300 text-green-700 p-4 rounded mb-6">
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


def aktif_baglanti():
    token = session.get("oturum_token")

    if not token:
        return None

    return AKTIF_OTURUMLAR.get(token)


def trendyol_get(seller_id, api_key, api_secret, params):
    """
    Trendyol Order V2 API isteği.
    """

    url = f"{TRENDYOL_BASE_URL}/{seller_id}/v2/orders"

    headers = {
        "User-Agent": f"{seller_id} - SelfIntegration",
        "Accept": "application/json"
    }

    try:
        response = requests.get(
            url,
            params=params,
            auth=(api_key, api_secret),
            headers=headers,
            timeout=REQUEST_TIMEOUT
        )
    except requests.exceptions.Timeout:
        raise RuntimeError(
            "Trendyol API bağlantısı zaman aşımına uğradı."
        )
    except requests.exceptions.ConnectionError:
        raise RuntimeError(
            "Trendyol API sunucusuna bağlantı kurulamadı."
        )
    except requests.exceptions.RequestException as exc:
        raise RuntimeError(
            f"Trendyol API bağlantı hatası: {exc}"
        )

    if response.status_code == 200:
        try:
            return response.json()
        except ValueError:
            raise RuntimeError(
                "Trendyol API geçersiz JSON yanıtı döndürdü."
            )

    if response.status_code == 401:
        raise RuntimeError(
            "API Key veya API Secret hatalı."
        )

    if response.status_code == 403:
        raise RuntimeError(
            "Trendyol API erişim yetkisi reddedildi."
        )

    if response.status_code == 404:
        raise RuntimeError(
            "Satıcı ID bulunamadı veya API endpoint'i geçersiz."
        )

    if response.status_code == 429:
        raise RuntimeError(
            "Trendyol API hız limiti aşıldı. Lütfen kısa süre sonra tekrar deneyin."
        )

    if response.status_code == 426:
        raise RuntimeError(
            "Trendyol API eski endpoint kullanımını reddetti. Order V2 kullanılmalıdır."
        )

    try:
        detay = response.json()
    except ValueError:
        detay = response.text[:500]

    raise RuntimeError(
        f"Trendyol API hata kodu: {response.status_code} - {detay}"
    )


def paketleri_getir(baglanti):
    """
    Delivered durumundaki sipariş paketlerini sayfalayarak getirir.
    """

    seller_id = baglanti["seller_id"]
    api_key = baglanti["api_key"]
    api_secret = baglanti["api_secret"]

    tum_paketler = []

    for page in range(MAX_PAGES):

        params = {
            "status": "Delivered",
            "page": page,
            "size": PAGE_SIZE,
            "orderByField": "PackageLastModifiedDate",
            "orderByDirection": "DESC"
        }

        data = trendyol_get(
            seller_id,
            api_key,
            api_secret,
            params
        )

        content = data.get("content", [])

        if not isinstance(content, list):
            raise RuntimeError(
                "Trendyol API yanıtındaki paket listesi okunamadı."
            )

        tum_paketler.extend(content)

        total_pages = data.get("totalPages")

        if total_pages is not None:
            try:
                if page + 1 >= int(total_pages):
                    break
            except (TypeError, ValueError):
                pass

        if len(content) < PAGE_SIZE:
            break

    return tum_paketler


def guvenli_deger(value):
    """
    HTML'e basılacak değerlerin temel güvenli dönüşümü.
    """

    if value is None:
        return ""

    value = str(value)

    replacements = {
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#x27;"
    }

    for eski, yeni in replacements.items():
        value = value.replace(eski, yeni)

    return value


def paket_satiri(paket):
    shipment_package_id = guvenli_deger(
        paket.get("shipmentPackageId", "-")
    )

    order_number = guvenli_deger(
        paket.get("orderNumber", "-")
    )

    cargo_provider = guvenli_deger(
        paket.get("cargoProviderName", "-")
    )

    cargo_deci = paket.get("cargoDeci")

    if cargo_deci is None:
        cargo_deci_html = '<span class="text-gray-400">Belirtilmemiş</span>'
    else:
        cargo_deci_html = (
            f'<strong>{guvenli_deger(cargo_deci)} desi</strong>'
        )

    shipment_number = guvenli_deger(
        paket.get("shipmentNumber", "-")
    )

    last_modified = guvenli_deger(
        paket.get("lastModifiedDate", "-")
    )

    return f"""
    <tr class="border-b">
        <td class="p-3">{shipment_package_id}</td>
        <td class="p-3">{order_number}</td>
        <td class="p-3">{shipment_number}</td>
        <td class="p-3">{cargo_provider}</td>
        <td class="p-3">{cargo_deci_html}</td>
        <td class="p-3 text-sm text-gray-500">{last_modified}</td>
    </tr>
    """


@app.route("/")
def ana_sayfa():
    baglanti = aktif_baglanti()

    if not baglanti:
        icerik = """
        <div class="bg-white p-8 rounded-xl border">
            <h1 class="text-2xl font-bold mb-3">
                FeedBackLoop
            </h1>

            <p class="text-gray-600 mb-6">
                Trendyol mağazanızı bağlayarak sipariş paketlerini
                ve kargo desi bilgilerini kontrol edin.
            </p>

            <a href="/ayarlar"
               class="inline-block bg-blue-600 text-white px-5 py-3 rounded-lg">
                🔒 Trendyol Mağazasını Bağla
            </a>
        </div>
        """

        return sayfa(
            icerik,
            hata=session.pop("hata_mesaji", ""),
            basari=session.pop("basari_mesaji", "")
        )

    magaza = guvenli_deger(
        baglanti.get("magaza_adi", "Mağaza")
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
                <div class="text-gray-500 text-sm">
                    Durum
                </div>
                <div class="text-lg font-bold text-green-600">
                    Bağlı
                </div>
            </div>

            <div class="border rounded-lg p-5">
                <div class="text-gray-500 text-sm">
                    Kontrol
                </div>
                <div class="text-lg font-bold">
                    Hazır
                </div>
            </div>

            <div class="border rounded-lg p-5">
                <div class="text-gray-500 text-sm">
                    Veri
                </div>
                <div class="text-lg font-bold">
                    Trendyol
                </div>
            </div>

        </div>

        <a href="/tarama"
           class="inline-block bg-blue-600 text-white px-5 py-3 rounded-lg">
            🔍 Siparişleri Tara
        </a>

    </div>
    """

    return sayfa(
        icerik,
        hata=session.pop("hata_mesaji", ""),
        basari=session.pop("basari_mesaji", "")
    )


@app.route("/ayarlar", methods=["GET", "POST"])
def ayarlar_sayfasi():

    if request.method == "POST":

        magaza_adi = request.form.get(
            "magaza_adi", ""
        ).strip()

        seller_id = request.form.get(
            "satici_id", ""
        ).strip()

        api_key = request.form.get(
            "api_key", ""
        ).strip()

        api_secret = request.form.get(
            "api_secret", ""
        ).strip()

        if not magaza_adi:
            return sayfa(
                ayarlar_formu(),
                hata="Mağaza adı boş bırakılamaz."
            )

        if not seller_id:
            return sayfa(
                ayarlar_formu(),
                hata="Satıcı ID boş bırakılamaz."
            )

        if not seller_id.isdigit():
            return sayfa(
                ayarlar_formu(),
                hata="Satıcı ID yalnızca rakamlardan oluşmalıdır."
            )

        if not api_key or not api_secret:
            return sayfa(
                ayarlar_formu(),
                hata="API Key ve API Secret zorunludur."
            )

        try:
            # Gerçek bağlantı testi.
            trendyol_get(
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

        # API bilgileri Flask cookie session'a yazılmaz.
        session.clear()
        session["oturum_token"] = token

        session["basari_mesaji"] = (
            "Trendyol mağazası başarıyla bağlandı."
        )

        return redirect(url_for("ana_sayfa"))

    return sayfa(ayarlar_formu())


def ayarlar_formu():
    return """
    <div class="max-w-xl">

        <div class="bg-white p-6 rounded-xl border">

            <h1 class="text-2xl font-bold mb-2">
                Trendyol Mağaza Bağlantısı
            </h1>

            <p class="text-gray-500 mb-6">
                Trendyol API bilgilerinizi girerek mağazanızı bağlayın.
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
                    class="w-full bg-blue-600 hover:bg-blue-700 text-white p-3 rounded-lg font-semibold"
                >
                    🔒 Bağlantıyı Test Et
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
        return redirect(url_for("ayarlar_sayfasi"))

    try:
        paketler = paketleri_getir(baglanti)

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

    toplam = len(paketler)

    # Şu aşamada API'nin döndürdüğü gerçek cargoDeci değerlerini
    # gösteriyoruz.
    # "Hatalı desi" tespiti için beklenen desi hesabı ayrıca
    # tanımlanmalıdır.
    desi_bilgileri = []

    eksik_desi = 0

    for paket in paketler:

        cargo_deci = paket.get("cargoDeci")

        if cargo_deci is None:
            eksik_desi += 1

        desi_bilgileri.append(
            paket_satiri(paket)
        )

    tablo = ""

    if desi_bilgileri:

        tablo = f"""
        <div class="bg-white rounded-xl border overflow-hidden">

            <div class="p-5 border-b">
                <h2 class="text-lg font-bold">
                    Taranan Paketler
                </h2>

                <p class="text-sm text-gray-500 mt-1">
                    {toplam} adet Delivered paket bulundu.
                </p>
            </div>

            <div class="overflow-x-auto">

                <table class="w-full text-left text-sm">

                    <thead class="bg-gray-50">
                        <tr>
                            <th class="p-3">Paket ID</th>
                            <th class="p-3">Sipariş No</th>
                            <th class="p-3">Kargo No</th>
                            <th class="p-3">Kargo Firması</th>
                            <th class="p-3">Cargo Desi</th>
                            <th class="p-3">Son Güncelleme</th>
                        </tr>
                    </thead>

                    <tbody>
                        {"".join(desi_bilgileri)}
                    </tbody>

                </table>

            </div>

        </div>
        """

    else:

        tablo = """
        <div class="bg-white p-8 rounded-xl border">
            <h2 class="text-lg font-bold mb-2">
                Paket bulunamadı
            </h2>

            <p class="text-gray-500">
                Seçilen Delivered durumunda sipariş paketi bulunamadı.
            </p>
        </div>
        """

    ozet = f"""
    <div class="grid md:grid-cols-3 gap-4 mb-6">

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
                Cargo Desi Mevcut
            </div>
            <div class="text-2xl font-bold text-green-600">
                {toplam - eksik_desi}
            </div>
        </div>

        <div class="bg-white p-5 rounded-xl border">
            <div class="text-sm text-gray-500">
                Desi Bilgisi Eksik
            </div>
            <div class="text-2xl font-bold">
                {eksik_desi}
            </div>
        </div>

    </div>
    """

    icerik = f"""
    <div class="mb-6">
        <h1 class="text-2xl font-bold">
            🔍 Sipariş Tarama
        </h1>

        <p class="text-gray-500 mt-1">
            Delivered durumundaki Trendyol paketleri kontrol edildi.
        </p>
    </div>

    {ozet}

    {tablo}

    <div class="mt-6">
        <a href="/tarama"
           class="inline-block bg-blue-600 text-white px-5 py-3 rounded-lg">
            🔄 Yeniden Tara
        </a>
    </div>
    """

    return sayfa(icerik)


@app.route("/cikis")
def exodus_yap():

    token = session.get("oturum_token")

    if token:
        AKTIF_OTURUMLAR.pop(token, None)

    session.clear()

    return redirect(url_for("ana_sayfa"))


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
        os.environ.get("PORT", 10000)
    )

    debug = (
        os.environ.get("FLASK_DEBUG", "0") == "1"
    )

    app.run(
        host="0.0.0.0",
        port=port,
        debug=debug
    )
