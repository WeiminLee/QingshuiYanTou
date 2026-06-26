"""
板块概念同步脚本（新浪财经源）

目标：抓取"概念板块 → 成分股"映射关系，落地到本地文件，不写 PostgreSQL。

数据源：akshare 新浪财经接口
- ak.stock_sector_spot(indicator="概念")        概念板块列表 + 板块行情
- ak.stock_sector_detail(sector=<label>)         概念板块成分股

输出目录：backend/data/board_concept/
- sina_concept_list.csv         概念列表（含板块行情快照）
- sina_concept_members.csv      概念→成分股 长表（所有概念合并）
- sina_concept_members.json     概念→成分股 分组（人工查看友好）
- meta.json                     抓取时间、概念数、成分股数、失败概念列表

用法：
    python -m scripts.sync_board_concept
    python -m scripts.sync_board_concept --output-dir /tmp/concepts --limit 5
"""

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

from app.data_pipeline.rate_limiter import get_akshare_limiter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("sync_board_concept")


DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "board_concept"


def fetch_concept_list() -> pd.DataFrame:
    """获取新浪概念板块列表（含板块快照行情）。"""
    get_akshare_limiter().wait_and_acquire()
    df = ak.stock_sector_spot(indicator="概念")
    if df is None or df.empty:
        raise RuntimeError("stock_sector_spot 返回空")
    df = df.copy()
    df["fetched_at"] = datetime.now().isoformat(timespec="seconds")
    return df


def fetch_concept_members(label: str) -> pd.DataFrame:
    """获取单个概念板块的成分股明细。"""
    get_akshare_limiter().wait_and_acquire()
    df = ak.stock_sector_detail(sector=label)
    if df is None:
        return pd.DataFrame()
    return df


def normalize_members(
    raw: pd.DataFrame,
    concept_label: str,
    concept_name: str,
) -> pd.DataFrame:
    """从新浪 detail 输出中只保留代码 / 名称 / 抓取时间。"""
    if raw.empty:
        return pd.DataFrame(
            columns=[
                "concept_label",
                "concept_name",
                "ts_code",
                "stock_code",
                "stock_name",
                "fetched_at",
            ]
        )

    sym = raw.get("symbol")
    code = raw.get("code")
    name = raw.get("name")

    out = pd.DataFrame(
        {
            "concept_label": concept_label,
            "concept_name": concept_name,
            "ts_code": _to_ts_code(sym, code),
            "stock_code": code.astype(str) if code is not None else "",
            "stock_name": name.astype(str) if name is not None else "",
            "fetched_at": datetime.now().isoformat(timespec="seconds"),
        }
    )
    return out


def _to_ts_code(sym_series, code_series) -> pd.Series:
    """新浪 symbol 形如 sh600000 / sz000001，转换为 600000.SH / 000001.SZ。"""

    def _conv(symbol: str, code: str) -> str:
        symbol = (symbol or "").lower().strip()
        code = (code or "").strip()
        if symbol.startswith("sh"):
            return f"{code}.SH"
        if symbol.startswith("sz"):
            return f"{code}.SZ"
        if symbol.startswith("bj"):
            return f"{code}.BJ"
        return code

    if sym_series is None or code_series is None:
        return pd.Series([""] * (len(code_series) if code_series is not None else 0))
    return pd.Series([_conv(s, c) for s, c in zip(sym_series.astype(str), code_series.astype(str))])


def run(output_dir: Path, limit: int | None) -> int:
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("拉取概念板块列表 ...")
    concept_df = fetch_concept_list()
    logger.info("概念板块数量：%d", len(concept_df))

    list_path = output_dir / "sina_concept_list.csv"
    concept_df.to_csv(list_path, index=False, encoding="utf-8-sig")
    logger.info("概念列表已写入 %s", list_path)

    if limit:
        concept_df = concept_df.head(limit)
        logger.info("limit=%d，仅抓取前 %d 个概念用于验证", limit, len(concept_df))

    members_frames: list[pd.DataFrame] = []
    members_grouped: dict[str, dict] = {}
    failed: list[dict] = []

    total = len(concept_df)
    started = time.time()

    for idx, row in enumerate(concept_df.itertuples(index=False), start=1):
        label = str(getattr(row, "label", "")).strip()
        name = str(getattr(row, "板块", "")).strip()
        if not label:
            continue

        logger.info("[%d/%d] %s (%s) ...", idx, total, name, label)
        try:
            raw = fetch_concept_members(label)
            members = normalize_members(raw, label, name)
        except Exception as exc:  # noqa: BLE001
            logger.warning("抓取失败：%s (%s) -> %s", name, label, exc)
            failed.append({"label": label, "name": name, "error": str(exc)})
            continue

        members_frames.append(members)
        members_grouped[label] = {
            "concept_label": label,
            "concept_name": name,
            "member_count": int(len(members)),
            "members": members[["ts_code", "stock_code", "stock_name"]].to_dict(orient="records"),
        }
        logger.info("  -> %d 只成分股", len(members))

    elapsed = time.time() - started

    if members_frames:
        merged = pd.concat(members_frames, ignore_index=True)
    else:
        merged = pd.DataFrame(
            columns=[
                "concept_label",
                "concept_name",
                "ts_code",
                "stock_code",
                "stock_name",
                "fetched_at",
            ]
        )

    members_csv = output_dir / "sina_concept_members.csv"
    merged.to_csv(members_csv, index=False, encoding="utf-8-sig")
    logger.info("成分股长表已写入 %s（行数=%d）", members_csv, len(merged))

    members_json = output_dir / "sina_concept_members.json"
    with members_json.open("w", encoding="utf-8") as fh:
        json.dump(
            list(members_grouped.values()),
            fh,
            ensure_ascii=False,
            indent=2,
        )
    logger.info("成分股分组 JSON 已写入 %s", members_json)

    meta = {
        "source": "sina (akshare.stock_sector_spot/detail)",
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
        "concept_total": int(total),
        "concept_success": int(len(members_grouped)),
        "concept_failed": len(failed),
        "stock_member_rows": int(len(merged)),
        "elapsed_seconds": round(elapsed, 2),
        "failed_concepts": failed,
        "files": {
            "concept_list": list_path.name,
            "concept_members_csv": members_csv.name,
            "concept_members_json": members_json.name,
        },
    }
    meta_path = output_dir / "meta.json"
    with meta_path.open("w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=2)
    logger.info("元数据已写入 %s", meta_path)

    logger.info(
        "完成：概念 %d / 成功 %d / 失败 %d / 成分股记录 %d / 耗时 %.1fs",
        total,
        len(members_grouped),
        len(failed),
        len(merged),
        elapsed,
    )
    return 0 if not failed else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="同步概念板块及成分股映射（新浪源）")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"输出目录，默认 {DEFAULT_OUTPUT_DIR}",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="只抓取前 N 个概念，用于小规模验证",
    )
    args = parser.parse_args()
    return run(output_dir=args.output_dir.resolve(), limit=args.limit)


if __name__ == "__main__":
    sys.exit(main())
