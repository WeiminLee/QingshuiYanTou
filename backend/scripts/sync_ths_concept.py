"""抓取同花顺 AI/CPO/算力/半导体 等概念的成分股，落地到本地文件。"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

import akshare as ak
import pandas as pd
import requests
from bs4 import BeautifulSoup

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("sync_ths_concept")

DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "board_concept"

# 默认抓取的 AI / 算力 / 半导体 / CPO 等热门概念
DEFAULT_THS_CONCEPTS = [
    # AI
    "AI PC",
    "AI手机",
    "AI视频",
    "AI应用",
    "AI智能体",
    "AI眼镜",
    "AI语料",
    "多模态AI",
    "智谱AI",
    "中国AI 50",
    # 算力 / 数据中心
    "东数西算(算力)",
    "算力租赁",
    "数据中心(AIDC)",
    "液冷服务器",
    "英伟达概念",
    # 光通信 / CPO
    "共封装光学(CPO)",
    # 半导体
    "存储芯片",
    "芯片概念",
    "汽车芯片",
    "第三代半导体",
    "MCU芯片",
]


def to_ts_code(code: str) -> str | None:
    code = (code or "").strip()
    if not code.isdigit() or len(code) != 6:
        return None
    if code.startswith(("60", "68")):
        return f"{code}.SH"
    if code.startswith(("00", "30", "20")):
        return f"{code}.SZ"
    if code.startswith(("43", "83", "87", "88", "89", "92")):
        return f"{code}.BJ"
    return None


def fetch_concept_list() -> pd.DataFrame:
    df = ak.stock_board_concept_name_ths()
    df.columns = [c.strip() for c in df.columns]
    return df


def fetch_members_for_concept(
    sess: requests.Session, code: str, max_pages: int = 5, sleep_between: float = 1.5
) -> tuple[list[tuple[str, str]], bool]:
    """返回 (rows, blocked)。blocked=True 表示触发风控。"""
    out: list[tuple[str, str]] = []
    blocked = False
    for page in range(1, max_pages + 1):
        if page == 1:
            url = f"https://q.10jqka.com.cn/gn/detail/code/{code}/"
        else:
            url = f"https://q.10jqka.com.cn/gn/detail/order/desc/page/{page}/code/{code}/"

        for attempt in range(3):
            try:
                r = sess.get(url, timeout=15)
                break
            except Exception as exc:  # noqa: BLE001
                logger.warning("  请求失败(尝试 %d/3) %s: %s", attempt + 1, url, exc)
                time.sleep(2)
        else:
            blocked = True
            break

        if r.status_code != 200:
            logger.warning("  HTTP %s page=%d", r.status_code, page)
            break
        if 'location.href="//upass' in r.text or len(r.text) < 1000:
            blocked = True
            break

        r.encoding = "gbk"
        soup = BeautifulSoup(r.text, "html.parser")
        table = soup.find("table")
        if not table:
            break
        rows = []
        for tr in table.find_all("tr")[1:]:
            cells = [c.get_text(strip=True) for c in tr.find_all("td")]
            if len(cells) >= 3:
                rows.append((cells[1], cells[2]))
        if not rows:
            break
        out.extend(rows)
        time.sleep(sleep_between)

    return out, blocked


def run(concepts: list[str], output_dir: Path, max_pages: int) -> int:
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("拉取同花顺 373 个概念列表 ...")
    concept_df = fetch_concept_list()
    name_to_code = dict(zip(concept_df["name"].astype(str), concept_df["code"].astype(str)))
    logger.info("ths 概念总数: %d", len(concept_df))

    list_path = output_dir / "ths_concept_list.csv"
    concept_df.to_csv(list_path, index=False, encoding="utf-8-sig")

    sess = requests.Session()
    sess.headers.update(
        {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Referer": "https://q.10jqka.com.cn/gn/",
        }
    )

    members_rows: list[dict] = []
    grouped: list[dict] = []
    failed: list[dict] = []
    blocked_concepts: list[str] = []

    started = time.time()
    for idx, name in enumerate(concepts, start=1):
        code = name_to_code.get(name)
        if not code:
            logger.warning("[%d/%d] %s -> 概念未找到", idx, len(concepts), name)
            failed.append({"name": name, "error": "concept_not_found"})
            continue

        logger.info("[%d/%d] %s (%s) ...", idx, len(concepts), name, code)
        try:
            rows, blocked = fetch_members_for_concept(sess, code, max_pages=max_pages)
        except Exception as exc:  # noqa: BLE001
            logger.warning("  抓取失败: %s", exc)
            failed.append({"name": name, "code": code, "error": str(exc)})
            continue

        if blocked:
            blocked_concepts.append(name)
        if not rows:
            failed.append({"name": name, "code": code, "error": "empty"})
            continue

        seen = set()
        members = []
        for raw_code, stock_name in rows:
            ts = to_ts_code(raw_code)
            if not ts or ts in seen:
                continue
            seen.add(ts)
            members.append({"ts_code": ts, "stock_code": raw_code, "stock_name": stock_name})

        for m in members:
            members_rows.append(
                {
                    "concept_code": code,
                    "concept_name": name,
                    **m,
                    "fetched_at": datetime.now().isoformat(timespec="seconds"),
                }
            )
        grouped.append(
            {
                "concept_code": code,
                "concept_name": name,
                "member_count": len(members),
                "members": members,
            }
        )
        logger.info("  -> %d 只成分股%s", len(members), " (触发分页限流)" if blocked else "")

    elapsed = time.time() - started

    members_csv = output_dir / "ths_concept_members.csv"
    if members_rows:
        pd.DataFrame(members_rows).to_csv(members_csv, index=False, encoding="utf-8-sig")
    else:
        pd.DataFrame(
            columns=[
                "concept_code",
                "concept_name",
                "ts_code",
                "stock_code",
                "stock_name",
                "fetched_at",
            ]
        ).to_csv(members_csv, index=False, encoding="utf-8-sig")

    members_json = output_dir / "ths_concept_members.json"
    with members_json.open("w", encoding="utf-8") as fh:
        json.dump(grouped, fh, ensure_ascii=False, indent=2)

    meta = {
        "source": "ths (akshare list + 10jqka detail page)",
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
        "concept_total": len(concepts),
        "concept_success": len(grouped),
        "concept_failed": len(failed),
        "concept_blocked": blocked_concepts,
        "stock_member_rows": len(members_rows),
        "elapsed_seconds": round(elapsed, 2),
        "max_pages": max_pages,
        "failed_concepts": failed,
        "files": {
            "concept_list": list_path.name,
            "concept_members_csv": members_csv.name,
            "concept_members_json": members_json.name,
        },
    }
    (output_dir / "ths_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(
        "完成: 概念 %d / 成功 %d / 失败 %d / 触发限流 %d / 成分股 %d / 耗时 %.1fs",
        len(concepts),
        len(grouped),
        len(failed),
        len(blocked_concepts),
        len(members_rows),
        elapsed,
    )
    return 0 if not failed else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="同花顺 AI/CPO/算力/半导体 概念成分股抓取")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--max-pages", type=int, default=5)
    parser.add_argument("--concepts", nargs="*", default=DEFAULT_THS_CONCEPTS)
    args = parser.parse_args()
    return run(args.concepts, args.output_dir.resolve(), args.max_pages)


if __name__ == "__main__":
    sys.exit(main())
