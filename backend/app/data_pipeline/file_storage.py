"""
FileStorage - 文件存储模块

管理 PDF 文件的本地存储。
迁移自 data_access_mvp/src/utils/file_storage.py
"""
import asyncio
import re
import requests
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse, parse_qs

import logging

from app.data_pipeline.rate_limiter import get_cninfo_pdf_limiter

logger = logging.getLogger(__name__)

# HTTP 请求头，伪装浏览器访问
HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/pdf,application/octet-stream,*/*;q=0.1",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "http://www.cninfo.com.cn/",
    "Connection": "keep-alive",
}

# 研报存储策略
REPORT_PATH_STOCK = "stock"
REPORT_PATH_INDUSTRY = "industry"
REPORT_PATH_NONE = None

# Phase 03 plan 03-02 / T-03-05：路径穿越缓解
# 合法 ts_code：6 位数字 + "." + 2 位字母交易所后缀（SH/SZ/BJ）
# 也允许纯 6 位数字（部分上游传入未带交易所），其它一律视为非法
_TS_CODE_PATTERN = re.compile(r"^[0-9]{6}(\.[A-Z]{2,3})?$")
# 允许在文件名中保留的字符；其余替换成 "_"
_FILENAME_SAFE = re.compile(r"[^0-9A-Za-z._\-一-鿿]")


def _sanitize_ts_code(ts_code: str) -> str:
    """校验/规范化 ts_code，阻断 path traversal（T-03-05）。

    合法形式：``000001`` 或 ``000001.SZ`` / ``688001.SH`` / ``830000.BJ``。
    不合规时降级为 ``"_invalid"``，不抛异常以免整批失败 —— 调用方可结合
    业务结果（已写库 vs 跳过）继续监控。

    示例：
        >>> _sanitize_ts_code("000001.SZ")
        '000001.SZ'
        >>> _sanitize_ts_code("../../etc")
        '_invalid'
    """
    if not isinstance(ts_code, str):
        return "_invalid"
    candidate = ts_code.strip()
    if not candidate:
        return "_invalid"
    if not _TS_CODE_PATTERN.match(candidate):
        logger.warning("非法 ts_code 被拦截（path traversal 防护）: %r", ts_code)
        return "_invalid"
    return candidate


def _sanitize_filename(filename: str) -> str:
    """裁剪文件名中的危险字符并截断长度。

    - 去掉路径分隔符、null 字节、控制字符
    - 限制 200 字符
    - 空值降级为 ``"_unnamed.pdf"``
    """
    if not isinstance(filename, str) or not filename.strip():
        return "_unnamed.pdf"
    cleaned = _FILENAME_SAFE.sub("_", filename.strip())
    return cleaned[:200] or "_unnamed.pdf"


class FileStorage:
    """PDF 文件存储管理"""

    def __init__(
        self,
        reports_dir: Path | None = None,
        notices_dir: Path | None = None,
    ):
        from app.config import settings

        # 外部存储根路径（与项目代码分离）
        self._data_root = Path(settings.minishare_data_root)

        # 研报存储（外部路径）
        self.reports_dir = reports_dir or (self._data_root / "reports")

        # 公告存储（外部路径，与研报保持一致）
        # 使用 minishare_data_root / "notices" 而非项目内 storage/notices
        self.notices_dir = notices_dir or (self._data_root / "notices")

        # 旧版 IRM 外部路径（保留向后兼容）
        self.external_notices_dir = self._data_root / "irm"

        # 确保目录存在
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self.notices_dir.mkdir(parents=True, exist_ok=True)
        self.external_notices_dir.mkdir(parents=True, exist_ok=True)

    def _get_notice_path(self, ts_code: str, pub_date: str, filename: str) -> Path:
        """公告存储路径：storage/notices/{ts_code}/{YYYY-MM}/

        T-03-05：``ts_code`` / ``filename`` 走 sanitizer，避免上游脏数据
        构造越界路径（如 ``"../../etc/passwd"``）。
        """
        safe_ts_code = _sanitize_ts_code(ts_code)
        safe_filename = _sanitize_filename(filename)
        if pub_date and len(pub_date) >= 6 and pub_date[:6].isdigit():
            year_month = f"{pub_date[:4]}-{pub_date[4:6]}"
        else:
            year_month = "unknown"
        storage_dir = self.notices_dir / safe_ts_code / year_month
        storage_dir.mkdir(parents=True, exist_ok=True)

        # 双重防护：解析后必须仍在 notices_dir 之下
        target = (storage_dir / safe_filename).resolve()
        notices_root = self.notices_dir.resolve()
        try:
            target.relative_to(notices_root)
        except ValueError:
            logger.error(
                "拦截到逃逸出 notices_dir 的路径: target=%s root=%s",
                target, notices_root,
            )
            target = notices_root / "_invalid" / safe_filename
            target.parent.mkdir(parents=True, exist_ok=True)
        return target

    def _get_report_path(
        self,
        ts_code: str,
        inst_csname: str,
        trade_date: str,
        filename: str,
    ) -> tuple[Optional[Path], str | None]:
        """
        研报存储路径决策。

        Returns:
            (file_path, storage_type) — file_path 为 None 时只建索引不下文件
        """
        if ts_code and ts_code.strip():
            sub_dir = ts_code
            storage_type = REPORT_PATH_STOCK
        elif inst_csname and self._is_broker_or_consult(inst_csname):
            safe_name = inst_csname[:30].replace("/", "_").replace("\\", "_")
            sub_dir = f"_industry/{safe_name}"
            storage_type = REPORT_PATH_INDUSTRY
        else:
            return None, REPORT_PATH_NONE

        if trade_date and len(trade_date) >= 6:
            year_month = f"{trade_date[:4]}-{trade_date[4:6]}"
        else:
            year_month = "unknown"

        storage_dir = self.reports_dir / sub_dir / year_month
        storage_dir.mkdir(parents=True, exist_ok=True)
        return storage_dir / filename, storage_type

    def _is_broker_or_consult(self, inst_csname: str) -> bool:
        """
        判断发布机构是否为券商/咨询机构。
        """
        BROKER_KEYWORDS = [
            "证券", "研究所", "研究院", "研究中心",
            "咨询", "顾问", "评级", "评估",
        ]
        EXCLUDE_KEYWORDS = [
            "WHO", "政府", "卫生部", "国家标准", "标准化技术委员会",
            "美国", "中国", "联合国", "欧盟", "央行", "财政部",
            "腾讯云", "阿里巴巴", "阿里云", "字节", "抖音",
        ]

        name_lower = inst_csname.lower()
        for kw in EXCLUDE_KEYWORDS:
            if kw in name_lower:
                return False

        for kw in BROKER_KEYWORDS:
            if kw in inst_csname:
                return True

        return False

    def save_notice(
        self,
        content: bytes,
        ts_code: str,
        filename: str,
        pub_date: str | None = None,
    ) -> Optional[Path]:
        """保存公告 PDF"""
        if not content[:5] == b"%PDF-":
            logger.warning("内容不是 PDF，放弃保存")
            return None
        try:
            file_path = self._get_notice_path(ts_code, pub_date or "", filename)
            file_path.write_bytes(content)
            logger.info(f"文件保存成功: {file_path}")
            return file_path
        except Exception as e:
            logger.error(f"文件保存失败: {e}")
            return None

    @staticmethod
    def _resolve_pdf_url(url: str) -> str | None:
        if not url or not url.strip():
            return None
        url = url.strip()

        # 情况 A: 已经是 PDF 链接（.pdf 结尾的各种域名都支持）
        if re.search(r'\.pdf$', url, re.IGNORECASE):
            return url.replace('http://', 'https://')

        # 情况 B: 详情页 URL → 提取 announcementId → 调 API 获取 PDF 地址
        if 'detail' in url and 'cninfo' in url:
            parsed = urlparse(url)
            qs = parse_qs(parsed.query)
            announce_id = qs.get('announcementId', [None])[0]
            if announce_id:
                try:
                    resp = requests.post(
                        'http://www.cninfo.com.cn/new/announcement/bulletin_detail',
                        params={'announceId': announce_id, 'flag': 'true'},
                        headers=HTTP_HEADERS,
                        timeout=15,
                    )
                    if resp.ok:
                        file_url = resp.json().get('fileUrl')
                        if file_url:
                            return file_url
                except Exception as e:
                    logger.warning("公告详情页 URL 解析失败 [%s]: %s", announce_id, e)

        return None

    def download_notice(
        self,
        url: str,
        ts_code: str,
        filename: str,
        pub_date: str | None = None,
    ) -> Optional[Path]:
        """下载并保存公告 PDF"""
        resolved_url = self._resolve_pdf_url(url)
        if not resolved_url:
            logger.warning("公告 URL 无法解析为 PDF 地址，跳过 [%s]", url[:80])
            return None
        try:
            get_cninfo_pdf_limiter().wait_and_acquire()
            response = requests.get(resolved_url, timeout=30, headers=HTTP_HEADERS)
            response.raise_for_status()

            content = response.content
            if not content[:5] == b"%PDF-":
                logger.warning(f"下载内容不是 PDF，可能是 HTML 错误页 [{resolved_url[:80]}]")
                return None

            return self.save_notice(content, ts_code, filename, pub_date)
        except Exception as e:
            logger.error(f"公告下载失败 [{resolved_url}]: {e}")
            return None

    async def _resolve_pdf_url_async(self, url: str) -> str | None:
        """异步版本 URL 解析——纯文本判断走同步，API 调用走线程池。"""
        if not url or not url.strip():
            return None
        url = url.strip()
        # 直接 PDF 链接，无需 API 调用
        if re.search(r'\.pdf$', url, re.IGNORECASE):
            return url.replace('http://', 'https://')
        # 详情页需要调 API，投递到线程池
        if 'detail' in url and 'cninfo' in url:
            return await asyncio.to_thread(self._resolve_pdf_url, url)
        return None

    async def download_notice_async(
        self,
        url: str,
        ts_code: str,
        filename: str,
        pub_date: str | None = None,
    ) -> Optional[Path]:
        """异步下载并保存公告 PDF。

        通过 asyncio.to_thread 将同步 HTTP 请求放入线程池，
        避免阻塞事件循环。调用方负责限速。
        """
        resolved_url = await self._resolve_pdf_url_async(url)
        if not resolved_url:
            logger.warning("公告 URL 无法解析为 PDF 地址，跳过 [%s]", url[:80])
            return None
        try:
            response = await asyncio.to_thread(
                requests.get, resolved_url, timeout=30, headers=HTTP_HEADERS
            )
            response.raise_for_status()
            content = response.content
            if not content[:5] == b"%PDF-":
                logger.warning(f"下载内容不是 PDF [{resolved_url[:80]}]")
                return None
            return self.save_notice(content, ts_code, filename, pub_date)
        except Exception as e:
            logger.error(f"公告下载失败 [{resolved_url}]: {e}")
            return None

    def save_report(
        self,
        content: bytes,
        ts_code: str,
        inst_csname: str,
        trade_date: str,
        filename: str,
    ) -> Optional[Path]:
        """保存研报 PDF"""
        if not content[:5] == b"%PDF-":
            logger.warning("内容不是 PDF，放弃保存")
            return None
        try:
            file_path, storage_type = self._get_report_path(
                ts_code, inst_csname, trade_date, filename
            )
            if file_path is None:
                logger.debug(f"研报不下载，只建索引: {filename}")
                return None
            file_path.write_bytes(content)
            logger.info(f"研报保存成功 [{storage_type}]: {file_path}")
            return file_path
        except Exception as e:
            logger.error(f"研报保存失败: {e}")
            return None

    def download_report(
        self,
        url: str,
        ts_code: str,
        inst_csname: str,
        trade_date: str,
        filename: str,
    ) -> Optional[Path]:
        """下载并保存研报 PDF"""
        try:
            file_path, storage_type = self._get_report_path(
                ts_code, inst_csname, trade_date, filename
            )
            if file_path is None:
                logger.debug(f"研报不下载，只建索引: {filename}")
                return None
            get_cninfo_pdf_limiter().wait_and_acquire()
            response = requests.get(url, timeout=30, headers=HTTP_HEADERS)
            response.raise_for_status()

            content = response.content
            if not content[:5] == b"%PDF-":
                logger.warning(f"下载内容不是 PDF，可能是 HTML 错误页 [{url[:80]}]")
                return None

            file_path.write_bytes(content)
            logger.info(f"研报下载成功 [{storage_type}]: {file_path}")
            return file_path
        except Exception as e:
            logger.error(f"研报下载失败 [{url}]: {e}")
            return None

    def _get_external_report_path(
        self,
        ts_code: str,
        inst_csname: str,
        trade_date: str,
        filename: str,
    ) -> tuple[Optional[Path], str | None]:
        """研报外部存储路径：minishare_data_root/reports/{ts_code}/{YYYY-MM}/"""
        safe_ts_code = _sanitize_ts_code(ts_code)
        safe_filename = _sanitize_filename(filename)
        if trade_date and len(trade_date) >= 6:
            year_month = f"{trade_date[:4]}-{trade_date[4:6]}"
        else:
            year_month = "unknown"

        storage_dir = self.external_reports_dir / safe_ts_code / year_month
        storage_dir.mkdir(parents=True, exist_ok=True)
        return storage_dir / safe_filename, REPORT_PATH_STOCK

    def save_report_external(
        self,
        content: bytes,
        ts_code: str,
        inst_csname: str,
        trade_date: str,
        filename: str,
    ) -> Optional[Path]:
        """保存研报 PDF 到外部存储"""
        if not content[:5] == b"%PDF-":
            logger.warning("内容不是 PDF，放弃保存")
            return None
        try:
            file_path, storage_type = self._get_external_report_path(
                ts_code, inst_csname, trade_date, filename
            )
            if file_path is None:
                logger.debug(f"研报外部存储跳过（无 ts_code）: {filename}")
                return None
            file_path.write_bytes(content)
            logger.info(f"研报外部保存成功: {file_path}")
            return file_path
        except Exception as e:
            logger.error(f"研报外部保存失败: {e}")
            return None

    def download_report_external(
        self,
        url: str,
        ts_code: str,
        inst_csname: str,
        trade_date: str,
        filename: str,
    ) -> Optional[Path]:
        """下载并保存研报 PDF 到外部存储（存在则跳过）"""
        try:
            file_path, storage_type = self._get_external_report_path(
                ts_code, inst_csname, trade_date, filename
            )
            if file_path is None:
                logger.debug(f"研报外部下载跳过（无 ts_code）: {filename}")
                return None
            if file_path.exists():
                logger.debug(f"研报已存在，跳过下载: {file_path}")
                return file_path
            get_cninfo_pdf_limiter().wait_and_acquire()
            response = requests.get(url, timeout=30, headers=HTTP_HEADERS)
            response.raise_for_status()

            content = response.content
            if not content[:5] == b"%PDF-":
                logger.warning(f"下载内容不是 PDF [{url[:80]}]")
                return None

            file_path.write_bytes(content)
            logger.info(f"研报外部下载成功: {file_path}")
            return file_path
        except Exception as e:
            logger.error(f"研报外部下载失败 [{url}]: {e}")
            return None

    def file_exists(self, file_path: Path) -> bool:
        """检查文件是否存在"""
        return file_path.exists()

    def delete_file(self, file_path: Path) -> bool:
        """删除文件"""
        try:
            if file_path.exists():
                file_path.unlink()
                logger.info(f"文件删除成功: {file_path}")
                return True
            return False
        except Exception as e:
            logger.error(f"文件删除失败: {file_path}: {e}")
            return False
