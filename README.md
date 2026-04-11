<p align="center">
  <h1 align="center">GSB Wi-Fi Manager</h1>
  <p align="center">
    KYK / GSB yurt ağlarına otomatik bağlanma, kota takibi ve kesintisiz internet deneyimi.
    <br />
    <a href="https://github.com/ugurboz/GSB-Wifi-Manager/releases"><strong>Son Sürümü İndir »</strong></a>
    <br />
    <br />
    <a href="https://github.com/ugurboz/GSB-Wifi-Manager/issues">Hata Bildir</a>
    ·
    <a href="https://github.com/ugurboz/GSB-Wifi-Manager/issues">Özellik Öner</a>
  </p>
</p>

<p align="center">
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/Python-3.8+-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python"></a>
  <a href="https://opensource.org/licenses/MIT"><img src="https://img.shields.io/badge/Lisans-MIT-green?style=for-the-badge" alt="License"></a>
  <a href="https://github.com/ugurboz/GSB-Wifi-Manager/releases"><img src="https://img.shields.io/badge/Platform-macOS%20%7C%20Windows-blue?style=for-the-badge" alt="Platform"></a>
</p>

---

## Nedir?

GSB Wi-Fi Manager, Türkiye genelindeki **KYK / Gençlik ve Spor Bakanlığı** yurtlarının Wi-Fi ağına (GSBWIFI) bağlanma sürecini tamamen otomatikleştiren bir masaüstü uygulamasıdır.

Portal'a her seferinde elle giriş yapmak, bağlantı koptuğunda fark edememek veya kota bittiğinde internetsiz kalmak gibi sorunları ortadan kaldırır.

---

## ✨ Özellikler

| Özellik | Açıklama |
|---------|----------|
| **🔄 Auto-Healer** | Bağlantı koptuğunda otomatik olarak algılar ve yeniden bağlanır. Arka planda çalışır, müdahale gerektirmez. |
| **👥 Çoklu Hesap** | Birden fazla TC Kimlik ile hesap ekleyebilir, aralarında tek tıkla geçiş yapabilirsiniz. |
| **📊 Kota Takibi** | Aylık internet kotanızı görsel bir ilerleme çubuğuyla anlık takip edin. |
| **🔀 Auto-Switch** | Aktif hesabın kotası dolduğunda sıradaki hesaba otomatik geçiş yapar. |
| **🔒 Güvenli Saklama** | Şifreler işletim sisteminin güvenli anahtar deposunda (macOS Keychain / Windows Credential Manager) saklanır. |
| **🖥️ Modern Arayüz** | macOS tasarım diline uygun, karanlık/aydınlık mod destekli şık arayüz. |

---

## 📸 Ekran Görüntüleri

> Ekran görüntüleri yakında eklenecektir.

<!-- 
<p align="center">
  <img src="screenshots/dashboard.png" width="700" alt="Dashboard">
</p>
-->

---

## 🚀 Kurulum

### Hazır Uygulama (Önerilen)

Python bilgisi gerektirmez. İndirip çalıştırmanız yeterlidir.

1. [**Releases**](https://github.com/ugurboz/GSB-Wifi-Manager/releases) sayfasına gidin.
2. İşletim sisteminize uygun dosyayı indirin:
   - **macOS:** `GSB-Wifi-Manager-macOS.zip`
   - **Windows:** `GSB-Wifi-Manager-Windows.zip`
3. Zip dosyasını çıkarın ve uygulamayı başlatın.

### Kaynak Koddan Çalıştırma (Geliştiriciler İçin)

```bash
# Repoyu klonlayın
git clone https://github.com/ugurboz/GSB-Wifi-Manager.git
cd GSB-Wifi-Manager

# Bağımlılıkları yükleyin
pip install -r requirements.txt

# Uygulamayı başlatın
python gsb_app.py
```

Alternatif olarak, projeyi geliştirme modunda kurarak terminalden `gsb` komutuyla çalıştırabilirsiniz:

```bash
pip install -e .
gsb
```

---

## 🛠️ Nasıl Çalışır?

```
┌─────────────────────────────────────────────────────┐
│                   GSB Wi-Fi Manager                 │
├─────────────────────────────────────────────────────┤
│                                                     │
│   1. Ağ Tespiti                                     │
│      └── GSBWIFI ağına bağlı mı kontrol et          │
│                                                     │
│   2. Portal Girişi                                  │
│      └── wifi.gsb.gov.tr'ye otomatik login          │
│                                                     │
│   3. Auto-Healer (Arka Plan)                        │
│      └── Bağlantıyı 5 sn aralıklarla izle           │
│      └── Kopma algılanırsa → yeniden bağlan          │
│                                                     │
│   4. Kota Kontrolü                                  │
│      └── Kota bittiyse → sıradaki hesaba geç         │
│                                                     │
└─────────────────────────────────────────────────────┘
```

---

## 🔒 Güvenlik

- **Şifreler** işletim sisteminizin güvenli anahtar deposunda saklanır:
  - macOS → Keychain
  - Windows → Credential Manager
- **TC Kimlik numaraları** yalnızca yerel cihazınızdaki `accounts.json` dosyasında bulunur ve bu dosya `.gitignore` ile Git dışında tutulur.
- Uygulama **hiçbir veriyi dışarıya göndermez**. Tüm iletişim yalnızca `wifi.gsb.gov.tr` portali ile yapılır.

---

## ⚙️ Teknik Detaylar

| Bileşen | Teknoloji |
|---------|-----------|
| Arayüz | [CustomTkinter](https://github.com/TomSchimansky/CustomTkinter) |
| HTTP İstemci | [Requests](https://docs.python-requests.org/) |
| HTML Ayrıştırma | [BeautifulSoup4](https://www.crummy.com/software/BeautifulSoup/) |
| Şifre Saklama | [Keyring](https://github.com/jaraco/keyring) |
| Paketleme | [PyInstaller](https://pyinstaller.org/) + GitHub Actions |

---

## 🤝 Katkıda Bulunma

Her türlü katkıya açığız!

1. Bu repoyu **fork** edin.
2. Yeni bir branch oluşturun: `git checkout -b ozellik/yeni-ozellik`
3. Değişikliklerinizi commit edin: `git commit -m 'Yeni özellik eklendi'`
4. Branch'inizi push edin: `git push origin ozellik/yeni-ozellik`
5. Bir **Pull Request** açın.

Hata bildirimleri ve özellik önerileri için [Issues](https://github.com/ugurboz/GSB-Wifi-Manager/issues) sayfasını kullanabilirsiniz.

---

## 📝 Lisans

Bu proje [MIT Lisansı](LICENSE) ile lisanslanmıştır.
