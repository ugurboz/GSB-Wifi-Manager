"""
GSB Wi-Fi Backend — Otomatik Giriş ve Kota Yönetimi

GUI veya CLI tarafından import edilebilir temiz API.
Tüm fonksiyonlar yapılandırılmış veri döndürür (print yapmaz).
"""

import requests
from bs4 import BeautifulSoup
from cryptography.fernet import Fernet
from dotenv import load_dotenv, set_key
import getpass
import time
import socket
import sys
import json
import os
import re
import subprocess
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ─── Sabitler ───────────────────────────────────────────────────────────────

SERVICE_NAME = "gsb_wifi_login"
BASE_URL = "https://wifi.gsb.gov.tr"
LOGIN_URL = f"{BASE_URL}/login.html"
AUTH_URL = f"{BASE_URL}/j_spring_security_check"
LOGOUT_URL = f"{BASE_URL}/logout"
DASHBOARD_URL = f"{BASE_URL}/index.html"
AUTO_LOGOUT_SECONDS = 60

# Hesap dosyası yolu (script ile aynı dizinde)
ACCOUNTS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "accounts.json")
ENV_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")

def _get_cipher():
    load_dotenv(ENV_FILE)
    key = os.getenv("GSB_SECRET_KEY")
    if not key:
        key = Fernet.generate_key().decode()
        set_key(ENV_FILE, "GSB_SECRET_KEY", key)
    return Fernet(key.encode())


# ─── Çoklu Hesap Yönetimi ───────────────────────────────────────────────────

def _load_accounts_data():
    """accounts.json dosyasını oku."""
    if os.path.exists(ACCOUNTS_FILE):
        try:
            with open(ACCOUNTS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {"accounts": [], "active_index": 0}


def _save_accounts_data(data):
    """accounts.json dosyasına yaz."""
    with open(ACCOUNTS_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_all_accounts():
    """
    Tüm kayıtlı hesapları döner.
    Returns:
        list of dict: [{'tc': '123...', 'label': 'Ad Soyad'}, ...]
    """
    data = _load_accounts_data()
    return data.get('accounts', [])


def get_active_index():
    """Aktif hesap indeksini döner."""
    data = _load_accounts_data()
    accounts = data.get('accounts', [])
    idx = data.get('active_index', 0)
    if idx >= len(accounts):
        return 0
    return idx


def set_active_index(index):
    """Aktif hesap indeksini ayarlar."""
    data = _load_accounts_data()
    accounts = data.get('accounts', [])
    if 0 <= index < len(accounts):
        data['active_index'] = index
        _save_accounts_data(data)


def add_account(tc, password, label=None):
    """
    Yeni hesap ekle.
    Args:
        tc: TC Kimlik No
        password: Şifre
        label: Gösterim adı (opsiyonel, daha sonra portaldan otomatik çekilir)
    Returns:
        bool: Başarılı ise True, zaten varsa False
    """
    data = _load_accounts_data()
    accounts = data.get('accounts', [])
    cipher = _get_cipher()
    enc_password = cipher.encrypt(password.encode()).decode()
    
    # Aynı TC varsa ekleme
    for acc in accounts:
        if acc['tc'] == tc:
            # Şifreyi güncelle
            acc['password'] = enc_password
            if label:
                acc['label'] = label
            _save_accounts_data(data)
            return False
    
    accounts.append({'tc': tc, 'label': label or tc, 'password': enc_password})
    data['accounts'] = accounts
    
    # İlk hesapsa aktif yap
    if len(accounts) == 1:
        data['active_index'] = 0
    
    _save_accounts_data(data)
    return True


def remove_account(tc):
    """
    Hesap sil.
    Returns:
        bool: Başarılı ise True
    """
    data = _load_accounts_data()
    accounts = data.get('accounts', [])
    new_accounts = [a for a in accounts if a['tc'] != tc]
    
    if len(new_accounts) == len(accounts):
        return False  # Bulunamadı
    
    data['accounts'] = new_accounts
    
    # Aktif index'i düzelt
    if data['active_index'] >= len(new_accounts):
        data['active_index'] = max(0, len(new_accounts) - 1)
    
    _save_accounts_data(data)
    
    return True


def update_account_label(tc, label):
    """Hesap etiketini güncelle (portaldan çekilen isim ile)."""
    data = _load_accounts_data()
    for acc in data.get('accounts', []):
        if acc['tc'] == tc:
            acc['label'] = label
            _save_accounts_data(data)
            return


def get_account_password(tc):
    """Bir hesabın şifresini JSON'dan çözüp al."""
    data = _load_accounts_data()
    for acc in data.get('accounts', []):
        if acc['tc'] == tc:
            enc_password = acc.get('password')
            if enc_password:
                cipher = _get_cipher()
                try:
                    return cipher.decrypt(enc_password.encode()).decode()
                except Exception:
                    return None
    return None


def get_active_credentials():
    """Aktif hesabın TC ve şifresini döner. Yoksa (None, None)."""
    accounts = get_all_accounts()
    if not accounts:
        return None, None
    idx = get_active_index()
    tc = accounts[idx]['tc']
    password = get_account_password(tc)
    return tc, password


# Geriye uyumluluk: Eski tek-hesap fonksiyonları
def get_credentials():
    """Aktif hesabın bilgilerini döner (geriye uyumluluk)."""
    return get_active_credentials()


def save_credentials(username, password):
    """Hesap ekler veya günceller (geriye uyumluluk)."""
    add_account(username, password)


def clear_credentials():
    """Tüm hesapları siler (geriye uyumluluk)."""
    accounts = get_all_accounts()
    if not accounts:
        return False
    for acc in accounts:
        remove_account(acc['tc'])
    return True


def is_quota_depleted(user_info):
    """
    Kota bitmiş mi kontrol et.
    Returns:
        bool: Kalan kota 0 veya çok düşükse True
    """
    if not user_info:
        return False
    try:
        # Önce Türkçe key'e bak, yoksa eski İngilizce key'e düş
        remaining = float(user_info.get('Toplam Kalan Kota (MB)',
                          user_info.get('Total Remaining Quota (MB)', 1)))
        return remaining <= 1.0  # 1 MB veya altı = bitti
    except (ValueError, TypeError):
        return False


def get_next_account_index():
    """
    Aktif hesaptan sonraki hesap indeksini döner.
    Returns:
        int veya None: Sonraki hesap indeksi, başka hesap yoksa None
    """
    accounts = get_all_accounts()
    if len(accounts) <= 1:
        return None
    current = get_active_index()
    next_idx = (current + 1) % len(accounts)
    if next_idx == current:
        return None
    return next_idx


# ─── Bağlantı Kontrolleri ──────────────────────────────────────────────────

GSB_HOST = "wifi.gsb.gov.tr"


def _get_wifi_device():
    """macOS'ta aktif Wi-Fi arayüz adını döner (en0/en1 gibi)."""
    try:
        out = subprocess.check_output(
            ["networksetup", "-listallhardwareports"],
            timeout=5,
            stderr=subprocess.DEVNULL,
        ).decode(errors='ignore')

        lines = out.splitlines()
        for i, line in enumerate(lines):
            l = line.strip().lower()
            if l in ("hardware port: wi-fi", "hardware port: airport"):
                for next_line in lines[i + 1:i + 5]:
                    if "device:" in next_line.lower():
                        return next_line.split(":", 1)[1].strip()
    except Exception:
        pass

    return "en0"

def _check_ssid():
    """macOS'ta bağlı Wi-Fi SSID'sini kontrol et."""
    try:
        # Yöntem 1: networksetup (hızlı ve kararlı)
        wifi_device = _get_wifi_device()
        out = subprocess.check_output(
            ["networksetup", "-getairportnetwork", wifi_device],
            timeout=5, stderr=subprocess.DEVNULL
        ).decode(errors='ignore').strip()
        # "Current Wi-Fi Network: GSBWIFI" formatı
        if ":" in out and "not associated" not in out.lower():
            return out.split(":", 1)[1].strip()
    except Exception:
        pass

    try:
        # Yöntem 2: airport aracı (bazı macOS sürümlerinde daha doğru)
        airport_cmd = "/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport"
        out = subprocess.check_output(
            [airport_cmd, "-I"],
            timeout=5,
            stderr=subprocess.DEVNULL,
        ).decode(errors='ignore')
        for line in out.splitlines():
            stripped = line.strip()
            if stripped.startswith("SSID:"):
                ssid = stripped.split(":", 1)[1].strip()
                if ssid:
                    return ssid
    except Exception:
        pass

    try:
        # Yöntem 3: system_profiler (fallback)
        out = subprocess.check_output(
            ["system_profiler", "SPAirPortDataType"],
            timeout=5, stderr=subprocess.DEVNULL
        ).decode(errors='ignore')
        
        in_current = False
        for line in out.splitlines():
            stripped = line.strip()
            if 'Current Network Information' in stripped:
                in_current = True
                continue
            if in_current and stripped and ':' not in stripped:
                # Bu satır SSID adıdır (ağ adı satırdan sonra ":" ile ayrılır)
                pass
            if in_current and 'SSID' in stripped and ':' in stripped:
                ssid = stripped.split(':', 1)[1].strip()
                return ssid
            # SSID, Current Network Information'dan sonra gelen ilk "key:" satırı
            # Ancak bazı versiyonlarda format farklı olabilir
            if in_current and stripped.endswith(':') and not stripped.startswith('-'):
                # Bu ağ adıdır (örn: "GSBWIFI:")
                return stripped.rstrip(':')
    except Exception:
        pass
    
    return None


def _can_resolve_host():
    """wifi.gsb.gov.tr DNS çözümlemesi yapılabiliyor mu?"""
    try:
        socket.getaddrinfo(GSB_HOST, 443, socket.AF_INET, socket.SOCK_STREAM)
        return True
    except (socket.gaierror, OSError):
        return False


def _can_reach_host():
    """wifi.gsb.gov.tr:443 portuna TCP bağlantısı kurulabiliyor mu?"""
    try:
        s = socket.create_connection((GSB_HOST, 443), timeout=5)
        s.close()
        return True
    except (OSError, socket.timeout):
        # HTTPS portu kapali olabilir, HTTP dene
        try:
            s = socket.create_connection((GSB_HOST, 80), timeout=5)
            s.close()
            return True
        except (OSError, socket.timeout):
            return False


def check_gsb_network():
    """
    GSB Wi-Fi ağına bağlı mıyız kontrolü.
    3 aşamalı kontrol:
      1. SSID kontrolü (macOS-only, hızlı)
      2. DNS çözümleme (wifi.gsb.gov.tr adresi çözünüyor mu?)
      3. TCP bağlantı (porta ulaşılıyor mu?)
    
    Returns:
        bool: GSB ağında ise True
    """
    # Aşama 1: SSID kontrolü
    ssid = _check_ssid()
    if ssid and "GSB" in ssid.upper():
        return True
    
    # Aşama 2: DNS
    if not _can_resolve_host():
        return False
    
    # Aşama 3: TCP bağlantı
    return _can_reach_host()


def check_gsb_session():
    """
    GSB portalında aktif oturum var mı kontrolü.
    Dashboard'a istek atıp login sayfasına yönlendirilip yönlendirilmediğimize bakar.
    
    Returns:
        dict with keys:
            - 'on_network': bool — GSB ağında mıyız
            - 'logged_in': bool — Giriş yapılmış mı
            - 'session': requests.Session veya None — Aktif session (varsa)
    """
    # Önce ağ varlığını URL bağımsız şekilde tespit et.
    # Portal kısa süre cevap vermese bile SSID/host erişimi olumluysa "on_network=True" kalmalı.
    result = {'on_network': check_gsb_network(), 'logged_in': False, 'session': None}

    if not result['on_network']:
        return result
    
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
    })
    
    # HTTPS dene, son çare olarak captive portal test adresi dene
    urls_to_try = [
        DASHBOARD_URL, 
        DASHBOARD_URL.replace("https://", "http://"),
        "http://captive.apple.com"  # Captive Portal'lar genelde bu http isteğini yakalayıp kendi portalına yönlendirir
    ]
    
    for url in urls_to_try:
        try:
            response = session.get(url, verify=False, timeout=5, allow_redirects=True)
            
            # Login sayfasına yönlendirildiyse oturum yok
            if 'login' in response.url.lower() or 'j_username' in response.text:
                result['logged_in'] = False
            elif 'logout' in response.text.lower() or 'Çıkış' in response.text:
                result['logged_in'] = True
                result['session'] = session
            
            return result  # başarılı: sonucu dön
        except requests.exceptions.RequestException:
            continue  # sonraki URL'yi dene
    
    # URL'ler cevap vermese de check_gsb_network() olumluysa "ağda" kabul ederiz.
    result['logged_in'] = False
    return result


def check_internet():
    """
    Gerçek internet erişimi var mı kontrolü (Google DNS üzerinden).
    GSB'ye giriş yapıldıktan SONRA kullanılır.
    
    Returns:
        bool: İnternet erişimi varsa True
    """
    try:
        socket.setdefaulttimeout(3)
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect(("8.8.8.8", 53))
        s.close()
        return True
    except OSError:
        return False


# ─── Ağ Kurtarma (DHCP / Wi-Fi Toggle) ─────────────────────────────────────

def _get_local_ip():
    """Wi-Fi arayüzünün mevcut IP adresini al. IP yoksa None döner."""
    try:
        device = _get_wifi_device()
        out = subprocess.check_output(
            ["ipconfig", "getifaddr", device],
            timeout=5, stderr=subprocess.DEVNULL
        ).decode(errors='ignore').strip()
        if out and not out.startswith('169.254'):  # Self-assigned IP = geçersiz
            return out
    except (subprocess.CalledProcessError, Exception):
        pass
    return None


def _renew_dhcp():
    """
    DHCP lease yenile. Yoğun ağlarda IP alamama sorununu çözer.
    sudo gerektirmez — ipconfig/networksetup kullanıcı seviyesinde çalışır.
    """
    device = _get_wifi_device()
    
    # Yöntem 1: ipconfig set DHCP (en hızlı)
    try:
        subprocess.run(
            ["ipconfig", "set", device, "DHCP"],
            timeout=10, capture_output=True
        )
    except Exception:
        pass
    
    # Yöntem 2: networksetup ile DHCP yenile
    try:
        subprocess.run(
            ["networksetup", "-setdhcp", "Wi-Fi"],
            timeout=10, capture_output=True
        )
    except Exception:
        pass


def _toggle_wifi():
    """
    Wi-Fi'yi kapatıp açar. IP alınamadığında son çare olarak kullanılır.
    Bu işlem ağı sıfırdan başlatır ve yeni bir DHCP isteği tetikler.
    """
    try:
        device = _get_wifi_device()
        # Wi-Fi kapat
        subprocess.run(
            ["networksetup", "-setairportpower", device, "off"],
            timeout=5, capture_output=True
        )
        time.sleep(2)
        # Wi-Fi aç
        subprocess.run(
            ["networksetup", "-setairportpower", device, "on"],
            timeout=5, capture_output=True
        )
        time.sleep(3)  # Ağa bağlanması için bekle
    except Exception:
        pass


def _force_connect_gsb():
    """
    Kayıtlı ağlardan GSB içerenleri bulup, zorla (otomatik) bağlanmaya çalışır.
    Wi-Fi kapalıysa önce Wi-Fi'yi açar.
    
    Returns:
        bool: Başarıyla bağlandıysa True
    """
    try:
        device = _get_wifi_device()
        
        # Wi-Fi açık mı kontrol et, kapalıysa aç
        status_out = subprocess.check_output(
            ["networksetup", "-getairportpower", device],
            timeout=5, stderr=subprocess.DEVNULL
        ).decode(errors='ignore')
        if "Off" in status_out:
            print("  📡 Wi-Fi kapalı, otomatik açılıyor...")
            subprocess.run(["networksetup", "-setairportpower", device, "on"], timeout=5, capture_output=True)
            time.sleep(3)
            
        # Kayıtlı ağlardan GSB içerenleri bul
        out = subprocess.check_output(
            ["networksetup", "-listpreferredwirelessnetworks", device],
            timeout=5, stderr=subprocess.DEVNULL
        ).decode(errors='ignore')
        
        gsb_ssids = []
        for line in out.splitlines():
            if 'GSB' in line.upper():
                gsb_ssids.append(line.strip())
        
        if not gsb_ssids:
            # GSB kelimesi geçen kaydedilmiş ağ yoksa varsayılan isimleri dene
            gsb_ssids = ["GSB Wifi", "GSBWIFI", "GSB-WiFi", "GSB_Wifi"]
            
        for target in gsb_ssids:
            # Şifresiz ağlar için sadece SSID yeterli
            subprocess.run(["networksetup", "-setairportnetwork", device, target], timeout=15, capture_output=True)
            time.sleep(3)
            current = _check_ssid()
            if current and target.upper() in current.upper():
                return True
                
    except Exception:
        pass
    
    return False


def _wait_for_ip(timeout=15):
    """
    IP adresi alınana kadar bekle.
    Returns:
        str veya None — IP adresi veya timeout olursa None
    """
    start = time.time()
    while time.time() - start < timeout:
        ip = _get_local_ip()
        if ip:
            return ip
        time.sleep(1)
    return None


def aggressive_network_recovery(max_cycles=5, verbose=True):
    """
    Ağ yoğunluğundan IP alamama sorununu agresif şekilde çözer.
    
    Strateji:
      1. DHCP lease yenile + IP bekle
      2. Başarısızsa Wi-Fi kapat/aç + IP bekle
      3. Tekrarla (max_cycles kadar)
    
    Args:
        max_cycles: Maksimum deneme döngüsü
        verbose: Terminale durum yazdırsın mı
    
    Returns:
        dict with keys:
            - 'success': bool
            - 'ip': str veya None
            - 'portal_reachable': bool
            - 'attempts': int
    """
    def _log(msg):
        if verbose:
            print(f"  [{time.strftime('%H:%M:%S')}] {msg}")

    for cycle in range(1, max_cycles + 1):
        _log(f"🔄 Ağ kurtarma döngüsü {cycle}/{max_cycles}")
        
        # Adım 1: Mevcut IP'yi kontrol et
        ip = _get_local_ip()
        if ip:
            _log(f"✅ IP mevcut: {ip}")
            # Portal erişilebilir mi?
            if _can_reach_host():
                return {'success': True, 'ip': ip, 'portal_reachable': True, 'attempts': cycle}
            else:
                _log("⚠️  IP var ama portal erişilemiyor, DNS/route bekleniyor...")
                time.sleep(3)
                if _can_reach_host():
                    return {'success': True, 'ip': ip, 'portal_reachable': True, 'attempts': cycle}
        
        # Adım 2: DHCP lease yenile
        _log("📡 DHCP lease yenileniyor...")
        _renew_dhcp()
        ip = _wait_for_ip(timeout=10)
        
        if ip:
            _log(f"✅ DHCP'den IP alındı: {ip}")
            time.sleep(2)  # Route'ların oturması için
            if _can_reach_host():
                return {'success': True, 'ip': ip, 'portal_reachable': True, 'attempts': cycle}
        
        # Adım 3: Wi-Fi toggle (son çare)
        if cycle <= 2 or cycle == max_cycles:
            _log("🔌 Wi-Fi kapatılıp açılıyor...")
            _toggle_wifi()
            ip = _wait_for_ip(timeout=20)
            
            if ip:
                _log(f"✅ Wi-Fi toggle sonrası IP alındı: {ip}")
                time.sleep(3)
                if _can_reach_host():
                    return {'success': True, 'ip': ip, 'portal_reachable': True, 'attempts': cycle}
                _log("⚠️  IP var ama portal henüz erişilemiyor")
            else:
                _log("❌ IP alınamadı, tekrar denenecek...")
        
        # Döngü arası bekleme (giderek artan)
        wait = min(3 * cycle, 10)
        _log(f"⏳ {wait} saniye bekleniyor...")
        time.sleep(wait)
    
    # Son kontrol
    ip = _get_local_ip()
    reachable = _can_reach_host() if ip else False
    return {'success': reachable, 'ip': ip, 'portal_reachable': reachable, 'attempts': max_cycles}


# ─── Giriş / Çıkış ─────────────────────────────────────────────────────────

def login(username, password):
    """
    GSB Wi-Fi'ye giriş yap.
    
    Returns:
        dict with keys:
            - 'success': bool
            - 'session': requests.Session veya None
            - 'message': str — Durum mesajı
            - 'error_type': str veya None — 'max_entry', 'wrong_password', 'connection', None
    """
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer': LOGIN_URL
    })

    try:
        # 1. Giriş sayfasını çek, CSRF token al
        response = session.get(LOGIN_URL, verify=False, timeout=10)
        soup = BeautifulSoup(response.text, 'html.parser')

        payload = {
            'j_username': username,
            'j_password': password,
            'submit': 'Giriş'
        }

        for hidden in soup.find_all("input", type="hidden"):
            name = hidden.get('name')
            value = hidden.get('value')
            if name:
                payload[name] = value

        # 2. POST ile kimlik doğrulama
        auth_response = session.post(
            AUTH_URL, data=payload, 
            allow_redirects=True, verify=False, timeout=10
        )

        # Başarı kontrolü
        if "Çıkış" in auth_response.text or "logout" in auth_response.text.lower():
            return {
                'success': True,
                'session': session,
                'message': 'Giriş başarılı',
                'error_type': None
            }
        elif "maximum entry reached" in auth_response.text.lower() or "maksimum giriş" in auth_response.text.lower():
            # Eski oturumu kapatıp tekrar dene
            try:
                session.get(LOGOUT_URL, verify=False, timeout=5)
                time.sleep(2)
                return login(username, password)
            except:
                pass
            return {
                'success': False,
                'session': None,
                'message': 'Maksimum giriş hakkı doldu. Eski oturum kapatılamadı.',
                'error_type': 'max_entry'
            }
        else:
            error_type = None
            if "hatalı" in auth_response.text.lower() or "yanlış" in auth_response.text.lower():
                error_type = 'wrong_password'
            
            return {
                'success': False,
                'session': None,
                'message': 'Giriş başarısız: Hatalı bilgiler veya sistem hatası',
                'error_type': error_type
            }

    except requests.exceptions.RequestException as e:
        return {
            'success': False,
            'session': None,
            'message': f'Bağlantı hatası: {e}',
            'error_type': 'connection'
        }


def logout(session=None):
    """
    GSB Wi-Fi oturumunu sunucudan kapat.
    'End Session' (Oturumu Sonlandır) butonuna JSF AJAX POST ile basar,
    ardından ConfirmDialog'daki 'Yes/Evet' butonuna AJAX POST atar.
    
    Returns:
        dict with keys:
            - 'success': bool
            - 'message': str
    """
    if not session:
        session = requests.Session()

    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
        'Referer': DASHBOARD_URL,
    })

    def _is_login_page(response):
        if not response:
            return False
        url = (response.url or '').lower()
        text = (response.text or '').lower()
        return ('login' in url) or ('j_username' in text)

    def _verify_logged_out():
        try:
            check = session.get(DASHBOARD_URL, verify=False, timeout=8, allow_redirects=True)
            return _is_login_page(check)
        except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectionError):
            return True
        except requests.exceptions.RequestException:
            return False

    def _extract_yes_button_id(partial_xml):
        # En güvenilir yol: confirm dialogundaki "ui-confirmdialog-yes" butonunun id/name'ini bul.
        m = re.search(
            r'(?:id|name)="([^"]+)"[^>]*ui-confirmdialog-yes|ui-confirmdialog-yes[^>]*(?:id|name)="([^"]+)"',
            partial_xml,
            re.IGNORECASE,
        )
        if m:
            return m.group(1) or m.group(2)

        for cdata in re.findall(r'<!\[CDATA\[(.*?)\]\]>', partial_xml, re.DOTALL):
            frag = BeautifulSoup(cdata, 'html.parser')
            for btn in frag.find_all('button'):
                classes = ' '.join(btn.get('class', []))
                txt = btn.get_text(strip=True).lower()
                if 'ui-confirmdialog-yes' in classes or txt in ('yes', 'evet'):
                    return btn.get('name') or btn.get('id')
        return None

    def _extract_view_state(text, fallback=None):
        # 1) Klasik partial-response ViewState güncellemesi
        m = re.search(r'javax\.faces\.ViewState.*?<!\[CDATA\[([^\]]+)', text, re.DOTALL)
        if m:
            return m.group(1)

        # 2) partial-response içinde dönen tam HTML'den input'u çek
        for cdata in re.findall(r'<!\[CDATA\[(.*?)\]\]>', text, re.DOTALL):
            frag = BeautifulSoup(cdata, 'html.parser')
            inp = frag.find('input', {'name': 'javax.faces.ViewState'})
            if inp and inp.get('value'):
                return inp.get('value')

        # 3) Ham metin içinde direkt input ara
        frag = BeautifulSoup(text, 'html.parser')
        inp = frag.find('input', {'name': 'javax.faces.ViewState'})
        if inp and inp.get('value'):
            return inp.get('value')

        return fallback

    def _try_direct_logout():
        candidates = [
            ('GET', LOGOUT_URL),
            ('POST', LOGOUT_URL),
            ('GET', f'{BASE_URL}/j_spring_security_logout'),
        ]
        for method, url in candidates:
            try:
                if method == 'GET':
                    resp = session.get(url, verify=False, timeout=8, allow_redirects=True)
                else:
                    resp = session.post(url, verify=False, timeout=8, allow_redirects=True)

                if _is_login_page(resp) or _verify_logged_out():
                    return True
            except requests.exceptions.RequestException:
                continue
        return False

    try:
        # 1) Öncelik: portal içindeki End Session + Confirm (JSF AJAX) akışı.
        page = session.get(DASHBOARD_URL, verify=False, timeout=10, allow_redirects=True)
        if _is_login_page(page):
            return {'success': True, 'message': 'Zaten oturum kapalı'}

        soup = BeautifulSoup(page.text, 'html.parser')

        view_state = None
        for inp in soup.find_all('input', {'name': 'javax.faces.ViewState'}):
            view_state = inp.get('value')
            if view_state:
                break

        if not view_state:
            return {'success': False, 'message': 'ViewState bulunamadı. Portal yapısı değişmiş olabilir.'}

        form = soup.find('form', id='servisUpdateForm')
        end_session_id = None
        if form:
            for btn in form.find_all('button'):
                txt = btn.get_text(strip=True).lower()
                if txt in ('end session', 'oturumu sonlandır', 'oturumu sonlandir',
                           'oturumu sonlandır', 'oturumu sonlandir'):
                    end_session_id = btn.get('name') or btn.get('id')
                    break

        # Eğer form bulunamazsa, sayfa genelinde de ara
        if not end_session_id:
            for btn in soup.find_all('button'):
                txt = btn.get_text(strip=True).lower()
                if any(k in txt for k in ('end session', 'oturumu sonland', 'sonlandır', 'sonlandir')):
                    end_session_id = btn.get('name') or btn.get('id')
                    break

        if not end_session_id:
            # Link olarak da dene (yeni portalda <a> olabilir)
            for a in soup.find_all('a'):
                txt = a.get_text(strip=True).lower()
                href = a.get('href', '')
                if any(k in txt for k in ('oturumu sonland', 'end session', 'sonlandır')):
                    # Direkt link varsa GET ile çık
                    try:
                        resp = session.get(BASE_URL + href if not href.startswith('http') else href,
                                         verify=False, timeout=8, allow_redirects=True)
                        if _is_login_page(resp) or _verify_logged_out():
                            return {'success': True, 'message': 'Oturum başarıyla kapatıldı'}
                    except requests.exceptions.RequestException:
                        pass

            if _try_direct_logout() or _verify_logged_out():
                return {'success': True, 'message': 'Oturum sunucudan kapatıldı'}
            return {'success': False, 'message': 'Oturumu Sonlandır butonu bulunamadı.'}

        ajax_headers = {
            'Faces-Request': 'partial/ajax',
            'X-Requested-With': 'XMLHttpRequest',
            'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
        }

        payload1 = {
            'javax.faces.partial.ajax': 'true',
            'javax.faces.source': end_session_id,
            'javax.faces.partial.execute': '@all',
            'servisUpdateForm': 'servisUpdateForm',
            end_session_id: end_session_id,
            'javax.faces.ViewState': view_state,
        }
        r1 = session.post(DASHBOARD_URL, data=payload1, headers=ajax_headers, verify=False, timeout=10)

        view_state = _extract_view_state(r1.text, fallback=view_state)

        yes_id = _extract_yes_button_id(r1.text)
        if not yes_id:
            # Confirm dialog butonu çoğu zaman ilk dashboard HTML'inde de mevcut.
            for b in soup.find_all('button'):
                classes = ' '.join(b.get('class', []))
                txt = b.get_text(strip=True).lower()
                if 'ui-confirmdialog-yes' in classes or txt in ('yes', 'evet'):
                    yes_id = b.get('name') or b.get('id')
                    if yes_id:
                        break

        if not yes_id:
            # Tahmini ID göndermek yanlış aksiyonu tetikleyebildiği için deneme yapmıyoruz.
            if _try_direct_logout() or _verify_logged_out():
                return {'success': True, 'message': 'Oturum sunucudan kapatıldı'}
            return {'success': False, 'message': 'Onay (Evet) butonu tespit edilemedi.'}

        payload2 = {
            'javax.faces.partial.ajax': 'true',
            'javax.faces.source': yes_id,
            'javax.faces.partial.execute': '@all',
            'servisUpdateForm': 'servisUpdateForm',
            yes_id: yes_id,
            'javax.faces.ViewState': view_state,
        }

        try:
            r2 = session.post(DASHBOARD_URL, data=payload2, headers=ajax_headers, verify=False, timeout=8)
            if '<redirect' in r2.text.lower() and _verify_logged_out():
                return {'success': True, 'message': 'Oturum başarıyla kapatıldı'}
        except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectionError):
            if _verify_logged_out():
                return {'success': True, 'message': 'Oturum başarıyla kapatıldı'}

        if _verify_logged_out() or _try_direct_logout():
            return {'success': True, 'message': 'Oturum başarıyla kapatıldı'}

        return {'success': False, 'message': 'End Session denendi ama oturum doğrulanamadı.'}

    except requests.exceptions.RequestException as e:
        return {'success': False, 'message': f'Ağ hatası: {e}'}


# ─── Kota Bilgileri ─────────────────────────────────────────────────────────

def fetch_user_info(session):
    """
    Giriş yapılmış session ile portal dashboard'undan kota ve hesap bilgilerini çek.
    
    Yeni GSB portalı (v4.0.4+) Türkçe etiketler ve çoklu paket tablosu kullanıyor.
    
    Returns:
        dict veya None — Anahtar-değer çiftleri halinde bilgiler.
        Örnek:
        {
            'Kullanıcı': 'Ad SOYAD',
            'Lokasyon': 'ÖRNEK LOKASYON',
            'Son Giriş': '26/09/2026 12:22:29',
            'Oturum Süresi': '0 gn 0 sa 0 dk 0 sn',
            'Toplam Kota (MB)': '32768.0',
            'Toplam Kalan Kota (MB)': '18154.0',
            'Başlangıç Tarihi': '01.09.2026',
            'Sona Erme Tarihi': '30.09.2026',
            'Kalan Kota Zamanı': '4 gn 11 sa 37 dk 30 sn',
            'Paketler': [
                {'Paket Tipi': 'Sosyal Medya', 'Toplam Kota (MB)': '5120.0', ...},
                {'Paket Tipi': 'Toplam', 'Toplam Kota (MB)': '32768.0', ...},
            ],
            # Geriye uyumluluk:
            'Total Quota (MB)': '32768.0',
            'Total Remaining Quota (MB)': '18154.0',
        }
    """
    if not session:
        return None
    
    try:
        response = session.get(DASHBOARD_URL, verify=False, timeout=10)
        soup = BeautifulSoup(response.text, 'html.parser')

        info = {}
        page_text = soup.get_text(separator='\n')

        # ── Kullanıcı Adı, Son Giriş, Konum ─────────────────────────
        # Yeni portal: "Ad SOYAD\nSon Giriş:\nKonum :" şeklinde düz metin

        # Kullanıcı adı: "Son Giriş:" öncesindeki son anlamlı satır
        for marker in ('Son Giriş:', 'Son Giriş :', 'Last Login'):
            if marker in page_text:
                parts = page_text.split(marker, 1)
                preceding = [l.strip() for l in parts[0].split('\n') if l.strip()]
                if preceding:
                    info['Kullanıcı'] = preceding[-1]
                # Son Giriş değeri: marker'dan sonraki ilk anlamlı satır
                following = [l.strip() for l in parts[1].split('\n') if l.strip()]
                if following:
                    val = following[0].lstrip(':').strip()
                    if val:
                        info['Son Giriş'] = val
                        info['Last Login'] = val  # geriye uyumluluk
                break

        # Konum / Location
        for marker in ('Konum', 'Location'):
            if marker in page_text:
                parts = page_text.split(marker, 1)
                following = [l.strip() for l in parts[1].split('\n') if l.strip()]
                if following:
                    val = following[0].lstrip(':').strip()
                    if val:
                        info['Lokasyon'] = val
                break

        # Oturum Süresi
        for marker in ('Oturum Süresi:', 'Oturum Suresi:', 'Session Time'):
            if marker in page_text:
                parts = page_text.split(marker, 1)
                following = [l.strip() for l in parts[1].split('\n') if l.strip()]
                if following:
                    val = following[0].lstrip(':').strip()
                    if val:
                        info['Oturum Süresi'] = val
                        info['Session Time'] = val  # geriye uyumluluk
                break

        # Login Zamanı
        for marker in ('Login Zamanı:', 'Login Zamani:', 'Login Time'):
            if marker in page_text:
                parts = page_text.split(marker, 1)
                following = [l.strip() for l in parts[1].split('\n') if l.strip()]
                if following:
                    val = following[0].lstrip(':').strip()
                    if val:
                        info['Login Zamanı'] = val
                        info['Login Time'] = val  # geriye uyumluluk
                break

        # ── Çoklu Paket Tabloları (Kota Bilgileri) ───────────────────
        # Portal artık birden fazla tablo gösteriyor:
        #   Tablo 1 → Paket Tipi: Sosyal Medya
        #   Tablo 2 → Paket Tipi: Toplam
        # Her tabloda: Toplam Kota (MB), Toplam Kalan Kota (MB),
        #              Başlangıç Tarihi, Sona Erme Tarihi, Kalan Kota Zamanı

        packages = []
        tables = soup.find_all('table')

        for table in tables:
            pkg = {}
            for row in table.find_all('tr'):
                cells = row.find_all(['td', 'th'], recursive=False)
                if len(cells) == 2:
                    label = cells[0].get_text(strip=True).rstrip(':')
                    value = cells[1].get_text(strip=True)
                    if label and value and len(value) < 200 and len(label) < 80:
                        pkg[label] = value
            if pkg:
                packages.append(pkg)

        info['Paketler'] = packages

        # "Toplam" paketini ana kota bilgisi olarak kullan (geriye uyumluluk)
        # Yoksa en son tabloyu al (genelde Toplam en sondadır)
        main_pkg = None
        for pkg in packages:
            ptype = pkg.get('Paket Tipi', pkg.get('Package Type', '')).lower()
            if ptype in ('toplam', 'total'):
                main_pkg = pkg
                break
        if not main_pkg and packages:
            main_pkg = packages[-1]

        if main_pkg:
            # Hem Türkçe hem İngilizce ihtimallerine karşı birleştirilmiş değerleri çek
            val_total = main_pkg.get('Toplam Kota (MB)', main_pkg.get('Total Quota (MB)'))
            val_rem = main_pkg.get('Toplam Kalan Kota (MB)', main_pkg.get('Total Remaining Quota (MB)'))
            val_start = main_pkg.get('Başlangıç Tarihi', main_pkg.get('Start Date'))
            val_end = main_pkg.get('Sona Erme Tarihi', main_pkg.get('Expiration Date'))
            val_time = main_pkg.get('Kalan Kota Zamanı', main_pkg.get('Remaining Quota Time'))
            val_type = main_pkg.get('Paket Tipi', main_pkg.get('Package Type'))
            
            if val_total:
                info['Toplam Kota (MB)'] = val_total
                info['Total Quota (MB)'] = val_total
            if val_rem:
                info['Toplam Kalan Kota (MB)'] = val_rem
                info['Total Remaining Quota (MB)'] = val_rem
            if val_start:
                info['Başlangıç Tarihi'] = val_start
            if val_end:
                info['Sona Erme Tarihi'] = val_end
                info['Next Refresh Date'] = val_end  # geriye uyumluluk
            if val_time:
                info['Kalan Kota Zamanı'] = val_time
            if val_type:
                info['Paket Tipi'] = val_type

        # ── Ek tablo dışı bilgiler (Internet Servisi vb.) ────────────
        for marker in ('Internet Servisi:', 'İnternet Servisi:', 'Internet Service'):
            if marker in page_text:
                parts = page_text.split(marker, 1)
                following = [l.strip() for l in parts[1].split('\n') if l.strip()]
                if following:
                    val = following[0].lstrip(':').strip()
                    if val and 'Şifre' not in val and 'Son Hareket' not in val:
                        info['Internet Servisi'] = val
                        info['Internet Service'] = val  # geriye uyumluluk
                break

        return info if info else None

    except requests.exceptions.RequestException:
        return None


# ─── Üst Düzey İşlemler (GUI için) ─────────────────────────────────────────

def connect_and_fetch(username, password):
    """
    Bağlan + bilgileri çek — GUI'nin tek çağrı ile kullanabileceği üst düzey fonksiyon.
    
    Returns:
        dict with keys:
            - 'status': str — 'not_on_network', 'login_failed', 'connected'
            - 'message': str
            - 'session': requests.Session veya None
            - 'user_info': dict veya None
            - 'error_type': str veya None
    """
    # 1. GSB ağında mıyız?
    status = check_gsb_session()
    
    if not status['on_network']:
        # Pes etmeden önce Wi-Fi'ye zorla bağlanmayı dene
        if _force_connect_gsb():
            time.sleep(2)
            status = check_gsb_session()
            
    if not status['on_network']:
        return {
            'status': 'not_on_network',
            'message': 'GSB Wi-Fi ağına bağlı değilsiniz',
            'session': None,
            'user_info': None,
            'error_type': 'network_error'
        }
    
    # 2. Zaten giriş yapılmış mı?
    if status['logged_in'] and status['session']:
        user_info = fetch_user_info(status['session'])
        return {
            'status': 'connected',
            'message': 'Zaten giriş yapılmış. Bilgiler çekildi.',
            'session': status['session'],
            'user_info': user_info,
            'error_type': None
        }
    
    # 3. Giriş yap
    login_result = login(username, password)
    
    if not login_result['success']:
        return {
            'status': 'login_failed',
            'message': login_result['message'],
            'session': None,
            'user_info': None,
            'error_type': login_result['error_type']
        }
    
    # 4. Bilgileri çek
    user_info = fetch_user_info(login_result['session'])
    
    return {
        'status': 'connected',
        'message': 'Giriş başarılı!',
        'session': login_result['session'],
        'user_info': user_info,
        'error_type': None
    }


# ─── CLI (Terminal) Modu ────────────────────────────────────────────────────

def _print_user_info_table(info):
    """Kullanıcı bilgilerini güzel tablo formatında yazdır."""
    if not info:
        return
    
    # Gösterilecek alanlar (Paketler hariç, özel yazdırılacak)
    skip_keys = {'Paketler'}  
    # Geriye uyumluluk key'lerini gizle (Türkçe zaten gösterilecek)
    compat_keys = {'Total Quota (MB)', 'Total Remaining Quota (MB)', 
                   'Next Refresh Date', 'Last Login', 'Login Time',
                   'Session Time', 'Internet Service'}
    
    display_items = [(k, v) for k, v in info.items() 
                     if k not in skip_keys and k not in compat_keys
                     and not isinstance(v, (list, dict))]
    
    if not display_items:
        return
    
    max_label_len = max(len(k) for k, _ in display_items)
    
    print("\n" + "═" * 58)
    print("  📋 HESAP BİLGİLERİ")
    print("═" * 58)
    for key, value in display_items:
        print(f"  {key:<{max_label_len}}  │  {value}")
    
    # Paket tabloları
    packages = info.get('Paketler', [])
    if packages:
        print("─" * 58)
        for pkg in packages:
            ptype = pkg.get('Paket Tipi', '?')
            total = pkg.get('Toplam Kota (MB)', '?')
            remaining = pkg.get('Toplam Kalan Kota (MB)', '?')
            
            # GB'ye çevir
            try:
                total_f = float(total)
                rem_f = float(remaining)
                used_f = total_f - rem_f
                pct = (used_f / total_f * 100) if total_f > 0 else 0
                
                def fmt(mb):
                    return f"{mb/1024:.2f} GB" if mb >= 1024 else f"{mb:.0f} MB"
                
                bar_len = 20
                filled = int(bar_len * pct / 100)
                bar = "█" * filled + "░" * (bar_len - filled)
                
                print(f"  📦 {ptype}: [{bar}] %{pct:.1f}")
                print(f"     Kullanılan: {fmt(used_f)} / Kalan: {fmt(rem_f)} / Toplam: {fmt(total_f)}")
            except (ValueError, TypeError):
                print(f"  📦 {ptype}: Toplam {total} MB / Kalan {remaining} MB")
    
    print("═" * 58)


def main():
    """
    Terminal modu — `gsb` komutu ile çalışır.
    
    Ne olursa olsun bağlanır:
    - Ağ yoksa → DHCP yeniler, Wi-Fi toggle eder, sürekli dener
    - Portal erişilmiyorsa → Agresif retry
    - Login başarısızsa → Tekrar dener
    - Bağlantı koptuysa → Otomatik yeniden bağlanır
    
    Argümanlar:
        --reset     : Kayıtlı hesap bilgilerini sil
        --no-keep   : Bağlantıdan sonra keepalive yapma, 60sn sonra çık
        --keepalive : (Varsayılan) Bağlantı izlemeyi sürdür
    """
    
    if "--reset" in sys.argv:
        if clear_credentials():
            print("✅ Kayıtlı bilgiler silindi.")
        else:
            print("ℹ️  Silinecek bilgi bulunamadı.")
        return
    
    # Varsayılan keepalive AÇIK, --no-keep ile kapatılabilir
    keepalive_mode = "--no-keep" not in sys.argv

    print()
    print("╔══════════════════════════════════════════════╗")
    print("║     🌐 GSB Wi-Fi Otomatik Bağlantı Sistemi  ║")
    print("╚══════════════════════════════════════════════╝")
    print()
    
    # ── 1. Hesap bilgilerini al ─────────────────────────────────────
    username, password = get_credentials()
    if not username:
        # Hiç hesap yok
        print("  ⚠️  Kayıtlı hesap bulunamadı. Lütfen bilgileri girin.\n")
        username = input("  TC Kimlik No (veya Pasaport No): ")
        password = getpass.getpass("  Şifre: ")
        save_credentials(username, password)
        print("  ✅ Bilgiler güvenli şekilde kaydedildi.\n")
    elif not password:
        # Hesap var ama şifre eksik (örn. keyring→Fernet geçişi sonrası)
        accounts = get_all_accounts()
        idx = get_active_index()
        label = accounts[idx].get('label', username) if accounts else username
        tc_masked = username[:3] + "****" + username[-3:] if len(username) > 6 else username
        print(f"  👤 Hesap: {label} ({tc_masked})")
        print(f"  ⚠️  Şifre kayıtlı değil (sistem güncellemesi nedeniyle tekrar girilmesi gerekiyor)\n")
        password = getpass.getpass("  Şifre: ")
        add_account(username, password, label)
        print("  ✅ Şifre güvenli şekilde kaydedildi.\n")
    else:
        # TC'nin ilk 3 ve son 3 hanesini göster
        tc_masked = username[:3] + "****" + username[-3:] if len(username) > 6 else username
        print(f"  👤 Hesap: {tc_masked}")
    
    # ── 2. Bağlantı döngüsü — NE OLURSA OLSUN BAĞLAN ──────────────
    session = None
    info = None
    attempt = 0
    max_login_attempts = 50  # Çok yüksek — pratik olarak sonsuz
    
    while attempt < max_login_attempts:
        attempt += 1
        
        print(f"\n  🔄 Bağlantı denemesi #{attempt}...")
        
        # 2a. GSB ağında mıyız?
        ssid = _check_ssid()
        on_gsb = ssid and "GSB" in ssid.upper() if ssid else False
        
        if on_gsb:
            print(f"  📶 Wi-Fi ağı: {ssid}")
        else:
            print(f"  📶 Wi-Fi ağı: {ssid or 'Bağlı değil'}")
            print("  📡 GSB ağına otomatik bağlanmaya çalışılıyor...")
            if _force_connect_gsb():
                ssid = _check_ssid()
                print(f"  ✅ Güncel Wi-Fi ağı: {ssid}")
            else:
                print("  ❌ GSB ağına bağlanılamadı. Kapsama alanında olduğunuza emin olun.")
        
        # 2b. IP kontrolü
        ip = _get_local_ip()
        
        if not ip:
            print("  ❌ IP adresi yok — ağ yoğunluğundan IP alınamıyor olabilir")
            print("  🔧 Agresif ağ kurtarma başlatılıyor...")
            
            recovery = aggressive_network_recovery(max_cycles=5, verbose=True)
            
            if not recovery['success']:
                print(f"  ❌ Ağ kurtarma başarısız ({recovery['attempts']} döngü denendi)")
                wait = min(5 * attempt, 30)
                print(f"  ⏳ {wait} saniye sonra yeniden denenecek... (Ctrl+C ile çık)")
                try:
                    time.sleep(wait)
                except KeyboardInterrupt:
                    print("\n  👋 Çıkılıyor...")
                    return
                continue
            
            ip = recovery['ip']
            print(f"  ✅ Ağ kurtarma başarılı! IP: {ip}")
        else:
            print(f"  🌐 IP adresi: {ip}")
        
        # 2c. Portal erişilebilir mi?
        if not _can_reach_host():
            print("  ⚠️  Portal (wifi.gsb.gov.tr) erişilemiyor, DHCP yenileniyor...")
            _renew_dhcp()
            time.sleep(3)
            if not _can_reach_host():
                print("  ❌ Portal hâlâ erişilemiyor")
                wait = min(3 * attempt, 15)
                print(f"  ⏳ {wait}sn sonra tekrar denenecek...")
                try:
                    time.sleep(wait)
                except KeyboardInterrupt:
                    print("\n  👋 Çıkılıyor...")
                    return
                continue
        
        print("  ✅ Portal erişilebilir")
        
        # 2d. Login dene
        result = connect_and_fetch(username, password)
        
        if result['status'] == 'connected':
            session = result['session']
            info = result['user_info']
            
            # Kullanıcı adını güncelle
            if info and info.get('Kullanıcı'):
                update_account_label(username, info['Kullanıcı'])
            
            print(f"\n  ✅ {result['message']}")
            break
        
        elif result['status'] == 'login_failed':
            print(f"  ❌ {result['message']}")
            
            if result['error_type'] == 'wrong_password':
                print("  🔑 Şifre hatalı! Bilgileri sıfırlamak için: gsb --reset")
                return
            
            # max_entry veya diğer hatalar — tekrar dene
            if result['error_type'] == 'max_entry':
                print("  🔄 Eski oturum kapatılıp tekrar denenecek...")
                try:
                    logout()  # Eski oturumu kapat
                except Exception:
                    pass
                time.sleep(3)
                continue
            
            # Connection error — ağ sorunu, tekrar dene
            wait = min(3 * attempt, 15)
            print(f"  ⏳ {wait}sn sonra tekrar denenecek...")
            try:
                time.sleep(wait)
            except KeyboardInterrupt:
                print("\n  👋 Çıkılıyor...")
                return
            continue
        
        elif result['status'] == 'not_on_network':
            print("  ❌ GSB ağı tespit edilemedi, ağ kurtarma deneniyor...")
            recovery = aggressive_network_recovery(max_cycles=3, verbose=True)
            if not recovery['success']:
                wait = min(5 * attempt, 30)
                print(f"  ⏳ {wait}sn sonra tekrar denenecek...")
                try:
                    time.sleep(wait)
                except KeyboardInterrupt:
                    print("\n  👋 Çıkılıyor...")
                    return
            continue
    
    if not session:
        print(f"\n  ❌ {max_login_attempts} deneme sonra bağlantı kurulamadı.")
        print("  💡 Wi-Fi ayarlarınızı kontrol edin ve gsb komutunu tekrar çalıştırın.")
        return
    
    # ── 3. Bilgileri göster ─────────────────────────────────────────
    _print_user_info_table(info)
    
    # ── 4. Keepalive veya zamanlı çıkış ────────────────────────────
    if keepalive_mode:
        print("\n  🔒 Bağlantı izleme aktif. (Ctrl+C ile çıkabilirsiniz)")
        print("     Bağlantı koparsa otomatik yeniden bağlanacak.\n")
        
        fail_count = 0
        check_interval = 15  # 15 saniyede bir kontrol
        
        while True:
            try:
                time.sleep(check_interval)
                
                if not check_internet():
                    fail_count += 1
                    ts = time.strftime('%H:%M:%S')
                    print(f"  [{ts}] ⚠️  Bağlantı kesildi! Yeniden bağlanılıyor... (#{fail_count})")
                    
                    # Önce basit login dene
                    login_result = login(username, password)
                    if login_result['success']:
                        session = login_result['session']
                        fail_count = 0
                        print(f"  [{time.strftime('%H:%M:%S')}] ✅ Bağlantı yeniden sağlandı!")
                        continue
                    
                    # Login olmadıysa ağ sorunu var, kurtarma başlat
                    if fail_count >= 2:
                        print(f"  [{time.strftime('%H:%M:%S')}] 🔧 Ağ kurtarma başlatılıyor...")
                        recovery = aggressive_network_recovery(
                            max_cycles=3, verbose=True
                        )
                        if recovery['success']:
                            login_result = login(username, password)
                            if login_result['success']:
                                session = login_result['session']
                                fail_count = 0
                                print(f"  [{time.strftime('%H:%M:%S')}] ✅ Kurtarma başarılı, bağlantı sağlandı!")
                                continue
                    
                    if fail_count > 10:
                        print(f"  [{time.strftime('%H:%M:%S')}] 😔 Çok fazla başarısız deneme, 60sn bekleniyor...")
                        time.sleep(60)
                    elif fail_count > 5:
                        print(f"  [{time.strftime('%H:%M:%S')}] ⏳ 15sn bekleniyor...")
                        time.sleep(15)
                else:
                    if fail_count > 0:
                        print(f"  [{time.strftime('%H:%M:%S')}] ✅ Bağlantı tekrar sağlandı!")
                        fail_count = 0
                
            except KeyboardInterrupt:
                print("\n")
                print("  🔒 Oturum kapatılıyor...")
                logout_result = logout(session)
                print(f"  {logout_result['message']}")
                print("\n  👋 Güle güle!")
                break
            except Exception as e:
                print(f"  ⚠️  Beklenmedik hata: {e}")
                time.sleep(15)
    else:
        # --no-keep modunda: 60sn sonra logout
        print(f"\n  ⏳ {AUTO_LOGOUT_SECONDS}sn sonra otomatik çıkış yapılacak...")
        print(f"     (Ctrl+C ile erken çıkabilirsiniz)")
        try:
            for remaining in range(AUTO_LOGOUT_SECONDS, 0, -1):
                mins, secs = divmod(remaining, 60)
                print(f"\r  Kalan süre: {mins:01d}:{secs:02d} ", end='', flush=True)
                time.sleep(1)
            print()
        except KeyboardInterrupt:
            print("\n\n  ⚡ Erken çıkış.")

        logout_result = logout(session)
        print(f"\n  🔒 {logout_result['message']}")
        print("\n  👋 Güle güle!")


if __name__ == "__main__":
    main()
