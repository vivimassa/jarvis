# ⚙️ JARVIS — MARK XLVIII (Community Fork)

**🌐 Language / Ngôn ngữ:  [English](#english)  ·  [Tiếng Việt](#tiếng-việt)**

> 🙏 Original project "MARK XLVIII" created by **[FatihMakes](https://www.youtube.com/@FatihMakes)**.
> Dự án gốc "MARK XLVIII" được phát triển bởi **[FatihMakes](https://www.youtube.com/@FatihMakes)**.
> Licensed **CC BY-NC 4.0** — free, non-commercial, attribution required.

---

<a id="english"></a>
## 🇬🇧 English

### A real-time, voice-first personal AI assistant for your desktop

A real-time voice AI that can hear, see, understand, and control your computer. Built on the **Google Gemini Live API** for native audio streaming — no subscriptions, bring your own free Gemini API key. This is a community fork of FatihMakes' original, with a floating arc-reactor HUD, an API cost meter, Vietnamese relationship-aware speech, a first-run setup wizard, and more.

### ✨ Highlights of this fork

- **🌀 Mini arc-reactor** — Shrink the HUD to a transparent, always-on-top, draggable and resizable glowing reactor that floats over your desktop and pulses/changes colour as JARVIS listens & speaks. Drag the ring or scroll to resize; double-click to restore.
- **🧙 First-run setup wizard** — 3-step onboarding: your name → how JARVIS should address you → Gemini API key. Re-run any time from the tray → **Reconfigure…**.
- **💰 API cost meter** — Live on-HUD spend tracker: Today / Monthly estimate / Session / Total (USD), persisted across restarts.
- **🛡️ Soft budget guard** — Set a daily/monthly cap by voice; the meter turns amber → red as you approach it, with one gentle heads-up per day. Never blocks.
- **🎵 Music** — "Play my liked music" opens YouTube Music in your logged-in browser; transport controls by voice (pause, next, previous, volume, mute) — works even in mini mode.
- **🇻🇳 Vietnamese relationship profiles** — Culturally-correct pronouns, tone, and sentence particles (the "ạ" rule). Switch by voice ("từ giờ xưng em gọi anh").
- **⌨️ Global hotkey** — Ctrl+Alt+J summons / dismisses JARVIS from anywhere — no wake word needed.
- **🔔 Opt-in check-ins** — Periodic silence-break pings are OFF by default; toggle from the tray.
- **🚀 Calmer startup** — Wake-word model loads off the UI thread (no freeze); greeting varies every session.
- **🖥️ Desktop packaging** — System tray, single-instance, `%APPDATA%` storage, file logs, PyInstaller build + Windows installer.

### 🚀 Core capabilities (from the original)

Real-time multilingual voice · system control (apps, volume, brightness, WiFi, power) · autonomous multi-step tasks · screen & webcam vision · persistent memory · voice + keyboard · morning briefing (time, weather, news) · CPU/RAM/GPU/temperature telemetry · weather · multi-mode web search · OS-native reminders · flight finder · file Q&A · code helper · browser control · messaging · YouTube · desktop control · silent language auto-detection.

### ⚡ Quick start (run from source)

```bash
git clone https://github.com/vivimassa/jarvis
cd JARVIS
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

On first launch, the setup wizard asks for your name, how you'd like to be addressed, and your free Gemini API key (get one at https://aistudio.google.com/apikey). Your key and memory are stored privately under `%APPDATA%\JARVIS` — nothing is hard-coded or shared.

### 📦 Install as a desktop app (Windows)

```powershell
.\build.ps1                 # 1. build -> dist\JARVIS\JARVIS.exe
iscc installer.iss          # 2. package -> Output\JARVIS-Setup.exe  (needs Inno Setup)
```

Creates Start-Menu/desktop shortcuts, an optional "start on login" entry, and an uninstaller. Your data in `%APPDATA%\JARVIS` survives reinstalls.

### 📋 Requirements

| Requirement | Details |
| --- | --- |
| **OS** | Windows 10/11 (macOS/Linux for source runs) |
| **Python** | 3.11 / 3.12 (for source) |
| **Microphone** | Required |
| **API Key** | Free Gemini key — entered in the setup wizard |
| **Optional** | LibreHardwareMonitor in `tools/` for temperatures |

### ⚠️ License

**CC BY-NC 4.0** — free to use, share, and adapt for non-commercial purposes, with attribution to FatihMakes and this fork. See [`LICENSE`](./LICENSE).

### 👤 Credits

- **Original creator — [FatihMakes](https://www.youtube.com/@FatihMakes)** ([Instagram](https://www.instagram.com/fatihmakes)). Please star and support the original project.
- **Fork & extensions —** https://github.com/vivimassa/jarvis

---

<a id="tiếng-việt"></a>
## 🇻🇳 Tiếng Việt

### Trợ lý AI cá nhân tương tác giọng nói thời gian thực trên máy tính

Một AI giọng nói hoạt động theo thời gian thực với khả năng nghe, nhìn, thấu hiểu và điều khiển máy tính của bạn. Dự án được xây dựng dựa trên **Google Gemini Live API** nhằm tối ưu hóa khả năng truyền tải âm thanh (audio streaming) gốc — không tốn chi phí duy trì, hoạt động hoàn toàn bằng khóa Gemini API miễn phí của riêng bạn.

Đây là một bản fork cộng đồng từ dự án gốc của FatihMakes, được bổ sung giao diện HUD lò phản ứng hồ quang (arc-reactor) dạng nổi, đồng hồ theo dõi chi phí API, mô hình xưng hô tiếng Việt tự nhiên theo ngữ cảnh quan hệ, trình hướng dẫn thiết lập lần đầu và nhiều tính năng mở rộng khác.

### ✨ Các điểm cải tiến nổi bật trên bản fork này

- **🌀 Lò phản ứng Arc thu nhỏ** — Thu gọn HUD thành một lò phản ứng phát sáng dạng nổi (floating UI), nền trong suốt, luôn hiển thị trên cùng (always-on-top) và có thể kéo thả hoặc thay đổi kích thước. Lò phản ứng sẽ nhấp nháy/đổi màu theo trạng thái lắng nghe hoặc phản hồi của JARVIS. Kéo phần viền hoặc cuộn chuột để chỉnh cỡ; nhấp đúp để khôi phục kích thước gốc.
- **🧙 Trình thiết lập lần đầu (Setup Wizard)** — Quy trình cấu hình nhanh qua 3 bước: Tên của bạn → Cách JARVIS xưng hô với bạn → Khóa Gemini API. Bạn có thể thay đổi lại bất cứ lúc nào từ khay hệ thống (System Tray) → **Reconfigure…**.
- **💰 Theo dõi chi phí API** — Đồng hồ đo chi phí hiển thị trực tiếp trên giao diện HUD: Hôm nay / Ước tính tháng / Phiên hiện tại / Tổng chi phí (USD), dữ liệu được lưu trữ tự động sau mỗi lần khởi động lại.
- **🛡️ Hạn mức ngân sách linh hoạt** — Đặt hạn mức chi tiêu theo ngày hoặc theo tháng trực tiếp bằng giọng nói. Hệ thống sẽ đổi màu cảnh báo từ Vàng → Đỏ khi tiến gần giới hạn và nhắc nhở nhẹ nhàng một lần mỗi ngày. Tuyệt đối không chặn hoặc ngắt quãng tác vụ của bạn.
- **🎵 Trình điều khiển nhạc** — Lệnh thoại "Play my liked music" sẽ tự động mở YouTube Music trên trình duyệt đã đăng nhập. Hỗ trợ đầy đủ các lệnh điều khiển (tạm dừng, chuyển bài, quay lại, tăng giảm âm lượng, tắt tiếng) — hoạt động mượt mà ngay cả ở chế độ thu nhỏ.
- **🇻🇳 Cấu hình xưng hô tiếng Việt** — Hệ thống đại từ nhân xưng, sắc thái giọng điệu và các tiểu từ cuối câu được tối ưu hóa theo đúng văn hóa Việt Nam (bao gồm quy tắc dùng từ "ạ"). Cho phép thay đổi linh hoạt bằng khẩu lệnh (Ví dụ: "từ giờ xưng em gọi anh").
- **⌨️ Phím tắt toàn cục (Global Hotkey)** — Sử dụng tổ hợp phím Ctrl+Alt+J để kích hoạt hoặc ẩn nhanh JARVIS từ bất kỳ đâu — không cần gọi câu lệnh kích hoạt (wake word).
- **🔔 Tùy chọn tương tác chủ động** — Tính năng chủ động bắt chuyện hoặc nhắc nhở sau một khoảng thời gian im lặng được TẮT theo mặc định; bạn có thể bật/tắt nhanh từ menu khay hệ thống.
- **🚀 Khởi động mượt mà** — Tiến trình tải mô hình nhận diện câu lệnh kích hoạt (wake-word model) được tách biệt khỏi luồng giao diện (UI thread), giúp ứng dụng không bị đóng băng khi khởi chạy. Lời chào cũng được làm mới ngẫu nhiên theo từng phiên làm việc.
- **🖥️ Đóng gói ứng dụng desktop** — Hỗ trợ chạy ẩn dưới khay hệ thống, cơ chế chạy một bản duy nhất (single-instance), lưu trữ dữ liệu cấu hình trong thư mục `%APPDATA%`, xuất nhật ký ra tệp (file logs), đóng gói bằng PyInstaller và tích hợp bộ cài đặt Windows tiện lợi.

### 🚀 Tính năng cốt lõi (Kế thừa từ bản gốc)

Tương tác giọng nói đa ngôn ngữ thời gian thực · Điều khiển hệ thống (ứng dụng, âm lượng, độ sáng màn hình, WiFi, trạng thái nguồn) · Tự động xử lý chuỗi tác vụ phức tạp gồm nhiều bước · Phân tích ngữ cảnh màn hình và Webcam (Vision) · Bộ nhớ lưu trữ lâu dài · Hỗ trợ nhập liệu song song bằng giọng nói và bàn phím · Điểm tin buổi sáng (thời gian, thời tiết, tin tức) · Giám sát thông số phần cứng (CPU/RAM/GPU/Nhiệt độ) · Tìm kiếm web đa chế độ · Tạo lời nhắc hệ điều hành · Tìm kiếm chuyến bay · Hỏi đáp trên tệp dữ liệu · Trợ lý lập trình · Điều khiển trình duyệt · Gửi tin nhắn · Tương tác YouTube · Điều khiển màn hình nền · Tự động nhận diện ngôn ngữ im lặng.

### ⚡ Khởi đầu nhanh (Chạy từ mã nguồn)

```bash
git clone https://github.com/vivimassa/jarvis
cd JARVIS
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

Trong lần đầu khởi chạy, trình thiết lập sẽ yêu cầu bạn cung cấp tên, cách thức xưng hô mong muốn và khóa Gemini API miễn phí của bạn (Lấy khóa tại: https://aistudio.google.com/apikey). Khóa API và dữ liệu bộ nhớ của bạn được lưu trữ riêng tư, an toàn trong thư mục `%APPDATA%\JARVIS` — cam kết không mã hóa cứng (hard-coded) hay chia sẻ ra bên ngoài.

### 📦 Đóng gói ứng dụng Desktop (Windows)

```powershell
.\build.ps1                 # 1. Biên dịch và xuất bản -> dist\JARVIS\JARVIS.exe
iscc installer.iss          # 2. Đóng gói tệp cài đặt -> Output\JARVIS-Setup.exe  (Yêu cầu cài đặt Inno Setup)
```

Trình đóng gói sẽ tự động tạo các lối tắt (shortcuts) ở Start-Menu/Màn hình nền, tùy chọn "Khởi động cùng Windows" và tệp gỡ cài đặt (uninstaller). Toàn bộ dữ liệu của bạn tại thư mục `%APPDATA%\JARVIS` sẽ được giữ nguyên vẹn kể cả khi cài đặt lại ứng dụng.

### 📋 Yêu cầu hệ thống

| Yêu cầu | Chi tiết |
| --- | --- |
| **Hệ điều hành** | Windows 10/11 (Hỗ trợ macOS/Linux khi chạy trực tiếp từ mã nguồn) |
| **Python** | Phiên bản 3.11 / 3.12 (Dành cho việc chạy mã nguồn) |
| **Thiết bị** | Yêu cầu Micro kết nối với máy tính |
| **API Key** | Khóa Gemini API miễn phí — nhập trực tiếp tại trình thiết lập lần đầu |
| **Tùy chọn nâng cao** | Cần tích hợp LibreHardwareMonitor trong thư mục `tools/` để đọc thông số nhiệt độ phần cứng |

### ⚠️ Giấy phép sử dụng

Dự án áp dụng giấy phép **CC BY-NC 4.0** — cho phép tự do sử dụng, chia sẻ và chỉnh sửa cho các mục đích phi thương mại, đồng thời bắt buộc phải ghi công (attribution) cho tác giả gốc **[FatihMakes](https://www.youtube.com/@FatihMakes)** và bản fork này. Chi tiết vui lòng xem tại tệp [`LICENSE`](./LICENSE).

### 👤 Thành phần phát triển

- **Tác giả gốc — [FatihMakes](https://www.youtube.com/@FatihMakes)** ([Instagram](https://www.instagram.com/fatihmakes)). Đừng quên nhấn Star ⭐ để ủng hộ dự án gốc của tác giả.
- **Bản Fork & Tiện ích mở rộng —** https://github.com/vivimassa/jarvis

---

> Built with Google Gemini Live · Fan homage to Marvel's JARVIS. Not affiliated with Marvel or Apple.
