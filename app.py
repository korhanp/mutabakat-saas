import os
from flask import Flask, render_template_string, request, redirect, url_for, session

app = Flask(__name__)

# Flask Konfigürasyon Ayarları (500 Hatasını Önleyen Kesin Çözüm)
app.config.update(
    SECRET_KEY="KargoMutabakatGuzelGuvenceKeyi98765!",
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax'
)

sahte_trendyol_verisi = [
  {
    "orderNumber": "748392011",
    "totalPrice": 400.00,
    "lines": [{"productName": "Kablosuz Oyuncu Kulaklığı", "realDesi": 2.0}],
    "packageHistories": [{"invoiceDesi": 5.0, "cargoFee": 75.00}]
  }
]

HTML_SABLONU = """
<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <title>FeedBackLoop | Güvenli Mutabakat Paneli</title>
    <script src="https://jsdelivr.net"></script>
</head>
<body class="bg-gray-50 font-sans text-gray-900">
    <nav class="bg-white border-b border-gray-200 px-6 py-4 flex justify-between items-center">
        <div class="flex items-center space-x-3">
            <span class="text-2xl">🛡️</span>
            <span class="text-xl font-bold text-blue-600">FeedBackLoop <span class="text-sm font-normal text-gray-500">SaaS Mutabakat</span></span>
        </div>
        <div class="space-x-4">
            <a href="/" class="text-sm font-medium text-gray-600 hover:text-blue-600">🏠 Panel</a>
            <a href="/ayarlar" class="text-sm font-medium text-gray-600 hover:text-blue-600">⚙️ Mağaza Girişi</a>
            {% if oturum_aktif %}
            <a href="/cikis" class="text-sm font-medium text-red-600 hover:text-red-800">❌ Oturumu Kapat</a>
            {% endif %}
        </div>
    </nav>

    <main class="max-w-7xl mx-auto px-4 py-8">
        {% if sayfa == 'panel' %}
            <div class="mb-6 bg-green-50 border border-green-200 p-4 rounded-xl flex justify-between items-center">
                <span class="text-sm text-green-800">🔒 Güvenli Geçici Bağlantı: <strong>{{ aktif_magaza }}</strong></span>
                <span class="bg-blue-100 text-blue-800 text-xs font-semibold px-2.5 py-0.5 rounded-full">Sıfır Veri Kaydı Modu</span>
            </div>

            {% if oturum_aktif %}
            <div class="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
                <div class="bg-white p-6 rounded-xl border border-gray-200 shadow-xs">
                    <p class="text-sm font-medium text-gray-500 uppercase">🚨 Toplam Finansal Kaçak</p>
                    <p class="text-3xl font-bold text-red-600 mt-2">{{ toplam_zarar }} TL</p>
                </div>
                <div class="bg-white p-6 rounded-xl border border-gray-200 shadow-xs">
                    <p class="text-sm font-medium text-gray-500 uppercase">🔎 İncelenen Sipariş</p>
                    <p class="text-3xl font-bold text-gray-900 mt-2">1 Adet</p>
                </div>
                <div class="bg-white p-6 rounded-xl border border-gray-200 shadow-xs">
                    <p class="text-sm font-medium text-gray-500 uppercase">💡 Hazır İtiraz Talebi</p>
                    <p class="text-3xl font-bold text-blue-600 mt-2">1 Adet</p>
                </div>
            </div>

            <div class="bg-white rounded-xl border border-gray-200 shadow-xs overflow-hidden">
                <table class="w-full text-left">
                    <thead>
                        <tr class="bg-gray-100 text-xs font-semibold text-gray-600 uppercase border-b">
                            <th class="px-6 py-3">Sipariş No</th>
                            <th class="px-6 py-3">Ürün Adı</th>
                            <th class="px-6 py-3 text-center">Gerçek Desi</th>
                            <th class="px-6 py-3 text-center">Kesilen Desi</th>
                            <th class="px-6 py-3 text-right">Zarar</th>
                        </tr>
                    </thead>
                    <tbody class="divide-y divide-gray-200 text-sm">
                        {% for hata in hatalar %}
                        <tr class="hover:bg-gray-50">
                            <td class="px-6 py-4 font-medium">{{ hata.order_no }}</td>
                            <td class="px-6 py-4 text-gray-600">{{ hata.urun_adi }}</td>
                            <td class="px-6 py-4 text-center text-green-600 font-bold">{{ hata.gercek_desi }}</td>
                            <td class="px-6 py-4 text-center text-red-600 font-bold">{{ hata.faturadaki_desi }}</td>
                            <td class="px-6 py-4 text-right text-red-600 font-bold">{{ hata.zarar }} TL</td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
            {% else %}
            <div class="text-center py-12 bg-white border border-gray-200 rounded-xl">
                <p class="text-gray-500 mb-4">Analiz sonuçlarını görmek için lütfen mağaza API anahtarlarınızla geçici oturum açın.</p>
                <a href="/ayarlar" class="bg-blue-600 text-white px-4 py-2 rounded-lg font-medium hover:bg-blue-700">⚙️ API Bilgilerini Gir</a>
            </div>
            {% endif %}

        {% elif sayfa == 'ayarlar' %}
            <div class="max-w-xl mx-auto bg-white border border-gray-200 rounded-xl p-8 shadow-xs">
                <div class="mb-6 p-3 bg-amber-50 border border-amber-200 rounded-lg text-xs text-amber-800">
                    ℹ️ <strong>Müşteri Bilgilendirmesi:</strong> Gireceğiniz API anahtarları hiçbir veritabanına kaydedilmez. Sadece bu tarayıcı sekmesindeki anlık analiz için kullanılır. Çıkış yaptığınızda sistemden tamamen silinir.
                </div>
                <h2 class="text-xl font-bold text-gray-900 mb-6">🔑 Trendyol Mağaza Girişi (Anlık Analiz)</h2>
                <form action="/ayarlar" method="POST" class="space-y-4">
                    <div>
                        <label class="block text-sm font-medium text-gray-700">Mağaza Adı</label>
                        <input type="text" name="magaza_adi" required class="mt-1 block w-full p-2 border border-gray-300 rounded-lg shadow-xs">
                    </div>
                    <div>
                        <label class="block text-sm font-medium text-gray-700">Trendyol Satıcı ID (Partner ID)</label>
                        <input type="text" name="satici_id" required class="mt-1 block w-full p-2 border border-gray-300 rounded-lg shadow-xs">
                    </div>
                    <div>
                        <label class="block text-sm font-medium text-gray-700">API Key</label>
                        <input type="text" name="api_key" required class="mt-1 block w-full p-2 border border-gray-300 rounded-lg shadow-xs">
                    </div>
                    <div>
                        <label class="block text-sm font-medium text-gray-700">API Secret Key</label>
                        <input type="password" name="api_secret" required class="mt-1 block w-full p-2 border border-gray-300 rounded-lg shadow-xs">
                    </div>
                    <button type="submit" class="w-full bg-blue-600 text-white font-medium p-2.5 rounded-lg hover:bg-blue-700 cursor-pointer">
                        🔒 Güvenli Bağlan ve Analiz Et
                    </button>
                </form>
            </div>
        {% endif %}
    </main>
</body>
</html>
"""

@app.route('/')
def ana_sayfa():
    magaza_adi = session.get('magaza_adi')
    oturum_aktif = True if magaza_adi else False
    aktif_magaza = magaza_adi if oturum_aktif else "Oturum Açılmadı"
    hatalar = []
    toplam_zarar = 0
    if oturum_aktif:
        for siparis in sahte_trendyol_verisi:
            order_no = siparis["orderNumber"]
            for urun in siparis["lines"]:
                gercek_desi = urun["realDesi"]
                for kargo in siparis["packageHistories"]:
                    faturadaki_desi = kargo["invoiceDesi"]
                    if faturadaki_desi > gercek_desi:
                        zarar = round((kargo["cargoFee"] / faturadaki_desi) * (faturadaki_desi - gercek_desi), 2)
                        toplam_zarar += zarar
                        hatalar.append({
                            "order_no": order_no, "urun_adi": urun["productName"],
                            "gercek_desi": gercek_desi, "faturadaki_desi": faturadaki_desi, "zarar": zarar
                        })
    return render_template_string(HTML_SABLONU, sayfa='panel', hatalar=hatalar, toplam_zarar=toplam_zarar, aktif_magaza=aktif_magaza, oturum_aktif=oturum_aktif)

@app.route('/ayarlar', methods=['GET', 'POST'])
def ayarlar_sayfasi():
    if request.method == 'POST':
        session['magaza_adi'] = request.form['magaza_adi']
        session['satici_id'] = request.form['satici_id']
        session['api_key'] = request.form['api_key']
        session['api_secret'] = request.form['api_secret']
        return redirect(url_for('ana_sayfa'))
    return render_template_string(HTML_SABLONU, sayfa='ayarlar', oturum_aktif=False)

@app.route('/cikis')
def cikis_yap():
    session.clear()
    return redirect(url_for('ana_sayfa'))

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port, debug=True)
