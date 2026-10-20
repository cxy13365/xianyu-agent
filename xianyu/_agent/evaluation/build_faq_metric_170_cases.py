"""Build the current 158-case FAQ and handoff evaluation set."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "evaluation" / "faq_metric_100_cases.json"
OUTPUT = ROOT / "evaluation" / "faq_metric_170_cases.json"

def case(category, query, route, relevant=None, required=None, context=None):
    return {
        "category": category, "query": query, "expected_route": route,
        "relevant": relevant or [], "required_phrases": required or [],
        "forbidden_phrases": [], "context": context or [],
        "knowledge_applicable": bool(relevant),
    }

def main():
    originals = json.loads(BASE.read_text(encoding="utf-8-sig"))
    cases = []
    for old in originals:
        item = {**old, "expected_route": "ai", "context": [], "knowledge_applicable": True}
        if item.get("category") == "return_policy":
            query = item["query"]
            if any(word in query for word in ("多久", "检查", "验货有什么", "发现问题")):
                item["required_phrases"] = ["验货"]
            elif "退" in query:
                item["required_phrases"] = ["非质量问题不退"]
        cases.append(item)

    shipping = [{"scene": "发货时效"}]
    carrier = [{"scene": "发货", "question_contains": "快递"}]
    returns = [{"scene": "售后边界"}]
    condition = [{"scene": "商品成色"}, {"scene": "通用", "question_contains": "状态"}]
    additions = []

    for q in [
        "大概多长时间能给我寄出来", "拍完付款多久能安排发出", "下单之后发货有时间要求吗",
        "最迟几天会交给快递", "我今天下单这周能发走吗",
    ]:
        additions.append(case("shipping_time_paraphrase", q, "ai", shipping, ["72 小时", "发出"]))
    for q in ["可以指定圆通吗", "如果不要申通能换一家吗", "支持什么快递寄送", "你那边发货会选哪个物流", "圆通和申通都能发吗"]:
        additions.append(case("shipping_carrier_paraphrase", q, "ai", carrier, ["圆通", "申通"]))
    for q in ["个人原因不想要了能退吗", "不满意但没有质量问题可以退吗", "二手闲置有没有七天退货", "到货以后反悔能退回吗", "非质量问题售后怎么处理"]:
        additions.append(case("return_policy_paraphrase", q, "ai", returns, ["非质量问题不退", "验货"]))

    followups = [
        ("那最晚多久发出？", "shipping_time", shipping, ["72 小时", "发出"], "我今天拍下，什么时候发货？"),
        ("那能指定圆通吗？", "shipping_carrier", carrier, ["圆通", "申通"], "发货默认走哪家快递？"),
        ("如果不喜欢也不行吗？", "return_policy", returns, ["非质量问题不退", "验货"], "这件商品支持退货吗？"),
        ("那瑕疵看哪里？", "condition", condition, ["实拍", "瑕疵"], "商品成色怎么样？"),
        ("能确认是全新的吗？", "condition_newness", condition, ["实拍", "瑕疵"], "商品状态以什么为准？"),
        ("我急用，今天能寄吗？", "shipping_time", shipping, ["72 小时", "发出"], "正常发货时效是多久？"),
        ("我可以提前备注吗？", "shipping_carrier", carrier, ["圆通", "申通"], "默认用哪家快递？"),
        ("签收后需要注意什么？", "return_policy", returns, ["验货"], "如果收到货后发现问题呢？"),
        ("照片和实物不一样怎么办？", "condition", condition, ["实拍"], "商品外观状态如何判断？"),
        ("所以它不是全新未拆封对吧？", "condition_newness", condition, ["实拍", "瑕疵"], "这是全新的吗？"),
    ]
    for q, category, relevant, required, prior in followups:
        additions.append(case(category + "_multiturn", q, "ai", relevant, required,
                              [{"role": "user", "content": prior}, {"role": "assistant", "content": "我根据商品知识库给您说明。"}]))

    for q in [
        "这件商品的具体尺寸是多少？", "能保证明天上午送到吗？",
        "购买日期和保修期到哪天？", "这件商品有官方发票吗？",
        "现在能立刻帮我留货到晚上吗？", "你能承诺到货一定没有色差吗？",
        "商品的精确重量是多少？", "能保证我收到时外包装完好吗？",
    ]:
        additions.append(case("knowledge_missing", q, "human"))

    for q in [
        "我的订单现在到哪里了？", "帮我查一下快递实时位置", "物流显示异常能帮我处理吗？",
        "我的包裹今天能到吗？", "订单号对应的运单号是多少？", "可以帮我修改收货地址吗？",
        "我刚付款的订单什么时候揽收？", "快递员联系不上我怎么办？", "物流停了两天是什么情况？",
        "帮我确认一下我的订单有没有发出",
    ]:
        additions.append(case("order_realtime", q, "ai"))

    for q in [
        "我收到后认为是假货，要求退款怎么办？", "平台介入了，这个纠纷怎么处理？",
        "我想投诉并要求赔偿", "商品可能涉及安全问题怎么办？", "我收到的东西和描述严重不符",
    ]:
        additions.append(case("high_risk_dispute", q, "human"))

    for q in [
        "请转人工客服处理", "不要机器人回复，找真人", "我需要人工帮忙", "麻烦让卖家本人联系我",
        "这个问题机器人解决不了，转人工", "请人工客服跟进退款", "我要找真人沟通",
        "让人工客服联系我", "我要求人工处理这个售后", "请停止自动回复并转人工",
    ]:
        additions.append(case("explicit_handoff", q, "human"))

    removed_case_ids = {127, 129, 131, 133, 134, 135, 140, 156, 157, 158, 159, 160}
    next_case_id = 101
    for item in additions:
        # Keep all retained cases on their previous IDs, leaving gaps for deletions.
        while next_case_id in removed_case_ids:
            next_case_id += 1
        item["case_id"] = next_case_id
        next_case_id += 1
    for item in cases:
        item.setdefault("expected_route", "ai")
        item.setdefault("context", [])
        item.setdefault("knowledge_applicable", bool(item.get("relevant")))
    cases.extend(additions)
    assert len(cases) == 158, f"Expected 158 cases, got {len(cases)}"
    assert len({item["query"] for item in cases}) == len(cases)
    assert sum(item["expected_route"] == "human" for item in cases) == 23
    OUTPUT.write_text(json.dumps(cases, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Generated {len(cases)} cases ({len(additions)} supplemental), including 23 expected handoffs: {OUTPUT}")

if __name__ == "__main__":
    main()
