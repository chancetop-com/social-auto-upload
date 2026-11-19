# 媒体直链下载与断点续传

**首选项目已有的 Requests 2.32.3。** 对 HTTP(S) 图片、视频直链，一条 GET 就能把文件逐块写入磁盘。若要减少依赖，Python 3.10–3.12 的标准库也足够。两者都需要由 CLI 保存未完成文件、识别远端版本，并决定能否追加。如果希望把分段下载和跨进程进度一并交给现成工具，优先考虑 aria2。它需要随部署提供 `aria2c`。[项目依赖](../../../pyproject.toml) · [Requests 流式响应](https://requests.readthedocs.io/en/latest/user/advanced/#body-content-workflow) · [Python HTTPResponse](https://docs.python.org/3.10/library/http.client.html#httpresponse-objects) · [aria2 恢复下载](https://aria2.github.io/manual/en/html/aria2c.html#resuming-download)

## 各方案替 CLI 做了什么

| 方案 | 内置能力 | 项目仍需负责 |
| --- | --- | --- |
| 标准库 `urllib.request` | 用 `Request` 发自定义请求头，`urlopen()` 返回带状态和响应头的对象。循环调用 `readinto(bytearray)` 可复用同一块内存。 | 保存进度，校验范围、版本和长度，处理 `HTTPError` 中的 416。适合希望下载模块只依赖标准库的场景。[urllib.request](https://docs.python.org/3.10/library/urllib.request.html#urllib.request.urlopen) · [readinto](https://docs.python.org/3.10/library/http.client.html#http.client.HTTPResponse.readinto) · [HTTPError](https://docs.python.org/3.10/library/urllib.error.html#urllib.error.HTTPError) |
| Requests | `get(..., stream=True)` 先取得响应头，`iter_content(chunk_size=B)` 逐块交付正文，响应可用 `with` 关闭。 | 同样需要持久化和校验，但可复用项目依赖。接触 `response.content` 会读完整个响应。[流式下载示例](https://requests.readthedocs.io/en/latest/user/quickstart/#raw-response-content) · [2.32.3 源码](https://github.com/psf/requests/blob/v2.32.3/src/requests/models.py#L799-L892) |
| yt-dlp（可嵌入 Python） | 提供 `YoutubeDL`，默认启用 `--continue` 和 `--part`。对其支持的视频输入，重启后可利用同名未完成文件。 | 适合需要视频站点解析的任务。其 HTTP 下载器处理 416 时可把长度差小于 100 字节的文件判作完成，通用图片和视频直链若要求字节完全一致，仍需独立校验。[嵌入 Python](https://github.com/yt-dlp/yt-dlp#embedding-yt-dlp) · [文件选项](https://github.com/yt-dlp/yt-dlp#filesystem-options) · [HTTP 下载器](https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/downloader/http.py) |
| PycURL / libcurl | `RESUME_FROM_LARGE` 接受字节偏移，`WRITEDATA` 可直接写二进制文件，适合需要在 Python 进程内使用 libcurl 的项目。 | 调用方提供偏移、选定输出文件位置并验证资源身份。部署增加原生扩展及其 libcurl 依赖。[libcurl 续传选项](https://curl.se/libcurl/c/CURLOPT_RESUME_FROM_LARGE.html) · [PycURL 写入文件](https://pycurl.github.io/docs/latest/quickstart.html#writing-to-a-file) · [安装说明](https://pycurl.github.io/docs/latest/install.html) |
| curl 命令行 | `--continue-at - --output media.part` 会取本地文件长度，请求剩余字节。再次启动命令即可利用旧文件。 | 部署需有 `curl`。本地长度只确定起点，资源版本仍要验证。`--etag-compare` 发送的是用于缓存的 `If-None-Match`，续传需要 `If-Range` 语义。[curl 续传说明](https://everything.curl.dev/usingcurl/downloads/resume.html) · [curl ETag 选项](https://curl.se/docs/manpage.html#--etag-compare) |
| aria2 命令行 | 在下载文件旁保存 `.aria2` 控制文件，记录已下载的分段。中断后在相同目录重跑通常即可恢复。默认 `--always-resume=true`，服务端不能续传时会停止。 | 保留数据文件和控制文件。切换链接须确认指向同一文件。来源提供可信摘要时可用 `--checksum` 校验。适合已有外部工具部署、希望利用多连接下载的场景。[控制文件](https://aria2.github.io/manual/en/html/aria2c.html#control-file) · [恢复策略](https://aria2.github.io/manual/en/html/aria2c.html#cmdoption-always-resume) · [切换链接](https://aria2.github.io/manual/en/html/aria2c.html#download-a-file) · [校验和](https://aria2.github.io/manual/en/html/aria2c.html#cmdoption-checksum) |

## 大文件会占多少内存

每个任务顺序读取、逐块写盘，需要校验时也逐块更新摘要，避免把整份文件读入内存。下载并发数可配，默认 **1**。若块大小为 `B`，同时下载 `W` 个文件，应用持有的正文缓冲约随 `W × B` 增长。下载 10 GiB 视频无需分配 10 GiB 内存，也无需为每块单独发 HTTP 请求。Python 对象、临时拷贝、文件缓冲、连接和 TLS 还会占用内存，因此块大小不能用作整个进程的 RSS 上限。[Python 定长读取](https://docs.python.org/3.10/library/http.client.html#http.client.HTTPResponse.readinto) · [Requests 流式下载示例](https://requests.readthedocs.io/en/latest/user/quickstart/#raw-response-content)

Requests 2.32.3 的 `iter_content()` 会自动解压，而 HTTP 字节范围按编码后的数据计算。建议首次下载和续传都发送 `Accept-Encoding: identity`，并在写入前确认响应未应用内容编码。若服务器仍返回带内容编码的响应，首版建议关闭响应并报告原因，保留已有断点。这同时避免了解码输出超出预期缓冲和本地偏移与远端字节错位。[Requests 2.32.3 实现](https://github.com/psf/requests/blob/v2.32.3/src/requests/models.py#L816-L829) · [RFC 9110 字节范围](https://www.rfc-editor.org/rfc/rfc9110.html#section-14.1.2)

重定向也需要控制正文的读取。Requests 2.32.3 在处理 3xx 时会读取中间响应的完整正文，即使禁用自动跟随，构建下一次请求时也可能进入这段逻辑。若需要保证每一跳都没有整份正文进入内存，可使用允许逐跳处理的传输接口，在收到响应头时提取 `Location`、关闭中间响应，再请求下一跳。例如 urllib3 的连接池可同时禁用自动跳转和正文预载。[Requests 跳转实现](https://github.com/psf/requests/blob/v2.32.3/src/requests/sessions.py#L149-L198) · [Session.send](https://github.com/psf/requests/blob/v2.32.3/src/requests/sessions.py#L710-L751) · [urllib3 流式读取](https://urllib3.readthedocs.io/en/2.6.3/advanced-usage.html#streaming-and-i-o) · [urllib3 PoolManager.urlopen](https://urllib3.readthedocs.io/en/2.6.3/reference/urllib3.poolmanager.html#urllib3.PoolManager.urlopen)

### 本机跨进程实测

在 macOS、CPython 3.11.11 上，由本机 HTTP 服务提供 16 MiB 和 128 MiB 的合成文件。每次只下载一个文件，使用 1 MiB 读取块且不压缩。首个进程写入 4 MiB 后退出，新进程发送带 `Range` 和 `If-Range` 的 GET。服务端采用固定强 ETag，四次续传均收到 206，逐块计算的 SHA-256 均与预期一致。请求头和断点恢复由测试程序实现。

| 客户端及读取方式 | 16 MiB 文件的 Python 分配峰值 | 128 MiB 文件的 Python 分配峰值 | 16 MiB / 128 MiB 文件的进程 RSS 峰值 |
| --- | ---: | ---: | ---: |
| urllib · `read(1 MiB)` | 2.14 MiB | 2.14 MiB | 27.91 / 28.14 MiB |
| Requests 2.32.3 · `iter_content(1 MiB)` | 2.05 MiB | 2.05 MiB | 37.16 / 37.05 MiB |

`tracemalloc` 在导入客户端后启用，统计新进程续传请求和写盘期间的 Python 分配。RSS 统计整个续传进程。文件增大八倍，两种客户端的 Python 分配峰值都基本持平。这组单连接、本机 HTTP 数据可以作为基线，HTTPS 和多文件并发需要按目标环境测量。

## CLI 重启后怎样决定是否追加

1. 首次下载写入任务专属的 `.part`，旁边记录资源标识、强 ETag、已知总长度和已持久化的连续字节数。建议每个文件只允许一个写入者。先刷新数据并同步至磁盘，再原子替换进度记录。重启若文件比记录长，截断到已确认位置。若更短，重新下载。校验完整后才在同一文件系统内原子更名，向上传流程交付最终路径。[Python fsync](https://docs.python.org/3.10/library/os.html#os.fsync) · [Python replace](https://docs.python.org/3.10/library/os.html#os.replace)
2. 假设本地已确认前 `N` 字节，续传发 `Range: bytes=N-` 并带上保存的强 ETag 作为 `If-Range`。弱 ETag（`W/` 前缀）不能用于此处。仅有 `Last-Modified` 时，规范允许在没有 ETag 且日期符合强校验器条件时使用。首版可只接受强 ETag，缺失时从头下。`Accept-Ranges: bytes` 只是提示，是否能续传取决于本次 GET 的实际响应。[RFC 9110 If-Range](https://www.rfc-editor.org/rfc/rfc9110.html#section-13.1.5) · [Accept-Ranges](https://www.rfc-editor.org/rfc/rfc9110.html#section-14.3)

| 续传响应 | 建议处理 |
| --- | --- |
| `206 Partial Content` | 核对单段 `Content-Range: bytes N-M/T` 的起点、终点、总长度与已存元数据。响应中的版本信息若冲突则停止追加。实收字节数应为 `M-N+1`。若只收到有效子范围，下次从 `M+1` 继续。覆盖整份文件后才交付。服务端用 `*` 表示总长未知时，需另行确认终点。[RFC 9110 Content-Range](https://www.rfc-editor.org/rfc/rfc9110.html#section-14.4) · [206](https://www.rfc-editor.org/rfc/rfc9110.html#section-15.3.7) |
| `200 OK` | 服务端可能忽略了 Range，也可能因对象已变而按 If-Range 返回整份新内容。将这次响应从零写入新的临时文件，并记录新的元数据。直接接到旧文件末尾会破坏文件。[RFC 9110 Range](https://www.rfc-editor.org/rfc/rfc9110.html#section-14.2) · [If-Range](https://www.rfc-editor.org/rfc/rfc9110.html#section-13.1.5) |
| `416 Range Not Satisfiable` | `Content-Range: bytes */T` 给出当前长度。只有本地已确认完整持有 `T` 字节，且可核对同一版本或可信摘要，才认定已完成。长度不符、缺少总长或身份不明时，重新获取整份文件。[RFC 9110 416](https://www.rfc-editor.org/rfc/rfc9110.html#section-15.5.17) · [强校验器](https://www.rfc-editor.org/rfc/rfc9110.html#section-8.8.1) |

签名 URL 的有效期也会影响续传。例如 S3 在请求开始时检查签名，过期前建立的下载可继续，过期后断线重连则会失败。建议保留断点，由有权限的来源提供新链接。确认新链接对应同一对象及版本后再续传。ETag 的唯一性限于同一资源，两个不同 URL 恰好返回相同的 ETag，并不足以证明它们指向同一个文件。[Amazon S3 预签名链接](https://docs.aws.amazon.com/AmazonS3/latest/userguide/using-presigned-url.html#PresignedUrl-Expiration) · [RFC 9110 校验器的作用域](https://www.rfc-editor.org/rfc/rfc9110.html#section-8.8.1)
