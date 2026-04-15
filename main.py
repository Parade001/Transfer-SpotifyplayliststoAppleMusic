import requests
import pandas as pd
import time
import os
import json
import random
import logging

# --- 核心配置区 ---
AUTHORIZATION_TOKEN = "Bearer eyJhbGciOiJFUz..."  # 请替换
USER_TOKEN = "0.ApWgM..."                          # 请替换
TARGET_PLAYLIST_ID = "p.ldvA7lMc4Wql5le"
STOREFRONT = "cn"

SOURCE_CSV_FILE = "export.csv"
ISRC_CACHE_FILE = "am_isrc_cache.json"
META_KEY = "_metadata_playlist_size" # 用于水位线拦截的特殊 Key

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

HEADERS = {
    "Authorization": AUTHORIZATION_TOKEN,
    "Music-User-Token": USER_TOKEN,
    "Content-Type": "application/json",
    "Origin": "https://music.apple.com",
}

def request_with_backoff(method, url, max_retries=5, **kwargs):
    for attempt in range(max_retries):
        try:
            r = requests.request(method, url, timeout=15, **kwargs)
            if r.status_code in [200, 201, 204]:
                return r
            elif r.status_code == 429:
                sleep_time = (1.5 ** attempt) + random.uniform(0.5, 1.5)
                logging.warning(f"⚠️ 触发限流，退避 {sleep_time:.2f}s (第 {attempt+1} 次尝试)")
                time.sleep(sleep_time)
            elif r.status_code == 401:
                logging.error("❌ Token 失效")
                raise SystemExit("Unauthorized")
            else:
                logging.error(f"❌ HTTP {r.status_code} 异常: {r.text[:100]}")
                return None
        except requests.exceptions.RequestException as e:
            logging.error(f"❌ 网络层异常: {e}")
            time.sleep(2 ** attempt)
    return None

def fetch_remote_playlist_song_ids(playlist_id):
    logging.info("🌐 拉取远端歌单快照...")
    existing_ids = set()
    url = f"https://api.music.apple.com/v1/me/library/playlists/{playlist_id}/tracks"

    while url:
        r = request_with_backoff("GET", url)
        if not r:
            raise SystemExit("❌ 远端状态拉取发生网络级中断，触发熔断。")

        data = r.json()
        for item in data.get('data', []):
            attrs = item.get('attributes', {})
            catalog_id = attrs.get('playParams', {}).get('catalogId')
            fallback_id = item.get('id')

            final_id = str(catalog_id) if catalog_id else str(fallback_id)
            if final_id:
                existing_ids.add(final_id)

        next_path = data.get('next')
        url = f"https://api.music.apple.com{next_path}" if next_path else None

    logging.info(f"✅ 远端快照拉取完成: 当前 {len(existing_ids)} 首")
    return existing_ids

def run_sync():
    if not os.path.exists(SOURCE_CSV_FILE):
        logging.error(f"❌ 缺少数据源 {SOURCE_CSV_FILE}")
        return

    try:
        df = pd.read_csv(SOURCE_CSV_FILE, encoding='utf-8')
    except UnicodeDecodeError:
        df = pd.read_csv(SOURCE_CSV_FILE, encoding='gbk')

    df.columns = df.columns.str.strip().str.lower()
    if 'isrc' not in df.columns:
        logging.error("❌ CSV 缺失 isrc 列")
        return

    source_isrcs = df['isrc'].dropna().astype(str).str.strip().unique().tolist()

    cache = {}
    last_remote_size = 0
    if os.path.exists(ISRC_CACHE_FILE):
        with open(ISRC_CACHE_FILE, 'r', encoding='utf-8') as f:
            cache = json.load(f)
            last_remote_size = cache.pop(META_KEY, 0) # 提出水位线数据

    uncached_isrcs = [i for i in source_isrcs if i not in cache]

    if uncached_isrcs:
        logging.info(f"🔍 查询 {len(uncached_isrcs)} 个未知 ISRC...")
        for i in range(0, len(uncached_isrcs), 25):
            batch = uncached_isrcs[i:i+25]
            url = f"https://api.music.apple.com/v1/catalog/{STOREFRONT}/songs?filter[isrc]={','.join(batch)}"

            r = request_with_backoff("GET", url)
            if r:
                data = r.json().get('data', [])
                found = set()
                for song in data:
                    isrc = song.get('attributes', {}).get('isrc')
                    if isrc and isrc not in found:
                        cache[isrc] = str(song['id'])
                        found.add(isrc)

                for missing in set(batch) - found:
                    cache[missing] = None
            time.sleep(0.5)

    desired_ids = {cache[i] for i in source_isrcs if cache.get(i)}
    remote_ids = fetch_remote_playlist_song_ids(TARGET_PLAYLIST_ID)

    # ==========================================
    # 【新增】水位线熔断防御机制 (Sanity Check)
    # ==========================================
    current_remote_size = len(remote_ids)
    if last_remote_size > 0 and current_remote_size < last_remote_size * 0.8:
        logging.error(f"❌ 致命异常：远端数据量发生断崖式下跌 (上次 {last_remote_size} -> 本次 {current_remote_size})。")
        logging.error("❌ 疑似 Apple API 分页数据静默截断。为防止海量重复写入，已触发熔断终止运行！")
        logging.error("💡 提示：如果是你手动清空了大部分歌单，请删除 am_isrc_cache.json 后重试。")
        raise SystemExit("Data integrity compromised. Circuit breaker triggered.")

    ids_to_add = list(desired_ids - remote_ids)

    # 无论是否有增量，更新水位线并统一落盘
    cache[META_KEY] = max(current_remote_size + len(ids_to_add), last_remote_size)
    with open(ISRC_CACHE_FILE, 'w', encoding='utf-8') as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)

    if not ids_to_add:
        logging.info("🎉 校验一致，无增量需写入。")
        return

    logging.info(f"🚀 准备追加 {len(ids_to_add)} 首...")
    add_url = f"https://api.music.apple.com/v1/me/library/playlists/{TARGET_PLAYLIST_ID}/tracks"

    for i in range(0, len(ids_to_add), 100):
        batch = [{"id": sid, "type": "songs"} for sid in ids_to_add[i:i+100]]
        r = request_with_backoff("POST", add_url, json={"data": batch})
        if r:
            logging.info(f"✅ 第 {i//100 + 1} 批写入成功")
        time.sleep(1)

if __name__ == "__main__":
    run_sync()
