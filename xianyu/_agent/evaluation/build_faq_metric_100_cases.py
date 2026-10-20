"""Generate 100 deterministic, labeled common-FAQ paraphrase cases."""
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
GROUPS=[
 {"category":"shipping_time","relevant":[{"scene":"发货时效"}],"required":["72 小时","发出"],"queries":[
 "今天拍下多久能发货","今天拍下多久寄出","下单以后一般几小时发出","下单后最晚什么时候发货","我现在拍大概什么时候能寄","今天下单预计多久发出","下单后要等多久才发货","付款后多久能发","平时多久可以寄出","正常发货时效是多久","急用的话当天能不能发","什么时候能安排快递","拍下商品后几小时内发货","付款后多长时间发出","今天买什么时候能寄","一般几天内可以发货","下单后多久交给快递","拍下后多久能发出","发货大概需要等几天","发货时间通常是多久"]},
 {"category":"shipping_carrier","relevant":[{"scene":"发货","question_contains":"快递"}],"required":["圆通","申通"],"queries":[
 "默认用什么快递发","发货走哪家快递","你们一般发哪家快递","能用圆通还是申通","店里默认快递是哪家","一般是圆通还是申通","买了之后用哪个快递寄","发货物流是哪一家","通常通过什么快递发出","可以告诉我发货公司吗","你们默认发哪家快递","寄件一般选什么快递","请问商品走什么物流","下单后会用哪家快递","发货是圆通还是申通","默认快递公司是什么","你们发货用哪家物流","一般用哪种快递寄出","可以指定快递吗默认是哪家","这边通常发什么快递"]},
 {"category":"return_policy","relevant":[{"scene":"售后边界"}],"required":["非质量问题不退","验货"],"queries":[
 "收到后不喜欢可以退吗","没有质量问题能退货吗","到手后觉得不合适支持退吗","商品不满意可以申请退货吗","非质量问题能不能退","签收后可以反悔退货吗","收到货不想要了能退吗","二手商品支持无理由退货吗","如果只是个人原因可以退吗","质量没问题但不喜欢能退吗","不合适可以退回去吗","签收后多久需要验货","收到商品后要不要马上检查","商品无瑕疵可以退吗","买家原因退货可以吗","收到货发现问题该怎么处理","到货后验货有什么要求","可以七天无理由退货吗","不喜欢这个商品售后怎么处理","签收后发现问题要及时做什么"]},
 {"category":"condition","relevant":[{"scene":"商品成色"},{"scene":"通用","question_contains":"状态"}],"required":["实拍","瑕疵"],"queries":[
 "这个商品的成色和状态怎么样","商品有瑕疵吗怎么看状态","这件东西成色如何","外观状态以什么为准","商品划痕磕碰情况怎么样","有捏痕或者明显瑕疵吗","能看看实物成色吗","商品状态是全新的吗","成色和手感怎么样","物品有无划痕瑕疵","实物状态可以看哪里","商品新旧程度如何判断","有没有瑕疵请说明一下","商品外观成色怎么样","这件商品的实际状态如何","状态和手感以什么为准","商品有没有磕碰痕迹","成色是否和图片一致","可以通过视频看商品状态吗","商品默认按什么成色描述"]},
 {"category":"condition_newness","relevant":[{"scene":"商品成色"},{"scene":"通用","question_contains":"状态"}],"required":["实拍","瑕疵"],"queries":[
 "这个是全新的吗","商品是不是未拆封的","有使用痕迹吗","买来以后用过没有","商品看上去新不新","这是二手还是全新的","外观有没有使用痕迹","能确认商品是不是全新吗","物品有没有磨损","表面划痕多不多","实物跟照片成色一样吗","商品有没有明显损伤","是不是全新未使用","能介绍一下新旧程度吗","图里看起来很新实际呢","是否存在小缺陷或瑕疵","有无需要特别说明的成色问题","商品的实际磨损情况如何","能发视频确认商品成色吗","商品状态以什么资料为准"]}
]
def main():
 cases=[]
 for group in GROUPS:
  assert len(group["queries"])==20
  for query in group["queries"]:
   cases.append({"case_id":len(cases)+1,"category":group["category"],"query":query,
    "relevant":group["relevant"],"required_phrases":group["required"],"forbidden_phrases":[]})
 assert len(cases)==100 and len({x["query"] for x in cases})==100
 path=ROOT/"evaluation"/"faq_metric_100_cases.json"
 path.write_text(json.dumps(cases,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
 print(f"Generated {len(cases)} unique cases: {path}")
if __name__=="__main__":main()

