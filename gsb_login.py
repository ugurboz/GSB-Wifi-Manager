"""
GSB Wi-Fi Backend — Otomatik Giriş ve Kota Yönetimi

GUI veya CLI tarafından import edilebilir temiz API.
Tüm fonksiyonlar yapılandırılmış veri döndürür (print yapmaz).
"""

import requests
from bs4 import BeautifulSoup
import keyring
import getpass
import time
import socket
import sys
import json
import os
import re
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ─── Sabitler ───────────────────────────────────────────────────────────────

SERVICE_NAME = "gsb_wifi_login"
BASE_URL = "https://wifi.gsb.gov.tr"
LOGIN_URL = f"{BASE_URL}/login.html"
AUTH_URL = f"{BASE_URL}/j_spring_security_check"
LOGOUT_URL = f"{BASE_URL}/logout"
DASHBOARD_URL = f"{BASE_URL}/index.html"

# Hesap dosyası yolu (script ile aynı dizinde)
ACCOUNTS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "accounts.json")


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
    
    # Aynı TC varsa ekleme
    for acc in accounts:
        if acc['tc'] == tc:
            # Şifreyi güncelle
            keyring.set_password(SERVICE_NAME, f"pass_{tc}", password)
            if label:
                acc['label'] = label
                _save_accounts_data(data)
            return False
    
    accounts.append({'tc': tc, 'label': label or tc})
    data['accounts'] = accounts
    
    # İlk hesapsa aktif yap
    if len(accounts) == 1:
        data['active_index'] = 0
    
    _save_accounts_data(data)
    keyring.set_password(SERVICE_NAME, f"pass_{tc}", password)
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
    
    try:
        keyring.delete_password(SERVICE_NAME, f"pass_{tc}")
    except keyring.errors.PasswordDeleteError:
        pass
    
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
    """Bir hesabın şifresini Keychain'den al."""
    return keyring.get_password(SERVICE_NAME, f"pass_{tc}")


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
        remaining = float(user_info.get('Total Remaining Quota (MB)', 1))
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

def _check_ssid():
    """macOS'ta bağlı Wi-Fi SSID'sini kontrol et."""
    import subprocess
    try:
        # Yöntem 1: system_profiler (en güvenilir)
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
    
    # Yöntem 2: networksetup (eski macOS)
    try:
        out = subprocess.check_output(
            ["networksetup", "-getairportnetwork", "en0"],
            timeout=5, stderr=subprocess.DEVNULL
        ).decode(errors='ignore')
        # "Current Wi-Fi Network: GSBWIFI" formatı
        if ":" in out and "not associated" not in out.lower():
            return out.split(":", 1)[1].strip()
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
    result = {'on_network': False, 'logged_in': False, 'session': None}
    
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
            result['on_network'] = True
            
            # Login sayfasına yönlendirildiyse oturum yok
            if 'login' in response.url.lower() or 'j_username' in response.text:
                result['logged_in'] = False
            elif 'logout' in response.text.lower() or 'Çıkış' in response.text:
                result['logged_in'] = True
                result['session'] = session
            
            return result  # başarılı: sonucu dön
        except requests.exceptions.RequestException:
            continue  # sonraki URL'yi dene
    
    # Hiçbir URL çalışmadıysa portala direkt ulaşılamıyor demektir.
    result['on_network'] = False
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
                if txt in ('end session', 'oturumu sonlandır', 'oturumu sonlandir'):
                    end_session_id = btn.get('name') or btn.get('id')
                    break

        if not end_session_id:
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
    
    Returns:
        dict veya None — Anahtar-değer çiftleri halinde bilgiler.
        Örnek:
        {
            'Kullanıcı': 'Ad SOYAD',
            'Lokasyon': 'ÖRNEK LOKASYON',
            'Last Login': '01.01.2026 12:00',
            'Session Time': '0 Day 0 h 0 m 1 s',
            'Total Quota (MB)': '32768.0',
            'Total Remaining Quota (MB)': '32377.03',
            ...
        }
    """
    if not session:
        return None
    
    try:
        response = session.get(DASHBOARD_URL, verify=False, timeout=10)
        soup = BeautifulSoup(response.text, 'html.parser')

        info = {}

        # Kullanıcı adı, Son Giriş ve Lokasyon bilgisini çek (sayfa metni üzerinden)
        # Portal yapısı karmaşık olduğu için tüm metni ayırarak aramak daha güvenilir.
        page_text = soup.get_text(separator=' \n ')
        
        # 'Last Login' çevresini analiz et
        if 'Last Login' in page_text:
            parts = page_text.split('Last Login')
            # 1. Kullanıcı Adı: 'Last Login' öncesindeki en son anlamlı satır
            preceding_lines = [line.strip() for line in parts[0].split('\n') if line.strip()]
            if preceding_lines:
                info['Kullanıcı'] = preceding_lines[-1]
                
            # 2. Son Giriş: 'Last Login' sonrasındaki ilk anlamlı metin
            following_lines = [line.strip() for line in parts[1].split('\n') if line.strip()]
            if following_lines:
                login_val = following_lines[0].lstrip(':').strip()
                if login_val:
                    info['Last Login'] = login_val
                    
        # 'Location' çevresini analiz et
        if 'Location' in page_text:
            loc_parts = page_text.split('Location')
            following_lines_loc = [line.strip() for line in loc_parts[1].split('\n') if line.strip()]
            if following_lines_loc:
                loc_val = following_lines_loc[0].lstrip(':').strip()
                if loc_val:
                    info['Lokasyon'] = loc_val

        # Tablo satırlarından kota bilgilerini çek
        seen_labels = set()
        skip_labels = {'', '------', '------------', 'Stop', 'Start', 'StopStart'}
        
        for row in soup.find_all('tr'):
            cells = row.find_all(['td', 'th'], recursive=False)
            if len(cells) == 2:
                label = cells[0].get_text(strip=True).rstrip(':')
                value = cells[1].get_text(strip=True)
                
                if (label and value 
                    and label not in skip_labels 
                    and value not in skip_labels
                    and label not in seen_labels
                    and len(value) < 100
                    and len(label) < 60):
                    info[label] = value
                    seen_labels.add(label)

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
        return {
            'status': 'not_on_network',
            'message': 'GSB Wi-Fi ağına bağlı değilsiniz. Önce GSBWIFI ağına bağlanın.',
            'session': None,
            'user_info': None,
            'error_type': None
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

def main():
    """Terminal modu — geriye uyumluluk için korundu."""
    
    if "--reset" in sys.argv:
        if clear_credentials():
            print("Kayıtlı bilgiler silindi.")
        else:
            print("Silinecek bilgi bulunamadı.")
        return

    keepalive_mode = "--keepalive" in sys.argv

    print("--- GSB Wi-Fi Otomatik Giriş Sistemi ---")
    
    # Credentials
    username, password = get_credentials()
    if not username or not password:
        print("GSB Wi-Fi bilgileri bulunamadı. Lütfen giriş yapın.")
        username = input("TC Kimlik No (veya Pasaport No): ")
        password = getpass.getpass("Şifre: ")
        save_credentials(username, password)
        print("Bilgileriniz Mac Anahtarlığına (Keychain) kaydedildi.")

    # Bağlan + bilgileri çek
    result = connect_and_fetch(username, password)
    
    if result['status'] == 'not_on_network':
        print(f"❌ {result['message']}")
        return
    
    if result['status'] == 'login_failed':
        print(f"❌ {result['message']}")
        if result['error_type'] == 'wrong_password':
            print("Bilgileri sıfırlamak için '--reset' komutunu kullanabilirsiniz.")
        return
    
    # Bilgileri göster
    session = result['session']
    info = result['user_info']
    
    print(f"\n✅ {result['message']}")
    
    if info:
        print("\n" + "=" * 55)
        print("📋 HESAP BİLGİLERİ")
        print("=" * 55)
        max_label_len = max(len(k) for k in info.keys())
        for key, value in info.items():
            print(f"  {key:<{max_label_len}}  │  {value}")
        print("=" * 55)

    if keepalive_mode:
        print("\nBağlantı izleme başlatıldı. (Kapatmak için Ctrl+C'ye basın)")
        fail_count = 0
        
        while True:
            try:
                if not check_internet():
                    fail_count += 1
                    print(f"[{time.strftime('%H:%M:%S')}] Bağlantı kesildi! Yeniden bağlanılıyor... (Deneme: {fail_count})")
                    
                    if fail_count > 3:
                        wait_time = min(60 * (fail_count - 2), 300)
                        print(f"Çok fazla başarısız deneme. {wait_time} saniye bekleniyor...")
                        time.sleep(wait_time)

                    login_result = login(username, password)
                    if login_result['success']:
                        session = login_result['session']
                        fail_count = 0
                else:
                    if fail_count > 0:
                        print(f"[{time.strftime('%H:%M:%S')}] Bağlantı tekrar sağlandı.")
                        fail_count = 0
                
                time.sleep(30)
                
            except KeyboardInterrupt:
                print("\nÇıkış yapılıyor...")
                break
            except Exception as e:
                print(f"Beklenmedik bir hata oluştu: {e}")
                time.sleep(30)
    else:
        # 60 saniye sonra logout
        print(f"\n⏳ {AUTO_LOGOUT_SECONDS} saniye sonra otomatik çıkış yapılacak...")
        print(f"   (Erken çıkmak için Ctrl+C'ye basın)")
        try:
            for remaining in range(AUTO_LOGOUT_SECONDS, 0, -1):
                mins, secs = divmod(remaining, 60)
                print(f"\r   Kalan süre: {mins:01d}:{secs:02d} ", end='', flush=True)
                time.sleep(1)
            print()
        except KeyboardInterrupt:
            print("\n\n⚡ Erken çıkış talebi alındı.")

        logout_result = logout(session)
        print(f"\n🔒 {logout_result['message']}")
        print("\n--- Oturum sonlandırıldı. İyi günler! ---")


if __name__ == "__main__":
    main()
