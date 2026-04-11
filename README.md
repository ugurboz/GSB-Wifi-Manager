# GSB Wi-Fi Auto-Pilot & Manager 🚀

Türkiye'deki Gençlik ve Spor Bakanlığı (GSB) / KYK yurt ağlarına (GSBWIFI) otomatik olarak bağlanmanızı sağlayan, kota durumunuzu takip eden ve bağlantı koptuğunda tamamen arka planda kendi kendini onararak (Auto-Healer) yeniden bağlanan modern ve şık bir masaüstü uygulamasıdır.

[![Python 3.8+](https://img.shields.io/badge/python-3.4+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![CustomTkinter](https://img.shields.io/badge/UI-CustomTkinter-lightgrey.svg)](https://github.com/TomSchimansky/CustomTkinter)

## ✨ Temel Özellikler

*   **🛡️ Auto-Healer (Otomatik Onarım):** Bağlantı koptuğunda portalı her 5 saniyede bir yoklar ve Wi-Fi geldiği an otomatik giriş yapar.
*   **📊 Akıllı Kota Yönetimi:** Kotanızı anlık takip eder. Kota dolduğunda sıradaki hesaba otomatik geçiş (Auto-Switch) yapar.
*   **👥 Çoklu Hesap Desteği:** Sınırsız sayıda TC Kimlik ve Şifre ekleyebilir, aralarında pürüzsüz geçiş yapabilirsiniz.
*   **🔒 Güvenlik:** Hesap bilgileriniz yerel cihazınızda `accounts.json` dosyasında saklanır; dışarıya hiçbir veri aktarılmaz.
*   **💻 Platform Bağımsız:** Windows, macOS ve Linux sistemlerde tam uyumlu çalışır.

## 🚀 Geliştiriciler İçin Hızlı Kurulum

Projeyi sisteminize profesyonel bir araç (CLI) olarak kurmak için:

1.  **Python** yüklü olduğundan emin olun.
2.  Repoyu klonlayın ve içine girin:
    ```bash
    git clone https://github.com/ugurboz/GSB-Wifi-Manager.git
    cd GSB-Wifi-Manager
    ```
3.  Projeyi geliştirme modunda kurun (bu, terminale `gsb` komutunu ekler):
    ```bash
    pip install -e .
    ```

## 🖥️ Kullanım

Kurulum tamamlandıktan sonra, herhangi bir terminal penceresinden şu komutu vermeniz yeterlidir:
```bash
gsb
```

## ⚙️ Teknik Altyapı
- **Ağ/HTTP:** `requests` & `beautifulsoup4`
- **UI:** `customtkinter` (Modern macOS temalı arayüz)
- **Paketleme:** `pyproject.toml` (Modern Python Packaging)

## 🤝 Katkıda Bulunma
Her türlü *Pull Request* (PR) ve hata bildirimi (*Issue*) kabul edilir. Projeyi daha da geliştirmek isterseniz repoyu forklayabilir ve iyileştirmelerinizi gönderebilirsiniz.

## 📝 Lisans
Bu proje [MIT Lisansı](LICENSE) altında paylaşılmaktadır. Özgürce kullanabilir, değiştirebilir ve dağıtabilirsiniz.
