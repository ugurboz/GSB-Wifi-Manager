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

# Kullanıcı yapılandırma ve veri dizini (~/.gsb_wifi)
def _get_config_dir():
    """Kullanıcı verilerinin saklanacağı dizini belirler (~/.gsb_wifi).
    Mevcut yerel dosya varsa güvenli bir şekilde taşır.
    """
    config_dir = os.getenv("GSB_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".gsb_wifi")
    os.makedirs(config_dir, exist_ok=True)
    if hasattr(os, "chmod"):
        try:
            os.chmod(config_dir, 0o700)
        except Exception:
            pass

    # Geriye dönük uyumluluk: Çalışma veya script dizininde eski dosya varsa kopyala
    search_dirs = [
        os.path.dirname(os.path.abspath(__file__)),
        os.getcwd()
    ]
    for fname in ("accounts.json", ".env"):
        dest = os.path.join(config_dir, fname)
        if not os.path.exists(dest):
            for sdir in search_dirs:
                src = os.path.join(sdir, fname)
                if os.path.exists(src) and os.path.abspath(src) != os.path.abspath(dest):
                    try:
                        import shutil
                        shutil.copy2(src, dest)
                        break
                    except Exception:
                        pass
    return config_dir

CONFIG_DIR = _get_config_dir()
ACCOUNTS_FILE = os.path.join(CONFIG_DIR, "accounts.json")
ENV_FILE = os.path.join(CONFIG_DIR, ".env")

def _get_cipher():
    load_dotenv(ENV_FILE)
    key = os.getenv("GSB_SECRET_KEY")
    if not key:
        key = Fernet.generate_key().decode()
        set_key(ENV_FILE, "GSB_SECRET_KEY", key)
        if hasattr(os, "chmod") and os.path.exists(ENV_FILE):
            try:
                os.chmod(ENV_FILE, 0o600)
            except Exception:
                pass
    return Fernet(key.encode())


# ─── Çoklu Hesap Yönetimi ───────────────────────────────────────────────────

def _load_accounts_data():
    """accounts.json dosyasını oku ve geçmiş aylara ait kota doldu etiketlerini temizle."""
    if os.path.exists(ACCOUNTS_FILE):
        try:
            with open(ACCOUNTS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Ay başında kotalar yenilendiği için geçmiş ay etiketlerini temizle
            current_month = time.strftime('%Y-%m')
            needs_save = False
            for acc in data.get('accounts', []):
                old_month = acc.get('quota_depleted_month')
                if old_month and old_month != current_month:
                    del acc['quota_depleted_month']
                    needs_save = True
            if needs_save:
                _save_accounts_data(data)
                
            return data
        except (json.JSONDecodeError, IOError):
            pass
    return {"accounts": [], "active_index": 0}


def _save_accounts_data(data):
    """accounts.json dosyasına yaz."""
    with open(ACCOUNTS_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    if hasattr(os, "chmod") and os.path.exists(ACCOUNTS_FILE):
        try:
            os.chmod(ACCOUNTS_FILE, 0o600)
        except Exception:
            pass


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


def validate_tc(tc):
    """
    TC Kimlik No doğrulama.
    - 11 haneli olmalı
    - Sadece rakamlardan oluşmalı
    - İlk hane 0 olamaz
    
    Returns:
        tuple: (bool, str) — (Geçerli mi, Hata mesajı)
    """
    if not tc:
        return False, "TC Kimlik No boş olamaz."
    if not tc.isdigit():
        return False, "TC Kimlik No sadece rakamlardan oluşmalıdır."
    if len(tc) != 11:
        return False, f"TC Kimlik No 11 haneli olmalıdır. (Girilen: {len(tc)} hane)"
    if tc[0] == '0':
        return False, "TC Kimlik No '0' ile başlayamaz."
    return True, ""


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
    old_active_idx = data.get('active_index', 0)
    old_active_tc = accounts[old_active_idx]['tc'] if 0 <= old_active_idx < len(accounts) else None
    
    new_accounts = [a for a in accounts if a['tc'] != tc]
    if len(new_accounts) == len(accounts):
        return False  # Bulunamadı
    
    data['accounts'] = new_accounts
    
    if not new_accounts:
        data['active_index'] = 0
    else:
        # Eğer silinen hesap o an aktif hesapsa, yeni aktif hesap ilk hesap (0) olsun
        if tc == old_active_tc:
            data['active_index'] = 0
        else:
            # Silinen hesap aktif hesap değilse, eski aktif hesabın yeni indexini bul
            found = False
            for i, a in enumerate(new_accounts):
                if a['tc'] == old_active_tc:
                    data['active_index'] = i
                    found = True
                    break
            if not found:
                data['active_index'] = 0
                
    _save_accounts_data(data)
    return True


def update_account_label(tc, label):
    """Hesap etiketini güncelle (portaldan çekilen isim ile)."""
    if not tc or not label:
        return False
    data = _load_accounts_data()
    changed = False
    for acc in data.get('accounts', []):
        if acc['tc'] == tc:
            if acc.get('label') != label:
                acc['label'] = label
                changed = True
            break
    if changed:
        _save_accounts_data(data)
        return True
    return False


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
    data = _load_accounts_data()
    if not data.get('accounts'):
        return False
    data['accounts'] = []
    data['active_index'] = 0
    _save_accounts_data(data)
    return True


def is_quota_depleted(user_info):
    """
    Portal kullanıcı verisinde kalan kota bitmiş mi kontrol et.
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


def is_account_quota_depleted(account_or_tc):
    """
    Belirtilen hesabın bu ayki kotası dolmuş olarak etiketlenmiş mi kontrol et.
    GSB kotaları her ay başında (1. gün 00:00) yenilendiği için, etiket sadece
    içinde bulunulan ay (YYYY-MM) boyunca geçerlidir. Ay değiştiğinde otomatik açılır.
    
    Returns:
        bool: Bu ay kotası dolmuşsa True, değilse False
    """
    if not account_or_tc:
        return False
    
    current_month = time.strftime('%Y-%m')
    
    if isinstance(account_or_tc, dict):
        month = account_or_tc.get('quota_depleted_month')
        return month == current_month
    elif isinstance(account_or_tc, str):
        for acc in get_all_accounts():
            if acc.get('tc') == account_or_tc:
                return acc.get('quota_depleted_month') == current_month
    return False


def mark_account_quota_depleted(tc, depleted=True):
    """
    Hesabın kotasını bu ay için doldu olarak etiketle veya etiketi kaldır.
    
    Args:
        tc: TC Kimlik No
        depleted: True ise bu ay için kota doldu etiketi koyar, False ise temizler
    """
    data = _load_accounts_data()
    changed = False
    current_month = time.strftime('%Y-%m')
    
    for acc in data.get('accounts', []):
        if acc.get('tc') == tc:
            if depleted:
                if acc.get('quota_depleted_month') != current_month:
                    acc['quota_depleted_month'] = current_month
                    changed = True
            else:
                if 'quota_depleted_month' in acc:
                    del acc['quota_depleted_month']
                    changed = True
            break
            
    if changed:
        _save_accounts_data(data)


def get_next_account_index(skip_quota_depleted=True):
    """
    Aktif hesaptan sonraki hesap indeksini döner.
    
    Args:
        skip_quota_depleted (bool): True ise bu ay kotası tükenmiş hesapları atlar.
    Returns:
        int veya None: Sonraki uygun hesap indeksi, başka uygun hesap yoksa None
    """
    accounts = get_all_accounts()
    if len(accounts) <= 1:
        return None
    
    current = get_active_index()
    n = len(accounts)
    
    # Sıradaki hesaplardan kotası dolmamış ilkini ara
    for step in range(1, n):
        idx = (current + step) % n
        if skip_quota_depleted:
            if not is_account_quota_depleted(accounts[idx]):
                return idx
        else:
            return idx
            
    # Eğer tüm diğer hesapların kotası dolmuşsa ve skip_quota_depleted=False ise
    if not skip_quota_depleted:
        return (current + 1) % n
        
    return None


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
    """macOS'ta bağlı Wi-Fi SSID'sini veya ağ kimliğini kontrol et."""
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

    # Yöntem 2: DHCP paketinden domain kontrolü (macOS Sonoma/Sequoia'da airport silindiğinde en güvenilir)
    try:
        wifi_device = _get_wifi_device()
        out = subprocess.check_output(
            ["ipconfig", "getpacket", wifi_device],
            timeout=3, stderr=subprocess.DEVNULL
        ).decode(errors='ignore')
        if "kykwifi" in out.lower() or "gsb" in out.lower():
            return "GSBWIFI"
    except Exception:
        pass

    # Yöntem 3: Portal sunucusu ve yerel IP erişilebilirliği
    try:
        if _get_local_ip() and _can_reach_host():
            return "GSBWIFI"
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
    Gerçek internet erişimi var mı kontrolü.
    Birden fazla endpoint deneyerek false alarm oranını azaltır.
    GSB captive portal ağlarında tek endpoint güvenilmez olabilir.
    
    Returns:
        bool: İnternet erişimi varsa True
    """
    # Birden fazla endpoint dene — herhangi biri çalışırsa internet var
    endpoints = [
        ("8.8.8.8", 53),       # Google DNS
        ("1.1.1.1", 53),       # Cloudflare DNS
        ("208.67.222.222", 53), # OpenDNS
    ]
    for host, port in endpoints:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(5)
            s.connect((host, port))
            s.close()
            return True
        except OSError:
            continue
    
    # TCP başarısızsa HTTP dene (GSB portalı arkasında DNS kısıtlı olabilir)
    try:
        r = requests.get("http://www.google.com/generate_204", timeout=5, verify=False)
        return r.status_code == 204 or r.status_code == 200
    except Exception:
        pass
    
    return False


def check_gsb_session_alive(session):
    """
    GSB portalında oturum hâlâ açık mı kontrol et.
    check_internet()'ten daha güvenilir — doğrudan portal durumunu kontrol eder.
    
    Returns:
        bool: Oturum açıksa True
    """
    if not session:
        return False
    try:
        r = session.get(DASHBOARD_URL, verify=False, timeout=8, allow_redirects=True)
        # 1. Önce Maksimum cihaz hatasını kontrol et (çünkü bu sayfada da Çıkış butonu olabilir)
        if 'maksimumcihaz' in r.url.lower() or 'maksimum cihaz' in r.text.lower() or 'maximum entry' in r.text.lower():
            return False
        # 2. Login sayfasına yönlendirildiyse oturum kapanmış
        if 'login' in r.url.lower() or 'j_username' in r.text:
            return False
        # 3. Dashboard'da "Çıkış" butonu varsa oturum açık
        if 'logout' in r.text.lower() or 'Çıkış' in r.text:
            return True
        return True
    except requests.exceptions.RequestException:
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
    GSB Wi-Fi ağına zorla bağlanır.
    
    - Başka bir ağa bağlıysa önce o ağdan kopar
    - Wi-Fi kapalıysa açar
    - Kayıtlı GSB ağlarını bulup bağlanır
    - Bulamazsa varsayılan GSB SSID'lerini dener
    
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
        
        # Şu anki bağlı SSID'yi kontrol et
        current_ssid = _check_ssid()
        
        if current_ssid and "GSB" not in current_ssid.upper():
            # Başka bir ağa bağlı! Önce kopar
            print(f"  📡 '{current_ssid}' ağından ayrılınıyor...")
            
            # Yöntem 1: airport ile disconnect (daha güvenilir)
            airport_cmd = "/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport"
            try:
                subprocess.run(
                    [airport_cmd, "-z"],  # -z = disassociate (ağdan kopar)
                    timeout=5, capture_output=True
                )
            except Exception:
                pass
            
            time.sleep(2)
            
            # Hâlâ bağlıysa, Wi-Fi toggle yap
            still_connected = _check_ssid()
            if still_connected and "GSB" not in still_connected.upper():
                print("  🔌 Wi-Fi yeniden başlatılıyor...")
                subprocess.run(
                    ["networksetup", "-setairportpower", device, "off"],
                    timeout=5, capture_output=True
                )
                time.sleep(1)
                subprocess.run(
                    ["networksetup", "-setairportpower", device, "on"],
                    timeout=5, capture_output=True
                )
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
            print(f"  📡 '{target}' ağına bağlanılıyor...")
            try:
                subprocess.run(["networksetup", "-setairportnetwork", device, target], timeout=15, capture_output=True)
            except subprocess.TimeoutExpired:
                # networksetup captive portal ağlarında asılı kalabilir, bağlantı aslında başarılı olmuş olabilir
                pass
            
            time.sleep(3)
            current = _check_ssid()
            if current and ("GSB" in current.upper() or target.upper() in current.upper()):
                print(f"  ✅ '{current}' ağına bağlandı!")
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

def _terminate_all_sessions(session, response=None):
    """
    'Maksimum Cihaz Hakkı Dolu' sayfasındaki tüm aktif oturumları sonlandırır.
    
    PrimeFaces AJAX simülasyonu başarısız olduğu için, doğrudan standart (non-AJAX)
    form submit yöntemi kullanıyoruz. Bu, JavaScript kapalı bir tarayıcının
    yapacağı gibi tüm form verilerini (hidden input'lar, ViewState ve buton adı)
    doğrudan POST etmektir.
    
    Args:
        session: requests.Session — login sırasında kullanılan session
        response: requests.Response veya None
    
    Returns:
        bool: En az bir işlem denendiyse True
    """
    MAX_DEVICE_URL = f"{BASE_URL}/maksimumCihazHakkiDolu.html"
    
    try:
        print("  📋 Aktif oturumlar kontrol ediliyor...")
        
        # JSF sistemlerinde Maksimum Cihaz sayfası POST verisiyle dolar.
        # Yeni bir GET isteği yaparsak tablo boş gelir veya login sayfasına atar.
        # Bu yüzden her zaman auth'tan gelen orijinal response'u kullanmalıyız.
        page = response
        
        if not page:
            # Fallback (normalde buraya düşmemeli)
            page = session.get(MAX_DEVICE_URL, verify=False, timeout=10, allow_redirects=True)
            
        soup = BeautifulSoup(page.text, 'html.parser')
        
        view_state = None
        for inp in soup.find_all('input', {'name': 'javax.faces.ViewState'}):
            view_state = inp.get('value')
            if view_state:
                break
                
        if not view_state:
            print("  ⚠️  ViewState bulunamadı, oturum sonlandırılamayabilir.")
            return False
            
        # "Sonlandır" butonlarını (veya formlarını) bul
        terminate_buttons = []
        for btn in soup.find_all('button'):
            text = btn.get_text(strip=True).lower()
            if any(k == text or k in text for k in ('sonlandır', 'sonlandir', 'terminate', 'end')):
                terminate_buttons.append(btn)
                
        if not terminate_buttons:
            print("  ⚠️  Sonlandırılacak aktif cihaz bulunamadı.")
            # Yalnızca GSB_DEBUG=1 olduğunda hata ayıklama dosyası kaydet
            if os.getenv("GSB_DEBUG") == "1":
                try:
                    debug_file = os.path.join(CONFIG_DIR, "gsb_debug_max_device.html")
                    with open(debug_file, "w", encoding="utf-8") as f:
                        f.write(page.text)
                    print(f"  🐛 Hata ayıklama sayfası '{debug_file}' konumuna kaydedildi.")
                except Exception:
                    pass
            return False
            
        print(f"  🔍 {len(terminate_buttons)} aktif oturum bulundu, sonlandırılıyor...")
        terminated_any = False
        
        # Her buton için standart form submit dene
        for idx, btn in enumerate(terminate_buttons):
            btn_name = btn.get('name') or btn.get('id')
            if not btn_name:
                continue
                
            form = btn.find_parent('form')
            if not form:
                continue
                
            form_action = form.get('action') or MAX_DEVICE_URL
            if not form_action.startswith('http'):
                form_action = f"{BASE_URL}{form_action if form_action.startswith('/') else '/' + form_action}"
                
            print(f"  🔄 Oturum #{idx+1} sonlandırılıyor...")
            
            # Form içindeki tüm input'ları topla (ViewState dahil)
            payload = {}
            for inp in form.find_all(['input', 'select', 'textarea']):
                name = inp.get('name')
                if name:
                    payload[name] = inp.get('value', '')
            
            # Butonun kendisini form data'ya ekle (tıklandığını belirtmek için)
            payload[btn_name] = btn_name
            
            # Güncel ViewState'i zorla
            payload['javax.faces.ViewState'] = view_state
            
            # AJAX İSTEMİYORUZ, standart POST
            headers = {
                'Content-Type': 'application/x-www-form-urlencoded',
                'Referer': MAX_DEVICE_URL,
                'Origin': BASE_URL,
            }
            
            try:
                r = session.post(form_action, data=payload, headers=headers, verify=False, timeout=15, allow_redirects=True)
                
                # Yeni ViewState al
                new_soup = BeautifulSoup(r.text, 'html.parser')
                for inp in new_soup.find_all('input', {'name': 'javax.faces.ViewState'}):
                    vs = inp.get('value')
                    if vs:
                        view_state = vs
                        break
                        
                terminated_any = True
                print(f"  ✅ Oturum #{idx+1} sonlandırma isteği gönderildi!")
                time.sleep(1)
            except Exception as e:
                print(f"  ❌ Oturum #{idx+1} hata: {e}")
                
        # Eğer buton bulamadıysa URL tabanlı fallback dene
        if not terminated_any:
            fallback_urls = [
                f"{BASE_URL}/terminateSession",
                f"{BASE_URL}/j_spring_security_logout",
            ]
            for url in fallback_urls:
                try:
                    session.get(url, verify=False, timeout=5)
                    terminated_any = True
                except:
                    pass

        return terminated_any
        
    except Exception as e:
        print(f"  ❌ Sonlandırma işlemi başarısız: {e}")
        return False


def login(username, password, _max_entry_retries=0):
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

        # Başarı/Hata kontrolü
        # 1. Önce Maksimum Cihaz kontrolü yap (çünkü o sayfada da Çıkış kelimesi var!)
        if ("maximum entry reached" in auth_response.text.lower()
              or "maksimum giriş" in auth_response.text.lower()
              or "maksimumcihaz" in auth_response.url.lower()
              or "maksimum cihaz" in auth_response.text.lower()):
            # Maksimum cihaz hakkı dolu — diğer cihazları zorla sonlandır ve tekrar dene
            if _max_entry_retries >= 3:
                return {
                    'success': False,
                    'session': None,
                    'message': 'Maksimum giriş hakkı doldu. 3 deneme sonra diğer cihazlar sonlandırılamadı.',
                    'error_type': 'max_entry'
                }
            terminated = _terminate_all_sessions(session, auth_response)
            if terminated:
                time.sleep(2)
                return login(username, password, _max_entry_retries + 1)
            return {
                'success': False,
                'session': None,
                'message': 'Maksimum giriş hakkı doldu. Diğer cihazlar sonlandırılamadı.',
                'error_type': 'max_entry'
            }
        
        # 2. Maksimum cihaz değilse, başarı kontrolü yap
        elif "Çıkış" in auth_response.text or "logout" in auth_response.text.lower():
            return {
                'success': True,
                'session': session,
                'message': 'Giriş başarılı',
                'error_type': None
            }
        else:
            # Login başarısız — sebebi ne olursa olsun (yanlış şifre, sistem hatası vs.)
            # Eğer login sayfasına geri atıldıysa veya başarı belirteci yoksa,
            # bu her zaman bir kimlik doğrulama hatasıdır.
            # Sonsuz döngüye girmemek için error_type'ı her zaman 'wrong_password' yapıyoruz.
            error_msg = 'Giriş başarısız: Hatalı TC veya şifre'
            
            # Portal'dan gelen spesifik hata mesajlarını kontrol et
            resp_lower = auth_response.text.lower()
            if any(k in resp_lower for k in ('hatalı', 'yanlış', 'incorrect', 'invalid', 'wrong', 'error')):
                error_msg = 'Giriş başarısız: TC veya şifre hatalı'
            elif 'login' in auth_response.url.lower() or 'j_username' in auth_response.text:
                error_msg = 'Giriş başarısız: Portal giriş bilgilerini kabul etmedi'
            
            return {
                'success': False,
                'session': None,
                'message': error_msg,
                'error_type': 'wrong_password'
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
            
            # Sadece geçerli kota paketi tablolarını al
            if pkg and ('Toplam Kota (MB)' in pkg or 'Total Quota (MB)' in pkg):
                if 'Total Quota (MB)' in pkg and 'Toplam Kota (MB)' not in pkg:
                    pkg['Toplam Kota (MB)'] = pkg['Total Quota (MB)']
                if 'Total Remaining Quota (MB)' in pkg and 'Toplam Kalan Kota (MB)' not in pkg:
                    pkg['Toplam Kalan Kota (MB)'] = pkg['Total Remaining Quota (MB)']
                if 'Package Type' in pkg and 'Paket Tipi' not in pkg:
                    pkg['Paket Tipi'] = pkg['Package Type']
                if 'Start Date' in pkg and 'Başlangıç Tarihi' not in pkg:
                    pkg['Başlangıç Tarihi'] = pkg['Start Date']
                if 'Expiration Date' in pkg and 'Sona Erme Tarihi' not in pkg:
                    pkg['Sona Erme Tarihi'] = pkg['Expiration Date']
                if 'Remaining Quota Time' in pkg and 'Kalan Kota Zamanı' not in pkg:
                    pkg['Kalan Kota Zamanı'] = pkg['Remaining Quota Time']
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
        if user_info and user_info.get('Kullanıcı') and username:
            update_account_label(username, user_info['Kullanıcı'])
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
    if user_info and user_info.get('Kullanıcı') and username:
        update_account_label(username, user_info['Kullanıcı'])
    
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
    
    # Gerçek kota paketlerini filtrele
    valid_packages = []
    for pkg in info.get('Paketler', []):
        tot = pkg.get('Toplam Kota (MB)', pkg.get('Total Quota (MB)'))
        rem = pkg.get('Toplam Kalan Kota (MB)', pkg.get('Total Remaining Quota (MB)'))
        if tot is not None and rem is not None:
            valid_packages.append(pkg)
            
    # Eğer paket listesinde kota paketi yoksa ama üst düzey info'da varsa paket oluştur
    if not valid_packages and ('Toplam Kota (MB)' in info or 'Total Quota (MB)' in info):
        tot = info.get('Toplam Kota (MB)', info.get('Total Quota (MB)'))
        rem = info.get('Toplam Kalan Kota (MB)', info.get('Total Remaining Quota (MB)'))
        if tot and rem:
            valid_packages.append({
                'Paket Tipi': info.get('Paket Tipi', info.get('Package Type', 'Toplam')),
                'Toplam Kota (MB)': tot,
                'Toplam Kalan Kota (MB)': rem
            })

    # Üst tabloda gösterilecek alanlar
    skip_keys = {'Paketler'}
    if valid_packages:
        # Kota paketleri altta şık progress bar ile gösterileceği için üstteki ham sayıları ve paket tipini gizle
        skip_keys.update({'Toplam Kota (MB)', 'Toplam Kalan Kota (MB)', 'Paket Tipi', 'Package Type'})

    compat_keys = {'Total Quota (MB)', 'Total Remaining Quota (MB)', 
                   'Next Refresh Date', 'Last Login', 'Login Time',
                   'Session Time', 'Internet Service'}
    
    display_items = [(k, v) for k, v in info.items() 
                     if k not in skip_keys and k not in compat_keys
                     and not isinstance(v, (list, dict))]
    
    if not display_items and not valid_packages:
        return
        
    max_label_len = max([len(k) for k, _ in display_items] + [15]) if display_items else 15
    
    print("\n" + "═" * 58)
    print("  📋 HESAP BİLGİLERİ")
    print("═" * 58)
    for key, value in display_items:
        print(f"  {key:<{max_label_len}}  │  {value}")
    
    if valid_packages:
        print("─" * 58)
        for pkg in valid_packages:
            ptype = pkg.get('Paket Tipi', pkg.get('Package Type', 'Paket'))
            if str(ptype).lower() == 'social media':
                ptype = 'Sosyal Medya'
            elif str(ptype).lower() == 'total':
                ptype = 'Toplam'
            elif str(ptype).lower() == 'education':
                ptype = 'Eğitim'
            
            total = pkg.get('Toplam Kota (MB)', pkg.get('Total Quota (MB)', '0'))
            remaining = pkg.get('Toplam Kalan Kota (MB)', pkg.get('Total Remaining Quota (MB)', '0'))
            
            try:
                total_f = float(total)
                rem_f = float(remaining)
                used_f = max(0.0, total_f - rem_f)
                pct = (used_f / total_f * 100) if total_f > 0 else 0
                
                def fmt(mb):
                    return f"{mb/1024:.2f} GB" if mb >= 1024 else f"{mb:.1f} MB"
                
                bar_len = 20
                filled = int(bar_len * pct / 100)
                bar = "█" * filled + "░" * (bar_len - filled)
                
                print(f"  📦 {ptype}: [{bar}] %{pct:.1f}")
                print(f"     Kullanılan: {fmt(used_f)} / Kalan: {fmt(rem_f)} / Toplam: {fmt(total_f)}")
            except (ValueError, TypeError):
                print(f"  📦 {ptype}: Toplam {total} MB / Kalan {remaining} MB")
    
    print("═" * 58)


def _print_keepalive_banner():
    """Bağlantı izleme durumu ve kısayolları ekrana yazdır."""
    print("\n  🔒 Bağlantı izleme aktif. Bağlantı koparsa otomatik bağlanacak.")
    print("  ────────────────────────────────────────────────────────")
    print("  ⌨️  Kısayollar:")
    print("     [1] + Enter: Hesap Ayarları Menüsünü Aç")
    print("     [Ctrl + C] : Uygulamadan çık (İnternet AÇIK kalır)")
    print("     [Ctrl + Z] : Oturumu kapat ve çık (İnternet KESİLİR)")
    print("  ────────────────────────────────────────────────────────\n")


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
    import signal
    
    _current_active_session = [None]
    
    # --- CTRL+Z (SIGTSTP) İle Oturum Kapatma ---
    def sigtstp_handler(signum, frame):
        print("\n\n  🔒 Oturum kapatılıyor... (Ctrl+Z algılandı)")
        try:
            curr_s = _current_active_session[0]
            logout_result = logout(curr_s)
            print(f"  {logout_result['message']}")
        except Exception:
            pass
        print("\n  👋 Güle güle!")
        sys.exit(0)
        
    try:
        signal.signal(signal.SIGTSTP, sigtstp_handler)
    except AttributeError:
        pass # Windows'ta SIGTSTP yok

    if "--help" in sys.argv or "-h" in sys.argv:
        print("\nKullanım: gsb [seçenekler]\n")
        print("Seçenek belirtilmezse otomatik olarak aktif hesapla bağlanır ve bağlantıyı izler.\n")
        print("  --add-account           : Yeni hesap ekle")
        print("  --list-accounts         : Kayıtlı hesapları listele")
        print("  --switch-account <idx>  : Aktif hesabı değiştir (Index no ile)")
        print("  --remove-account <tc>   : Belirtilen hesabı sil")
        print("  --logout                : Mevcut oturumu kapat (İnterneti keser)")
        print("  --reset                 : Tüm hesap bilgilerini sıfırla")
        print("  --no-keep               : Bağlantıdan sonra izleme yapma (60sn sonra çıkar)")
        print("\nKısayollar:")
        print("  Ctrl+C : Uygulamadan çık (Bağlantı açık kalır)")
        print("  Ctrl+Z : Oturumu güvenle kapat ve çık (Bağlantı kesilir)\n")
        return

    if "--logout" in sys.argv:
        print("\n  🔒 Oturum kapatılıyor...")
        res = logout(None)
        print(f"  {res['message']}")
        return
        
    if "--list-accounts" in sys.argv:
        accounts = get_all_accounts()
        if not accounts:
            print("\n  ℹ️  Kayıtlı hesap bulunmamaktadır.\n")
            return
        idx = get_active_index()
        print("\n  📋 Kayıtlı Hesaplar:")
        for i, acc in enumerate(accounts):
            marker = "⭐" if i == idx else "  "
            quota_tag = " [⚠️ Kota Dolu (Ay Sonu Yenilenir)]" if is_account_quota_depleted(acc) else ""
            print(f"  {marker} [{i}] {acc.get('label', acc['tc'])} ({acc['tc'][:3]}********){quota_tag}")
        print("\n  Aktif hesabı değiştirmek için: gsb --switch-account <index>\n")
        return
        
    if "--add-account" in sys.argv:
        print("\n  ➕ Yeni Hesap Ekle")
        tc = input("  TC Kimlik No: ").strip()
        valid, msg = validate_tc(tc)
        if not valid:
            print(f"  ❌ {msg}\n")
            return
        pwd = getpass.getpass("  Şifre: ").strip()
        if not pwd:
            print("  ❌ Şifre boş olamaz.\n")
            return
        label = input("  Etiket (Örn: Telefonum): ").strip()
        is_new = add_account(tc, pwd, label or tc)
        if is_new:
            print(f"  ✅ Yeni hesap başarıyla eklendi! ({label or tc})\n")
        else:
            print(f"  ℹ️  Mevcut hesap başarıyla güncellendi! ({label or tc})\n")
        
        accounts = get_all_accounts()
        for i, acc in enumerate(accounts):
            if acc['tc'] == tc:
                if len(accounts) > 1 and i != get_active_index():
                    ans = input(f"  ⭐ Bu hesabı aktif hesap yapmak ister misiniz? (E/h): ").strip().lower()
                    if ans in ('', 'e', 'evet', 'y', 'yes'):
                        set_active_index(i)
                        print(f"  ✅ Aktif hesap seçildi: [{i}] {acc.get('label', acc['tc'])}\n")
                break
        return
        
    if "--switch-account" in sys.argv:
        accounts = get_all_accounts()
        if not accounts:
            print("\n  ❌ Kayıtlı hesap bulunamadı.\n")
            return
        
        idx_arg = None
        try:
            flag_idx = sys.argv.index("--switch-account")
            if flag_idx + 1 < len(sys.argv) and not sys.argv[flag_idx + 1].startswith("-"):
                idx_arg = sys.argv[flag_idx + 1]
        except ValueError:
            pass
        
        if idx_arg is None:
            print("\n  📋 Kayıtlı Hesaplar:")
            curr_idx = get_active_index()
            for i, acc in enumerate(accounts):
                marker = "⭐" if i == curr_idx else "  "
                quota_tag = " [⚠️ Kota Dolu (Ay Sonu Yenilenir)]" if is_account_quota_depleted(acc) else ""
                print(f"  {marker} [{i}] {acc.get('label', acc['tc'])} ({acc['tc'][:3]}********){quota_tag}")
            idx_str = input("\n  Geçilecek hesabın numarası: ").strip()
        else:
            idx_str = idx_arg
        
        if idx_str.isdigit() and 0 <= int(idx_str) < len(accounts):
            new_idx = int(idx_str)
            set_active_index(new_idx)
            chosen = accounts[new_idx]
            quota_tag = " [⚠️ Kota Dolu (Ay Sonu Yenilenir)]" if is_account_quota_depleted(chosen) else ""
            print(f"\n  ✅ Aktif hesap değiştirildi: [{new_idx}] {chosen.get('label', chosen['tc'])}{quota_tag}\n")
        else:
            print(f"\n  ❌ Geçersiz index! 0 ile {len(accounts)-1} arasında bir değer girin.\n")
        return
        
    if "--remove-account" in sys.argv:
        accounts = get_all_accounts()
        if not accounts:
            print("\n  ❌ Kayıtlı hesap bulunamadı.\n")
            return
        
        target_arg = None
        try:
            flag_idx = sys.argv.index("--remove-account")
            if flag_idx + 1 < len(sys.argv) and not sys.argv[flag_idx + 1].startswith("-"):
                target_arg = sys.argv[flag_idx + 1]
        except ValueError:
            pass
        
        if target_arg is None:
            print("\n  📋 Silinecek Hesabı Seçin:")
            for i, acc in enumerate(accounts):
                marker = "⭐" if i == get_active_index() else "  "
                print(f"  {marker} [{i}] {acc.get('label', acc['tc'])} ({acc['tc'][:3]}********)")
            target_str = input("\n  Index numarası veya TC Kimlik No: ").strip()
        else:
            target_str = target_arg
        
        if not target_str:
            print("\n  ❌ İşlem iptal edildi.\n")
            return
        
        if target_str.isdigit() and len(target_str) < 3 and 0 <= int(target_str) < len(accounts):
            target_tc = accounts[int(target_str)]['tc']
            target_label = accounts[int(target_str)].get('label', target_tc)
        else:
            target_tc = target_str
            target_label = target_str
            for acc in accounts:
                if acc['tc'] == target_tc:
                    target_label = acc.get('label', target_tc)
                    break
        
        if remove_account(target_tc):
            print(f"\n  ✅ Hesap silindi: {target_label} ({target_tc[:3]}****)\n")
        else:
            print(f"\n  ⚠️  Belirtilen hesaba ait kayıt bulunamadı: {target_str}\n")
        return

    if "--reset" in sys.argv:
        if clear_credentials():
            print("\n  ✅ Tüm kayıtlı hesap bilgileri silindi.\n")
        else:
            print("\n  ℹ️  Silinecek bilgi bulunamadı.\n")
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
        while True:
            username = input("  TC Kimlik No (veya Pasaport No): ").strip()
            valid, msg = validate_tc(username)
            if valid:
                break
            print(f"  ❌ {msg}")
        password = getpass.getpass("  Şifre: ").strip()
        if not password:
            print("  ❌ Şifre boş olamaz.")
            return
        save_credentials(username, password)
        print("  ✅ Bilgiler güvenli şekilde kaydedildi.\n")
    elif not password:
        # Hesap var ama şifre eksik
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
        accounts = get_all_accounts()
        idx = get_active_index()
        label = accounts[idx].get('label') if accounts and idx < len(accounts) else None
        tc_masked = username[:3] + "****" + username[-3:] if len(username) > 6 else username
        display_name = f"{label} ({tc_masked})" if label and label != username else tc_masked
        print(f"  👤 Hesap: {display_name}")

    # Aktif hesabın kotası bu ay dolmuş olarak etiketlendiyse, kotası olan hesaba otomatik geç
    if username and is_account_quota_depleted(username):
        alt_idx = get_next_account_index(skip_quota_depleted=True)
        if alt_idx is not None:
            accounts = get_all_accounts()
            alt_acc = accounts[alt_idx]
            alt_label = alt_acc.get('label', alt_acc['tc'][:3] + '****')
            print(f"  ℹ️  Aktif hesabın kotası bu ay dolmuş. Kotası açık hesaba geçiliyor: {alt_label}")
            set_active_index(alt_idx)
            username, password = get_credentials()
    
    # ── 2. Bağlantı döngüsü — NE OLURSA OLSUN BAĞLAN ──────────────
    session = None
    info = None
    attempt = 0
    max_login_attempts = 50  # Çok yüksek — pratik olarak sonsuz
    attempted_tc = set()     # Şifre veya kota nedeniyle denenen hesaplar
    
    while attempt < max_login_attempts:
        attempt += 1
        attempted_tc.add(username)
        
        print(f"\n  🔄 Bağlantı denemesi #{attempt}...")
        
        # 2a. GSB ağında mıyız?
        ssid = _check_ssid()
        on_gsb = ssid and "GSB" in ssid.upper() if ssid else False
        
        if on_gsb:
            print(f"  📶 Wi-Fi ağı: {ssid}")
        else:
            if ssid:
                print(f"  📶 Wi-Fi ağı: {ssid} (GSB değil!)")
                print(f"  🔀 '{ssid}' ağından ayrılıp GSB Wi-Fi'ye geçiliyor...")
            else:
                print(f"  📶 Wi-Fi ağı: Bağlı değil")
                print("  📡 GSB ağına otomatik bağlanmaya çalışılıyor...")
            if _force_connect_gsb():
                ssid = _check_ssid() or "GSBWIFI"
                print(f"  ✅ GSB ağına bağlandı: {ssid}")
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
            _current_active_session[0] = session
            info = result['user_info']
            
            # Kullanıcı adını güncelle
            if info and info.get('Kullanıcı'):
                updated = update_account_label(username, info['Kullanıcı'])
                if updated:
                    print(f"  ✨ Hesap ismi güncellendi: {info['Kullanıcı']}")
            
            print(f"\n  ✅ {result['message']}")
            
            # ── Kota kontrolü: Bitmiş mi? ──
            if info and is_quota_depleted(info):
                print("\n  ⚠️  Bu hesabın kotası tükenmiş! (Ay sonuna kadar pasif olarak etiketlendi)")
                mark_account_quota_depleted(username, True)
                next_idx = get_next_account_index(skip_quota_depleted=True)
                accounts = get_all_accounts()
                if next_idx is not None and next_idx < len(accounts) and accounts[next_idx]['tc'] not in attempted_tc:
                    next_acc = accounts[next_idx]
                    next_label = next_acc.get('label', next_acc['tc'][:3] + '****')
                    print(f"  🔄 Sonraki hesaba geçiliyor: {next_label}")
                    
                    # Mevcut oturumu kapat
                    try:
                        logout(session)
                    except Exception:
                        pass
                    session = None
                    _current_active_session[0] = None
                    
                    # Sonraki hesaba geç
                    set_active_index(next_idx)
                    username, password = get_credentials()
                    if username and password:
                        attempt = 0  # Sayacı sıfırla
                        continue
                else:
                    print("  📛 Başka aktif kotası olan hesap bulunamadı (Tüm hesapların kotası dolmuş)!")
                    print("  💡 Kotalar ay başında otomatik olarak yenilenecektir.")
            else:
                # Kota tükenmemiş, varsa eski etiketi temizle
                mark_account_quota_depleted(username, False)
            
            break
        
        elif result['status'] == 'login_failed':
            print(f"  ❌ {result['message']}")
            
            if result['error_type'] == 'wrong_password':
                print("  🔑 TC veya şifre hatalı!")
                
                # Başka hesap var mı ve denenmedi mi?
                next_idx = get_next_account_index(skip_quota_depleted=True)
                accounts = get_all_accounts()
                if next_idx is not None and next_idx < len(accounts) and accounts[next_idx]['tc'] not in attempted_tc:
                    next_acc = accounts[next_idx]
                    next_label = next_acc.get('label', next_acc['tc'][:3] + '****')
                    print(f"  🔄 Sonraki hesaba geçiliyor: {next_label}")
                    set_active_index(next_idx)
                    username, password = get_credentials()
                    if username and password:
                        attempt = 0
                        continue
                
                # Başka hesap yoksa veya tüm hesaplar denendiyse dur
                print("  ⛔ Kayıtlı hesaplar ile bağlantı sağlanamadı (şifre hatalı).")
                print("  💡 Bilgileri düzenlemek için: gsb --reset veya gsb --add-account")
                return
            
            # max_entry veya diğer hatalar — tekrar dene
            if result['error_type'] == 'max_entry':
                print("  📱 Diğer cihazlar sonlandırılıyor, tekrar denenecek...")
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
        _print_keepalive_banner()
        
        fail_count = 0
        consecutive_fails = 0  # Ardışık başarısızlık sayısı
        check_interval = 30  # 30 saniyede bir kontrol (GSB ağında daha kararlı)
        
        while True:
            try:
                import select
                r, _, _ = select.select([sys.stdin], [], [], check_interval)
                if r:
                    choice = sys.stdin.readline().strip()
                    if choice == '1':
                        try:
                            while True:
                                print("\n  ⚙️  Hesap Ayarları Menüsü")
                                print("  [1] Kayıtlı Hesapları Listele")
                                print("  [2] Aktif Hesabı Değiştir")
                                print("  [3] Yeni Hesap Ekle")
                                print("  [4] Hesap Sil")
                                print("  [0] Menüden Çık ve İzlemeye Dön")
                                
                                sub = input("\n  Seçiminiz: ").strip()
                                if sub == '1':
                                    accounts = get_all_accounts()
                                    idx = get_active_index()
                                    print("\n  📋 Kayıtlı Hesaplar:")
                                    if not accounts:
                                        print("     Kayıtlı hesap yok.")
                                    else:
                                        for i, acc in enumerate(accounts):
                                            marker = "⭐" if i == idx else "  "
                                            quota_tag = " [⚠️ Kota Dolu (Ay Sonu Yenilenir)]" if is_account_quota_depleted(acc) else ""
                                            print(f"     {marker} [{i}] {acc.get('label', acc['tc'])} ({acc['tc'][:3]}********){quota_tag}")
                                elif sub == '2':
                                    accounts = get_all_accounts()
                                    if not accounts:
                                        print("  ❌ Kayıtlı hesap yok.")
                                    else:
                                        print("\n  📋 Kayıtlı Hesaplar:")
                                        curr_active = get_active_index()
                                        for i, acc in enumerate(accounts):
                                            marker = "⭐" if i == curr_active else "  "
                                            quota_tag = " [⚠️ Kota Dolu (Ay Sonu Yenilenir)]" if is_account_quota_depleted(acc) else ""
                                            print(f"     {marker} [{i}] {acc.get('label', acc['tc'])} ({acc['tc'][:3]}********){quota_tag}")
                                        idx_str = input("\n  Geçilecek hesabın Index numarası (İptal için Enter): ").strip()
                                        if not idx_str:
                                            continue
                                        if idx_str.isdigit() and 0 <= int(idx_str) < len(accounts):
                                            new_idx = int(idx_str)
                                            if new_idx == curr_active:
                                                print("  ℹ️ Bu hesap zaten aktif hesap.")
                                                continue
                                            set_active_index(new_idx)
                                            chosen = accounts[new_idx]
                                            quota_tag = " (⚠️ Kota Dolu)" if is_account_quota_depleted(chosen) else ""
                                            print(f"  ✅ Aktif hesap seçildi: [{new_idx}] {chosen.get('label', chosen['tc'])}{quota_tag}")
                                            username, password = get_credentials()
                                            
                                            ans = input("  🔄 Şimdi bu hesaba geçiş yapılsın mı? (E/h): ").strip().lower()
                                            if ans in ('', 'e', 'evet', 'y', 'yes'):
                                                print("  🔒 Mevcut oturum kapatılıyor...")
                                                if session:
                                                    try:
                                                        logout(session)
                                                    except Exception:
                                                        pass
                                                session = None
                                                _current_active_session[0] = None
                                                print(f"  📡 {chosen.get('label', chosen['tc'])} ile giriş yapılıyor...")
                                                res = connect_and_fetch(username, password)
                                                if res['status'] == 'connected':
                                                    session = res['session']
                                                    info = res['user_info']
                                                    _current_active_session[0] = session
                                                    consecutive_fails = 0
                                                    fail_count = 0
                                                    print("  ✅ Yeni hesapla başarıyla bağlanıldı!")
                                                    _print_user_info_table(info)
                                                    _print_keepalive_banner()
                                                    break
                                                else:
                                                    print(f"  ❌ Yeni hesaba geçilemedi: {res['message']}")
                                        else:
                                            print(f"  ❌ Geçersiz index! 0 ile {len(accounts)-1} arasında girin.")
                                elif sub == '3':
                                    print("\n  ➕ Yeni Hesap Ekle")
                                    tc = input("  TC Kimlik No (İptal için Enter): ").strip()
                                    if not tc:
                                        continue
                                    valid, msg = validate_tc(tc)
                                    if not valid:
                                        print(f"  ❌ {msg}")
                                        continue
                                    pwd = getpass.getpass("  Şifre: ").strip()
                                    if not pwd:
                                        print("  ❌ Şifre boş olamaz.")
                                        continue
                                    label = input("  Etiket (Örn: Telefonum): ").strip()
                                    is_new = add_account(tc, pwd, label or tc)
                                    if is_new:
                                        print(f"  ✅ Yeni hesap eklendi: {label or tc}")
                                    else:
                                        print(f"  ℹ️  Mevcut hesap güncellendi: {label or tc}")
                                    
                                    ans = input("  🔄 Şimdi bu yeni hesaba geçiş yapılsın mı? (E/h): ").strip().lower()
                                    if ans in ('', 'e', 'evet', 'y', 'yes'):
                                        accounts = get_all_accounts()
                                        for i, a in enumerate(accounts):
                                            if a['tc'] == tc:
                                                set_active_index(i)
                                                break
                                        username, password = get_credentials()
                                        print("  🔒 Mevcut oturum kapatılıyor...")
                                        if session:
                                            try:
                                                logout(session)
                                            except Exception:
                                                pass
                                        session = None
                                        _current_active_session[0] = None
                                        print(f"  📡 {label or tc} ile giriş yapılıyor...")
                                        res = connect_and_fetch(username, password)
                                        if res['status'] == 'connected':
                                            session = res['session']
                                            info = res['user_info']
                                            _current_active_session[0] = session
                                            consecutive_fails = 0
                                            fail_count = 0
                                            print("  ✅ Yeni hesapla başarıyla bağlanıldı!")
                                            _print_user_info_table(info)
                                            _print_keepalive_banner()
                                            break
                                        else:
                                            print(f"  ❌ Giriş yapılamadı: {res['message']}")
                                elif sub == '4':
                                    accounts = get_all_accounts()
                                    if not accounts:
                                        print("  ❌ Kayıtlı hesap yok.")
                                    else:
                                        print("\n  📋 Silinecek Hesabı Seçin:")
                                        curr_active = get_active_index()
                                        for i, acc in enumerate(accounts):
                                            marker = "⭐" if i == curr_active else "  "
                                            print(f"     {marker} [{i}] {acc.get('label', acc['tc'])} ({acc['tc'][:3]}********)")
                                        target = input("\n  Index numarası veya TC Kimlik No (İptal için Enter): ").strip()
                                        if not target:
                                            continue
                                        if target.isdigit() and len(target) < 3 and 0 <= int(target) < len(accounts):
                                            target_tc = accounts[int(target)]['tc']
                                            target_label = accounts[int(target)].get('label', target_tc)
                                        else:
                                            target_tc = target
                                            target_label = target
                                            for a in accounts:
                                                if a['tc'] == target_tc:
                                                    target_label = a.get('label', target_tc)
                                                    break
                                        
                                        confirm = input(f"  ⚠️  '{target_label}' ({target_tc[:3]}****) hesabını silmek istediğinize emin misiniz? (e/H): ").strip().lower()
                                        if confirm in ('e', 'evet', 'y', 'yes'):
                                            is_active_deleted = (target_tc == username)
                                            if remove_account(target_tc):
                                                print(f"  ✅ Hesap silindi: {target_label}")
                                                accounts = get_all_accounts()
                                                if accounts:
                                                    username, password = get_credentials()
                                                    if is_active_deleted:
                                                        new_active = accounts[get_active_index()]
                                                        print(f"  🔒 Silinen hesabın ({target_label}) oturumu kapatılıyor...")
                                                        if session:
                                                            try:
                                                                logout(session)
                                                            except Exception:
                                                                pass
                                                        session = None
                                                        _current_active_session[0] = None
                                                        
                                                        print(f"  🔄 '{new_active.get('label', new_active['tc'])}' hesabına otomatik geçiş yapılıyor...")
                                                        res = connect_and_fetch(username, password)
                                                        if res['status'] == 'connected':
                                                            session = res['session']
                                                            info = res['user_info']
                                                            _current_active_session[0] = session
                                                            consecutive_fails = 0
                                                            fail_count = 0
                                                            print("  ✅ Yeni hesaba başarıyla geçildi!")
                                                            _print_user_info_table(info)
                                                            _print_keepalive_banner()
                                                            break
                                                        else:
                                                            print(f"  ❌ Yeni hesaba otomatik bağlanılamadı: {res['message']}")
                                                else:
                                                    print("  🔒 Silinen hesabın oturumu kapatılıyor...")
                                                    if session:
                                                        try:
                                                            logout(session)
                                                        except Exception:
                                                            pass
                                                    session = None
                                                    _current_active_session[0] = None
                                                    print("  ⚠️  Kayıtlı hiç hesap kalmadı. Oturum kapatıldı.")
                                                    break
                                            else:
                                                print("  ❌ Hesap bulunamadı.")
                                elif sub == '0':
                                    print("\n  ▶️ İzlemeye devam ediliyor...")
                                    username, password = get_credentials()
                                    if session:
                                        try:
                                            fresh = fetch_user_info(session)
                                            if fresh:
                                                info = fresh
                                        except Exception:
                                            pass
                                        _print_user_info_table(info)
                                    else:
                                        print("  ℹ️ Aktif oturum yok, bağlantı kontrol edilecek...")
                                    _print_keepalive_banner()
                                    break
                                else:
                                    print("  ❌ Geçersiz seçim.")
                        except (KeyboardInterrupt, EOFError):
                            print("\n  ↩️  Menüden çıkıldı, izlemeye dönülüyor...")
                            username, password = get_credentials()
                            _print_keepalive_banner()
                        continue
                
                ts = time.strftime('%H:%M:%S')
                
                # 1. Önce GSB portal oturumunu kontrol et (en güvenilir yöntem)
                session_alive = check_gsb_session_alive(session)
                
                if session_alive:
                    # Oturum açık — internet erişimini ayrıca kontrol etmeye gerek yok
                    if consecutive_fails > 0:
                        print(f"  [{ts}] ✅ Bağlantı stabil!")
                    consecutive_fails = 0
                    fail_count = 0
                    continue
                
                # 2. Portal oturumu kapalı görünüyor — gerçekten mi kontrol et
                #    (GSB ağı yavaş olabilir, tek başarısızlıkta panik yapma)
                if consecutive_fails == 0:
                    consecutive_fails += 1
                    time.sleep(5)  # 5sn bekle
                    
                    if check_gsb_session_alive(session) or check_internet():
                        consecutive_fails = 0
                        continue
                
                # 3. Ardışık başarısızlık — gerçekten bağlantı kopmuş
                consecutive_fails += 1
                fail_count += 1
                print(f"  [{ts}] ⚠️  GSB oturumu düştü! Yeniden bağlanılıyor... (#{fail_count})")
                
                # Önce basit login dene
                login_result = login(username, password)
                if login_result['success']:
                    session = login_result['session']
                    _current_active_session[0] = session
                    consecutive_fails = 0
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
                            _current_active_session[0] = session
                            consecutive_fails = 0
                            fail_count = 0
                            print(f"  [{time.strftime('%H:%M:%S')}] ✅ Kurtarma başarılı, bağlantı sağlandı!")
                            continue
                
                if fail_count > 10:
                    print(f"  [{time.strftime('%H:%M:%S')}] 😔 Çok fazla başarısız deneme, 60sn bekleniyor...")
                    time.sleep(60)
                elif fail_count > 5:
                    print(f"  [{time.strftime('%H:%M:%S')}] ⏳ 15sn bekleniyor...")
                    time.sleep(15)
                
            except KeyboardInterrupt:
                print("\n  🔓 Bağlantı açık bırakılarak çıkılıyor... (Ctrl+C)")
                print("\n  👋 Güle güle!")
                break
            except Exception as e:
                print(f"  ⚠️  Beklenmedik hata: {e}")
                time.sleep(15)
    else:
        # --no-keep modunda: 60sn sonra logout
        print(f"\n  ⏳ {AUTO_LOGOUT_SECONDS}sn sonra otomatik çıkış yapılacak...")
        print(f"     (Ctrl+C ile bağlantıyı açık bırakıp çıkabilirsiniz)")
        try:
            for remaining in range(AUTO_LOGOUT_SECONDS, 0, -1):
                mins, secs = divmod(remaining, 60)
                print(f"\r  Kalan süre: {mins:01d}:{secs:02d} ", end='', flush=True)
                time.sleep(1)
            print()
        except KeyboardInterrupt:
            print("\n\n  🔓 Bağlantı açık bırakılarak çıkılıyor... (Ctrl+C)")
            print("\n  👋 Güle güle!")
            return

        # Süre normal dolduysa çıkış yap
        logout_result = logout(session)
        print(f"\n  🔒 {logout_result['message']}")
        print("\n  👋 Güle güle!")


if __name__ == "__main__":
    main()
