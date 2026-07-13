# ⚙️ JARVIS — MARK XLVIII (Community Fork)

**🌐 Language / Ngôn ngữ:  [English](#english)  ·  [Tiếng Việt](#tiếng-việt)**

> 🙏 Original project "MARK XLVIII" created by **[FatihMakes](https://www.youtube.com/@FatihMakes)**.
> Dự án gốc "MARK XLVIII" được tạo bởi **[FatihMakes](https://www.youtube.com/@FatihMakes)**.
> Licensed **CC BY-NC 4.0** — free, non-commercial, attribution required.

---

<a name="english"></a>
## 🇬🇧 English

### A real-time, voice-first personal AI assistant for your desktop

A real-time voice AI that can hear, see, understand, and control your computer. Built on the
**Google Gemini Live API** for native audio streaming — no subscriptions, bring your own free
Gemini API key. This is a community fork of FatihMakes' original, with a floating arc-reactor
HUD, an API cost meter, Vietnamese relationship-aware speech, a first-run setup wizard, and more.

### ✨ Highlights of this fork

| Area | What's new |
|---|---|
| 🌀 **Mini arc-reactor** | Shrink the HUD to a transparent, always-on-top, draggable **and resizable** glowing reactor that floats over your desktop and pulses/changes colour as JARVIS listens & speaks. Drag the ring or scroll to resize; double-click to restore. |
| 🧙 **First-run setup wizard** | 3-step onboarding: your name → how JARVIS should address you → Gemini API key. Re-run any time from the tray → **Reconfigure…**. |
| 💰 **API cost meter** | Live on-HUD spend tracker: **Today / Monthly estimate / Session / Total** (USD), persisted across restarts. |
| 🛡️ **Soft budget guard** | Set a daily/monthly cap by voice; the meter turns amber → red as you approach it, with one gentle heads-up per day. **Never blocks.** |
| 🎵 **Music** | "Play my liked music" opens YouTube Music in your logged-in browser; **transport controls** by voice (pause, next, previous, volume, mute) — works even in mini mode. |
| 🇻🇳 **Vietnamese relationship profiles** | Culturally-correct pronouns, tone, and sentence particles (the "ạ" rule). Switch by voice ("từ giờ xưng em gọi anh"). |
| ⌨️ **Global hotkey** | **Ctrl+Alt+J** summons / dismisses JARVIS from anywhere — no wake word needed. |
| 🔔 **Opt-in check-ins** | Periodic silence-break pings are OFF by default; toggle from the tray. |
| 🚀 **Calmer startup** | Wake-word model loads off the UI thread (no freeze); greeting varies every session. |
| 🖥️ **Desktop packaging** | System tray, single-instance, `%APPDATA%` storage, file logs, PyInstaller build + Windows installer. |

### 🚀 Core capabilities (from the original)

Real-time multilingual voice · system control (apps, volume, brightness, WiFi, power) ·
autonomous multi-step tasks · screen & webcam vision · persistent memory · voice + keyboard ·
morning briefing (time, weather, news) · CPU/RAM/GPU/temperature telemetry · weather ·
multi-mode web search · OS-native reminders · flight finder · file Q&A · code helper ·
browser control · messaging · YouTube · desktop control · silent language auto-detection.

### ⚡ Quick start (run from source)

```bash
git clone <your-fork-url>
cd JARVIS
python -m venv .venv && .venv\Scripts\activate      # Windows
pip install -r requirements.txt
python main.py
```

On first launch, the **setup wizard** asks for your name, how you'd like to be addressed, and
your **free Gemini API key** (get one at https://aistudio.google.com/apikey). Your key and
memory are stored privately under `%APPDATA%\JARVIS` — nothing is hard-coded or shared.

### 📦 Install as a desktop app (Windows)

```powershell
.\build.ps1                 # 1. build → dist\JARVIS\JARVIS.exe
iscc installer.iss          # 2. package → Output\JARVIS-Setup.exe  (needs Inno Setup)
```

Creates Start-Menu/desktop shortcuts, an optional "start on login" entry, and an uninstaller.
Your data in `%APPDATA%\JARVIS` survives reinstalls.

### 📋 Requirements

| Requirement | Details |
| --- | --- |
| **OS** | Windows 10/11 (macOS/Linux for source runs) |
| **Python** | 3.11 / 3.12 (for source) |
| **Microphone** | Required |
| **API Key** | Free Gemini key — entered in the setup wizard |
| **Optional** | LibreHardwareMonitor in `tools/` for temperatures |

### ⚠️ License

**CC BY-NC 4.0** — free to use, share, and adapt for **non-commercial** purposes, **with
attribution** to FatihMakes and this fork. See [`LICENSE`](./LICENSE).

### 👤 Credits

- **Original creator — [FatihMakes](https://www.youtube.com/@FatihMakes)** ([Instagram](https://www.instagram.com/fatihmakes)). Please star and support the original project.
- **Fork & extensions —** _add your GitHub handle here._

---

<a name="tiếng-việt"></a>
## 🇻🇳 Tiếng Việt

### Trợ lý AI cá nhân, ưu tiên giọng nói, chạy thời gian thực trên máy tính của bạn

Một AI giọng nói thời gian thực có thể nghe, nhìn, hiểu và điều khiển máy tính của bạn. Được xây
dựng trên **Google Gemini Live API** để truyền âm thanh gốc — không thuê bao, bạn tự dùng khóa
API Gemini miễn phí của mình. Đây là bản fork cộng đồng từ dự án gốc của FatihMakes, bổ sung
lò phản ứng hồ quang thu nhỏ nổi trên màn hình, đồng hồ đo chi phí API, cách xưng hô tiếng Việt
theo quan hệ, trình hướng dẫn cài đặt lần đầu, và nhiều tính năng khác.

### ✨ Điểm nổi bật của bản fork này

| Hạng mục | Tính năng mới |
|---|---|
| 🌀 **Lò phản ứng thu nhỏ** | Thu nhỏ HUD thành một lò phản ứng phát sáng, nền trong suốt, luôn nổi trên cùng, **kéo di chuyển và đổi kích thước được**, nhấp nháy/đổi màu khi JARVIS nghe và nói. Kéo vành ngoài hoặc lăn chuột để đổi cỡ; nhấp đúp để phóng to lại. |
| 🧙 **Trình cài đặt lần đầu** | 3 bước: tên của bạn → cách JARVIS xưng hô với bạn → khóa API Gemini. Chạy lại bất cứ lúc nào từ khay hệ thống → **Reconfigure…**. |
| 💰 **Đồng hồ đo chi phí API** | Theo dõi chi tiêu ngay trên HUD: **Hôm nay / Ước tính tháng / Phiên / Tổng** (USD), lưu qua các lần khởi động. |
| 🛡️ **Bảo vệ ngân sách (mềm)** | Đặt hạn mức ngày/tháng bằng giọng nói; đồng hồ chuyển vàng → đỏ khi gần chạm hạn, nhắc nhẹ một lần mỗi ngày. **Không bao giờ chặn.** |
| 🎵 **Nhạc** | "Phát nhạc yêu thích của tôi" mở YouTube Music trong trình duyệt đã đăng nhập; **điều khiển phát** bằng giọng nói (tạm dừng, bài kế, bài trước, âm lượng, tắt tiếng) — hoạt động cả ở chế độ thu nhỏ. |
| 🇻🇳 **Hồ sơ quan hệ tiếng Việt** | Đại từ, giọng điệu và tiểu từ cuối câu đúng văn hoá (quy tắc "ạ"). Đổi bằng giọng nói ("từ giờ xưng em gọi anh"). |
| ⌨️ **Phím tắt toàn cục** | **Ctrl+Alt+J** gọi / tắt JARVIS từ bất cứ đâu — không cần từ đánh thức. |
| 🔔 **Chủ động: tuỳ chọn bật** | Các lời nhắc khi im lặng đã TẮT mặc định; bật/tắt từ khay hệ thống. |
| 🚀 **Khởi động mượt hơn** | Mô hình từ đánh thức tải ngoài luồng giao diện (không treo); lời chào thay đổi mỗi phiên. |
| 🖥️ **Đóng gói ứng dụng** | Khay hệ thống, chạy một bản duy nhất, lưu ở `%APPDATA%`, ghi log ra tệp, dựng bằng PyInstaller + bộ cài Windows. |

### 🚀 Tính năng cốt lõi (từ bản gốc)

Giọng nói đa ngôn ngữ thời gian thực · điều khiển hệ thống (ứng dụng, âm lượng, độ sáng, WiFi,
nguồn) · tác vụ nhiều bước tự động · thị giác màn hình & webcam · bộ nhớ lâu dài · nhập bằng
giọng nói + bàn phím · bản tin buổi sáng (giờ, thời tiết, tin tức) · giám sát CPU/RAM/GPU/nhiệt
độ · thời tiết · tìm kiếm web nhiều chế độ · nhắc việc theo hệ điều hành · tìm chuyến bay · hỏi
đáp tệp · trợ giúp lập trình · điều khiển trình duyệt · nhắn tin · YouTube · điều khiển màn hình
nền · tự nhận diện ngôn ngữ.

### ⚡ Bắt đầu nhanh (chạy từ mã nguồn)

```bash
git clone <đường-dẫn-fork-của-bạn>
cd JARVIS
python -m venv .venv && .venv\Scripts\activate      # Windows
pip install -r requirements.txt
python main.py
```

Lần chạy đầu, **trình cài đặt** sẽ hỏi tên bạn, cách bạn muốn được xưng hô, và **khóa API Gemini
miễn phí** (lấy tại https://aistudio.google.com/apikey). Khóa và bộ nhớ của bạn được lưu riêng
tư trong `%APPDATA%\JARVIS` — không có gì bị mã hoá cứng hay chia sẻ ra ngoài.

### 📦 Cài đặt như một ứng dụng (Windows)

```powershell
.\build.ps1                 # 1. dựng → dist\JARVIS\JARVIS.exe
iscc installer.iss          # 2. đóng gói → Output\JARVIS-Setup.exe  (cần Inno Setup)
```

Tạo lối tắt Start-Menu/màn hình nền, tuỳ chọn "khởi động cùng Windows", và bộ gỡ cài đặt. Dữ
liệu trong `%APPDATA%\JARVIS` được giữ lại qua các lần cài lại.

### 📋 Yêu cầu

| Yêu cầu | Chi tiết |
| --- | --- |
| **Hệ điều hành** | Windows 10/11 (macOS/Linux khi chạy từ mã nguồn) |
| **Python** | 3.11 / 3.12 (khi chạy từ mã nguồn) |
| **Micro** | Bắt buộc |
| **Khóa API** | Khóa Gemini miễn phí — nhập trong trình cài đặt |
| **Tuỳ chọn** | LibreHardwareMonitor trong `tools/` để đọc nhiệt độ |

### ⚠️ Giấy phép

**CC BY-NC 4.0** — được tự do sử dụng, chia sẻ và chỉnh sửa cho mục đích **phi thương mại**, kèm
**ghi công** cho FatihMakes và bản fork này. Xem [`LICENSE`](./LICENSE).

### 👤 Ghi công

- **Tác giả gốc — [FatihMakes](https://www.youtube.com/@FatihMakes)** ([Instagram](https://www.instagram.com/fatihmakes)). Hãy star và ủng hộ dự án gốc.
- **Fork & mở rộng —** _thêm tên GitHub của bạn ở đây._

---

> Built with Google Gemini Live · Fan homage to Marvel's JARVIS. Not affiliated with Marvel or Apple.
