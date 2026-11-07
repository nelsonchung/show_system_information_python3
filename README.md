# 樹莓派系統觀測站

Python 3 標準函式庫實作的唯讀內網驗證原型，不需 pip 套件，不需 root。

## 啟動

```sh
cd /media/nelson/work-disk/develop/show_system_information_python3
python3 server.py --host 192.168.8.235 --port 8080
```

瀏覽器開啟 http://192.168.8.235:8080 。預設省略 --host 時只接受本機連線。

此次驗證以背景程序執行，PID 存在 `.runtime/server.pid`，執行日誌在 `.runtime/server.log`。
停止此次程序（先確認 PID 對應本專案）：

```sh
ps -fp "$(cat .runtime/server.pid)"
kill "$(cat .runtime/server.pid)"
```

重開機後需重新啟動；此版本未安裝 systemd 服務或修改系統設定。

## 功能與 API

- `GET /api/health`：服務健康狀態。
- `GET /api/system`：主機／型號／OS／核心版本、CPU 使用率（約 150ms 取樣）與 1/5/15 分鐘平均負載、記憶體與 Swap、運作時間、根目錄及開發目錄所在檔案系統容量、網路介面累計收送位元組、溫度、樹莓派欠壓與降頻旗標。
- `GET /api/dmesg?lines=200`：目前核心環形緩衝區最後 1–1000 行。讀取不會清除日誌；這不是完整歷史紀錄，舊資料可能已被覆蓋。權限不足回傳 HTTP 503 與錯誤資訊。
- 系統資訊每 5 秒更新，可暫停；日誌按需取得，支援對當前快照做文字篩選。
- 網路數值是累計流量，不是即時速率。磁碟根目錄與開發目錄可能位於同一檔案系統。記憶體已使用量依 `MemTotal - MemAvailable` 計算。
- `vcgencmd` 不存在時顯示無法取得，其餘資訊仍可使用。

## 驗證

```sh
python3 -m unittest -v
python3 -m py_compile server.py test_server.py
```

`/proc`、`/sys` 為 Linux 介面，完整系統資料測試需在 Linux 執行。

## 使用範圍

目前無登入、HTTPS 或請求頻率限制；僅供受信任內網的功能驗證，所有可連線者均可讀取資訊。Python `http.server` 不適合直接作為正式對外服務。正式部署可再加入身分驗證、正式 HTTP server、限流與服務管理。

僅提供固定唯讀路由、固定命令參數，不接受任意命令或檔案路徑。網頁以 textContent 顯示資料，不把日誌當 HTML 執行。SSH 密碼未寫入程式。

## 新增的診斷區塊

以下區塊與系統資訊一起每 5 秒更新，各自處理失敗狀態；單一來源不可用時不影響其他區塊。

| API | 資料與來源 |
| --- | --- |
| `GET /api/network` | `ip -j address show` 取得所有介面的 IPv4／IPv6（CIDR）；`/proc/net/wireless` 取得可用 Wi-Fi 訊號 dBm。沒有無線訊號資料顯示 —，來源不可讀時另顯示錯誤。 |
| `GET /api/services` | 系統層級 `systemctl --failed --type=service`，列出名稱、載入、狀態、子狀態與說明。沒有 failed 不表示所有應用程式健康，也不包含一般 inactive 服務、使用者層級服務或 Docker 容器健康。 |
| `GET /api/processes` | `ps` 提供 CPU 與記憶體前 10 名、PID、程序名稱、CPU%、RAM%、RSS。CPU 是啟動以來的平均，100% 代表一顆核心，可超過 100%；不是 top 的瞬間取樣。RSS 為常駐實體記憶體，單位轉為 bytes。 |
| `GET /api/usb` | `/sys/bus/usb/devices` 提供 VID:PID、Bus／Device、製造商、產品、協商速率；包含 root hub，省略 USB interface 重複列與裝置序號。裝置可熱插拔，下次更新反映變化。 |

程式沒有新增 sudo 權限或第三方 Python 套件。診斷 API 來源不可用時回 HTTP 503 與錯誤資訊。服務異常只讀取，不會停止、重啟或重設服務。

新增檔案 `diagnostics.py` 與 `test_diagnostics.py`；擴充 `server.py`、`test_server.py`、`index.html`、`app.js`、`style.css`、本 README。舊版備份位於 `.runtime/before-diagnostics.tar.gz`，未寫入 git。

參考：[systemctl 官方文件](https://www.freedesktop.org/software/systemd/man/latest/systemctl.html)、[Debian ps 手冊](https://manpages.debian.org/trixie/procps/ps.1.en.html)。
