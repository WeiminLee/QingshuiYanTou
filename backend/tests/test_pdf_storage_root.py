"""PDF 根目录统一为 /data/qingshui/pdf（chemagent 数据盘）。

测试 cwd 为 backend，故 compose 路径从测试文件位置回推仓库根，
不依赖 cwd。
"""

from pathlib import Path

import yaml

from app.ops.worker_config import WorkerSettings

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_PATH = REPO_ROOT / "deploy/chemagent/docker-compose.yml"
PDF_MOUNT = "/data/qingshui/pdf:/data/qingshui/pdf"


def test_worker_config_default_root():
    assert WorkerSettings.pdf_storage_root == "/data/qingshui/pdf"


def test_compose_mounts_pdf_volume_into_backend():
    compose = yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))
    assert PDF_MOUNT in compose["services"]["backend"]["volumes"]


def test_compose_does_not_mount_pdf_volume_into_data_mcp():
    compose = yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))
    volumes = compose["services"]["data-mcp"].get("volumes") or []
    assert not any("/pdf" in str(volume) for volume in volumes)


def test_worker_supervisor_pins_pdf_root():
    source = (REPO_ROOT / "deploy/chemagent/worker_supervisor.py").read_text(encoding="utf-8")
    assert "PDF_STORAGE_ROOT=/data/qingshui/pdf" in source
    assert "qingshui-pdfs" not in source
