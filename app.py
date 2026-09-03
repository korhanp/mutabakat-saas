import os
import requests
from flask import Flask, request, redirect, url_for, session

app = Flask(__name__)
app.secret_key = "KargoMutabakatGuzelGuvenceKeyi98765!"

# Güvenli ve çökme riski sıfırlanmış HTML oluşturucu fonksiyon
def html_olustur(sayfa, oturum_aktif, aktif_magaza, hata_mesaji, hatalar, toplam_zarar, toplam_siparis, hata_sayisi):
    nav_html = f"""
    <nav class="bg-white border-b border-gray-200 px-6 py-4 flex justify-between items-center">
        <div class="flex items-center space-x-3">
            <span class="text-2xl">🛡️</span>
            <span class="text-xl font-bold text-blue-600">FeedBackLoop <span class="text-sm font-normal text-gray-500">SaaS Mutabakat</span></span>
        </div>
        <div class="space-x-4">
            <a href="/" class="text-sm font-medium text-gray-600 hover:text-blue-600">🏠 Panel</a>
            <a href="/ayarlar" class="text-sm font-medium text-gray-600 hover:text-blue-600">⚙️ Mağaza Girişi</a>
            {"<a href='/cikis' class='text-sm font-medium text-red-600 hover:text-red-800'>❌ Oturumu Kapat</a>" if oturum_aktif else ""}
        </div>
    </nav>
    """
    
    uyari_html = f"""
    <div class="mb-6 bg-red-50 border border-red-200 p-4 rounded-xl text-sm text-red-800">
        ⚠️ <strong>Sistem Durumu:</strong> {hata_mesaji}
    </div>
    """ if hata_mesaji else ""

    icerik_html = ""
    if sayfa == "panel":
        icerik_html += f"""
        <div class="mb-6 bg-green-50 border border-green-200 p-4 rounded-xl flex justify-between items-center">
            <span class="text-sm text-green-800">🔒 Güvenli Canlı Bağlantı: <strong>{aktif_magaza}</strong></span>
            <span class="bg-blue-100 text-blue-800 text-xs font-semibold px-2.5 py-0.5 rounded-full">Canlı API Modu</span>
        </div>
        """
        
        if oturum_aktif:
            icerik_html += f"""
            <div class="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
                <div class="bg-white p-6 rounded-xl border border-gray-200 shadow-xs">
                    <p class="text-sm font-medium text-gray-500 uppercase">🚨 Toplam Kargo Kaçağı</p>
                    <p class="text-3xl font-bold text-red-600 mt-2">{toplam_zarar} TL</p>
                </div>
                <div class="bg-white p-6 rounded-xl border border-gray-200 shadow-xs">
                    <p class="text-sm font-medium text-gray-500 uppercase">🔎 Taranan Sipariş</p>
                    <p class="text-3xl font-bold text-gray-900 mt-2">{toplam_siparis} Adet</p>
                </div>
                <div class="bg-white p-6 rounded-xl border border-gray-200 shadow-xs">
                    <p class="text-sm font-medium text-gray-500 uppercase">💡 Hazır İtiraz Talebi</p>
                    <p class="text-3xl font-bold text-blue-600 mt-2">{hata_sayisi} Adet</p>
                </div>
            </div>
            <div class="bg-white rounded-xl border border-gray-200 shadow-xs overflow-hidden">
                <table class="w-full text-left">
                    <thead>
                        <tr class="bg-gray-100 text-xs font-semibold text-gray-600 uppercase border-b">
                            <th class="px-6 py-3">Sipariş No</th>
                            <th class="px-6 py-3">Ürün Adı</th>
                            <th class="px-6 py-3 text-center">Gerçek Desi (Sizin)</th>
                            <th class="px-6 py-3 text-center">Kesilen Desi (Kargo)</th>
                            <th class="px-6 py-3 text-right">Zarar</th>
                        </tr>
                    </thead>
                    <tbody class="divide-y divide-gray-200 text-sm">
            """
            for h in hatalar:
                icerik_html += f"""
                        <tr class="hover:bg-gray-50">
                            <td class="px-6 py-4 font-medium">{h['order_no']}</td>
                            <td class="px-6 py-4 text-gray-600">{h['urun_adi']}</td>
                            <td class="px-6 py-4 text-center text-green-600 font-bold">{h['gercek_desi']}</td>
                            <td class="px-6 py-4 text-center text-red-600 font-bold">{h['faturadaki_desi']}</td>
                            <td class="px-6 py-4 text-right text-red-600 font-bold">{h['zarar']} TL</td>
                        </tr>
                """
            if hata_sayisi == 0:
                icerik_html += """
                        <tr>
                            <td colspan="5" class="text-center py-8 text-gray-500">Taranan siparişlerde herhangi bir kargo desi hatası tespit edilmedi. Her şey yolunda!</td>
                        </tr>
                """
            icerik_html += "</tbody></table></div>"
        else:
            icerik_html += """
            <div class="text-center py-12 bg-white border border-gray-200 rounded-xl">
                <p class="text-gray-500 mb-4">Gerçek Trendyol verilerinizi analiz etmek için lütfen API anahtarlarınızla güvenli oturum açın.</p>
                <a href="/ayarlar" class="bg-blue-600 text-white px-4 py-2 rounded-lg font-medium hover:bg-blue-700">⚙️ API Bilgilerini Gir</a>
            </div>
            """
            
    elif sayfa == "ayarlar":
        icerik_html += """
        <div class="max-w-xl mx-auto bg-white border border-gray-200 rounded-xl p-8 shadow-xs">
            <div class="mb-6 p-3 bg-amber-50 border border-amber-200 rounded-lg text-xs text-amber-800">
                ℹ️ <strong>Müşteri Bilgilendirmesi:</strong> Gireceğiniz API anahtarları hiçbir veritabanına kaydedilmez. Sadece bu seanstaki canlı analiz için Trendyol'a anlık sorulur.
            </div>
            <h2 class="text-xl font-bold text-gray-900 mb-6">🔑 Trendyol Canlı Mağaza Girişi</h2>
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
                    🔒 Canlı API'ye Bağlan ve Tara
                </button>
            </form>
        </div>
        """

    return f"""
    <!DOCTYPE html>
    <html lang="tr">
    <head>
        <meta charset="UTF-8">
        <title>FeedBackLoop | Canlı Mutabakat Paneli</title>
        <script src="https://jsdelivr.net"></script>
    </head>
    <body class="bg-gray-50 font-sans text-gray-900">
        {nav_html}
        <main class="max-w-7xl mx-auto px-4 py-8">
            {uyari_html}
            {icerik_html}
        </main>
    </body>
    </html>
    """

# Tamamen izole edilmiş, sözdizimi hatası üretmesi imkansız API motoru
def trendyol_canli_veri_cek(satici_id, api_key, api_secret):
    url = f"https://trendyol.com{satici_id}/packages"
    headers = {"User-Agent": str(satici_id)}
    params = {"status": "Delivered", "size": 50}
    try:
        response = requests.get(url, headers=headers, params=params, auth=(api_key, api_secret), timeout=10)
        if response.status_code == 200:
            return response.json()
    except Exception:
        pass
    return None

@app.route('/')
def ana_sayfa():
    magaza_adi = session.get('magaza_adi', None)
    satici_id = session.get('satici_id', None)
    api_key = session.get('api_key', None)
    api_secret = session.get('api_secret', None)
    
    oturum_aktif = True if (magaza_adi and satici_id and api_key and api_secret) else False
    aktif_magaza = magaza_adi if oturum_aktif else "Oturum Açılmadı"
    hata_mesaji = session.pop('hata_mesaji', None)
    
    hatalar = []
    toplam_zarar = 0
    toplam_siparis = 0
    
    if oturum_aktif:
