import time
import threading
import customtkinter as ctk

from gsb_login import (
    get_credentials,
    connect_and_fetch,
    fetch_user_info,
    logout,
    check_gsb_session_alive,
    check_internet,
    validate_tc,
    # Çoklu hesap
    get_all_accounts,
    get_active_index,
    set_active_index,
    add_account,
    remove_account,
    update_account_label,
    get_account_password,
    is_quota_depleted,
    is_account_quota_depleted,
    mark_account_quota_depleted,
    get_next_account_index,
)

ctk.set_appearance_mode("System")
ctk.set_default_color_theme("blue")

# Modern Premium Renk Paleti (Mac-vari)
COLOR_MAIN_BG = ("#F2F2F7", "#0D0D0D")
COLOR_SIDEBAR_BG = ("#E5E5EA", "#161618")
COLOR_CARD_BG = ("#FFFFFF", "#202022")

COLOR_ACCENT = "#0A84FF"
COLOR_ACCENT_HOVER = "#0066CC"

COLOR_SUCCESS = "#30D158"
COLOR_SUCCESS_HOVER = "#24A143"

COLOR_DANGER = "#FF453A"
COLOR_DANGER_HOVER = "#D9362B"

COLOR_WARNING = "#FF9F0A"

FONT_MAIN = "Helvetica Neue"  # veya System

class GSBApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("GSB Wi-Fi Yönetimi")
        self.geometry("950x620")
        self.resizable(False, False)

        # Arka plan rengini ana renk yap
        self.configure(fg_color=COLOR_MAIN_BG)

        # Temel 2 sütunlu Layout
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)

        self.session = None
        self.current_user_info = None
        self.logout_in_progress = False
        self.keepalive_running = False
        self.attempted_tc_set = set()

        self.setup_ui()
        self.after(100, self.start_initial_check)
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

    # ================================================================
    # UI SETUP
    # ================================================================

    def setup_ui(self):
        # ── SIDEBAR ──
        self.sidebar_frame = ctk.CTkFrame(self, width=220, corner_radius=0, fg_color=COLOR_SIDEBAR_BG)
        self.sidebar_frame.grid(row=0, column=0, sticky="nsew")
        self.sidebar_frame.grid_rowconfigure(4, weight=1)

        self.logo_label = ctk.CTkLabel(
            self.sidebar_frame, text="✨ GSB Wi-Fi", 
            font=ctk.CTkFont(family=FONT_MAIN, size=22, weight="bold")
        )
        self.logo_label.grid(row=0, column=0, padx=20, pady=(30, 30))

        self.btn_nav_dashboard = ctk.CTkButton(
            self.sidebar_frame, text="Genel Bakış", corner_radius=8, height=40,
            fg_color="transparent", text_color=("gray10", "gray90"),
            hover_color=("gray80", "gray30"),
            font=ctk.CTkFont(family=FONT_MAIN, size=15),
            anchor="w", command=self.show_dashboard_tab
        )
        self.btn_nav_dashboard.grid(row=1, column=0, padx=15, pady=5, sticky="ew")

        self.btn_nav_accounts = ctk.CTkButton(
            self.sidebar_frame, text="Hesaplar", corner_radius=8, height=40,
            fg_color="transparent", text_color=("gray10", "gray90"),
            hover_color=("gray80", "gray30"),
            font=ctk.CTkFont(family=FONT_MAIN, size=15),
            anchor="w", command=self.show_accounts_tab
        )
        self.btn_nav_accounts.grid(row=2, column=0, padx=15, pady=5, sticky="ew")

        # Oturum kapat vs. en altta olacak
        self.bottom_btns_frame = ctk.CTkFrame(self.sidebar_frame, fg_color="transparent")
        self.bottom_btns_frame.grid(row=5, column=0, padx=15, pady=(10, 20), sticky="ew")
        self.bottom_btns_frame.grid_columnconfigure(0, weight=1)
        self.bottom_btns_frame.grid_columnconfigure(1, weight=1)
        
        self.logout_btn = ctk.CTkButton(
            self.bottom_btns_frame, text="Oturumu Kapat", corner_radius=8, height=40,
            fg_color=COLOR_WARNING, hover_color="#D98A09", text_color="white",
            font=ctk.CTkFont(family=FONT_MAIN, size=13, weight="bold"),
            command=self.on_logout_click
        )
        self.logout_btn.grid(row=0, column=0, padx=(0, 5), sticky="ew")
        self.logout_btn.configure(state="disabled")
        
        self.exit_btn = ctk.CTkButton(
            self.bottom_btns_frame, text="Çık", corner_radius=8, height=40,
            fg_color="#374151", hover_color="#4B5563", text_color="white",
            font=ctk.CTkFont(family=FONT_MAIN, size=13, weight="bold"),
            command=self.on_exit_click
        )
        self.exit_btn.grid(row=0, column=1, padx=(5, 0), sticky="ew")

        # ── MAIN CONTENT AREA ──
        self.main_area = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        self.main_area.grid(row=0, column=1, sticky="nsew", padx=25, pady=25)
        self.main_area.grid_rowconfigure(0, weight=1)
        self.main_area.grid_columnconfigure(0, weight=1)

        # Container for splash/login/loaders (hides sidebar when active, or covers main area)
        self.overlay_frame = ctk.CTkFrame(self.main_area, corner_radius=15, fg_color=COLOR_CARD_BG)
        
        # Dashboard ve Hesaplar frameleri
        self.dashboard_frame = ctk.CTkFrame(self.main_area, fg_color="transparent")
        self.accounts_frame = ctk.CTkFrame(self.main_area, fg_color="transparent")

        self._build_overlay()
        self._build_dashboard()
        self._build_accounts()
        
        # Başlangıçta hepsini gizle, sadece overlay/loader göster
        self.set_active_nav(self.btn_nav_dashboard)

    # ================================================================
    # OVERLAYS (Loading & Login)
    # ================================================================
    
    def _build_overlay(self):
        # YÜKLENİYOR
        self.loading_subframe = ctk.CTkFrame(self.overlay_frame, fg_color="transparent")
        self.loading_label = ctk.CTkLabel(
            self.loading_subframe, text="Kontrol ediliyor...",
            font=ctk.CTkFont(family=FONT_MAIN, size=16, weight="bold")
        )
        self.loading_label.pack(pady=20)
        self.spinner = ctk.CTkProgressBar(self.loading_subframe, mode="indeterminate", width=250, progress_color=COLOR_ACCENT)
        self.spinner.pack(pady=10)

        # GİRİŞ / İLK HESAP EKLEME
        self.login_subframe = ctk.CTkFrame(self.overlay_frame, fg_color="transparent")
        
        ctk.CTkLabel(
            self.login_subframe, text="Hoş Geldiniz",
            font=ctk.CTkFont(family=FONT_MAIN, size=32, weight="bold")
        ).pack(pady=(20, 5))
        
        ctk.CTkLabel(
            self.login_subframe, text="Başlamak için GSB Wi-Fi bilgilerinizi girin.",
            font=ctk.CTkFont(family=FONT_MAIN, size=14), text_color=("gray40", "gray60")
        ).pack(pady=(0, 30))

        self.tc_input = ctk.CTkEntry(
            self.login_subframe, placeholder_text="TC Kimlik No",
            width=320, height=50, corner_radius=10, font=ctk.CTkFont(size=15)
        )
        self.tc_input.pack(pady=10)
        
        self.pass_input = ctk.CTkEntry(
            self.login_subframe, placeholder_text="Şifre", show="*",
            width=320, height=50, corner_radius=10, font=ctk.CTkFont(size=15)
        )
        self.pass_input.pack(pady=10)

        self.status_label = ctk.CTkLabel(
            self.login_subframe, text="", font=ctk.CTkFont(size=13)
        )
        self.status_label.pack(pady=5)

        self.login_btn = ctk.CTkButton(
            self.login_subframe, text="Bağlan / Kaydet", 
            font=ctk.CTkFont(family=FONT_MAIN, size=16, weight="bold"),
            width=320, height=50, corner_radius=10, 
            fg_color=COLOR_ACCENT, hover_color=COLOR_ACCENT_HOVER,
            command=self.on_login_click
        )
        self.login_btn.pack(pady=20)
        
        # Enter tuşu ile giriş yapabilme
        self.pass_input.bind("<Return>", lambda e: self.on_login_click())
        self.tc_input.bind("<Return>", lambda e: self.pass_input.focus())

    # ================================================================
    # DASHBOARD
    # ================================================================

    def _build_dashboard(self):
        # HEADER (Name and Status)
        self.header_card = ctk.CTkFrame(self.dashboard_frame, corner_radius=15, fg_color=COLOR_CARD_BG)
        self.header_card.pack(fill="x", pady=(0, 15), ipady=15)
        
        self.user_label = ctk.CTkLabel(
            self.header_card, text="Bağlanıyor...", 
            font=ctk.CTkFont(family=FONT_MAIN, size=24, weight="bold")
        )
        self.user_label.pack(side="left", padx=25)
        
        # Sağda ufak durum hapı
        self.conn_badge = ctk.CTkFrame(self.header_card, corner_radius=20, fg_color=COLOR_SUCCESS)
        self.conn_badge.pack(side="right", padx=25, pady=0)
        self.conn_label = ctk.CTkLabel(
            self.conn_badge, text="Bağlı", font=ctk.CTkFont(size=12, weight="bold"), text_color="white"
        )
        self.conn_label.pack(padx=18, pady=6)

        # 2'Lİ GRID (KOTA ve BİLGİLER)
        self.dash_grid = ctk.CTkFrame(self.dashboard_frame, fg_color="transparent")
        self.dash_grid.pack(fill="both", expand=True)
        self.dash_grid.grid_columnconfigure(0, weight=1)
        self.dash_grid.grid_columnconfigure(1, weight=1)
        
        # KOTA KARTI
        self.quota_card = ctk.CTkFrame(self.dash_grid, corner_radius=15, fg_color=COLOR_CARD_BG)
        self.quota_card.grid(row=0, column=0, sticky="nsew", padx=(0, 7))
        
        ctk.CTkLabel(
            self.quota_card, text="Aylık İnternet Kotası",
            font=ctk.CTkFont(family=FONT_MAIN, size=18, weight="bold")
        ).pack(anchor="w", padx=25, pady=(25, 5))
        
        self.refresh_date_label = ctk.CTkLabel(
            self.quota_card, text="Yenilenme: -",
            font=ctk.CTkFont(size=12), text_color=("gray40", "gray60")
        )
        self.refresh_date_label.pack(anchor="w", padx=25, pady=(0, 10))
        
        # Dinamik kotalar için container
        self.quota_container = ctk.CTkScrollableFrame(self.quota_card, fg_color="transparent")
        self.quota_container.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        # OTURUM KARTI
        self.info_card = ctk.CTkFrame(self.dash_grid, corner_radius=15, fg_color=COLOR_CARD_BG)
        self.info_card.grid(row=0, column=1, sticky="nsew", padx=(7, 0))
        
        ctk.CTkLabel(
            self.info_card, text="Oturum Bilgileri",
            font=ctk.CTkFont(family=FONT_MAIN, size=18, weight="bold")
        ).pack(anchor="w", padx=25, pady=(25, 15))
        
        self.login_time_label = ctk.CTkLabel(
            self.info_card, text="Giriş Saati: -", font=ctk.CTkFont(size=13),
            wraplength=280, justify="left"
        )
        self.login_time_label.pack(anchor="w", padx=25, pady=(5, 10))
        
        self.location_label = ctk.CTkLabel(
            self.info_card, text="Lokasyon: -", font=ctk.CTkFont(size=13),
            wraplength=280, justify="left"
        )
        self.location_label.pack(anchor="w", padx=25, pady=(0, 10))
        
        self.service_label = ctk.CTkLabel(
            self.info_card, text="Servis: -", font=ctk.CTkFont(size=13), text_color=("gray40", "gray60")
        )
        self.service_label.pack(anchor="w", padx=25, pady=(0, 15))

        self.refresh_btn = ctk.CTkButton(
            self.info_card, text="Verileri Yenile", corner_radius=10, height=45,
            fg_color=COLOR_ACCENT, hover_color=COLOR_ACCENT_HOVER,
            font=ctk.CTkFont(family=FONT_MAIN, size=14, weight="bold"),
            command=self.on_refresh_click
        )
        self.refresh_btn.pack(side="bottom", fill="x", padx=25, pady=25)

    # ================================================================
    # ACCOUNTS
    # ================================================================

    def _build_accounts(self):
        # HEADER
        ctk.CTkLabel(
            self.accounts_frame, text="Hesaplar",
            font=ctk.CTkFont(family=FONT_MAIN, size=28, weight="bold")
        ).pack(anchor="w", pady=(0, 20))
        
        # Liste
        self.accounts_scroll = ctk.CTkScrollableFrame(self.accounts_frame, corner_radius=15, fg_color="transparent")
        self.accounts_scroll.pack(fill="both", expand=True, pady=(0, 10))

        # Ekleme Kartı (Alt taraf)
        add_frame = ctk.CTkFrame(self.accounts_frame, corner_radius=15)
        add_frame.pack(fill="x", pady=10, ipady=10)
        
        ctk.CTkLabel(
            add_frame, text="Yeni Hesap Ekle",
            font=ctk.CTkFont(family=FONT_MAIN, size=16, weight="bold")
        ).pack(anchor="w", padx=20, pady=(15, 10))
        
        input_row = ctk.CTkFrame(add_frame, fg_color="transparent")
        input_row.pack(fill="x", padx=20, pady=5)
        
        self.add_tc_input = ctk.CTkEntry(
            input_row, placeholder_text="TC Kimlik No",
            width=170, height=40, corner_radius=8
        )
        self.add_tc_input.pack(side="left", padx=(0, 8))
        
        self.add_pass_input = ctk.CTkEntry(
            input_row, placeholder_text="Şifre", show="*",
            width=150, height=40, corner_radius=8
        )
        self.add_pass_input.pack(side="left", padx=(0, 8))

        self.add_label_input = ctk.CTkEntry(
            input_row, placeholder_text="Etiket (Opsiyonel)",
            width=150, height=40, corner_radius=8
        )
        self.add_label_input.pack(side="left", padx=(0, 8))
        
        self.add_btn = ctk.CTkButton(
            input_row, text="Ekle", width=80, height=40, corner_radius=8,
            fg_color=COLOR_SUCCESS, hover_color=COLOR_SUCCESS_HOVER,
            font=ctk.CTkFont(weight="bold"),
            command=self.on_add_account
        )
        self.add_btn.pack(side="right", padx=(5, 0))
        
        self.add_feedback = ctk.CTkLabel(add_frame, text="", font=ctk.CTkFont(size=12))
        self.add_feedback.pack(anchor="w", padx=20, pady=(5, 0))
        
        # Enter tuşu ile alanlar arası geçiş ve ekleme
        self.add_tc_input.bind("<Return>", lambda e: self.add_pass_input.focus())
        self.add_pass_input.bind("<Return>", lambda e: self.add_label_input.focus())
        self.add_label_input.bind("<Return>", lambda e: self.on_add_account())

    def refresh_accounts_list(self):
        for widget in self.accounts_scroll.winfo_children():
            widget.destroy()

        accounts = get_all_accounts()
        active_idx = get_active_index()

        if not accounts:
            ctk.CTkLabel(
                self.accounts_scroll, text="Kayıtlı hesap yok.", text_color="gray"
            ).pack(pady=20)
            return

        for i, acc in enumerate(accounts):
            is_active = (i == active_idx)
            self._create_account_row(i, acc, is_active)

    def _create_account_row(self, index, acc, is_active):
        row = ctk.CTkFrame(self.accounts_scroll, corner_radius=10)
        row.pack(fill="x", pady=5, padx=5, ipady=5)

        tc_masked = acc['tc'][:3] + "****" + acc['tc'][-3:] if len(acc['tc']) > 6 else acc['tc']
        is_depleted = is_account_quota_depleted(acc)

        left_side = ctk.CTkFrame(row, fg_color="transparent")
        left_side.pack(side="left", padx=15, pady=5)
        
        title_font = ctk.CTkFont(family=FONT_MAIN, size=16, weight="bold" if is_active else "normal")
        color = COLOR_SUCCESS if is_active else ("gray10", "gray90")
        
        title_row = ctk.CTkFrame(left_side, fg_color="transparent")
        title_row.pack(anchor="w")

        ctk.CTkLabel(
            title_row, text=acc['label'], text_color=color, font=title_font
        ).pack(side="left")

        if is_depleted:
            badge = ctk.CTkFrame(title_row, corner_radius=6, fg_color="#3B2609")
            badge.pack(side="left", padx=8)
            ctk.CTkLabel(
                badge, text="⚠️ Kota Dolu (Ay Sonu Yenilenir)", 
                font=ctk.CTkFont(size=11, weight="bold"), text_color="#FF9F0A"
            ).pack(padx=6, pady=2)
        
        status_sub = f"TC: {tc_masked} {'(Aktif Bağlantı)' if is_active else ''}"
        ctk.CTkLabel(
            left_side, text=status_sub,
            font=ctk.CTkFont(size=12), text_color="gray"
        ).pack(anchor="w")

        right_side = ctk.CTkFrame(row, fg_color="transparent")
        right_side.pack(side="right", padx=15, pady=5)

        if not is_active:
            btn_txt = "Yine de Geç" if is_depleted else "Geçiş Yap"
            btn_col = ("#4B5563", "#374151") if is_depleted else COLOR_ACCENT
            btn_hov = ("#6B7280", "#4B5563") if is_depleted else COLOR_ACCENT_HOVER
            ctk.CTkButton(
                right_side, text=btn_txt, corner_radius=6, width=95, height=32,
                fg_color=btn_col, hover_color=btn_hov,
                font=ctk.CTkFont(family=FONT_MAIN, weight="bold", size=12),
                command=lambda idx=index: self.on_switch_account(idx)
            ).pack(side="left", padx=5)

        ctk.CTkButton(
            right_side, text="Sil", corner_radius=6, width=50, height=32,
            fg_color=COLOR_DANGER, hover_color=COLOR_DANGER_HOVER,
            font=ctk.CTkFont(family=FONT_MAIN, weight="bold", size=12),
            command=lambda tc=acc['tc']: self.on_remove_account(tc)
        ).pack(side="left", padx=5)

    # ================================================================
    # NAVIGATION LOGIC
    # ================================================================

    def hide_all(self):
        self.overlay_frame.grid_forget()
        self.dashboard_frame.grid_forget()
        self.accounts_frame.grid_forget()
        
        self.btn_nav_dashboard.configure(fg_color="transparent")
        self.btn_nav_accounts.configure(fg_color="transparent")

    def show_dashboard_tab(self):
        self.hide_all()
        self.btn_nav_dashboard.configure(state="normal")
        self.btn_nav_accounts.configure(state="normal")
        self.dashboard_frame.grid(row=0, column=0, sticky="nsew")
        self.set_active_nav(self.btn_nav_dashboard)

    def show_accounts_tab(self):
        self.hide_all()
        self.btn_nav_dashboard.configure(state="normal")
        self.btn_nav_accounts.configure(state="normal")
        self.refresh_accounts_list()
        self.accounts_frame.grid(row=0, column=0, sticky="nsew")
        self.set_active_nav(self.btn_nav_accounts)
        
    def set_active_nav(self, btn):
        btn.configure(fg_color=("gray85", "gray25"))

    def show_loading(self, msg):
        self.hide_all()
        self.btn_nav_dashboard.configure(state="disabled")
        self.btn_nav_accounts.configure(state="disabled")
        self.logout_btn.configure(state="disabled")
        self.login_subframe.pack_forget()
        self.loading_label.configure(text=msg)
        self.loading_subframe.pack(expand=True)
        self.overlay_frame.grid(row=0, column=0, sticky="nsew")
        self.spinner.start()

    def show_login_screen(self, msg=None):
        self.hide_all()
        self.btn_nav_dashboard.configure(state="disabled")
        self.btn_nav_accounts.configure(state="disabled")
        self.logout_btn.configure(state="disabled")
        self.spinner.stop()
        self.loading_subframe.pack_forget()
        
        accounts = get_all_accounts()
        if accounts:
            tc, _ = get_credentials()
            if tc:
                self.tc_input.delete(0, 'end')
                self.tc_input.insert(0, tc)
                pwd = get_account_password(tc)
                if pwd:
                    self.pass_input.delete(0, 'end')
                    self.pass_input.insert(0, pwd)

        if msg:
            self.status_label.configure(text=msg, text_color=COLOR_WARNING)
        else:
            self.status_label.configure(text="")
            
        self.login_subframe.pack(expand=True)
        self.overlay_frame.grid(row=0, column=0, sticky="nsew")

    # ================================================================
    # CORE LOGIC
    # ================================================================

    def start_initial_check(self):
        self.show_loading("Ağ durumu kontrol ediliyor...")
        threading.Thread(target=self.do_initial_check, daemon=True).start()

    def do_initial_check(self):
        accounts = get_all_accounts()

        if not accounts:
            self.after(0, self.show_login_screen, "Başlamak için bir hesap ekleyin.")
            return

        # Aktif hesabın kotası bu ay dolmuşsa ve kotası açık başka hesap varsa otomatik ona geç
        active_idx = get_active_index()
        if 0 <= active_idx < len(accounts):
            if is_account_quota_depleted(accounts[active_idx]):
                alt_idx = get_next_account_index(skip_quota_depleted=True)
                if alt_idx is not None:
                    set_active_index(alt_idx)

        # Doğrudan Auto-Healer'ı (Oto-yeniden bağlanma) başlat!
        self.after(0, self.start_auto_healer)

    def start_auto_healer(self):
        if getattr(self, 'healer_running', False):
            return
        self.stop_keepalive_monitor()
        self.healer_running = True
        self.run_healer_loop()

    def stop_auto_healer(self):
        self.healer_running = False

    def start_keepalive_monitor(self):
        """Bağlantı açıkken arka planda periyodik oturum kontrolü yapar."""
        if getattr(self, 'keepalive_running', False):
            return
        self.keepalive_running = True
        threading.Thread(target=self._keepalive_task, daemon=True).start()

    def stop_keepalive_monitor(self):
        self.keepalive_running = False

    def _keepalive_task(self):
        """30 saniyede bir portal oturumunu kontrol eder, koparsa auto-healer'ı tetikler."""
        while getattr(self, 'keepalive_running', False):
            for _ in range(30):
                if not getattr(self, 'keepalive_running', False):
                    return
                time.sleep(1)

            if not getattr(self, 'keepalive_running', False):
                return
            if getattr(self, 'logout_in_progress', False) or not self.session:
                return

            # Oturum hâlâ ayakta mı?
            alive = check_gsb_session_alive(self.session)
            if not alive:
                time.sleep(5)
                if not getattr(self, 'keepalive_running', False):
                    return
                if check_gsb_session_alive(self.session) or check_internet():
                    continue

                # Oturum düşmüş — auto-healer'ı devreye sok
                self.keepalive_running = False
                self.session = None
                self.after(0, self.start_auto_healer)
                return

    def run_healer_loop(self):
        if not getattr(self, 'healer_running', False):
            return
        threading.Thread(target=self._healer_task, daemon=True).start()

    def _healer_task(self):
        tc, password = get_credentials()
        if not tc:
            self.stop_auto_healer()
            self.after(0, self.show_login_screen, "Kayıtlı hesap bulunamadı.")
            return
        if not password:
            self.stop_auto_healer()
            self.after(0, self.show_login_screen, "Şifre eksik, lütfen tekrar girin.")
            return

        self.attempted_tc_set.add(tc)
        self.after(0, self.set_dashboard_reconnecting_state)
        result = connect_and_fetch(tc, password)
        
        # Eğer manuel olarak bu sırada çıkış yapıldıysa veya durdurulduysa işlemi iptal et
        if not getattr(self, 'healer_running', False):
            return

        if result['status'] == 'connected':
            self.stop_auto_healer()
            self.session = result['session']
            info = result['user_info']
            if info and info.get('Kullanıcı'):
                update_account_label(tc, info['Kullanıcı'])
            
            # Kota kontrolü — bitmiş mi?
            if info and is_quota_depleted(info):
                mark_account_quota_depleted(tc, True)
                self.after(0, self.refresh_accounts_list)
                next_idx = get_next_account_index(skip_quota_depleted=True)
                accounts = get_all_accounts()
                if next_idx is not None and next_idx < len(accounts) and accounts[next_idx]['tc'] not in self.attempted_tc_set:
                    next_name = accounts[next_idx].get('label', accounts[next_idx]['tc'][:3] + '****')
                    self.after(0, lambda: self.show_loading(f"Kota bitti! {next_name} hesabına geçiliyor..."))
                    try:
                        logout(self.session)
                    except Exception:
                        pass
                    self.session = None
                    set_active_index(next_idx)
                    self.after(1000, self.start_auto_healer)
                    return
                else:
                    self.attempted_tc_set.clear()
                    self.after(0, self.populate_dashboard, info)
                    self.after(500, lambda: self.update_healer_status(
                        "⚠️ Tüm hesapların kotası dolmuş! (Ay başında yenilenir)"
                    ))
                    return
            else:
                # Kota tükenmemiş, normalse önceki kota doldu etiketini kaldır
                mark_account_quota_depleted(tc, False)
                self.after(0, self.refresh_accounts_list)
            
            self.attempted_tc_set.clear()
            self.after(0, self.populate_dashboard, info)
        else:
            # Login başarısız (şifre yanlış) ise diğer hesaba geçmeyi dene
            if result.get('error_type') in ('auth_error', 'wrong_password') or 'TC' in result.get('message', ''):
                next_idx = get_next_account_index(skip_quota_depleted=True)
                accounts = get_all_accounts()
                if next_idx is not None and next_idx < len(accounts) and accounts[next_idx]['tc'] not in self.attempted_tc_set:
                    next_name = accounts[next_idx].get('label', accounts[next_idx]['tc'][:3] + '****')
                    self.after(0, lambda: self.show_loading(f"Şifre hatalı! {next_name} hesabına geçiliyor..."))
                    set_active_index(next_idx)
                    if getattr(self, 'healer_running', False):
                        self.after(1500, self.run_healer_loop)
                    return
                
                self.attempted_tc_set.clear()
                self.stop_auto_healer()
                self.after(0, self.show_login_screen, "TC veya şifre hatalı! Bilgileri düzenleyin.")
                return
            
            # Ağ sorunu veya drop yedi (hemen tekrar deneyecek)
            msg = result.get('message', 'Bağlantı kurulamadı')
            self.after(0, lambda: self.update_healer_status(msg))
            
            # 5 saniye bekle ve yine dene
            if getattr(self, 'healer_running', False):
                self.after(5000, self.run_healer_loop)

    def set_dashboard_reconnecting_state(self):
        self.show_dashboard_tab()
        self.user_label.configure(text="Bağlantı Aranıyor...")
        self.conn_label.configure(text="Bekliyor")
        self.conn_badge.configure(fg_color=COLOR_WARNING)
        self.location_label.configure(text="")
        self.login_time_label.configure(text="")
        self.service_label.configure(text="")
        
        # Dinamik kotaları temizle
        for widget in self.quota_container.winfo_children():
            widget.destroy()
        self.refresh_date_label.configure(text="")
        self.logout_btn.configure(state="disabled")
        self.refresh_btn.configure(state="disabled")

    def update_healer_status(self, msg):
        if getattr(self, 'healer_running', False):
            # Mesajı kısa tut, taşmasın
            short_msg = msg[:60] + '...' if len(msg) > 60 else msg
            self.location_label.configure(text=f"{short_msg}\n(Yeniden denenecek...)")

    def on_login_click(self):
        tc = self.tc_input.get().strip()
        pwd = self.pass_input.get().strip()
        if not tc or not pwd:
            self.status_label.configure(text="TC ve şifre gerekli.", text_color=COLOR_DANGER)
            return
        
        # TC Validasyonu
        valid, msg = validate_tc(tc)
        if not valid:
            self.status_label.configure(text=msg, text_color=COLOR_DANGER)
            return

        add_account(tc, pwd)
        accounts = get_all_accounts()
        for i, acc in enumerate(accounts):
            if acc['tc'] == tc:
                set_active_index(i)
                break

        self.hide_all()
        # Giriş yapıldığı an auto-healer başlasın, bu sayede manuel bekleme olmaz
        self.start_auto_healer()

    def populate_dashboard(self, user_info):
        self.spinner.stop()
        self.current_user_info = user_info
        
        # Oturum açık olduğu için Dashboard'u göster
        self.show_dashboard_tab()

        if user_info:
            self.user_label.configure(text=user_info.get('Kullanıcı', '-'))
            self.location_label.configure(text=f"Lokasyon: {user_info.get('Lokasyon', '-')}")
            self.conn_label.configure(text="Bağlı")
            self.conn_badge.configure(fg_color=COLOR_SUCCESS)

            # Kotaları dinamik oluştur (Sosyal Medya, Toplam vs. hepsi için)
            for widget in self.quota_container.winfo_children():
                widget.destroy()

            packages = user_info.get('Paketler', [])
            
            # Eğer paketler boşsa (eski veya basit mod), tekli gösterim için fake bir paket oluştur
            if not packages:
                packages = [{
                    'Paket Tipi': 'Toplam',
                    'Toplam Kota (MB)': user_info.get('Toplam Kota (MB)', user_info.get('Total Quota (MB)', 0)),
                    'Toplam Kalan Kota (MB)': user_info.get('Toplam Kalan Kota (MB)', user_info.get('Total Remaining Quota (MB)', 0))
                }]
            
            for pkg in packages:
                # Sadece kotası olan paketleri göster (Session Time gibi tabloları atla)
                if 'Toplam Kota (MB)' not in pkg and 'Total Quota (MB)' not in pkg:
                    continue
                
                # Türkçe mi İngilizce mi kontrol et, uygun ismi al
                ptype = pkg.get('Paket Tipi', pkg.get('Package Type', 'Paket'))
                
                # Eğer İngilizce ise isimleri Türkçeleştir (ör. Social Media -> Sosyal Medya)
                if ptype.lower() == 'social media':
                    ptype = 'Sosyal Medya'
                elif ptype.lower() == 'total':
                    ptype = 'Toplam'
                elif ptype.lower() == 'education':
                    ptype = 'Eğitim'
                
                total_raw = pkg.get('Toplam Kota (MB)', pkg.get('Total Quota (MB)', 0))
                rem_raw = pkg.get('Toplam Kalan Kota (MB)', pkg.get('Total Remaining Quota (MB)', 0))
                
                try:
                    total = float(total_raw)
                    rem = float(rem_raw)
                    used = total - rem
                    progress = (used / total) if total > 0 else 0
                except (ValueError, TypeError):
                    total, rem, used, progress = 0, 0, 0, 0

                pkg_frame = ctk.CTkFrame(self.quota_container, fg_color="transparent")
                pkg_frame.pack(fill="x", pady=(0, 15))
                
                # Paket Başlığı
                ctk.CTkLabel(
                    pkg_frame, text=ptype,
                    font=ctk.CTkFont(family=FONT_MAIN, size=14, weight="bold")
                ).pack(anchor="w", padx=10, pady=(0, 5))
                
                # Progress Bar
                bar = ctk.CTkProgressBar(pkg_frame, height=12, corner_radius=6, fg_color="#3A3A3C")
                if progress > 0.9:
                    bar.configure(progress_color=COLOR_DANGER)
                elif progress > 0.7:
                    bar.configure(progress_color=COLOR_WARNING)
                else:
                    bar.configure(progress_color=COLOR_SUCCESS)
                bar.pack(fill="x", padx=10, pady=(0, 5))
                bar.set(progress)
                
                # Değerler
                def fmt(mb):
                    return f"{mb/1024:.2f} GB" if mb >= 1024 else f"{(mb):.0f} MB"
                
                val_frame = ctk.CTkFrame(pkg_frame, fg_color="transparent")
                val_frame.pack(fill="x", padx=10)
                
                ctk.CTkLabel(val_frame, text=f"Kullanılan: {fmt(used)}", font=ctk.CTkFont(size=11), text_color=("gray40", "gray60")).pack(side="left")
                ctk.CTkLabel(val_frame, text=f"Kalan: {fmt(rem)}", font=ctk.CTkFont(size=11, weight="bold")).pack(side="right")

            self.refresh_date_label.configure(
                text=f"Yenilenme: {user_info.get('Sona Erme Tarihi', user_info.get('Next Refresh Date', '-'))}"
            )
            self.login_time_label.configure(
                text=f"Giriş Saati: {user_info.get('Login Zamanı', user_info.get('Login Time', user_info.get('Son Giriş', user_info.get('Last Login', '-'))))}"
            )
            self.service_label.configure(
                text=f"Servis: {user_info.get('Internet Servisi', user_info.get('Internet Service', 'GSB-WiFi'))}"
            )

            if is_quota_depleted(user_info):
                self.after(500, self.try_auto_switch)

        self.logout_btn.configure(state="normal", text="Oturumu Kapat")
        self.refresh_btn.configure(state="normal", text="Sistemi Yenile")
        self.start_keepalive_monitor()

    # ================================================================
    # YENİLE / ÇIKIŞ / HESAP DEĞİŞTİRME
    # ================================================================

    def on_refresh_click(self):
        if self.logout_in_progress:
            return

        if not self.session:
            self.refresh_btn.configure(state="disabled", text="Bağlanıyor...")
            threading.Thread(target=self.do_reconnect, daemon=True).start()
            return
            
        self.refresh_btn.configure(state="disabled", text="Yenileniyor...")
        threading.Thread(target=self.do_refresh, daemon=True).start()

    def do_reconnect(self):
        tc, pwd = get_credentials()
        if not tc or not pwd:
            self.after(0, lambda: self.refresh_btn.configure(state="normal", text="Tekrar Bağlan"))
            return
            
        self.after(0, self.start_auto_healer)

    def do_refresh(self):
        info = fetch_user_info(self.session)
        if getattr(self, 'logout_in_progress', False):
            return
            
        if info:
            self.after(0, self.populate_dashboard, info)
        else:
            # Eğer portal yanıt vermezse veya oturum düşmüşse, auto-healer başlasın!
            self.session = None
            self.after(0, self.start_auto_healer)

    def on_logout_click(self):
        if self.logout_in_progress:
            return

        self.logout_in_progress = True
        self.stop_auto_healer()
        self.stop_keepalive_monitor()
        self.logout_btn.configure(state="disabled", text="Kapatılıyor...")
        self.refresh_btn.configure(state="disabled", text="Kapatılıyor...")
        threading.Thread(target=self.do_logout, daemon=True).start()

    def do_logout(self):
        session_to_close = self.session
        self.session = None

        try:
            result = logout(session_to_close)
        except Exception as e:
            result = {'success': False, 'message': f'Çıkış sırasında hata: {e}'}

        self.session = None

        msg = result.get('message', 'Bağlantı Kesildi') if result['success'] else result.get('message', 'Hata, tekrar deneyin.')
        color = COLOR_WARNING if result['success'] else COLOR_DANGER
        
        def update_ui():
            self.logout_in_progress = False
            self.user_label.configure(text="Bağlı Değil")
            self.location_label.configure(text=msg)
            self.conn_label.configure(text="Kapalı")
            self.conn_badge.configure(fg_color=color)
            
            # Dinamik kota widget'larını temizle
            for widget in self.quota_container.winfo_children():
                widget.destroy()
            
            self.refresh_date_label.configure(text="")
            self.login_time_label.configure(text="")
            self.service_label.configure(text="")
            
            self.logout_btn.configure(state="disabled", text="Oturum Kapalı")
            self.refresh_btn.configure(state="normal", text="Tekrar Bağlan")
        
        self.after(0, update_ui)

    def on_add_account(self):
        tc = self.add_tc_input.get().strip()
        pwd = self.add_pass_input.get().strip()
        label = self.add_label_input.get().strip()

        if not tc or not pwd:
            self.add_feedback.configure(text="TC ve şifre gerekli.", text_color=COLOR_DANGER)
            self._clear_feedback_later()
            return
        
        # TC Validasyonu
        valid, msg = validate_tc(tc)
        if not valid:
            self.add_feedback.configure(text=f"❌ {msg}", text_color=COLOR_DANGER)
            self._clear_feedback_later()
            return

        is_new = add_account(tc, pwd, label or tc)
        if is_new:
            self.add_feedback.configure(text="✅ Hesap eklendi!", text_color=COLOR_SUCCESS)
        else:
            self.add_feedback.configure(text="ℹ️ Hesap güncellendi.", text_color="gray")

        self.add_tc_input.delete(0, 'end')
        self.add_pass_input.delete(0, 'end')
        self.add_label_input.delete(0, 'end')
        self.refresh_accounts_list()
        self._clear_feedback_later()

    def _clear_feedback_later(self):
        """Feedback mesajını 3 saniye sonra temizle."""
        self.after(3000, lambda: self.add_feedback.configure(text=""))

    def on_remove_account(self, tc):
        accounts = get_all_accounts()
        active_idx = get_active_index()
        active_tc = accounts[active_idx]['tc'] if accounts and active_idx < len(accounts) else None
        
        is_active = (tc == active_tc)
        old_session = self.session if is_active else None
        
        if is_active:
            self.stop_auto_healer()
            self.stop_keepalive_monitor()
            self.session = None
            self.current_user_info = None

        remove_account(tc)
        self.refresh_accounts_list()
        
        if is_active:
            remaining = get_all_accounts()
            if remaining:
                new_idx = get_active_index()
                new_acc = remaining[new_idx]
                new_name = new_acc.get('label', new_acc['tc'][:3] + '****')
                self.show_loading(f"Aktif hesap silindi. {new_name} hesabına geçiliyor...")
                
                def do_logout_and_switch():
                    if old_session:
                        try:
                            logout(old_session)
                        except Exception:
                            pass
                    self.after(500, self.start_auto_healer)
                    
                threading.Thread(target=do_logout_and_switch, daemon=True).start()
            else:
                self.show_loading("Aktif hesap silindi. Oturum kapatılıyor...")
                
                def do_logout_and_show_login():
                    if old_session:
                        try:
                            logout(old_session)
                        except Exception:
                            pass
                    self.after(0, lambda: self.show_login_screen("Aktif hesap silindi. Yeni hesap ekleyin."))
                    
                threading.Thread(target=do_logout_and_show_login, daemon=True).start()

    def on_switch_account(self, index):
        set_active_index(index)
        self.show_loading("Hesap değiştiriliyor...")
        threading.Thread(target=self.do_switch, daemon=True).start()

    def do_switch(self):
        # Durum kargaşası yaratmamak için varsa önceki healer ve keepalive loop'u durdur!
        self.stop_auto_healer()
        self.stop_keepalive_monitor()
        
        if getattr(self, 'session', None):
            try:
                logout(self.session)
            except Exception:
                pass
            self.session = None

        tc, pwd = get_credentials()
        if not tc or not pwd:
            self.after(0, self.show_login_screen, "Hesap bilgileri eksik.")
            return

        # Doğrudan auto-healer'a emanet et
        self.after(0, self.start_auto_healer)

    def try_auto_switch(self):
        tc, _ = get_credentials()
        if tc:
            mark_account_quota_depleted(tc, True)
            self.refresh_accounts_list()

        next_idx = get_next_account_index(skip_quota_depleted=True)
        if next_idx is None:
            self.update_healer_status("⚠️ Tüm hesapların kotası dolmuş! (Ay başında yenilenir)")
            return

        accounts = get_all_accounts()
        next_name = accounts[next_idx].get('label', accounts[next_idx]['tc'][:3] + '****')

        self.show_loading(f"Kota bitti! {next_name} hesabına geçiliyor...")
        set_active_index(next_idx)
        threading.Thread(target=self.do_switch, daemon=True).start()

    def on_closing(self):
        # X tuşuna basınca: oturum kapatılmadan sadece uygulama kapanır
        self.stop_auto_healer()
        self.stop_keepalive_monitor()
        self.destroy()

    def on_exit_click(self):
        """Sol alttaki 'Çık' butonu: oturumu açık bırakarak uygulamayı kapat."""
        self.stop_auto_healer()
        self.stop_keepalive_monitor()
        self.destroy()


def main():
    app = GSBApp()
    app.mainloop()

if __name__ == "__main__":
    main()
