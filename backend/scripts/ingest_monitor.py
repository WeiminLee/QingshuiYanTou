#!/usr/bin/env python3
"""清水投研 入库监控（数据获取 + 抽取任务 持续入库观测）

云端 cron 每 5 分钟执行一次，快照三面：
  A. 数据获取侧（Mongo kg_evidence）：总量、近 1h/24h 新增、24h 按来源分桶
  B. 数据获取任务（PG sync_task_status）：各采集任务最近一次运行状态
  C. 抽取侧（Mongo kg_extraction_jobs）：pending/running/failed/done_1h
  D. link 层产出（PG reltuples 估计）

告警规则（写 alerts 数组到日志，fail-safe 不影响主链路）：
  1. MONITOR_MONGO_ERROR / MONITOR_PG_ERROR —— 监控自身失败（不静默）
  2. EVIDENCE_DRY —— 24h 零新增（采集断粮）
  3. EXTRACT_STALLED —— pending>0 且 1h 无 done 且无 lease（worker 断头）
  4. FAILED_INCRAISED —— 抽取 failed>100
  5. TASK_FAILED(name) —— 采集任务 24h 内运行失败
  6. TASK_RETRY_FAIL(name) —— 采集任务连续失败次数 >0

日志：/root/qingshui_monitor/ingest-monitor.log（单行 JSON）
"""

import json
import subprocess
from datetime import UTC, datetime

MONGO = "mongodb://qingshui:qingshui123@127.0.0.1:27017/qingshui?authSource=admin"

MONGO_JS = """
const ev = db.kg_evidence, j = db.kg_extraction_jobs;
const now = Date.now();
const bySource = {};
ev.aggregate([
  {$match: {created_at: {$gte: new Date(now-86400000)}}},
  {$group: {_id: '$source_type', n: {$sum: 1}}},
  {$sort: {n: -1}}
]).forEach(d => bySource[d._id || 'unknown'] = d.n);
print(JSON.stringify({
  ev_total: ev.estimatedDocumentCount(),
  ev_1h: ev.countDocuments({created_at: {$gte: new Date(now-3600000)}}),
  ev_24h: ev.countDocuments({created_at: {$gte: new Date(now-86400000)}}),
  ev_24h_by_source: bySource,
  pending: j.countDocuments({status: 'pending'}),
  running: j.countDocuments({status: 'running'}),
  failed: j.countDocuments({status: 'failed'}),
  done_1h: j.countDocuments({status: 'done', updated_at: {$gte: new Date(now-3600000)}}),
  claim_recent: j.countDocuments({status: 'running', lease_expires_at: {$gte: new Date(now-900000)}})
}));
"""

PG_LINK_SQL = (
    "SELECT relname, reltuples::bigint FROM pg_class "
    "WHERE relname IN ('link_links','link_keywords') AND relkind='r';"
)

PG_TASK_SQL = """
SELECT DISTINCT ON (task_name) task_name, status, completed_at, total_items,
       success_count, fail_count, consecutive_failures,
       left(coalesce(error_message,''), 80)
FROM sync_task_status ORDER BY task_name, id DESC;
"""

PG_QUEUE_SQL = """
SELECT job_type, status, count(*) FROM ingestion_jobs GROUP BY job_type, status;
"""


def _docker_exec(args: list[str]) -> str:
    r = subprocess.run(
        ["docker", "exec", *args], capture_output=True, text=True, timeout=90
    )
    return r.stdout.strip()


def _fetch_mongo() -> dict:
    raw = _docker_exec(["qingshui_mongo", "mongosh", MONGO, "--quiet", "--eval", MONGO_JS])
    return json.loads(raw.splitlines()[-1])


def _fetch_pg_link() -> dict:
    out = _docker_exec(
        ["qingshui_postgres", "psql", "-U", "qingshui", "-d", "qingshui", "-Atc", PG_LINK_SQL]
    )
    pg = {}
    for line in out.splitlines():
        if "|" in line:
            name, n = line.split("|", 1)
            pg[name] = int(float(n)) if n else 0
    return pg


def _fetch_tasks() -> dict:
    out = _docker_exec(
        ["qingshui_postgres", "psql", "-U", "qingshui", "-d", "qingshui",
         "-AtF", "|", "-c", PG_TASK_SQL]
    )
    today_utc = datetime.now(UTC)
    today_local = datetime.now()
    tasks = {}
    for line in out.splitlines():
        parts = line.split("|")
        if len(parts) < 7:
            continue
        name, status, completed, total, succ, fail, cf = parts[:7]
        err = parts[7] if len(parts) > 7 else ""
        age_h = None
        if completed:
            try:
                dt = datetime.fromisoformat(completed.replace(" ", "T"))
                # PG 时间戳为本地 naive 时间（Asia/Shanghai），按同基准算 age_h
                if dt.tzinfo is None:
                    age_h = round((today_local - dt).total_seconds() / 3600, 1)
                else:
                    age_h = round((today_utc - dt).total_seconds() / 3600, 1)
            except ValueError:
                pass
        tasks[name] = {
            "status": status,
            "age_h": age_h,
            "total": _int(total),
            "ok": _int(succ),
            "fail": _int(fail),
            "cf": _int(cf),
            "err": err,
        }
    return tasks


def _int(v: str) -> int:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


def _fetch_queue() -> dict:
    out = _docker_exec(
        ["qingshui_postgres", "psql", "-U", "qingshui", "-d", "qingshui",
         "-AtF", "|", "-c", PG_QUEUE_SQL]
    )
    q: dict[str, dict[str, int]] = {}
    for line in out.splitlines():
        parts = line.split("|")
        if len(parts) < 3:
            continue
        job_type, status, n = parts[0], parts[1], _int(parts[2])
        q.setdefault(job_type, {})[status] = n
    return q


def _load_prev() -> dict:
    try:
        with open("/root/qingshui_monitor/ingest-monitor.log", encoding="utf-8") as f:
            lines = [ln for ln in f.read().splitlines() if ln.strip()]
        return json.loads(lines[-1]) if lines else {}
    except Exception:  # noqa: BLE001
        return {}


def main() -> None:
    prev = _load_prev()
    snap: dict = {}
    alerts: list[str] = []

    try:
        snap.update(_fetch_mongo())
    except Exception as e:  # noqa: BLE001
        snap["mongo_error"] = str(e)[:200]

    try:
        snap["pg"] = _fetch_pg_link()
    except Exception as e:  # noqa: BLE001
        snap["pg_error"] = str(e)[:200]

    try:
        snap["tasks"] = _fetch_tasks()
    except Exception as e:  # noqa: BLE001
        snap["task_error"] = str(e)[:200]

    try:
        snap["iq"] = _fetch_queue()
    except Exception as e:  # noqa: BLE001
        snap["queue_error"] = str(e)[:200]

    if "mongo_error" in snap:
        alerts.append("MONITOR_MONGO_ERROR")
    if "pg_error" in snap:
        alerts.append("MONITOR_PG_ERROR")
    if "task_error" in snap:
        alerts.append("MONITOR_TASK_ERROR")
    if "queue_error" in snap:
        alerts.append("MONITOR_QUEUE_ERROR")

    # 采集队列：dead 累积 = 处理器缺失/持续失败（本次事故正是 pdf_download dead=203）
    for jt, st in snap.get("iq", {}).items():
        if st.get("dead", 0) > 0:
            alerts.append(f"QUEUE_DEAD({jt}={st['dead']})")
        if st.get("failed", 0) > 50:
            alerts.append(f"QUEUE_FAILED({jt}={st['failed']})")

    # 队列停滞：有待办却无进展（本次事故的另一面——下载死而未察）
    prev_q = prev.get("iq", {})
    for jt, st in snap.get("iq", {}).items():
        pending = st.get("pending", 0)
        if pending <= 0:
            continue
        prev_ok = prev_q.get(jt, {}).get("success", 0)
        now_ok = st.get("success", 0)
        if prev_ok and now_ok <= prev_ok and st.get("running", 0) == 0:
            alerts.append(f"QUEUE_STALLED({jt},pending={pending})")

    if "mongo_error" not in snap:
        if snap["ev_24h"] == 0:
            alerts.append("EVIDENCE_DRY(ev_24h=0)")
        if snap["pending"] > 0 and snap["done_1h"] == 0 and snap["claim_recent"] == 0:
            alerts.append("EXTRACT_STALLED(worker 未领任务)")
        if snap["failed"] > 100:
            alerts.append(f"FAILED_INCRAISED(failed={snap['failed']})")

    for name, t in snap.get("tasks", {}).items():
        if t["cf"] > 0:
            alerts.append(f"TASK_RETRY_FAIL({name},cf={t['cf']})")
        elif t["status"] == "failed" and t["age_h"] is not None and t["age_h"] < 24:
            alerts.append(f"TASK_FAILED({name})")

    record = {
        "ts": datetime.now(UTC).isoformat(timespec="seconds"),
        "alerts": alerts,
        **snap,
    }
    with open("/root/qingshui_monitor/ingest-monitor.log", "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(json.dumps(record, ensure_ascii=False))


if __name__ == "__main__":
    main()
