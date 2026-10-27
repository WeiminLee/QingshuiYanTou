import json
import os
from datetime import UTC, datetime

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("MONGODB_URL", "mongodb://localhost:27017/test")
os.environ.setdefault("LLM_API_KEY", "test-key")
os.environ.setdefault("MASTER_PASSWORD", "test-master-pass-1234")
os.environ.setdefault("API_KEY", "test-api-key")

from app.signals.auto_ingestion import ingest_event_signals
from app.signals.event_ingestion import event_to_source_payload, extract_event_signal_records
from app.signals.evidence_ingestion import evidence_to_source_payload, extract_evidence_signal_records_with_kg
from app.signals.extractor import RuleSignalExtractor
from app.signals.research_derivation import _confidence, derive_candidates

BSE_TITLE = "证监会：将推出一系列举措促进北交所新三板一体化高质量发展"
BSE_BODY = "吴清在2026金融街论坛表示，下一步将推出北证50ETF、北交所新股市值配售、创新性评价标准，并优化新三板分层。"
SURVEY_TITLE = "10月以来五家北交所公司获机构调研 订单交付与业务拓展受关注"
ETF_SUMMARY = "北交所新添指数基金入口。北证50ETF若落地，申购资金按指数进入成分股，这是原先没有的资金注入。"
PLACE_SUMMARY = "北交所打新多了一道市值门槛。市值配售若执行，申购资金得先买成成分股，这是新的持仓需求。"


def _event(source: str, title: str, body: str, event_id: str = "EV:bse") -> dict:
    return {
        "event_id": event_id,
        "source": source,
        "title": title,
        "summary": body,
        "content": body,
        "publish_at": datetime(2026, 10, 19, 17, 14, tzinfo=UTC),
        "url": "https://example.test/bse",
        "metadata": {},
    }


def _signal(
    *,
    subject: str = "北交所",
    subject_type: str = "sector",
    landing_form: str = "北证50ETF",
    summary: str = ETF_SUMMARY,
    excerpt: str = "下一步将推出北证50ETF",
    transmission: str = "申购资金按指数进入成分股，这是原先没有的资金入口",
    falsify: str = "ETF不批或没有净申购则这句改号",
    polarity: str = "positive",
    signal_type: str = "policy",
) -> dict:
    return {
        "subject_name": subject,
        "subject_type": subject_type,
        "signal_type": signal_type,
        "polarity": polarity,
        "landing_form": landing_form,
        "transmission": transmission,
        "falsify": falsify,
        "summary": summary,
        "evidence_excerpt": excerpt,
        "strength": 74,
    }


def _response(*signals: dict, new_layer: bool = True, surface: str = "证监会推出一系列举措，这是利好") -> str:
    return json.dumps({"surface": surface, "new_layer": new_layer, "signals": list(signals)}, ensure_ascii=False)


def _llm(payload: str):
    async def _call(prompt: str) -> str:
        _call.prompt = prompt
        return payload

    _call.prompt = ""
    return _call


async def _derive(event: dict, raw: str, prior: list[str] | None = None):
    caller = _llm(raw)
    outcome = await derive_candidates(event_to_source_payload(event), llm=caller, prior_lines=prior or [])
    return outcome, caller.prompt


def test_sync_event_extractor_is_closed():
    with pytest.raises(RuntimeError):
        extract_event_signal_records(_event("eastmoney_flash", BSE_TITLE, BSE_BODY))


@pytest.mark.asyncio
async def test_bse_etf_becomes_one_second_order_signal_and_not_the_headline():
    outcome, _prompt = await _derive(_event("eastmoney_flash", BSE_TITLE, BSE_BODY), _response(_signal()))

    assert outcome.stats["derived"] == 1
    candidate = outcome.candidates[0]
    assert candidate.source_type == "news:llm"
    assert candidate.summary == ETF_SUMMARY
    assert candidate.summary != BSE_TITLE
    assert BSE_TITLE not in candidate.summary
    assert "资金注入" in candidate.summary
    assert candidate.evidence_excerpt == "下一步将推出北证50ETF"
    assert candidate.metadata["derivation"] == "second_order"
    assert candidate.metadata["landing_form"] == "北证50ETF"
    assert candidate.metadata["surface"] == "证监会推出一系列举措，这是利好"
    assert candidate.metadata["event_origin"] == "eastmoney"
    assert candidate.metadata["raw_source"] == "eastmoney_flash"
    assert "一系列举措" not in candidate.summary


@pytest.mark.asyncio
async def test_two_landing_forms_stay_two_signals():
    outcome, _prompt = await _derive(
        _event("eastmoney_flash", BSE_TITLE, BSE_BODY),
        _response(
            _signal(),
            _signal(
                landing_form="市值配售",
                summary=PLACE_SUMMARY,
                excerpt="北交所新股市值配售",
                transmission="打新资金必须先持有北交所市值，这是原先没有的持仓约束",
                falsify="配售规则不落地则这句作废",
            ),
        ),
    )

    forms = {item.metadata["landing_form"] for item in outcome.candidates}
    assert forms == {"北证50ETF", "市值配售"}
    assert len({item.summary for item in outcome.candidates}) == 2


@pytest.mark.asyncio
async def test_same_landing_form_keeps_one_signal_id_when_the_wording_changes():
    first, _prompt = await _derive(_event("eastmoney_flash", BSE_TITLE, BSE_BODY), _response(_signal()))
    second, _prompt = await _derive(
        _event("eastmoney_flash", BSE_TITLE, BSE_BODY),
        _response(_signal(excerpt="将推出北证50ETF", summary=ETF_SUMMARY + "通道没变。")),
    )
    other, _prompt = await _derive(
        _event("eastmoney_flash", BSE_TITLE, BSE_BODY),
        _response(
            _signal(
                landing_form="市值配售",
                summary=PLACE_SUMMARY,
                excerpt="北交所新股市值配售",
            )
        ),
    )

    from app.signals.extractor import stable_signal_id

    assert stable_signal_id(first.candidates[0]) == stable_signal_id(second.candidates[0])
    assert stable_signal_id(first.candidates[0]) != stable_signal_id(other.candidates[0])


@pytest.mark.asyncio
async def test_survey_order_keyword_does_not_enter_signals():
    event = _event("eastmoney_flash", SURVEY_TITLE, SURVEY_TITLE, event_id="EV:survey")
    payload = event_to_source_payload(event)
    assert RuleSignalExtractor().extract(payload), "规则抽到了订单，推导必须把它挡掉"

    outcome, _prompt = await _derive(
        event,
        _response(
            _signal(
                landing_form="订单交付",
                signal_type="order",
                summary="机构问询把订单交付推进了公开讨论，这是新的关注点。",
                excerpt="订单交付与业务拓展受关注",
                transmission="问询本身不改变交付，只是把话题放到了台面上",
            )
        ),
    )

    assert outcome.candidates == []
    assert "form_not_specific" in outcome.rejected


COMPUTE_TITLE = "算力需求转化为经营增量 产业链盈利弹性增强"
COMPUTE_BODY = "算力需求向产业链传导。高端覆铜板、印制电路板等环节盈利改善。服务器、计算与存储芯片销售增长。"
JD_TITLE = "京东成立京玩互娱网络科技公司"
JD_BODY = "京东成立北京京玩互娱网络科技有限公司。经营范围包含：文具用品批发；文具用品零售；组织文化艺术交流活动；动漫游戏开发等。"
MINIMAX_TITLE = "花旗：MiniMax新模型是关键里程碑 凸显行业转向企业级智能体工作流"
MINIMAX_BODY = "MiniMax周一晚间发布M3.1 Flash模型，并称实现了推理速度提升3倍、成本降低70%。花旗称，该模型巩固了MiniMax的竞争地位，并可能加速其在开发者及企业生态系统中的B2B变现进程。"
CITIC_TITLE = "中信建投：建议关注企业级AI应用、算力服务及国产芯片和超节点"
CITIC_BODY = "DeepSeek API价格不变，并开放搜索与抓取接口。智谱发布法律专用模型。阶跃披露长程Agent训练方案。"


@pytest.mark.asyncio
async def test_result_words_are_not_a_landing_form_even_with_a_shift_sentence():
    outcome, _prompt = await _derive(
        _event("eastmoney_flash", COMPUTE_TITLE, COMPUTE_BODY, "EV:compute"),
        _response(
            _signal(
                subject="高端覆铜板、印制电路板",
                subject_type="sector",
                signal_type="earnings",
                landing_form="盈利改善",
                summary="算力需求从芯片采购向高端覆铜板的利润率传导。盈利改善若只是涨价，这句改号。",
                excerpt="高端覆铜板、印制电路板等环节盈利改善",
                transmission="涨价把需求推进了覆铜板的利润",
                falsify="依据不足",
            )
        ),
    )
    assert outcome.candidates == []
    assert "form_not_specific" in outcome.rejected


@pytest.mark.asyncio
async def test_first_batch_thin_rows_stay_out():
    profit, _prompt = await _derive(
        _event("eastmoney_flash", COMPUTE_TITLE, COMPUTE_BODY, "EV:compute"),
        _response(
            _signal(
                subject="高端覆铜板、印制电路板",
                subject_type="sector",
                signal_type="earnings",
                landing_form="盈利改善",
                summary="算力需求向高端覆铜板、印制电路板传导，推动盈利改善",
                excerpt="高端覆铜板、印制电路板等环节盈利改善",
                transmission="算力需求推动该环节盈利改善",
                falsify="依据不足",
            ),
            _signal(
                subject="服务器、计算与存储芯片",
                subject_type="sector",
                signal_type="earnings",
                landing_form="销售增长",
                summary="算力需求向服务器、计算与存储芯片传导，推动销售增长",
                excerpt="服务器、计算与存储芯片销售增长",
                transmission="算力需求推动该环节销售增长",
                falsify="依据不足",
            ),
        ),
    )
    jd, _prompt = await _derive(
        _event("eastmoney_flash", JD_TITLE, JD_BODY, "EV:jd"),
        _response(
            _signal(
                subject="北京京玩互娱网络科技有限公司",
                subject_type="company",
                signal_type="policy",
                landing_form="动漫游戏开发",
                summary="京东通过全资设立新公司切入动漫游戏开发赛道，拓展了其在泛娱乐及数字内容领域的业务布局。",
                excerpt="经营范围包含：文具用品批发；文具用品零售；组织文化艺术交流活动；动漫游戏开发等。",
                transmission="新公司把经营范围扩到动漫游戏开发",
                falsify="依据不足",
            )
        ),
    )
    minimax, _prompt = await _derive(
        _event("eastmoney_flash", MINIMAX_TITLE, MINIMAX_BODY, "EV:minimax"),
        _response(
            _signal(
                subject="MiniMax",
                subject_type="company",
                signal_type="capacity",
                landing_form="M3.1 Flash模型",
                summary="MiniMax通过M3.1 Flash模型实现推理速度与成本效率的显著优化，标志着其竞争重心向端到端智能体工作流转移，进而加速B2B商业化进程。",
                excerpt="MiniMax周一晚间发布M3.1 Flash模型，并称实现了推理速度提升3倍、成本降低70%。",
                transmission="推理变快、成本下降，竞争重心转向企业级工作流",
                falsify="依据不足",
            )
        ),
    )

    assert profit.candidates == []
    assert jd.candidates == []
    assert minimax.candidates == []
    assert "form_not_specific" in profit.rejected
    assert "summary_no_shift" in jd.rejected
    assert "summary_no_shift" in minimax.rejected


@pytest.mark.asyncio
async def test_named_product_with_a_channel_shift_still_enters():
    outcome, _prompt = await _derive(
        _event("eastmoney_flash", MINIMAX_TITLE, MINIMAX_BODY, "EV:minimax"),
        _response(
            _signal(
                subject="MiniMax",
                subject_type="company",
                signal_type="capacity",
                landing_form="M3.1 Flash模型",
                summary="M3.1 Flash模型把推理从按次的高成本到企业级工作流铺得开的调用。若调用量不涨，则这句改号。",
                excerpt="MiniMax周一晚间发布M3.1 Flash模型",
                transmission="单次推理成本下降之后，企业级工作流的调用量才放得开",
                falsify="若开发者调用量不随降价上升，则这句改号",
            )
        ),
        ["MiniMax：推理仍是按次的高成本"],
    )
    assert len(outcome.candidates) == 1
    assert outcome.candidates[0].metadata["landing_form"] == "M3.1 Flash模型"


@pytest.mark.asyncio
async def test_invented_prior_regime_does_not_enter():
    ant_title = "蚂蚁百灵开源Ming-3.0语音系列模型"
    ant_body = "蚂蚁百灵开源Ming-3.0语音系列，分别提供语音合成、音频理解与对话、语音识别三个系列。开发者可以将不同能力组合进自己的工作流。"
    ant, _prompt = await _derive(
        _event("eastmoney_flash", ant_title, ant_body, "EV:ant"),
        _response(
            _signal(
                subject="蚂蚁百灵",
                subject_type="company",
                signal_type="capacity",
                landing_form="开源Ming-3.0语音系列",
                summary="从封闭模型向开源Ming-3.0语音系列开放，开发者可组合能力进工作流。",
                excerpt="蚂蚁百灵开源Ming-3.0语音系列",
                transmission="开源之后开发者可以自己组合语音能力",
                falsify="依据不足",
            )
        ),
    )
    scene_title = "首批标志性重大应用场景项目发布 向民营企业开放"
    scene_body = "国家发展改革委等部门联合发布首批136项标志性重大场景项目，向民营企业开放，并提供场景验证空间。"
    scene, _prompt = await _derive(
        _event("eastmoney_flash", scene_title, scene_body, "EV:scene"),
        _response(
            _signal(
                subject="国家发展改革委等部门",
                subject_type="policy",
                signal_type="policy",
                landing_form="首批136项标志性重大场景项目",
                summary="从无明确准入向民营企业开放，通过首批136项标志性重大场景项目提供场景验证空间。",
                excerpt="首批136项标志性重大场景项目，向民营企业开放",
                transmission="项目清单把场景验证开放给民营企业",
                falsify="依据不足",
            )
        ),
    )
    assert ant.candidates == []
    assert scene.candidates == []
    assert "shift_ungrounded" in ant.rejected
    assert "shift_ungrounded" in scene.rejected


@pytest.mark.asyncio
async def test_from_to_without_watermark_or_source_is_rejected():
    outcome, _prompt = await _derive(
        _event("eastmoney_flash", CITIC_TITLE, CITIC_BODY, "EV:citic"),
        _response(
            _signal(
                subject="DeepSeek",
                subject_type="company",
                signal_type="capacity",
                landing_form="开放搜索与抓取接口",
                summary="DeepSeek通过开放搜索与抓取接口，从单纯算力/模型输出向具备实时数据获取能力的Agent形态演进，降低了企业级AI应用开发的数据获取门槛。",
                excerpt="API价格不变，并开放搜索与抓取接口",
                transmission="模型输出多了实时抓取，开发侧不用自建数据入口",
                falsify="若后续API调用量未随接口开放而显著增长，则改号。",
            )
        ),
    )
    assert outcome.candidates == []
    assert "shift_ungrounded" in outcome.rejected


@pytest.mark.asyncio
async def test_first_batch_named_channels_still_enter():
    outcome, _prompt = await _derive(
        _event("eastmoney_flash", CITIC_TITLE, CITIC_BODY, "EV:citic"),
        _response(
            _signal(
                subject="DeepSeek",
                subject_type="company",
                signal_type="capacity",
                landing_form="开放搜索与抓取接口",
                summary="DeepSeek通过开放搜索与抓取接口，从单纯算力/模型输出向具备实时数据获取能力的Agent形态演进，降低了企业级AI应用开发的数据获取门槛。",
                excerpt="API价格不变，并开放搜索与抓取接口",
                transmission="模型输出多了实时抓取，开发侧不用自建数据入口",
                falsify="若后续API调用量未随接口开放而显著增长，或第三方测评中因数据抓取导致准确率下降，则改号。",
            ),
            _signal(
                subject="智谱",
                subject_type="company",
                signal_type="capacity",
                landing_form="发布法律专用模型",
                summary="智谱发布法律专用模型，标志着AI应用从通用能力向垂直行业深度渗透，验证了通用底座再微调的企业级应用落地路径。",
                excerpt="智谱发布法律专用模型",
                transmission="通用模型之外多了一条垂直微调的交付通道",
                falsify="若该模型在真实法律场景中的采纳率极低，或通用大模型通过微调迅速覆盖该领域，则改号。",
            ),
            _signal(
                subject="阶跃",
                subject_type="company",
                signal_type="capacity",
                landing_form="披露长程Agent训练方案",
                summary="阶跃披露长程Agent训练方案，表明AI能力正从单点任务执行向长周期、多步骤的复杂任务编排演进，对算力服务的持续性和稳定性提出更高要求。",
                excerpt="阶跃披露长程Agent训练方案",
                transmission="任务从单步变成多步编排，算力要持续在线",
                falsify="若该训练方案在实际长程任务中失败率未显著降低，或通用模型通过架构优化实现同等长程能力，则改号。",
            ),
        ),
        [
            "DeepSeek：单纯算力/模型输出，没有搜索接口",
            "智谱：通用能力覆盖法律以外的任务",
            "阶跃：单点任务执行已有方案",
        ],
    )
    forms = {item.metadata["landing_form"] for item in outcome.candidates}
    assert forms == {"开放搜索与抓取接口", "发布法律专用模型", "披露长程Agent训练方案"}


@pytest.mark.asyncio
async def test_no_new_layer_writes_nothing_even_if_a_signal_is_attached():
    outcome, _prompt = await _derive(
        _event("eastmoney_flash", SURVEY_TITLE, SURVEY_TITLE, event_id="EV:survey"),
        _response(_signal(), new_layer=False),
    )
    assert outcome.candidates == []
    assert outcome.stats["no_new_layer"] == 1
    assert outcome.stats["derived"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"evidence_excerpt": "北证50ETF已经获批发行"}, "excerpt_not_in_source"),
        ({"landing_form": "沪深300ETF"}, "form_not_in_source"),
        ({"landing_form": "一系列举措", "summary": "一系列举措打开了新的资金口。北交所因此多了一条入口。"}, "form_not_specific"),
        ({"subject_name": "政策主题"}, "subject_banned"),
        ({"subject_name": "沪深300"}, "subject_not_in_source"),
        ({"summary": BSE_BODY}, "summary_is_surface"),
        ({"falsify": ""}, "missing_falsify"),
    ],
)
async def test_ungrounded_signal_is_rejected(overrides, reason):
    item = _signal()
    item.update(overrides)
    outcome, _prompt = await _derive(_event("eastmoney_flash", BSE_TITLE, BSE_BODY), _response(item))
    assert outcome.candidates == []
    assert reason in outcome.rejected


@pytest.mark.asyncio
async def test_price_tape_skips_the_model():
    called = {"llm": False}

    async def boom(prompt: str) -> str:
        called["llm"] = True
        raise AssertionError(prompt)

    event = _event("eastmoney_flash", "创业板跌超2%", "创业板跌超2%，两市成交额萎缩。", event_id="EV:tape")
    outcome = await derive_candidates(event_to_source_payload(event), llm=boom, prior_lines=[])
    assert called["llm"] is False
    assert outcome.candidates == []
    assert outcome.stats["skipped_tape"] == 1


@pytest.mark.asyncio
async def test_tape_plus_mechanism_still_goes_to_research():
    called = {"llm": False}

    async def answer(prompt: str) -> str:
        called["llm"] = True
        return _response(new_layer=False)

    event = _event(
        "eastmoney_flash",
        "创业板跌超2%",
        "创业板跌超2%，证监会表示下一步将推出北证50ETF。",
        event_id="EV:mixed",
    )
    outcome = await derive_candidates(event_to_source_payload(event), llm=answer, prior_lines=[])
    assert called["llm"] is True
    assert outcome.stats["no_new_layer"] == 1


@pytest.mark.asyncio
async def test_prior_signals_are_the_watermark_in_the_prompt():
    prior = ["北交所：浙商证券签署北交所保荐协议，没有指数基金入口"]
    _outcome, prompt = await _derive(_event("eastmoney_flash", BSE_TITLE, BSE_BODY), _response(_signal()), prior)
    assert prior[0] in prompt
    assert "已有水位" in prompt
    assert "删句" in prompt
    assert "旧状态只能引用已有水位" in prompt
    assert "summary 必须原样包含落地形式" in prompt


@pytest.mark.asyncio
async def test_repeating_the_watermark_is_rejected():
    prior = [f"北交所：{ETF_SUMMARY}"]
    outcome, _prompt = await _derive(_event("eastmoney_flash", BSE_TITLE, BSE_BODY), _response(_signal()), prior)
    assert outcome.candidates == []
    assert "summary_repeats_watermark" in outcome.rejected


@pytest.mark.asyncio
async def test_llm_failure_writes_nothing_and_does_not_fall_back_to_rules():
    event = _event("cls", "十五五规划强调算力基础设施", "十五五规划强调算力基础设施建设。", event_id="EV:policy")
    assert RuleSignalExtractor().extract(event_to_source_payload(event))

    async def broken(prompt: str) -> str:
        raise TimeoutError("down")

    failed = await derive_candidates(event_to_source_payload(event), llm=broken, prior_lines=[])
    assert failed.candidates == []
    assert failed.stats["derivation_failed"] == 1

    garbage = await derive_candidates(
        event_to_source_payload(event),
        llm=_llm("我觉得这是利好，政策加码。"),
        prior_lines=[],
    )
    assert garbage.candidates == []
    assert garbage.stats["derivation_failed"] == 1


@pytest.mark.asyncio
async def test_watermark_lookup_failure_does_not_call_the_model(monkeypatch):
    async def down(terms, **kwargs):
        raise RuntimeError("timeout")

    async def boom(prompt: str) -> str:
        raise AssertionError(prompt)

    monkeypatch.setattr("app.signals.research_derivation.lookup_prior_signal_lines", down)
    monkeypatch.setattr("app.signals.research_derivation._call_llm", boom)
    outcome = await derive_candidates(event_to_source_payload(_event("eastmoney_flash", BSE_TITLE, BSE_BODY)))
    assert outcome.candidates == []
    assert outcome.stats["derivation_failed"] == 1
    assert outcome.rejected == ["watermark_unavailable"]


@pytest.mark.asyncio
async def test_default_llm_uses_the_extraction_model_with_thinking_off(monkeypatch):
    seen: dict = {}

    async def model() -> str:
        return "Qwen3.6-35B-A3B"

    async def chat(prompt: str, **kwargs):
        seen["prompt"] = prompt
        seen.update(kwargs)
        return _response(new_layer=False)

    monkeypatch.setattr("app.core.llm_client.get_extraction_model", model)
    monkeypatch.setattr("app.core.llm_client.chat_async", chat)
    outcome = await derive_candidates(
        event_to_source_payload(_event("eastmoney_flash", BSE_TITLE, BSE_BODY)),
        prior_lines=["北交所：已有保荐，没有指数基金"],
    )
    assert outcome.stats["no_new_layer"] == 1
    assert seen["model"] == "Qwen3.6-35B-A3B"
    assert seen["force_disable_thinking"] is True


@pytest.mark.asyncio
async def test_pboc_and_cls_land_on_their_lanes():
    pboc, _prompt = await _derive(
        _event("pboc", "央行：创设北交所互换便利工具", "央行决定创设北交所互换便利工具，用于北证50ETF的流动性支持。", "EV:pboc"),
        _response(
            _signal(
                summary="北交所多了互换便利工具这条流动性通道。质押品范围是原先没有的。",
                excerpt="创设北交所互换便利工具",
                landing_form="互换便利工具",
                transmission="北证50ETF可以拿来做质押，这是新的流动性通道",
            )
        ),
    )
    cls, _prompt = await _derive(
        _event("财联社", BSE_TITLE, BSE_BODY, "EV:cls"),
        _response(_signal()),
    )
    assert pboc.candidates[0].source_type == "event:llm"
    assert pboc.candidates[0].metadata["event_origin"] == "pboc"
    assert cls.candidates[0].source_type == "news:llm"
    assert cls.candidates[0].metadata["event_origin"] == "cls"


@pytest.mark.asyncio
async def test_announcement_and_irm_evidence_do_not_fall_back_to_rules():
    announcement = {
        "evidence_id": "EV:ann",
        "source_type": "announcement",
        "source_name": "重大合同公告",
        "text_excerpt": "测试公司样机验证后签订重大合同，相关产品进入规模化交付阶段。",
        "subject_hint": {"title": "测试公司签订重大合同"},
        "metadata": {},
    }
    assert RuleSignalExtractor().extract(evidence_to_source_payload(announcement))
    empty, propagations = await extract_evidence_signal_records_with_kg(
        announcement,
        llm=_llm(_response(new_layer=False)),
        prior_lines=[],
    )
    assert empty == []
    assert propagations == []

    accepted, propagations = await extract_evidence_signal_records_with_kg(
        announcement,
        llm=_llm(
            _response(
                _signal(
                    subject="测试公司",
                    subject_type="company",
                    signal_type="order",
                    landing_form="重大合同",
                    summary="测试公司新进入该客户的合格供方。重大合同若生效，供货从样机变成持续交付。",
                    excerpt="签订重大合同",
                    transmission="供货从验证变成持续交付，这是新的收入入口",
                    falsify="合同不生效则这句作废",
                )
            )
        ),
        prior_lines=[],
    )
    assert len(accepted) == 1
    assert accepted[0]["source_type"] == "announcement:llm"
    assert accepted[0]["summary"].startswith("测试公司新进入")
    assert accepted[0]["metadata_"]["derivation"] == "second_order"
    assert propagations == []

    irm, _props = await extract_evidence_signal_records_with_kg(
        {**announcement, "evidence_id": "EV:irm", "source_type": "irm"},
        llm=_llm(
            _response(
                _signal(
                    subject="测试公司",
                    subject_type="company",
                    signal_type="order",
                    landing_form="重大合同",
                    summary="测试公司新进入该客户的合格供方。重大合同若生效，供货从样机变成持续交付。",
                    excerpt="签订重大合同",
                    transmission="供货从验证变成持续交付，这是新的收入入口",
                    falsify="依据不足",
                )
            )
        ),
        prior_lines=[],
    )
    assert irm[0]["source_type"] == "irm:llm"
    assert irm[0]["metadata_"]["falsify"] == "依据不足"

    async def broken(prompt: str) -> str:
        raise TimeoutError("down")

    with pytest.raises(RuntimeError, match="signal derivation failed"):
        await extract_evidence_signal_records_with_kg(announcement, llm=broken, prior_lines=[])


@pytest.mark.asyncio
async def test_market_evidence_still_uses_rules():
    signals, _propagations = await extract_evidence_signal_records_with_kg(
        {
            "evidence_id": "EV:mkt",
            "source_type": "market",
            "source_name": "行情",
            "text_excerpt": "公司签订重大合同。",
            "subject_hint": {"title": "行情播报"},
            "metadata": {},
        }
    )
    assert signals
    assert {row["source_type"] for row in signals} == {"market"}
    assert "order" in {row["signal_type"] for row in signals}


class _Session:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def commit(self):
        return None


@pytest.mark.asyncio
async def test_ingest_upserts_the_derived_sentence_and_skips_tape(monkeypatch):
    saved: list[dict] = []

    async def lookup(terms, **kwargs):
        assert "北交所" in terms
        return ["北交所：浙商证券签署北交所保荐协议"]

    async def llm(prompt: str) -> str:
        assert "浙商证券签署北交所保荐协议" in prompt
        return _response(_signal())

    async def upsert(session, signals, propagations):
        assert propagations == []
        saved.extend(signals)
        return len(signals), 0

    monkeypatch.setattr("app.signals.research_derivation.lookup_prior_signal_lines", lookup)
    monkeypatch.setattr("app.signals.research_derivation._call_llm", llm)
    monkeypatch.setattr("app.signals.auto_ingestion.async_session", lambda: _Session())
    monkeypatch.setattr("app.signals.auto_ingestion._upsert_signal_records", upsert)

    result = await ingest_event_signals([_event("eastmoney_flash", BSE_TITLE, BSE_BODY)])
    assert result["signals_upserted"] == 1
    assert result["derived"] == 1
    assert saved[0]["source_type"] == "news:llm"
    assert saved[0]["summary"] == ETF_SUMMARY
    assert saved[0]["metadata_"]["derivation"] == "second_order"
    assert saved[0]["metadata_"]["surface"] != saved[0]["summary"]

    def no_db():
        raise AssertionError("tape must not open a session")

    monkeypatch.setattr("app.signals.auto_ingestion.async_session", no_db)
    skipped = await ingest_event_signals(
        [_event("eastmoney_flash", "创业板跌超2%", "创业板跌超2%，两市成交额萎缩。", "EV:tape")]
    )
    assert skipped["signals_upserted"] == 0
    assert skipped["skipped_tape"] == 1


def _calls():
    prompts: list[str] = []

    def script(*payloads: str):
        async def _call(prompt: str) -> str:
            index = _call.n
            _call.n += 1
            prompts.append(prompt)
            if index >= len(payloads):
                raise AssertionError("extra llm call")
            payload = payloads[index]
            if isinstance(payload, BaseException):
                raise payload
            return payload

        _call.n = 0
        return _call

    return prompts, script


@pytest.mark.asyncio
async def test_missing_form_in_summary_is_rewritten_once():
    prompts, script = _calls()
    missing = _signal(
        summary="北交所新添指数基金入口。若落地，申购资金按指数进入成分股，这是原先没有的资金注入。",
    )
    outcome = await derive_candidates(
        event_to_source_payload(_event("eastmoney_flash", BSE_TITLE, BSE_BODY)),
        llm=script(_response(missing), _response(_signal())),
        prior_lines=[],
    )
    assert len(prompts) == 2
    assert "落地形式没有原样出现在摘要里" in prompts[1]
    assert outcome.stats["derived"] == 1
    assert outcome.candidates[0].summary == ETF_SUMMARY


@pytest.mark.asyncio
async def test_missing_shift_is_rewritten_once():
    prompts, script = _calls()
    flat = _signal(
        summary="北交所若推出指数基金，北证50ETF会把申购资金按指数送进成分股，成分股因此多出一笔配置需求。",
    )
    outcome = await derive_candidates(
        event_to_source_payload(_event("eastmoney_flash", BSE_TITLE, BSE_BODY)),
        llm=script(_response(flat), _response(_signal())),
        prior_lines=[],
    )
    assert len(prompts) == 2
    assert "摘要没有写出通道变化" in prompts[1]
    assert outcome.candidates[0].summary == ETF_SUMMARY


@pytest.mark.asyncio
async def test_second_miss_still_writes_nothing():
    prompts, script = _calls()
    missing = _signal(
        summary="北交所新添指数基金入口。若落地，申购资金按指数进入成分股，这是原先没有的资金注入。",
    )
    outcome = await derive_candidates(
        event_to_source_payload(_event("eastmoney_flash", BSE_TITLE, BSE_BODY)),
        llm=script(_response(missing), _response(missing)),
        prior_lines=[],
    )
    assert len(prompts) == 2
    assert outcome.candidates == []
    assert outcome.stats["derived"] == 0
    assert "form_not_in_summary" in outcome.rejected


@pytest.mark.asyncio
async def test_invented_form_and_prior_do_not_get_a_rewrite():
    prompts, script = _calls()
    invented_form = _signal(landing_form="封闭模型接口", excerpt="下一步将推出北证50ETF")
    await derive_candidates(
        event_to_source_payload(_event("eastmoney_flash", BSE_TITLE, BSE_BODY)),
        llm=script(_response(invented_form)),
        prior_lines=[],
    )
    invented_prior = _signal(
        summary="北交所从封闭发行向北证50ETF开放，这是新的资金入口。",
        landing_form="北证50ETF",
        excerpt="下一步将推出北证50ETF",
    )
    await derive_candidates(
        event_to_source_payload(_event("eastmoney_flash", BSE_TITLE, BSE_BODY)),
        llm=script(_response(invented_prior)),
        prior_lines=[],
    )
    assert len(prompts) == 2


@pytest.mark.asyncio
async def test_retry_call_failure_keeps_the_first_rejection():
    prompts, script = _calls()
    missing = _signal(
        summary="北交所新添指数基金入口。若落地，申购资金按指数进入成分股，这是原先没有的资金注入。",
    )
    outcome = await derive_candidates(
        event_to_source_payload(_event("eastmoney_flash", BSE_TITLE, BSE_BODY)),
        llm=script(_response(missing), TimeoutError("down")),
        prior_lines=[],
    )
    assert len(prompts) == 2
    assert outcome.candidates == []
    assert outcome.stats["derivation_failed"] == 0
    assert outcome.rejected == ["form_not_in_summary"]


@pytest.mark.asyncio
async def test_no_new_layer_is_not_rewritten():
    prompts, script = _calls()
    outcome = await derive_candidates(
        event_to_source_payload(_event("eastmoney_flash", BSE_TITLE, BSE_BODY)),
        llm=script(_response(new_layer=False)),
        prior_lines=[],
    )
    assert len(prompts) == 1
    assert outcome.stats["no_new_layer"] == 1


def test_confidence_is_not_a_flat_constant():
    # 同强度下，写得出证伪的置信高于写不出（依据不足）的
    assert _confidence(80, "ETF 不批则改号") > _confidence(80, "依据不足")
    # 强度越高，置信越高
    assert _confidence(100, "证伪") > _confidence(50, "证伪")
    # 始终落在 [0.50, 0.95]，不再是一个固定的 0.8
    for strength in range(1, 101):
        assert 0.50 <= _confidence(strength, "证伪条件") <= 0.95
        assert 0.50 <= _confidence(strength, "依据不足") <= 0.95


def test_channel_shift_accepts_natural_channel_words():
    from app.signals.research_derivation import _states_channel_shift

    assert _states_channel_shift("项目被锁定为合同项下分节点收款与收入确认通道。")
    assert _states_channel_shift("业务整体迁移至子公司承接运营，改变了承载主体。")
    assert _states_channel_shift("注册资本增加至6亿元，打开了资本金通道。")
    assert not _states_channel_shift("公司收入增长，利润改善。")


@pytest.mark.asyncio
async def test_ellipsis_excerpt_keeps_the_contiguous_segment():
    signal = _signal(excerpt="下一步将推出北证50ETF...并优化新三板分层")
    outcome, _prompt = await _derive(
        _event("eastmoney_flash", BSE_TITLE, BSE_BODY),
        _response(signal),
    )
    assert outcome.stats["derived"] == 1
    assert outcome.candidates[0].evidence_excerpt == "下一步将推出北证50ETF"
    assert "..." not in outcome.candidates[0].evidence_excerpt


@pytest.mark.asyncio
async def test_landing_form_only_in_title_is_rejected_and_retried():
    prompts, script = _calls()
    title_form = _signal(
        subject="参股公司",
        subject_type="company",
        landing_form="向参股公司增资暨关联交易",
        summary="向参股公司增资暨关联交易打开了资本金通道，改善参股公司资金结构。",
        excerpt="公司拟对参股公司进行增资",
        transmission="增资改变了参股公司的资本金通道",
        falsify="若增资未实施则改号",
    )
    event = _event(
        "eastmoney_flash",
        "关于向参股公司增资暨关联交易的公告",
        "公司拟对参股公司进行增资，具体方案另行公告。",
    )
    outcome = await derive_candidates(
        event_to_source_payload(event),
        llm=script(_response(title_form), _response(title_form)),
        prior_lines=[],
    )
    assert len(prompts) == 2
    assert "form_only_in_title" in outcome.rejected
    assert outcome.candidates == []


def test_summary_prompt_placeholder_is_stripped():
    from app.signals.research_derivation import _clean_summary

    assert _clean_summary("删句后的二阶导：公司通过协议打通了融资通道。") == "公司通过协议打通了融资通道。"
    assert _clean_summary("删句后，公司通过协议打通了融资通道。") == "公司通过协议打通了融资通道。"
    assert _clean_summary("【summary】公司通过协议打通了融资通道。") == "公司通过协议打通了融资通道。"
    assert _clean_summary("公司通过协议打通了融资通道。") == "公司通过协议打通了融资通道。"


@pytest.mark.asyncio
async def test_proposal_form_is_rejected():
    proposal = _signal(
        subject="封测工厂",
        subject_type="product",
        landing_form="关于公司拟对外投资的议案",
        summary="关于公司拟对外投资的议案打通了资本金通道，用于封测工厂建设。",
        excerpt="公司审议通过《关于公司拟对外投资的议案》",
        transmission="该议案打通了封测工厂的资本金通道",
        falsify="若投资未实施则改号",
    )
    event = _event(
        "eastmoney_flash",
        "关于公司拟对外投资的公告",
        "公司审议通过《关于公司拟对外投资的议案》，拟投资建设封测工厂。",
    )
    outcome, _prompt = await _derive(event, _response(proposal))
    assert "form_not_specific" in outcome.rejected
    assert outcome.candidates == []
