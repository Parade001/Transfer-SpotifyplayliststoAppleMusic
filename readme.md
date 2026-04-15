# Spotify to Apple Music Playlist Sync (Industrial Grade)
# Spotify 到 Apple Music 歌单同步工具（工业级）

[![Python](https://img.shields.io/badge/Python-3.7+-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

[中文说明](#中文说明) | [English Documentation](#english-documentation)

---

<h2 id="中文说明">🇨🇳 中文说明</h2>

这是一个具备高容错、幂等性写入和断点续传能力的 Python 脚本，用于将 Spotify 的歌单无缝同步到 Apple Music。它采用了“最终一致性”架构，专为应对 Apple Music Web API 的严苛限流和不稳定状态而设计。

### ✨ 核心特性
* **绝对幂等性 (Idempotent Writes)**：每次运行前会拉取 Apple Music 远端真实状态进行比对，彻底杜绝重复导入。
* **智能本地缓存 (ISRC Caching)**：永久记录已查询过的 ISRC 映射关系，二次运行 API 请求量直降 90%+，极大降低被封禁风险。
* **水位线熔断防御 (Circuit Breaker)**：智能识别 Apple API 分页数据静默截断故障，防止因接口异常导致的灾难性海量重复写入。
* **指数退避算法 (Exponential Backoff)**：遇 `429 Too Many Requests` 时自动通过指数退避及随机抖动平滑重试。
* **一键式增量同步**：无需手动区分新旧文件，直接用最新的数据源覆盖即可。

### 🛠️ 准备工作

1.  **获取 Spotify 歌单 CSV 数据源**：
    * 访问 [Exportify.app](https://exportify.app/)。
    * 使用你的 Spotify 账号授权登录。
    * 找到你需要同步的歌单，点击 **Export** 导出为 CSV 文件。
    * 将下载的文件重命名为 `export.csv`，并与本脚本放在同一目录下。

2.  **获取 Apple Music 授权凭证 (Tokens)**：
    * 在浏览器登录 [Apple Music 网页版](https://music.apple.com/)。
    * 按 `F12` 打开开发者工具，切换到 **Console (控制台)** 面板。
    * 粘贴并运行以下两行代码，直接提取你的专属 Token：
      ```javascript
      console.log("Authorization: Bearer " + MusicKit.getInstance().developerToken);
      console.log("Music-User-Token: " + MusicKit.getInstance().musicUserToken);
      ```
    * 复制控制台输出的这两行字符串。

3.  **获取目标歌单 ID**：
    * 在 Apple Music 网页版打开你想要导入的目标歌单。
    * 查看浏览器地址栏，URL 结尾类似 `.../playlist/p.ldvA7lMc4Wql5le`，其中 `p.ldvA7lMc4Wql5le` 就是目标 ID。

### 🚀 快速开始

1. **安装依赖**:
   ```bash
   pip install requests pandas
