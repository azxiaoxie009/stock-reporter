#!/usr/bin/env python3
"""
A股投资报告生成器 - 早报 / 盘尾 / 周末版
GitHub Actions云端定时运行
用法：python3 generate_report.py [morning|afternoon|weekend]
"""
from __future__ import annotations
import os, requests, datetime, re, sys

os.environ["TZ"] = "Asia/Shanghai"
try:
    import time as _time
    _time.tzset()
except AttributeError:
    pass

# ── 用户配置 ─────────────────────────────────────────────
TOTAL_CASH = 150000.0
MAX_STOCKS = 4
# 【重要】如有仓位调整，请通知"仓位调整"，本列表由用户确认（2026-04-17起生效）
HOLDINGS = [
    {"code":"002223","name":"鱼跃医疗","shares":700,"cost":36.959,
     "tags":["医药","医疗器械","养老","医保","健康","中药","集采"],
     "watch":"集采降价、医疗器械政策、老龄化"},
    {"code":"002142","name":"宁波银行","shares":600,"cost":29.898,
     "tags":["银行","降息","降准","房地产","信贷","LPR","息差","存款"],
     "watch":"房地产风险、净息差、业绩增速"},
    {"code":"002736","name":"国信证券","shares":1000,"cost":17.216,
     "tags":["券商","注册制","IPO","北交所","资本市场","两融","投行","并购"],
     "watch":"成交量、两融余额、IPO节奏"},
]
SMTP_USER = "704901171@qq.com"
SMTP_PASS = "yoyqmwluklabbcic"
SMTP_HOST = "smtp.qq.com"
SMTP_PORT = 465
# ─────────────────────────────────────────────────────────

def fetch_quotes():
    result = {}
    try:
        r = requests.get(
            "https://push2.eastmoney.com/api/qt/ulist.np/get"
            "?fltt=2&invt=2"
            "&fields=f2,f3,f4,f15,f16,f18,f12,f14"
            "&secids=1.000001,0.399001,0.399006,1.000300,1.000985"
            "&ut=fa5fd1943c7b386f172d6893dbfba10b",
            headers={"Referer":"https://quote.eastmoney.com","User-Agent":"Mozilla/5.0"},
            timeout=10)
        d = r.json()
        key_map = {"000001":"sh000001","399001":"sz399001","399006":"sz399006",
                   "000300":"sh000300","000985":"sh000985"}
        for item in d.get("data",{}).get("diff",[]):
            code = str(item.get("f12",""))
            key = key_map.get(code, "")
            if not key: continue
            result[key] = {
                "name": item.get("f14",""),
                "close": float(item.get("f2",0) or 0),
                "pct":  float(item.get("f3",0) or 0),
                "change": float(item.get("f4",0) or 0),
                "high": float(item.get("f15",0) or 0),
                "low":  float(item.get("f16",0) or 0),
                "prev_close": float(item.get("f18",0) or 0),
            }
    except Exception as e:
        print(f"东方财富行情获取失败: {e}")
    try:
        r = requests.get(
            "http://hq.sinajs.cn/list=hkHSI,hkHSTECH",
            headers={"Referer":"http://finance.sina.com.cn"}, timeout=10)
        r.encoding = "gbk"
        name_map = {"hkHSI":"恒生指数","hkHSTECH":"恒生科技"}
        for line in r.text.strip().split("\n"):
            if "=" not in line: continue
            raw = line.split("=")[0].strip()
            key = raw.split("_")[-1] if "_" in raw else raw
            val = line.split('"')[1] if '"' in line else ""
            parts = val.split(",")
            if len(parts) < 9: continue
            close = float(parts[5]) if parts[5] else 0.0
            prev_close = float(parts[3]) if parts[3] else close
            pct = float(parts[8]) if parts[8] else 0.0
            change = float(parts[7]) if parts[7] else 0.0
            # 优先用东方财富返回的名称兜底，否则用 Sina 解析
            name = name_map.get(key, key)
            result[key] = {
                "name": name, "close": close, "pct": pct,
                "change": change, "prev_close": prev_close,
            }
    except Exception as e:
        print(f"港股行情获取失败: {e}")
    return result

def fetch_us_quotes():
    tickers = {"^IXIC":"纳斯达克","^DJI":"道琼斯","^GSPC":"标普500"}
    result = {}
    for sym, name in tickers.items():
        try:
            url = "https://query1.finance.yahoo.com/v8/finance/chart/" + sym
            params = {"interval":"1d","range":"2d"}
            r = requests.get(url, params=params, headers={"User-Agent":"Mozilla/5.0"}, timeout=10)
            d = r.json()
            res = d.get("chart",{}).get("result",[{}])[0]
            closes = [c for c in res.get("indicators",{}).get("quote",[{}])[0].get("close",[]) if c is not None]
            if len(closes) >= 2:
                curr = closes[-1]; prev = closes[-2]
                result[sym] = {"name":name,"close":curr,"pct":(curr-prev)/prev*100}
            elif len(closes) == 1:
                result[sym] = {"name":name,"close":closes[0],"pct":0}
        except Exception as e:
            print(f"  {name}获取失败: {e}")
    return result

def fetch_stock_price(code):
    """返回 (当前价, 昨收)"""
    try:
        pre = "sh" if code.startswith("6") else "sz"
        r = requests.get(f"http://hq.sinajs.cn/list={pre}{code}",
                        headers={"Referer":"http://finance.sina.com.cn"}, timeout=10)
        r.encoding = "gbk"
        v = r.text.split('"')[1].split(",")
        price = float(v[3]) if len(v) > 3 else 0.0
        yclose = float(v[2]) if len(v) > 2 else price
        return price, yclose
    except:
        return 0.0, 0.0

def fetch_a50():
    try:
        r = requests.get("https://hq.sinajs.cn/list=hsi05088",
                         headers={"Referer":"http://finance.sina.com.cn"}, timeout=8)
        r.encoding = "gbk"
        v = r.text.split('"')[1].split(",")
        if len(v) > 5: return float(v[5])
    except:
        pass
    return None

# ━━━━ 新增功能①：市场宽度（上涨/下跌家数等） ━━━━━━━━━━━━━━
def fetch_market_breadth():
    """
    获取A股市场宽度指标：上涨/下跌家数、涨停/跌停家数
    返回: {up_count, down_count, limit_up, limit_down, ad_ratio, total}
    """
    result = {
        "up_count": None, "down_count": None,
        "limit_up": None, "limit_down": None,
        "ad_ratio": None, "total": None,
    }
    try:
        r = requests.get(
            "https://push2.eastmoney.com/api/qt/stockqot/get"
            "?ut=fa5fd1943c7b386f172d6893dbfba10b&fltt=2"
            "&fields=f1,f2,f3,f4,f12,f13,f14,f15,f16,f17,f18"
            "&secids=1.000001",
            headers={"Referer":"https://quote.eastmoney.com","User-Agent":"Mozilla/5.0"},
            timeout=10)
        d = r.json()
        stock_list = (
            (d.get("data") or {}).get("stockList", []) or
            (d.get("data") or {}).get("stocks", [])
        )
        for s in stock_list:
            if str(s.get("f12", "")) == "000001":
                result["up_count"]    = s.get("f15")
                result["down_count"]  = s.get("f16")
                result["limit_up"]    = s.get("f17")
                result["limit_down"]  = s.get("f18")
    except Exception as e:
        print(f"市场宽度获取失败: {e}")

    if result["up_count"] is None:
        try:
            r2 = requests.get(
                "https://push2.eastmoney.com/api/qt/ulist.np/get"
                "?fltt=2&invt=2"
                "&fields=f2,f3,f4,f12,f13,f14"
                "&secids=1.000001,0.399001,0.399006,1.000300,1.000985"
                "&ut=fa5fd1943c7b386f172d6893dbfba10b",
                headers={"Referer":"https://quote.eastmoney.com","User-Agent":"Mozilla/5.0"},
                timeout=10)
            items = (r2.json().get("data", {}) or {}).get("diff", [])
            up_n = sum(1 for x in items if float(x.get("f3", 0)) > 0)
            dn_n = sum(1 for x in items if float(x.get("f3", 0)) < 0)
            result["up_count"]   = up_n
            result["down_count"] = dn_n
        except Exception as e:
            print(f"备用涨跌家数获取失败: {e}")

    if result["up_count"] and result["down_count"]:
        result["total"] = result["up_count"] + result["down_count"]
        result["ad_ratio"] = round(result["up_count"] / result["down_count"], 2)
    return result

# ━━━━ 新增功能②：北向资金 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def fetch_north_money():
    result = {"north_net": None, "north_pct": None, "hk_to_sh": None, "hk_to_sz": None}
    try:
        r = requests.get(
            "https://push2.eastmoney.com/api/qt/kamt/get"
            "?fields1=f2,f3,f4,f5&fields2=f1",
            headers={"Referer":"https://quote.eastmoney.com","User-Agent":"Mozilla/5.0"},
            timeout=10)
        d = r.json()
        data  = d.get("data", {}) or {}
        north = data.get("north", {}) or {}
        hk2sh = data.get("hk2sh", {}) or {}
        hk2sz = data.get("hk2sz", {}) or {}
        result["north_net"] = north.get("f2")
        result["north_pct"] = north.get("f3")
        result["hk_to_sh"]  = hk2sh.get("f2")
        result["hk_to_sz"]  = hk2sz.get("f2")
    except Exception as e:
        print(f"北向资金获取失败: {e}")
    return result

# ━━━━ 新增功能④：持仓阿尔法分析 ━━━━━━━━━━━━━━━━━━━━━━━━━━━
def calc_holding_alpha(hvals, quotes):
    sh_pct = quotes.get("sh000001", {}).get("pct", 0.0)
    result = []
    for h in hvals:
        day_pct = h.get("day_pct", 0.0)
        alpha   = round(day_pct - sh_pct, 2)
        result.append({**h, "alpha": alpha, "sh_pct": sh_pct})
    return result

# ━━━━ 新增功能③：明日操作指引 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def calc_tomorrow_guide(quotes, avg_pct, north_data):
    sh      = quotes.get("sh000001", {})
    sh_close = sh.get("close", 0)
    sh_pct   = sh.get("pct", 0)
    sh_high  = sh.get("high", 0)
    sh_low   = sh.get("low", 0)
    resist  = round(sh_high * 0.998, 2) if sh_high else None
    support = round(sh_low  * 1.002, 2) if sh_low  else None
    north_net = north_data.get("north_net")
    if north_net is not None:
        if north_net > 5e7:
            north_dir = "外资大幅流入，支撑强 👍"
        elif north_net > 0:
            north_dir = "外资小幅净买入"
        else:
            north_dir = f"外资净卖出{('，留意尾盘' if north_net < -2e7 else '')}"
    else:
        north_dir = "北向数据获取中"
    if avg_pct > 1.0:
        trend_txt = "偏多"; trend_note = f"明日高开概率大，关注{resist}能否突破"
    elif avg_pct < -1.0:
        trend_txt = "偏空"; trend_note = f"明日低开风险大，{support}能否企稳"
    else:
        trend_txt = "震荡"
        pt_range = (sh_high - sh_low) if (sh_high and sh_low) else 0
        trend_note = f"明日方向不明，震荡格局，高低点相差{pt_range:.0f}点"
    actions = []
    if avg_pct > 0.5:
        actions.append({"icon":"📈","label":"顺势操作","text":"大盘强势，可继续持股，关注证券板块轮动机会"})
    elif avg_pct < -0.5:
        actions.append({"icon":"🛡️","label":"防御为主","text":"大盘偏弱，控制仓位，不盲目加仓"})
    else:
        actions.append({"icon":"⚖️","label":"观望","text":"大盘无明显方向，震荡行情高抛低吸"})
    if north_net is not None and north_net < -10e7:
        actions.append({"icon":"⚠️","label":"北向警示","text":"外资大幅流出，需警惕系统性风险"})
    return {
        "sh_close": sh_close, "sh_pct": sh_pct,
        "support": support, "resist": resist,
        "trend": trend_txt, "trend_note": trend_note,
        "north_dir": north_dir, "north_net": north_net,
        "actions": actions, "avg_pct": avg_pct,
    }

# ━━━━ 新增功能⑤：周末财报日历 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def fetch_earnings_calendar():
    today = datetime.date.today()
    result = []
    try:
        r = requests.get(
            "https://np-anotice-stock.eastmoney.com/api/security/ann"
            f"?sr=-1&page_size=30&page_index=1"
            f"&ann_type=SHA,CYB,SZA,HSZA,BJA"
            f"&begin={today.isoformat()}"
            f"&end={(today+datetime.timedelta(days=14)).isoformat()}"
            f"&client_source=web",
            headers={"Referer":"https://www.eastmoney.com","User-Agent":"Mozilla/5.0"},
            timeout=10)
        items = ((r.json().get("data") or {}).get("list") or [])
        keywords = ["业绩预告","业绩快报","年报","半年报","季报","净利润","营业收入"]
        seen = set()
        for item in items:
            title = item.get("title",""); date = item.get("notice_date","")
            if any(kw in title for kw in keywords) and title not in seen:
                seen.add(title)
                result.append({"title": title[:90], "date": date})
    except Exception as e:
        print(f"财报日历获取失败: {e}")
    macro = [
        ("周一","中国4月LPR利率公布"),
        ("周三","美国4月CPI通胀数据"),
        ("周五","中国4月进出口数据"),
    ]
    for day, title in macro:
        result.append({"title": f"[宏观] {title}", "date": f"本周{day}"})
    return result[:10]


def fetch_stock_ma(code):
    """获取个股 MA5 / MA20 / MA60，带重试"""
    import time
    pre = "1" if code.startswith("6") else "0"
    secid = f"{pre}.{code}"
    url = (
        f"https://push2his.eastmoney.com/api/qt/stock/kline/get"
        f"?secid={secid}&fields1=f1,f2,f3,f4,f5,f6"
        f"&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"
        f"&klt=101&fqt=1&lmt=70"
    )
    headers = {
        "Referer": "https://quote.eastmoney.com",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Accept": "application/json",
        "Connection": "keep-alive",
    }
    for attempt in range(3):
        try:
            r = requests.get(url, headers=headers, timeout=5)
            r.raise_for_status()
            d = r.json()
            klines = d.get("data", {}).get("klines", [])
            if not klines or len(klines) < 20:
                return None
            prices = [float(k.split(",")[2]) for k in klines]
            ma5  = sum(prices[-5:])  / 5
            ma20 = sum(prices[-20:]) / 20
            ma60 = sum(prices[-60:]) / 60 if len(prices) >= 60 else None
            cur  = prices[-1]
            vol_list = [float(k.split(",")[6]) for k in klines[-20:]]
            avg_vol = sum(vol_list) / len(vol_list)
            vol_ratio = vol_list[-1] / avg_vol if avg_vol > 0 else 1.0
            return {"ma5": ma5, "ma20": ma20, "ma60": ma60, "cur": cur, "vol_ratio": vol_ratio}
        except Exception as e:
            if attempt < 2:
                time.sleep(1.5)  # 重试前等1.5秒
                continue
            print(f"  {code} MA获取失败: {e}")
            return None

def calc_resistance_levels(code, cur_price):
    """
    基于近60日K线数据，计算个股的短期/中期压力位和回测支撑位。
    短期压力位 = 近20日最高价
    中期压力位 = MA60 或近60日次高点（取较小值，更实际）
    回踩支撑  = 20日均线MA20
    使用新浪财经K线接口（东方财富接口对部分股票返回null，改用新浪）
    """
    import time, requests
    # 新浪接口：sz/sh前缀
    symbol = ("sz" + code) if not code.startswith("6") else ("sh" + code)
    url = (f"https://money.finance.sina.com.cn/quotes_service/api/json_v2.php"
           f"/CN_MarketData.getKLineData?symbol={symbol}&scale=240&ma=5,20,60&datalen=70")
    headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn"}
    for attempt in range(2):
        try:
            r = requests.get(url, headers=headers, timeout=5)
            r.raise_for_status()
            klines = r.json()
            if not klines or len(klines) < 20:
                return None
            prices  = [float(k["close"]) for k in klines]
            highs   = [float(k["high"])  for k in klines]
            ma5_list  = [k.get("ma_price5")  for k in klines if k.get("ma_price5")]
            ma20_list = [k.get("ma_price20") for k in klines if k.get("ma_price20")]
            ma60_list = [k.get("ma_price60") for k in klines if k.get("ma_price60")]

            high_20 = max(highs[-20:])
            ma20    = ma20_list[-1]  if ma20_list else sum(prices[-20:])/20
            ma60    = ma60_list[-1]  if ma60_list else (sum(prices[-60:])/60 if len(prices)>=60 else high_20)
            high_60 = max(highs[-60:]) if len(highs)>=60 else high_20

            # 短期阻力=20日高点，中期阻力=MA60与60日高取小（更实际）
            short_r  = high_20
            medium_r = min(ma60, high_60)
            short_space  = (short_r  - cur_price) / cur_price * 100 if cur_price > 0 else 0
            medium_space = (medium_r - cur_price) / cur_price * 100 if cur_price > 0 else 0
            return {
                "resistance_20d":   round(short_r,  2),
                "resistance_60d":   round(medium_r, 2),
                "ma20":             round(ma20,    2),
                "short_space_pct":  round(short_space,  1),
                "medium_space_pct": round(medium_space, 1),
            }
        except Exception as e:
            if attempt < 1:
                time.sleep(1)
                continue
            return None



def fetch_stock_info_em(code):
    """获取个股基本面 via 东方财富，带重试"""
    import time
    pre = "1" if code.startswith("6") else "0"
    secid = f"{pre}.{code}"
    url = (
        f"https://push2.eastmoney.com/api/qt/stock/get"
        f"?secid={secid}"
        "&fields=f58,f47,f48,f162,f167,f116,f117"
    )
    headers = {
        "Referer": "https://quote.eastmoney.com",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Accept": "application/json",
    }
    for attempt in range(3):
        try:
            r = requests.get(url, headers=headers, timeout=5)
            r.raise_for_status()
            d = r.json()
            data = d.get("data", {}) or {}
            name = data.get("f58", "") or ""
            mkt_cap = data.get("f47", 0) or 0
            pe_ttm  = data.get("f162", 0) or 0
            pb      = data.get("f167", 0) or 0
            profit_growth = data.get("f116", 0) or 0
            revenue_growth = data.get("f117", 0) or 0
            return {
                "name": name,
                "mkt_cap_yi": round(mkt_cap / 10000, 0) if mkt_cap else 0,
                "pe_ttm": round(pe_ttm, 1) if pe_ttm and pe_ttm > 0 else None,
                "pb": round(pb, 2) if pb and pb > 0 else None,
                "profit_growth": round(profit_growth, 1) if profit_growth else None,
                "revenue_growth": round(revenue_growth, 1) if revenue_growth else None,
            }
        except Exception as e:
            if attempt < 2:
                time.sleep(1.0)
                continue
            return {}

    return {}

def fetch_news():
    news = []
    try:
        r = requests.get(
            "https://zhibo.sina.com.cn/api/zhibo/feed?zhibo_id=152"
            "&page=1&page_size=25&tag_id=0&dire=f&dpc=1&pagesize=25&id=0",
            headers={"Referer":"https://finance.sina.com.cn"}, timeout=10)
        for item in r.json().get("result",{}).get("data",{}).get("feed",{}).get("list",[]):
            txt = re.sub(r"<[^>]+>","",item.get("rich_text","")).strip()
            if txt and len(txt) > 10:
                news.append({"text":txt,"source":"新浪"})
    except Exception as e:
        print(f"新浪快讯失败: {e}")
    try:
        r = requests.get(
            "https://np-anotice-stock.eastmoney.com/api/security/ann"
            "?sr=-1&page_size=15&page_index=1&ann_type=SHA,CYB,SZA,HSZA,BJA&client_source=web",
            headers={"Referer":"https://www.eastmoney.com"}, timeout=10)
        for item in r.json().get("data",{}).get("list",[]):
            t = item.get("title","")
            if t: news.append({"text":t,"source":"东财公告"})
    except Exception as e:
        print(f"东财公告失败: {e}")
    return news

POS_KWS = ["上涨","反弹","突破","牛市","做多","加仓","增持","超配","买入","超预期",
           "业绩增长","政策支持","降息","降准","宽松","万亿","资金流入","外资","北向",
           "净买入","开门红","涨停","大幅上涨","历史新高","超跌反弹","资金净流入",
           "业绩超预期","订单饱满","产能扩张","市场份额提升","行业景气","景气回升","盈利预测上调"]
NEG_KWS = ["下跌","暴跌","跳水","熊市","做空","减持","减仓","低配","卖出","不及预期",
           "业绩下滑","监管","收紧","加息","缩表","外资流出","踩雷","黑天鹅","暴雷",
           "违约","美股大跌","跌停","历史新低","资金净流出","业绩下修","商誉减值"]
SEC_KWS = {
    "医疗":   ["医疗","医药","医保","集采","医疗器械","老龄化","养老","健康","中药","创新药","疫苗"],
    "银行":   ["银行","降息","降准","LPR","信贷","房地产","息差","不良率","净息差","宽信用"],
    "券商":   ["券商","注册制","IPO","北交所","资本市场","两融","交易量","投行","并购"],
    "科技":   ["AI","人工智能","半导体","芯片","国产替代","算力","大模型","英伟达","算力租赁"],
    "新能源": ["新能源","锂电","光伏","储能","碳中和","电动车","固态电池","充电桩","风电"],
    "消费":   ["消费","白酒","家电","汽车","内需","零售","扩内需","促消费"],
    "宏观":   ["GDP","CPI","PPI","PMI","美联储","人民币","汇率","美股","港股","美债","特朗普关税"],
}

def analyze_sentiment(text):
    p = sum(1 for k in POS_KWS if k in text)
    n = sum(1 for k in NEG_KWS if k in text)
    return "positive" if p > n else ("negative" if n > p else "neutral")

def match_sectors(text):
    found = []
    for sec, kws in SEC_KWS.items():
        for kw in kws:
            if kw in text:
                found.append(sec); break
    return list(set(found))

S_ICO = {"positive":"📈","negative":"📉","neutral":"⚖️"}
def tc(p): c=float(p); return "#e34a4a" if c>0 else ("#3a9e4f" if c<0 else "#888")
def sc(s): return {"positive":"#e34a4a","negative":"#3a9e4f","neutral":"#888"}.get(s,"#888")

def send_email(subject, html):
    import smtplib, ssl
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    from email.header import Header
    msg = MIMEMultipart("alternative")
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = SMTP_USER; msg["To"] = SMTP_USER
    msg.attach(MIMEText(html, "html", "utf-8"))
    ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=ctx) as sv:
        sv.login(SMTP_USER, SMTP_PASS)
        sv.sendmail(SMTP_USER, [SMTP_USER], msg.as_string())
    print(f"✅ 邮件已发送: {subject}")

def now_str():
    from datetime import timezone, timedelta
    CST = timezone(timedelta(hours=8))
    n = datetime.datetime.now(CST)
    wd = {0:"周一",1:"周二",2:"周三",3:"周四",4:"周五",5:"周六",6:"周日"}
    return n, f"{n.year}年{n.month}月{n.day}日 {wd[n.weekday()]} {n.strftime('%H:%M')}"

def calc_avg_pct(quotes):
    vals = [float(quotes.get(k,{}).get("pct",0)) for k in ["sh000001","sz399001","sz399006","sh000300","sh000985"]]
    return sum(vals)/len(vals) if vals else 0.0

def calc_holding_values():
    result = []
    for h in HOLDINGS:
        price, yclose = fetch_stock_price(h["code"])
        mv = h["shares"] * price
        day_pct = (price / yclose - 1) * 100 if yclose else 0.0
        # 获取短期/中期压力位（用于止盈点参考）
        res_data = calc_resistance_levels(h["code"], price) if price > 0 else None
        short_tp  = res_data["resistance_20d"] if res_data else None   # 短期止盈：20日高点
        medium_tp = res_data["resistance_60d"] if res_data else None   # 中期止盈：MA60或60日高
        result.append({**h, "price": price, "yclose": yclose,
                       "day_pct": day_pct, "market_value": mv,
                       "short_tp": short_tp, "medium_tp": medium_tp,
                       "resistance_data": res_data})
    return result


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  个股操盘建议
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def get_stock_advice(hval, news_list, avg_pct, quotes):
    name   = hval["name"]
    shares = hval["shares"]
    cost   = hval["cost"]
    price  = hval.get("price", 0)
    tags   = hval.get("tags", [])
    watch  = hval.get("watch", "")

    if not price:
        return {"name": name, "action": "⏳ 关注中", "color": "#888", "bg": "#f5f5f5",
                "reason": "价格获取中，明日早报再分析", "signal": "neutral", "price": None,
                "stop_loss": None, "add_zone": None, "urgent": False, "pnl": None}

    pnl = (price - cost) / cost * 100
    pnl_abs = (price - cost) * shares
    bull = avg_pct > 0.3; bear = avg_pct < -0.3
    tagged = [{**x, "sentiment": analyze_sentiment(x["text"])} for x in news_list]
    rel = [x for x in tagged if any(t in x["text"] for t in tags)]
    pos_n = sum(1 for x in rel if x["sentiment"] == "positive")
    neg_n = sum(1 for x in rel if x["sentiment"] == "negative")
    sent_signal = "positive" if pos_n > neg_n else ("negative" if neg_n > pos_n else "neutral")

    if pnl <= -8.0:
        return {"name": name, "action": "🚨 建议止损", "color": "#e34a4a", "bg": "#fff5f5",
                "reason": f"亏损{pnl:.1f}%，已破-8%止损线！保住本金，控制亏损扩散。",
                "signal": "negative", "price": price, "pnl": pnl, "cost": cost,
                "watch": watch, "urgent": True, "stop_loss": round(price * 0.97, 2), "add_zone": None,
                "short_tp": hval.get("short_tp"), "medium_tp": hval.get("medium_tp"),
                "resistance_data": hval.get("resistance_data")}

    if pnl <= -5.0:
        action = "⚠️ 减仓观望" if (bear or sent_signal == "negative") else "🔔 设置止损"
        reason = f"亏损{pnl:.1f}%，接近止损区。"
        if bear: reason += " 大盘偏弱，双重压力，建议减仓控制仓位。"
        else: reason += f" 建议设置价格提醒：跌破{cost*0.92:.2f}元（-8%）提醒止损。"
        return {"name": name, "action": action, "color": "#e34a4a", "bg": "#fff5f5",
                "reason": reason, "signal": "negative", "price": price, "pnl": pnl,
                "cost": cost, "watch": watch, "urgent": False,
                "stop_loss": round(cost * 0.92, 2), "add_zone": round(price * 0.95, 2),
                "short_tp": hval.get("short_tp"), "medium_tp": hval.get("medium_tp"),
                "resistance_data": hval.get("resistance_data")}

    if pnl >= 15.0:
        # 卖点：使用技术面压力位（已由 calc_holding_values 注入）
        short_tp  = hval.get("short_tp")   # 20日高点
        medium_tp = hval.get("medium_tp")  # MA60/60日高
        # 构建卖点说明
        tp_lines = []
        if short_tp and short_tp > price:
            gain_s = (short_tp / price - 1) * 100
            tp_lines.append(f"短期目标 {short_tp:.2f}元（距现价+{gain_s:.1f}%）")
        if medium_tp and medium_tp > (short_tp or 0):
            gain_m = (medium_tp / price - 1) * 100
            tp_lines.append(f"中期目标 {medium_tp:.2f}元（距现价+{gain_m:.1f}%）")
        tp_str = " | ".join(tp_lines) if tp_lines else None
        reason = f"盈利{pnl:.1f}%（{pnl_abs:,.0f}元），已超止盈线！"
        if sent_signal == "positive": reason += " 基本面+消息面均支撑，可分批止盈，先卖1/3锁利。"
        elif sent_signal == "negative": reason += " 但消息面出现利空，建议全部或大部分止盈。"
        else: reason += " 建议分批止盈：涨超20%全部走，跌破13%全部走。"
        if tp_str: reason += f" 压力位参考：{tp_str}。"
        return {"name": name, "action": "🎯 止盈参考", "color": "#e34a4a", "bg": "#fff5f5",
                "reason": reason, "signal": "positive", "price": price, "pnl": pnl,
                "cost": cost, "watch": watch, "urgent": False,
                "stop_loss": round(price * 0.88, 2), "add_zone": None,
                "short_tp": short_tp, "medium_tp": medium_tp,
                "resistance_data": hval.get("resistance_data")}

    if pnl >= 8.0:
        reason = f"盈利{pnl:.1f}%（{pnl_abs:,.0f}元），在安全垫内。"
        if sent_signal == "positive": reason += " 基本面+消息面偏多，坚定持有，可适度加仓。"
        elif sent_signal == "negative": reason += " 但消息面有隐忧，可适当减仓锁定部分利润。"
        else: reason += f" 强势运行，持有待涨，同时上移止损到成本价{cost:.2f}元。"
        return {"name": name, "action": "✅ 持有为主", "color": "#27ae60", "bg": "#f0fff4",
                "reason": reason, "signal": "positive", "price": price, "pnl": pnl,
                "cost": cost, "watch": watch, "urgent": False,
                "stop_loss": cost, "add_zone": round(price * 1.03, 2),
                "short_tp": hval.get("short_tp"), "medium_tp": hval.get("medium_tp"),
                "resistance_data": hval.get("resistance_data")}

    if pnl >= 0:
        reason = f"盈利{pnl:.1f}%（{pnl_abs:,.0f}元），在成本上方，安心持有。"
        if sent_signal == "positive": reason += " 消息面偏多，有望继续上攻。"
        elif sent_signal == "negative": reason += f" 消息面偏空，注意回落风险，止损设在成本价{cost:.2f}元。"
        else: reason += f" 无明显方向，继续持股，止损{cost:.2f}元。"
        return {"name": name, "action": "✅ 安心持有", "color": "#27ae60", "bg": "#f0fff4",
                "reason": reason, "signal": sent_signal, "price": price, "pnl": pnl,
                "cost": cost, "watch": watch, "urgent": False,
                "stop_loss": cost,
                "add_zone": None if sent_signal == "negative" else round(price * 0.98, 2),
                "short_tp": hval.get("short_tp"), "medium_tp": hval.get("medium_tp"),
                "resistance_data": hval.get("resistance_data")}

    reason = f"浮亏{pnl:.1f}%（{pnl_abs:,.0f}元），仍在安全区间。"
    if watch: reason += " 关注方向：" + watch + "。"
    if sent_signal == "positive": reason += " 基本面支撑+消息面偏多，可考虑逢低小幅加仓拉低成本。"
    elif sent_signal == "negative": reason += f" 消息面偏空，若跌破成本{cost:.2f}元注意止损。"
    else: reason += " 无明显催化，耐心等待，不追加投入。"
    stop_color = "#e34a4a" if pnl < -3 else "#f39c12"
    return {"name": name, "action": "🔔 耐心持有", "color": stop_color, "bg": "#fff8e1",
            "reason": reason, "signal": sent_signal, "price": price, "pnl": pnl,
            "cost": cost, "watch": watch, "urgent": False, "stop_loss": cost,
            "add_zone": round(price * 0.97, 2) if sent_signal == "positive" else None,
            "short_tp": hval.get("short_tp"), "medium_tp": hval.get("medium_tp"),
            "resistance_data": hval.get("resistance_data")}

def html_stock_advice(hvals, news_list, avg_pct, quotes):
    out = ""
    for hval in hvals:
        adv = get_stock_advice(hval, news_list, avg_pct, quotes)
        price_str = (f"{adv['price']:.2f}元" if adv["price"] else "获取中")
        pnl_str   = (f"{adv['pnl']:+.1f}%"  if adv["pnl"] is not None else "")
        pnl_abs   = (adv["pnl"] / 100 * hval["cost"] * hval["shares"]) if adv["pnl"] is not None else 0
        pnl_abs_str = (f"({pnl_abs:+.0f}元)" if pnl_abs else "")
        urgent_tag = " <span style='background:#e34a4a;color:#fff;font-size:9px;padding:1px 5px;border-radius:8px;font-weight:700'>急</span>" if adv.get("urgent") else ""
        stop_str  = (f"止损参考：{adv['stop_loss']:.2f}元" if adv.get("stop_loss") else "")
        add_str   = (f"加仓参考：{adv['add_zone']:.2f}元"  if adv.get("add_zone")  else "")
        tags_str  = ("关注：" + hval.get("watch","无") if hval.get("watch") else "")
        out += (
            f"<div style='border:1px solid #eee;border-radius:12px;padding:12px;margin-bottom:10px;background:#fafbff'>"
            f"<div style='display:flex;align-items:center;gap:8px;margin-bottom:8px'>"
            f"<div style='font-size:15px;font-weight:700;color:#1a1a2e'>{adv['name']}</div>"
            f"<div style='font-size:11px;color:#aaa'>{hval['shares']}股</div>"
            f"<div style='margin-left:auto;text-align:right'>"
            f"<div style='font-size:14px;font-weight:700;color:{adv['color']}'>{adv['action']}{urgent_tag}</div>"
            f"<div style='font-size:11px;color:#888'>{price_str} <b style='color:{adv['color']}'>{pnl_str}</b> {pnl_abs_str}</div>"
            f"</div></div>"
            f"<div style='font-size:12px;color:#444;line-height:1.6;margin-bottom:6px'>{adv['reason']}</div>")
        if stop_str or add_str:
            tags_line = "  |  ".join(x for x in [stop_str, add_str] if x)
            out += f"<div style='font-size:10px;color:#4a90d9;margin-bottom:4px'>{tags_line}</div>"
        # 卖点展示（压力位）——从 hval 读取，所有持仓都显示
        stp_h = hval.get("short_tp")
        mtp_h = hval.get("medium_tp")
        res_d = hval.get("resistance_data") or {}
        current_price = adv.get("price", 0)
        # 计算价格距压力位距离
        gap_note = ""
        if stp_h and current_price > 0:
            gap = (stp_h / current_price - 1) * 100
            if gap <= 5:
                gap_note = " ⚠️接近短期压力"
            elif gap <= 10:
                gap_note = " 距压力+{:.0f}%".format(gap)
        if mtp_h and mtp_h != stp_h and current_price > 0:
            gap2 = (mtp_h / current_price - 1) * 100
            if gap2 <= 5:
                gap_note += " ⚠️接近中期压力"
        if stp_h or mtp_h:
            tp_parts = []
            if stp_h: tp_parts.append("🎯 短期 {stp_h:.2f}元".format(stp_h=stp_h))
            if mtp_h: tp_parts.append("🎯 中期 {mtp_h:.2f}元".format(mtp_h=mtp_h))
            tp_html = "  ".join(tp_parts)
            out += "<div style='font-size:10px;color:#27ae60;margin-bottom:4px'>" + tp_html + "</div>"
            if gap_note:
                out += "<div style='font-size:10px;color:#e34a4a;margin-bottom:4px'>" + gap_note.strip() + "</div>"
        if tags_str and tags_str != "关注：无":
            out += f"<div style='font-size:10px;color:#888'>{tags_str}</div>"
        out += "</div>"
    return out

def get_position_advice(avg, total_mv):
    ratio = total_mv/TOTAL_CASH*100
    advices = []
    if avg > 1.0:
        advices.append({"icon":"📉","action":"⚠️ 减仓提示","color":"#e34a4a","bg":"#fff5f5",
            "text":f"大盘涨幅超1%，今日强势明显，建议适度减仓锁利，将仓位降至50%以下。个人持仓{ratio:.0f}%，注意高开后回落风险。"})
    elif avg < -1.0:
        if ratio > 60:
            advices.append({"icon":"🛡️","action":"🛡️ 控仓提示","color":"#3a9e4f","bg":"#f0fff4",
                "text":f"大盘跌幅超1%，当前持仓{ratio:.0f}%偏高，建议减仓控制风险，保留更多现金，等待底部信号再加仓。"})
        else:
            advices.append({"icon":"🔔","action":"🔔 低吸提示","color":"#4a90d9","bg":"#f0f5ff",
                "text":f"大盘下跌但跌幅可控，当前仓位{ratio:.0f}%，若有子弹可少量低吸超跌优质股，整体仓位控制在60%以内。"})
    else:
        if ratio < 40:
            advices.append({"icon":"💡","action":"💡 补仓参考","color":"#4a90d9","bg":"#f0f5ff",
                "text":f"当前仓位{ratio:.0f}%偏低，大盘平稳，若看好后市可逢低分批加仓至50-60%，不要一把梭。"})
        elif ratio > 70:
            advices.append({"icon":"⚠️","action":"⚠️ 控仓参考","color":"#e34a4a","bg":"#fff5f5",
                "text":f"当前仓位{ratio:.0f}%较高，建议适当分散风险，避免单票集中，保持总仓位不超过七成。"})
        else:
            advices.append({"icon":"✅","action":"✅ 仓位适中","color":"#27ae60","bg":"#f0fff4",
                "text":f"当前仓位{ratio:.0f}%合理，大盘无明显趋势，继续持股待涨，保持现有配置不变。"})
    return advices

def adj_rows(advices):
    out = ""
    for adv in advices:
        out += ("<div class='adj'>"
                "<div class='adji'>" + adv["icon"] + "</div>"
                "<div class='adjb'>"
                "<div class='adjn' style='color:" + adv["color"] + "'>" + adv["action"] + "</div>"
                "<div class='adjt'>" + adv["text"] + "</div></div></div>")
    return out


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  个股推荐引擎（稳健型）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 稳健选股池：各行业龙头 / 细分冠军
STOCK_POOL = [
    ("002007","华兰生物","血制品/疫苗",
     "血制品赛道壁垒高、浆站资源稀缺，供给偏紧推动价格上行；四价流感疫苗为独家大单品；当前估值处历史低位，PEG<1，安全边际充足。",
     35, 5.0),
    ("000538","云南白药","中药/日化",
     "品牌护城河极深，牙膏市占率稳定第一，医美+中药新业务打开成长空间；国企改革提升运营效率；低估值高股息，适合长期持有。",
     30, 4.0),
    ("600196","复星医药","创新药/医疗器械",
     "创新药进入密集收获期，多款生物类似药+CAR-T上市在即；医疗器械稳健增长；国际化布局领先，估值具备性价比。",
     40, 4.5),
    ("600036","招商银行","零售银行",
     "零售银行标杆，资产质量优异，息差韧性强；财富管理业务持续高增长；当前PB处历史低位，性价比突出，适合稳健配置。",
     12, 1.5),
    ("601166","兴业银行","商业银行",
     "「商行+投行」战略成效显著，中间业务收入增速领先；资产质量持续改善；低估值+高股息，适合稳健底仓。",
     10, 1.2),
    ("600030","中信证券","综合券商",
     "券商龙头，IPO项目储备全行业第一；资本市场改革直接受益；当前PB处历史底部，弹性大+防御强，适合震荡市配置。",
     25, 1.8),
    ("000776","广发证券","券商",
     "财富管理转型领先，公募基金保有量行业前三；自营业务稳健；当前估值低估明显，安全边际高。",
     22, 1.5),
    ("600519","贵州茅台","高端白酒",
     "高端白酒绝对龙头，定价权无可撼动；茅台酒供需紧平衡，出厂价具备上调空间；业绩确定性强，高股息，A股最稳健核心资产之一。",
     40, 12.0),
    ("000858","五粮液","高端白酒",
     "浓香型白酒龙头，品牌力仅次于茅台；动销边际改善，渠道库存健康；估值处历史中枢，性价比较高。",
     25, 6.0),
    ("601012","隆基绿能","光伏龙头",
     "光伏组件龙头，BC电池技术行业领先，成本优势显著；海外产能布局完善，规避贸易壁垒；当前股价处历史低位，周期底部布局价值凸显。",
     30, 3.5),
    ("603259","药明康德","CXO龙头",
     "全球CXO龙头，临床前CRO+CDMO双轮驱动；新签订单持续高增长，业绩确定性强；估值回调至历史低位，配置价值凸显。",
     35, 5.5),
    ("600900","长江电力","水电/高股息",
     "长江干流稀缺水电资产，现金流充沛、业绩稳定；乌白电站注入后装机翻倍；承诺高分红（>=70%），A股最典型的高股息稳健标的。",
     30, 3.0),
    ("002461","珠江啤酒","啤酒",
     "华南啤酒龙头，餐饮渠道复苏带动销量增长；产品结构升级，高端产品占比提升；当前PE处历史低位，弹性较大。",
     25, 3.0),
    ("601888","中国中免","免税零售",
     "免税行业绝对龙头，政策支持消费回流；海南自贸港政策持续加码，客流边际改善；当前估值处历史低位，反弹弹性大。",
     35, 6.0),
]

def recommend_stocks(news_list, avg_pct):
    """
    稳健型个股推荐：
    1. 排除已有持仓
    2. 基本面筛选：PE/PB满足阈值
    3. 技术面筛选：MA5 > MA20（多头排列），价格在MA20上方
    4. 消息面：近期无重大利空
    5. 大盘过滤：熊市环境下降低进攻型标的
    """
    HOLDING_CODES = {h["code"] for h in HOLDINGS}

    bull = avg_pct > 0.3
    bear = avg_pct < -0.3

    tagged = [{**x,"sentiment":analyze_sentiment(x["text"]),"sectors":match_sectors(x["text"])}
              for x in news_list]
    neg_text = " ".join(x["text"] for x in tagged if x["sentiment"]=="negative")
    pos_text = " ".join(x["text"] for x in tagged if x["sentiment"]=="positive")

    candidates = []

    for code, name, sector, reason, pe_max, pb_max in STOCK_POOL:
        if code in HOLDING_CODES:
            continue

        # ── 1. 基本面筛选 ───────────────────
        info = fetch_stock_info_em(code)
        name = info.get("name", name) or name
        pe = info.get("pe_ttm")
        pb = info.get("pb")
        mkt_cap = info.get("mkt_cap_yi", 0)

        if pe is not None and pe > pe_max:
            continue
        if pb is not None and pb > pb_max:
            continue
        if mkt_cap > 0 and mkt_cap < 50:
            continue

        # ── 2. 技术面筛选 ───────────────────
        ma_data = fetch_stock_ma(code)
        if ma_data is None:
            continue
        ma5  = ma_data["ma5"]
        ma20 = ma_data["ma20"]
        ma60 = ma_data["ma60"]
        cur  = ma_data["cur"]
        vol_ratio = ma_data["vol_ratio"]

        # 多头排列：MA5 > MA20，且价格在MA20上方
        if not (ma5 > ma20 and cur > ma20 * 0.97):
            continue
        # MA60辅助：价格在MA60上方更强
        above_ma60 = cur > ma60 if ma60 else True
        # 量比合理（不要异常放量）
        if vol_ratio > 5.0:
            continue

        # ── 3. 消息面利空排除 ───────────────
        # 特定个股被点名利空
        stock_neg_kws = {"002007":["召回","造假","停产"],
                         "000538":["召回","调查","违规"],
                         "600196":["黑天鹅","调查","暴雷"],
                         "600036":["不良率飙升","大幅裁员"],
                         "600030":["监管处罚","造假"],
                         "600519":["塑化剂","假酒"],
                         "000858":["假酒","质量门"],
                         "601012":["双反","补贴取消"],
                         "603259":["实体清单","制裁"],
                         "600900":["来水偏枯","地质灾害"],
                        }
        neg_kws = stock_neg_kws.get(code, [])
        if any(kw in neg_text for kw in neg_kws):
            continue

        # ── 4. 风险收益评分 ─────────────────
        score = 0.0
        # 技术面加分
        if above_ma60: score += 2  # 在MA60上方
        if ma5 > ma20 * 1.02: score += 1  # MA5明显高于MA20
        if 0.8 <= vol_ratio <= 2.0: score += 1  # 量比健康
        # 基本面加分
        if pe is not None and pe < pe_max * 0.7: score += 2  # 明显低估
        if info.get("profit_growth") and info["profit_growth"] > 10: score += 1
        if info.get("revenue_growth") and info["revenue_growth"] > 10: score += 1
        # 消息面加分
        sector_kws = {"银行":["银行","净息差","降息","降准"],
                      "券商":["券商","注册制","IPO","成交量"],
                      "医药":["医药","集采","创新药","医疗器械"],
                      "消费":["白酒","消费","扩内需"],
                      "新能源":["光伏","储能","新能源","碳中和"]}
        skws = next((v for k,v in sector_kws.items() if k in sector), [])
        if any(kw in pos_text for kw in skws):
            score += 2
        if any(kw in neg_text for kw in skws):
            score -= 1

        price = cur
        gap_pct = (ma20 - cur) / ma20 * 100 if ma20 else 0
        if gap_pct > 0 and gap_pct < 3:
            score += 1  # 贴近MA20，有一定安全边际

        candidates.append({
            "code": code, "name": name, "sector": sector,
            "reason": reason, "score": score,
            "price": round(price, 2), "pe": pe, "pb": pb,
            "ma5": round(ma5, 2), "ma20": round(ma20, 2), "ma60": round(ma60, 2) if ma60 else None,
            "vol_ratio": round(vol_ratio, 2),
            "above_ma60": above_ma60,
        })

    # ── 实时价格验价（确保推荐价与当前价偏差不超过2%）─────────────
    verified = []
    for c in candidates:
        try:
            live_price, _ = fetch_stock_price(c["code"])
            if live_price and live_price > 0:
                gap = abs(live_price - c["price"]) / c["price"] * 100
                if gap <= 2.0:
                    c["price"] = round(live_price, 2)
                    verified.append(c)
                else:
                    print(f"  ⚠️ [{c['code']}] 推荐价{c['price']} vs 实时价{live_price} 偏差{gap:.1f}%，已丢弃")
            else:
                verified.append(c)
        except Exception:
            verified.append(c)  # 无法验证时保留
    verified.sort(key=lambda x: -x["score"])
    return verified[:3]

def build_order_strategy(code, name, sector, price, ma20, avg_pct):
    """
    根据股价与MA20的距离，生成稳健型条件单策略
    """
    bull = avg_pct > 0.3
    bear = avg_pct < -0.3

    # 计算建议买入价（贴近MA20，分批建仓）
    entry1 = round(ma20 * 1.00, 2)   # 贴近MA20建仓
    entry2 = round(ma20 * 0.97, 2)   # 回调3%再加仓
    entry3 = round(ma20 * 0.93, 2)   # 回调7%最后一批

    # 止损位（硬止损：亏损8%）
    stop_loss = round(price * 0.92, 2)

    # 止盈位（分批止盈）
    profit_take1 = round(entry1 * 1.10, 2)   # 涨10%先卖1/3
    profit_take2 = round(entry1 * 1.15, 2)   # 涨15%再卖1/3
    profit_take3 = round(entry1 * 1.20, 2)   # 涨20%全部清仓

    # 移动止损
    trail_stop = round(price * 0.96, 2)  # 从浮盈最高点跌6%止盈

    strategy = {
        "entry1": entry1, "entry2": entry2, "entry3": entry3,
        "stop_loss": stop_loss,
        "profit_take1": profit_take1, "profit_take2": profit_take2, "profit_take3": profit_take3,
        "trail_stop": trail_stop,
        "risk_pct": round((price - stop_loss) / price * 100, 1),
        "max_profit_pct": round((profit_take3 - entry1) / entry1 * 100, 1),
    }
    return strategy

def html_recommendation_section(recs, hvals, avg_pct, news_list):
    """
    生成「今日推荐个股」HTML段落
    - 有推荐：逐个展示个股详情（含理由+条件单）
    - 无推荐：明确告知原因
    """
    holding_codes = {h["code"] for h in HOLDINGS}
    holding_names  = {h["code"]: h["name"] for h in HOLDINGS}
    n_holdings = len(HOLDINGS)
    vacancy = MAX_STOCKS - n_holdings
    vacancy_str = f"（当前持仓{n_holdings}只，最多可持仓{MAX_STOCKS}只，空位{vacancy}个）"

    if not recs:
        return (
            "<div style=\'background:#f8f9fc;border-radius:12px;padding:16px;text-align:center\'>"
            "<div style=\'font-size:20px;margin-bottom:8px\'>🔍</div>"
            "<div style=\'font-size:14px;font-weight:700;color:#555;margin-bottom:6px\'>今日暂无推荐个股</div>"
            "<div style=\'font-size:12px;color:#888;line-height:1.6\'>"
            "当前市场环境不符合稳健建仓条件，建议耐心等待。<br>"
            "可能原因：大盘趋势不明、优质标的估值偏高、技术面尚未形成多头排列。<br>"
            "保持现有持仓，继续执行现有条件单策略。{vacancy_str}"
            "</div></div>".format(vacancy_str=vacancy_str)
        )

    # 如果有空位，提示可以替换哪只
    replace_tip = ""
    if vacancy == 0:
        # 满仓，提示替换建议
        weak_holdings = [h for h in hvals if (h.get("price",0)-h["cost"])/h["cost"]*100 < -5 or
                          (h.get("price",0)-h["cost"])/h["cost"]*100 > 20]
        if weak_holdings:
            weakest = weak_holdings[0]
            pnl = (weakest.get("price",0)-weakest["cost"])/weakest["cost"]*100
            replace_tip = (
                f"<div style=\'background:#fff8e1;border-radius:10px;padding:10px;margin-bottom:10px\'>"
                f"<div style=\'font-size:11px;font-weight:700;color:#e07b00;margin-bottom:4px\'>⚠️ 满仓提示（已持有{MAX_STOCKS}只）</div>"
                f"<div style=\'font-size:12px;color:#666\'>"
                f"当前已满{MAX_STOCKS}只持仓，如考虑换仓，建议关注："
                f"<b>{weakest['name']}</b>（{weakest['code']}，盈亏{pnl:+.1f}%）<br>"
                f"理由：盈亏比已超出目标范围，可考虑分批止盈/止损后换入。"
                "</div></div>"
            )
        else:
            replace_tip = (
                f"<div style=\'background:#f0fff4;border-radius:10px;padding:10px;margin-bottom:10px\'>"
                f"<div style=\'font-size:11px;font-weight:700;color:#27ae60;margin-bottom:4px\'>✅ 满仓提示（已持有{MAX_STOCKS}只）</div>"
                f"<div style=\'font-size:12px;color:#666\'>"
                f"当前已满{MAX_STOCKS}只持仓，暂无替换建议。现有持仓均在正常盈亏区间内，继续执行条件单策略。"
                "</div></div>"
            )

    # 头部提示
    vacancy_note = ""
    if vacancy > 0:
        vacancy_note = (
            f"<div style=\'background:#eef6ff;border-radius:10px;padding:10px;margin-bottom:12px\'>"
            f"<div style=\'font-size:12px;color:#4a90d9\'>"
            f"📋 当前持仓{n_holdings}只，最多可持仓{MAX_STOCKS}只，有 <b>{vacancy}个</b> 空位可建仓"
            "</div></div>"
        )

    out = vacancy_note
    if replace_tip:
        out += replace_tip

    for i, rec in enumerate(recs):
        code = rec["code"]
        name = rec["name"]
        sector = rec["sector"]
        reason = rec["reason"]
        price = rec["price"]
        ma20 = rec["ma20"]
        score = rec["score"]
        pe = rec.get("pe")
        pb = rec.get("pb")

        strat = build_order_strategy(code, name, sector, price, ma20, avg_pct)

        # 星级评分显示
        stars = "★" * min(int(score), 5) + "☆" * max(0, 5 - int(score))

        # 风险标签
        risk_tag = ""
        if strat["risk_pct"] <= 6:
            risk_tag = "<span style=\'background:#e8f5ee;color:#27ae60;font-size:10px;padding:2px 8px;border-radius:10px;font-weight:700\'>低风险</span>"
        elif strat["risk_pct"] <= 8:
            risk_tag = "<span style=\'background:#fff8e1;color:#e07b00;font-size:10px;padding:2px 8px;border-radius:10px;font-weight:700\'>中风险</span>"
        else:
            risk_tag = "<span style=\'background:#fff5f5;color:#e34a4a;font-size:10px;padding:2px 8px;border-radius:10px;font-weight:700\'>高风险</span>"

        # 基本面信息
        fin_info = ""
        if pe or pb:
            fin_parts = []
            if pe: fin_parts.append(f"PE {pe}")
            if pb: fin_parts.append(f"PB {pb}")
            fin_info = "<span style=\'font-size:11px;color:#888\'> | " + " ".join(fin_parts) + "</span>"

        out += (
            f"<div style=\'border:1px solid #e0e8f5;border-radius:12px;padding:14px;margin-bottom:14px;background:#fafbff\'>"
            # 标题行
            f"<div style=\'display:flex;align-items:center;gap:8px;margin-bottom:10px\'>"
            f"<div style=\'background:#4a90d9;color:#fff;font-size:11px;font-weight:700;padding:2px 10px;border-radius:10px\'>推荐{i+1}</div>"
            f"<div style=\'font-size:16px;font-weight:700;color:#1a1a2e\'>{name} <span style=\'font-size:11px;color:#aaa;font-weight:400\'>{code}</span></div>"
            f"<div style=\'margin-left:auto;display:flex;gap:6px;align-items:center\'>{risk_tag}</div>"
            f"</div>"
            # 基本面行
            f"<div style=\'font-size:12px;color:#555;margin-bottom:8px\'>"
            f"<span style=\'background:#f0f4ff;color:#4a90d9;font-size:11px;padding:1px 6px;border-radius:6px;font-weight:600\'>{sector}</span>"
            f"<span style=\'margin-left:6px\'>现价 <b>{price:.2f}元</b></span>"
            f"{fin_info}"
            f"</div>"
            # 推荐理由
            f"<div style=\'background:#fff;border-radius:10px;padding:10px;margin-bottom:10px\'>"
            f"<div style=\'font-size:10px;font-weight:700;color:#4a90d9;margin-bottom:4px\'>📌 推荐理由</div>"
            f"<div style=\'font-size:12px;color:#444;line-height:1.7\'>{reason}</div>"
            f"</div>"
            # 条件单策略
            f"<div style=\'background:#f8f9fc;border-radius:10px;padding:10px\'>"
            f"<div style=\'font-size:10px;font-weight:700;color:#888;margin-bottom:8px\'>📋 稳健型条件单策略（参考）</div>"
            f"<div style=\'display:grid;grid-template-columns:1fr 1fr;gap:4px;font-size:11px\'>"
            # 建仓策略
            f"<div style=\'background:#fff;border-radius:8px;padding:8px\'>"
            f"<div style=\'color:#27ae60;font-weight:700;margin-bottom:4px\'>🟢 分批建仓</div>"
            f"<div style=\'color:#444\'>首笔：<b>{strat['entry1']:.2f}元</b>（贴近MA20）<br>"
            f"二笔：{strat['entry2']:.2f}元（回调-3%）<br>"
            f"末笔：{strat['entry3']:.2f}元（极限回调-7%）</div>"
            f"</div>"
            # 止损策略
            f"<div style=\'background:#fff;border-radius:8px;padding:8px\'>"
            f"<div style=\'color:#e34a4a;font-weight:700;margin-bottom:4px\'>🔴 止损策略</div>"
            f"<div style=\'color:#444\'>硬止损：<b>{strat['stop_loss']:.2f}元</b><br>"
            f"（买入价-{strat['risk_pct']:.1f}%）<br>"
            f"移动止损：跌破最高点-6%触发</div>"
            f"</div>"
            # 止盈策略
            f"<div style=\'background:#fff;border-radius:8px;padding:8px;grid-column:1/-1\'>"
            f"<div style=\'color:#4a90d9;font-weight:700;margin-bottom:4px\'>🔵 分批止盈</div>"
            f"<div style=\'color:#444;line-height:1.8\'>"
            f"① 涨10% → <b>{strat['profit_take1']:.2f}元</b> → 卖1/3 锁利（{strat['max_profit_pct']:.0f}%空间→首笔可+{strat['profit_take1']:.0f}元）<br>"
            f"② 涨15% → <b>{strat['profit_take2']:.2f}元</b> → 再卖1/3<br>"
            f"③ 涨20% → <b>{strat['profit_take3']:.2f}元</b> → 全部清仓，落袋为安"
            f"</div></div>"
            f"</div></div>"
        )

    return out


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  HTML 报告构建
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CSS = """<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;background:#f0f2f7;color:#1a1a2e;padding:0}
.wrap{padding:14px;max-width:600px;margin:0 auto}
h1{font-size:18px;font-weight:700;color:#1a1a2e;margin-bottom:10px;line-height:1.4}
.card{background:#fff;border-radius:14px;padding:14px;margin-bottom:12px;box-shadow:0 2px 8px rgba(0,0,0,.06)}
.lbl{font-size:10px;font-weight:700;color:#888;text-transform:uppercase;letter-spacing:.6px;margin-bottom:10px;display:block}
.banner{border-radius:14px;padding:16px;margin-bottom:12px;text-align:center}
.banner h2{font-size:18px;font-weight:700;margin-bottom:4px;color:inherit}
.banner p{font-size:12px;opacity:.85;margin-top:4px}
.igrid{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}
.icard{background:#f8f9fc;border-radius:10px;padding:10px 6px;text-align:center}
.iname{font-size:10px;color:#888;margin-bottom:4px;font-weight:500}
.iclose{font-size:15px;font-weight:700;color:#222}
.ipct{font-size:12px;font-weight:600;margin-top:3px}
.bar{background:#eee;border-radius:8px;height:24px;overflow:hidden;display:flex}
.bi{background:linear-gradient(90deg,#4a90d9,#5ba3f0);height:100%;display:flex;align-items:center;justify-content:center;color:#fff;font-size:10px;font-weight:700;white-space:nowrap;overflow:hidden}
.bc{background:#dff0e5;height:100%;display:flex;align-items:center;justify-content:center;color:#1a7a42;font-size:10px;font-weight:700;white-space:nowrap;overflow:hidden}
.bleg{display:flex;justify-content:space-between;font-size:11px;color:#888;margin-top:5px;flex-wrap:wrap;gap:4px}
table{width:100%;border-collapse:collapse;font-size:12px}
th{background:#f5f7fa;padding:9px 6px;text-align:left;color:#888;font-weight:600;font-size:10px;border-bottom:1px solid #eee;text-transform:uppercase;letter-spacing:.5px}
td{padding:9px 6px;border-bottom:1px solid #f5f5f5;vertical-align:middle}
.hname{font-weight:600;color:#222;font-size:13px}
.hcode{font-size:10px;color:#aaa;margin-top:1px}
.nitem{display:flex;gap:10px;padding:10px 0;border-bottom:1px solid #f5f5f5}
.nitem:last-child{border-bottom:none}
.nico{font-size:15px;flex-shrink:0;padding-top:2px;width:22px;text-align:center}
.nbody{flex:1}
.ntext{font-size:13px;line-height:1.5;color:#222}
.nmeta{font-size:10px;color:#aaa;margin-top:3px}
.adj{display:flex;align-items:flex-start;gap:10px;padding:10px 0;border-bottom:1px solid #f5f5f5}
.adj:last-child{border-bottom:none}
.adji{font-size:18px;flex-shrink:0;width:24px;text-align:center;padding-top:1px}
.adjb{flex:1}
.adjn{font-size:13px;font-weight:700;margin-bottom:3px}
.adjt{font-size:11px;color:#666;line-height:1.5}
.ft{text-align:center;font-size:11px;color:#aaa;padding:14px 0}
@media(max-width:430px){
.igrid{grid-template-columns:repeat(2,1fr)}
th,td{padding:7px 4px;font-size:11px}
.bleg{font-size:10px}
}
</style>"""

def html_head(title):
    return ("<!DOCTYPE html><html><head>"
            "<meta charset=\'utf-8\'>"
            "<meta name=\'viewport\' content=\'width=device-width,initial-scale=1\'>"
            "<title>" + title + "</title>" + CSS + "</head><body>"
            "<div class=\'wrap\'>")

def title_div():
    n, ds = now_str()
    return "<h1>" + ds + "</h1>"

def card(lbl, body):
    return "<div class=\'card\'><span class=\'lbl\'>" + lbl + "</span>" + body + "</div>"

def banner(icon, title, note, bg):
    return ("<div class=\'banner\' style=\'background:" + bg + "\'>"
            "<h2>" + icon + " " + title + "</h2><p>" + note + "</p></div>")

def idx_grid(rows):
    return "<div class=\'igrid\'>" + rows + "</div>"

def idx_card(name, close, pct):
    arrow = "▲" if pct > 0 else ("▼" if pct < 0 else "—")
    c = tc(pct)
    c_str = "{:,.2f}".format(close) if close >= 1 else "{:,.2f}".format(close)
    p_str = "{:+.2f}".format(pct)
    return ("<div class=\'icard\'><div class=\'iname\'>" + name + "</div>"
            "<div class=\'iclose\'>" + c_str + "</div>"
            "<div class=\'ipct\' style=\'color:" + c + "\'>" + arrow + " " + p_str + "%</div></div>")

def pos_bar(total_mv):
    ratio = total_mv/TOTAL_CASH*100; inv = 100-ratio
    bi_w = ratio if ratio > 5 else 5; bc_w = inv if inv > 5 else 5
    return ("<div class=\'bar\'>"
            "<div class=\'bi\' style=\'width:" + "{:.1f}".format(bi_w) + "%\'>" + "{:.0f}".format(ratio) + "% 持仓</div>"
            "<div class=\'bc\' style=\'width:" + "{:.1f}".format(bc_w) + "%\'>" + "{:.0f}".format(inv) + "% 现金</div>"
            "</div>"
            "<div class=\'bleg\'>"
            "<span>📦 持仓 " + "{:,.0f}".format(total_mv) + "元</span>"
            "<span>💵 现金 " + "{:,.0f}".format(TOTAL_CASH-total_mv) + "元</span>"
            "<span>💰 总计 " + "{:,.0f}".format(TOTAL_CASH) + "元</span></div>")

def hold_table(hvals, total_mv, label="当日"):
    """持仓明细表，label控制列头文字（早报=上日，午报/晚报=当日）"""
    rows = ""
    for h in hvals:
        mv = h["market_value"]
        pnl = (h["price"]-h["cost"])/h["cost"]*100
        pct_t = mv/total_mv*100 if total_mv > 0 else 0
        day_pct = h.get("day_pct", 0.0)
        price_str = "{:.2f}".format(h["price"]) if h["price"] else "—"
        day_str = ("{:+.2f}%".format(day_pct)) if day_pct != 0.0 else "—"
        rows += ("<tr>"
                 "<td><div class=\'hname\'>" + h["name"] + "</div><div class=\'hcode\'>" + h["code"] + "</div></td>"
                 "<td style=\'text-align:center\'>" + str(h["shares"]) + "</td>"
                 "<td style=\'text-align:right\'>{:.2f}</td>".format(h["cost"]) +
                 "<td style=\'text-align:right;color:" + tc(h["price"]-h["cost"]) + "\'>" + price_str + "</td>"
                 "<td style=\'text-align:right;color:" + tc(day_pct) + "\'>" + day_str + "</td>"
                 "<td style=\'text-align:right;color:" + tc(pnl) + "\'>" + "{:+.1f}".format(pnl) + "%</td>"
                 "<td style=\'text-align:right\'>" + "{:.1f}".format(pct_t) + "%</td></tr>")
    return ("<table>"
            "<tr><th>名称/代码</th><th style=\'text-align:center\'>股数</th><th style=\'text-align:right\'>成本</th>"
            "<th style=\'text-align:right\'>现价</th><th style=\'text-align:right\'>" + label + "涨跌</th>"
            "<th style=\'text-align:right\'>持仓盈亏</th><th style=\'text-align:right\'>占总%</th></tr>"
            + rows + "</table>")

def news_rows(tagged):
    out = ""
    for n in tagged[:8]:
        secs = "·".join(n["sectors"]) if n["sectors"] else ""
        meta = n.get("source","") + (" · "+secs if secs else "")
        txt = n["text"][:130] + ("…" if len(n["text"]) > 130 else "")
        out += ("<div class=\'nitem\'><div class=\'nico\'>" + S_ICO.get(n["sentiment"],"⚖️") + "</div>"
                "<div class=\'nbody\'><div class=\'ntext\'>" + txt + "</div>"
                "<div class=\'nmeta\'>" + meta + "</div></div></div>")
    return out

def hold_analysis_rows(hvals, news_list):
    tagged = [{**x,"sentiment":analyze_sentiment(x["text"]),"sectors":match_sectors(x["text"])} for x in news_list]
    out = ""
    for h in HOLDINGS:
        rel = []
        for tag in h["tags"]:
            for item in tagged:
                if tag in item["text"]:
                    rel.append(item)
        seen = set(); deduped = []
        for x in rel:
            k = x["text"][:30]
            if k not in seen:
                seen.add(k); deduped.append(x)
        rel = deduped[:3]
        pos_c = sum(1 for x in rel if x["sentiment"]=="positive")
        neg_c = sum(1 for x in rel if x["sentiment"]=="negative")
        imp = "positive" if pos_c>neg_c else ("negative" if neg_c>pos_c else "neutral")
        ic = sc(imp)
        ib = "#ffeaea" if imp=="positive" else ("#e8f5ee" if imp=="negative" else "#f5f5f5")
        it = {"positive":"偏多","negative":"偏空","neutral":"中性"}.get(imp,"中性")
        hval = next((v for v in hvals if v["code"]==h["code"]),{})
        price = hval.get("price",0)
        day_pct = hval.get("day_pct", 0.0)
        pnl = (price-h["cost"])/h["cost"]*100 if price else 0
        price_str = "{:.2f}元".format(price) if price else "获取中"
        day_str = ("+" if day_pct >= 0 else "") + "{:.2f}%".format(day_pct)
        pnl_str = ("+" if pnl >= 0 else "") + "{:.1f}".format(pnl)
        rel_txt = "；".join(x["text"][:28] for x in rel)[:85] if rel else "今日暂无直接相关消息，关注大盘整体走势"
        out += ("<div class=\'nitem\'>"
                "<div class=\'nico\'>" + S_ICO.get(imp,"⚖️") + "</div>"
                "<div class=\'nbody\'>"
                "<div class=\'ntext\'><b>" + h["name"] + "</b> "
                "<span style=\'color:" + ic + ";background:" + ib + ";font-size:10px;padding:1px 6px;border-radius:10px;font-weight:700\'>" + it + "</span> "
                "<span style=\'font-size:11px;color:#aaa\'>" + price_str
                + " <span style=\'color:" + tc(day_pct) + "\'>" + day_str + "</span>"
                + " 持仓" + ("+" if pnl >= 0 else "") + "{:.1f}%".format(pnl) + "</span>"
                "</div>"
                "<div class=\'nmeta\'>相关：" + rel_txt + "…</div>"
                "</div></div>")
    return out


# ━━━━ 早盘报告 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def build_morning_report(us_q, quotes, hvals, news_list, north_data=None, breadth=None):
    n, ds = now_str()
    title = "📈 早盘快报 · " + ds
    avg = calc_avg_pct(quotes)
    bull = avg > 0.3; bear = avg < -0.3
    total_mv = sum(h["market_value"] for h in hvals)

    html = html_head(title) + title_div()

    # 外盘夜报
    us_rows = "".join(idx_card(q["name"],q.get("close",0),q.get("pct",0)) for q in us_q.values())
    if us_rows:
        html += card("🌙 昨夜美股", idx_grid(us_rows))

    # A50情绪
    a50 = fetch_a50()
    if a50 is not None:
        a50_bg = "#fff5f5" if a50>0 else ("#f0fff4" if a50<0 else "#f8f8f8")
        a50_ic = "📈" if a50>0 else ("📉" if a50<0 else "⚖️")
        a50_note = "A50上涨，早盘A股偏多" if a50>0.3 else ("A50下跌，早盘A股偏弱" if a50<-0.3 else "A50平稳，早盘震荡")
        html += banner(a50_ic, "A50期货 {a50:+.2f}%".format(a50=a50), a50_note, a50_bg)

    # A股指数
    idx_r = ""
    for key in ["sh000001","sz399001","sz399006","sh000300","sh000985","hkHSI","hkHSTECH"]:
        q = quotes.get(key,{}); c=q.get("close",0); p=q.get("pct",0)
        if c: idx_r += idx_card(q.get("name",key),c,p)
    html += card("📊 大盘指数", idx_grid(idx_r))

    # 大盘情绪
    tr_bg = "#fff5f5" if bull else ("#f0fff4" if bear else "#f8f8f8")
    tr_ic = "📈" if bull else ("📉" if bear else "⚖️")
    tr_txt = "大盘偏多" if bull else ("大盘偏空" if bear else "大盘震荡")
    tr_note = "市场情绪较好，可适当关注机会" if bull else ("注意控制仓位风险" if bear else "盘面平稳，观望为主")
    html += banner(tr_ic, "今日大盘预判：" + tr_txt, tr_note, tr_bg)

    # 仓位总览
    html += card("💼 账户仓位总览", pos_bar(total_mv))
# 北向资金（新增）
    nn = north_data.get("north_net")
    nn_sh = north_data.get("hk_to_sh")
    nn_sz = north_data.get("hk_to_sz")
    nn_pct = north_data.get("north_pct")
    if nn is not None:
        nn_yi = nn / 1e8
        nn_abs = abs(nn_yi)
        nn_color = "#e34a4a" if nn > 0 else "#3a9e4f"
        nn_icon = "↑" if nn > 0 else "↓"
        nn_txt = f"{nn_icon}{nn_abs:.2f}亿"
        sh_txt = (f"沪股通 {nn_sh/1e8:+.2f}亿" if nn_sh else "")
        sz_txt = (f"深股通 {nn_sz/1e8:+.2f}亿" if nn_sz else "")
        sub_txt = " ".join(x for x in [sh_txt, sz_txt] if x)
        nn_note = "今日外资主要流入板块" if nn > 0 else "今日外资主要流出板块"
        north_html = (
            f"<div style='text-align:center;padding:8px 0'>"
            f"<div style='font-size:28px;font-weight:700;color:{nn_color}'>{nn_txt}</div>"
            f"<div style='font-size:12px;color:#888;margin-top:4px'>{sub_txt or nn_note}</div></div>"
        )
        if nn_pct is not None:
            north_html += f"<div style='text-align:center;font-size:11px;color:#aaa'>北向持股变化 {nn_pct:+.2f}%</div>"
        html += card("🌊 北向资金（外资流向）", north_html)

    # 持仓明细
    html += card("📋 持仓个股复盘", hold_table(hvals, total_mv, label="上日涨跌"))
# 市场宽度（新增）
    if breadth and (breadth.get("up_count") or breadth.get("ad_ratio")):
        up = breadth.get("up_count") or 0
        dn = breadth.get("down_count") or 0
        lu = breadth.get("limit_up") or 0
        ld = breadth.get("limit_down") or 0
        ad = breadth.get("ad_ratio")
        # 涨跌颜色
        ad_color = "#e34a4a" if (ad and ad > 1) else ("#3a9e4f" if (ad and ad < 1) else "#888")
        ad_txt = f'{ad:.2f}' if ad else "—"
        up_color = "#e34a4a" if up > dn else "#3a9e4f"
        lu_color = "#e34a4a" if lu > 20 else ("#f39c12" if lu > 10 else "#888")
        ld_color = "#3a9e4f" if ld > 20 else ("#f39c12" if ld > 10 else "#888")
        breadth_html = (
            f"<div style='display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px'>"
            f"<div style='background:#f8f9fc;border-radius:10px;padding:10px;text-align:center'>"
            f"<div style='font-size:11px;color:#888;margin-bottom:4px'>上涨家数</div>"
            f"<div style='font-size:20px;font-weight:700;color:{up_color}'>{up:,}</div>"
            f"<div style='font-size:11px;color:#aaa'>下跌 {dn:,} 家</div></div>"
            f"<div style='background:#f8f9fc;border-radius:10px;padding:10px;text-align:center'>"
            f"<div style='font-size:11px;color:#888;margin-bottom:4px'>涨跌比</div>"
            f"<div style='font-size:20px;font-weight:700;color:{ad_color}'>{ad_txt}</div>"
            f"<div style='font-size:11px;color:#aaa'>上涨/下跌</div></div>"
            f"<div style='background:#f8f9fc;border-radius:10px;padding:10px;text-align:center'>"
            f"<div style='font-size:11px;color:#888;margin-bottom:4px'>涨停 / 跌停</div>"
            f"<div style='font-size:16px;font-weight:700'>"
            f"<span style='color:{lu_color}'>▲{lu}</span> / "
            f"<span style='color:{ld_color}'>▼{ld}</span></div>"
            f"<div style='font-size:11px;color:#aaa'>投机情绪</div></div></div>"
        )
        html += card("📊 市场宽度（两市），共" + str(breadth.get("total") or "—") + "只", breadth_html)
    else:
        html += card("📊 市场宽度", "<div style='text-align:center;color:#888;font-size:12px'>数据获取中，稍后更新</div>")

    # 个股操盘建议
    html += card("🎯 个股操盘建议", html_stock_advice(hvals, news_list, avg, quotes))

    # 消息面
    tagged = [{**x,"sentiment":analyze_sentiment(x["text"]),"sectors":match_sectors(x["text"])} for x in news_list]
    pos_n = [x for x in tagged if x["sentiment"]=="positive"]
    neg_n = [x for x in tagged if x["sentiment"]=="negative"]
    html += card("📰 重要消息面（利好 {:d} 条 / 利空 {:d} 条）".format(len(pos_n),len(neg_n)),
                 news_rows(pos_n+neg_n))

    # 今日推荐个股（稳健型）
    recs = recommend_stocks(news_list, avg)
    html += card("🔍 今日推荐个股", html_recommendation_section(recs, hvals, avg, news_list))

    # 仓位建议
    adv = get_position_advice(avg,total_mv)
    html += card("🎯 仓位调整建议", adj_rows(adv))
# 明日操作指引（新增）
    tg = calc_tomorrow_guide(quotes, avg, north_data)
    sh = quotes.get("sh000001", {})
    sh_close = tg["sh_close"]; sh_pct = tg["sh_pct"]
    resist = tg["resist"]; support = tg["support"]
    trend = tg["trend"]; trend_note = tg["trend_note"]
    north_dir = tg["north_dir"]
    acts = tg["actions"]
    trend_color = "#e34a4a" if trend=="偏多" else ("#3a9e4f" if trend=="偏空" else "#888")
    trend_icon  = "📈" if trend=="偏多" else ("📉" if trend=="偏空" else "⚖️")
    # 大盘关键点位
    point_html = ""
    if resist and support:
        point_html = (
            f"<div style='display:flex;gap:16px;justify-content:center;padding:8px 0;border-top:1px solid #f0f0f0;margin-top:8px'>"
            f"<div style='text-align:center'><div style='font-size:10px;color:#888'>上证压力</div>"
            f"<div style='font-size:15px;font-weight:700;color:#e34a4a'>{resist}</div></div>"
            f"<div style='text-align:center'><div style='font-size:10px;color:#888'>上证收盘</div>"
            f"<div style='font-size:15px;font-weight:700;color:#1a1a2e'>{sh_close:.0f}</div></div>"
            f"<div style='text-align:center'><div style='font-size:10px;color:#888'>上证支撑</div>"
            f"<div style='font-size:15px;font-weight:700;color:#3a9e4f'>{support}</div></div></div>"
        )
    north_note = f"<div style='font-size:11px;color:#aaa;text-align:center;margin-bottom:6px'>{north_dir}</div>"
    acts_html = ""
    for act in acts:
        acts_html += (
            f"<div style='display:flex;gap:8px;padding:6px 0;border-bottom:1px solid #f5f5f5'>"
            f"<div style='font-size:14px'>{act['icon']}</div>"
            f"<div><div style='font-size:12px;font-weight:700;color:#1a1a2e'>{act['label']}</div>"
            f"<div style='font-size:11px;color:#666'>{act['text']}</div></div></div>"
        )
    tomorrow_html = (
        f"<div style='text-align:center;padding:10px 0'>"
        f"<div style='display:inline-block;background:#f5f7fa;border-radius:12px;padding:6px 16px;margin-bottom:8px'>"
        f"<span style='font-size:16px;margin-right:6px'>{trend_icon}</span>"
        f"<span style='font-size:18px;font-weight:700;color:{trend_color}'>{trend}</span>"
        f"<span style='font-size:12px;color:#888;margin-left:8px'>{sh_close:.0f}点 {sh_pct:+.2f}%</span></div>"
        f"<div style='font-size:12px;color:#555;margin-bottom:4px'>{trend_note}</div></div>"
        + north_note + point_html +
        f"<div style='margin-top:6px'>{acts_html}</div>"
    )
    html += card("🔮 明日操作指引", tomorrow_html)

    html += "<div class=\'ft\'>Generated by 虾兵2号 🦞 · GitHub Actions云端</div></div></body></html>"
    return html, title

# ━━━━ 盘尾报告 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def build_afternoon_report(quotes, hvals, news_list):
    n, ds = now_str()
    title = "📊 盘尾简报 · " + ds
    avg = calc_avg_pct(quotes)
    bull = avg > 0.3; bear = avg < -0.3
    total_mv = sum(h["market_value"] for h in hvals)

    html = html_head(title) + title_div()

    # 收盘指数
    idx_r = ""
    for key in ["sh000001","sz399001","sz399006","sh000300","sh000985","hkHSI","hkHSTECH"]:
        q = quotes.get(key,{}); c=q.get("close",0); p=q.get("pct",0)
        if c: idx_r += idx_card(q.get("name",key),c,p)
    html += card("📊 今日收盘", idx_grid(idx_r))

    # 收盘总结
    tr_bg = "#fff5f5" if bull else ("#f0fff4" if bear else "#f8f8f8")
    tr_ic = "📈" if bull else ("📉" if bear else "⚖️")
    tr_txt = "今日偏多" if bull else ("今日偏空" if bear else "今日震荡")
    sh_close = quotes.get("sh000001",{}).get("close",0)
    sh_pct = quotes.get("sh000001",{}).get("pct",0)
    tr_note = "上证 {:.2f} {:+.2f}%，两市整体{}".format(sh_close,sh_pct,tr_txt[2:])
    html += banner(tr_ic, "今日收盘："+tr_txt, tr_note, tr_bg)

    # 仓位总览
    html += card("💼 账户仓位总览", pos_bar(total_mv))

    # 持仓明细
    html += card("📋 持仓个股复盘", hold_table(hvals,total_mv))

    # 个股操盘建议
    html += card("🎯 个股操盘建议", html_stock_advice(hvals, news_list, avg, quotes))

    # 持仓个股今日影响分析
    html += card("📋 持仓个股今日影响分析", hold_analysis_rows(hvals,news_list))
# 持仓阿尔法分析（新增）
    alpha_vals = calc_holding_alpha(hvals, quotes)
    sh_pct_ref = alpha_vals[0].get("sh_pct", 0) if alpha_vals else 0
    alpha_rows = ""
    for av in alpha_vals:
        a = av.get("alpha", 0)
        a_color = "#e34a4a" if a > 0 else ("#3a9e4f" if a < 0 else "#888")
        a_icon  = "▲" if a > 0 else ("▼" if a < 0 else "—")
        dp = av.get("day_pct", 0)
        dp_str = f"{dp:+.2f}%"
        name = av.get("name","")
        code = av.get("code","")
        alpha_rows += (
            f"<tr>"
            f"<td><div class='hname'>{name}</div><div class='hcode'>{code}</div></td>"
            f"<td style='text-align:right;color:#888'>{dp_str}</td>"
            f"<td style='text-align:right'>大盘{sh_pct_ref:+.2f}%</td>"
            f"<td style='text-align:right;color:{a_color};font-weight:700'>{a_icon}{abs(a):.2f}%</td></tr>"
        )
    alpha_table = (
        "<table>"
        "<tr><th>名称</th><th style='text-align:right'>今日涨跌</th>"
        "<th style='text-align:right'>基准大盘</th>"
        "<th style='text-align:right'>超额（α）</th></tr>"
        + alpha_rows +
        "</table>"
        "<div style='font-size:10px;color:#aaa;margin-top:6px'>◆ 超额收益 α > 0 表示跑赢大盘，α < 0 表示跑输大盘</div>"
    )
    html += card("📊 持仓超额收益（α）分析", alpha_table)

    # 消息面
    tagged = [{**x,"sentiment":analyze_sentiment(x["text"]),"sectors":match_sectors(x["text"])} for x in news_list]
    pos_n = [x for x in tagged if x["sentiment"]=="positive"]
    neg_n = [x for x in tagged if x["sentiment"]=="negative"]
    html += card("📰 重要消息面（利好 {:d} 条 / 利空 {:d} 条）".format(len(pos_n),len(neg_n)), news_rows(pos_n+neg_n))

    # 明日推荐个股
    recs = recommend_stocks(news_list, avg)
    html += card("🔍 明日推荐个股", html_recommendation_section(recs, hvals, avg, news_list))

    # 仓位建议
    adv = get_position_advice(avg,total_mv)
    html += card("🎯 仓位调整建议", adj_rows(adv))

    html += "<div class=\'ft\'>Generated by 虾兵2号 🦞 · GitHub Actions云端</div></div></body></html>"
    return html, title

# ━━━━ 周末报告 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def build_weekend_report(news_list, a50_pct):
    n, ds = now_str()
    title = "📋 周末消息面分析 · " + ds
    tagged = [{**x,"sentiment":analyze_sentiment(x["text"]),"sectors":match_sectors(x["text"])} for x in news_list]
    pos_n = [x for x in tagged if x["sentiment"]=="positive"]
    neg_n = [x for x in tagged if x["sentiment"]=="negative"]
    sec_news = {}
    for item in tagged:
        for s in item["sectors"]:
            sec_news.setdefault(s,[]).append(item)
    pos_c = len(pos_n); neg_c = len(neg_n)
    overall = "positive" if pos_c>neg_c+2 else ("negative" if neg_c>pos_c+2 else "neutral")
    ov_bg = {"positive":"#fff5f5","negative":"#f0fff4","neutral":"#f8f8f8"}[overall]
    ov_ico = S_ICO.get(overall,"⚖️")
    ov_txt = {"positive":"消息面偏暖，周一谨慎看多","negative":"消息面偏空，注意控仓风险","neutral":"消息面平稳，无明确方向"}[overall]

    hold_analysis = []
    for h in HOLDINGS:
        rel = []
        for tag in h["tags"]:
            for item in tagged:
                if tag in item["text"]: rel.append(item)
        seen = set(); deduped = []
        for x in rel:
            k = x["text"][:30]
            if k not in seen: seen.add(k); deduped.append(x)
        rel = deduped[:4]
        pc = sum(1 for x in rel if x["sentiment"]=="positive")
        nc = sum(1 for x in rel if x["sentiment"]=="negative")
        imp = "positive" if pc>nc else ("negative" if nc>pc else "neutral")
        hold_analysis.append({"name":h["name"],"code":h["code"],"cost":h["cost"],
                              "shares":h["shares"],"watch":h["watch"],"impact":imp,"relevant":rel})

    sec_summary = []
    for sec in ["医疗","银行","券商","科技","新能源","消费","宏观"]:
        if sec not in sec_news: continue
        items = sec_news[sec]
        pc = sum(1 for x in items if x["sentiment"]=="positive")
        nc = sum(1 for x in items if x["sentiment"]=="negative")
        imp_s = "positive" if pc>nc else ("negative" if nc>pc else "neutral")
        sec_summary.append({"name":sec,"impact":imp_s,
            "impact_txt":{"positive":"偏多","negative":"偏空","neutral":"中性"}[imp_s],"news":items[:2]})

    html = html_head(title) + title_div()

    if a50_pct is not None:
        a50_bg = "#fff5f5" if a50_pct>0 else ("#f0fff4" if a50_pct<0 else "#f8f8f8")
        a50_ic = "📈" if a50_pct>0 else ("📉" if a50_pct<0 else "⚖️")
        a50_note = "周一开盘偏多信号" if a50_pct>0.3 else ("周一开盘偏弱" if a50_pct<-0.3 else "周一开盘平稳")
        html += banner(a50_ic, "A50期货 {:+.2f}%".format(a50_pct), a50_note, a50_bg)

    html += banner(ov_ico, ov_txt,
        "共分析 {:d} 条资讯 | 利好 {:d} 条 | 利空 {:d} 条".format(len(news_list),pos_c,neg_c), ov_bg)
    html += card("📰 重要财经快讯", news_rows(tagged[:8]))

    if sec_summary:
        sec_rows_out = ""
        for s in sec_summary:
            ic = sc(s["impact"])
            ib = "#ffeaea" if s["impact"]=="positive" else ("#e8f5ee" if s["impact"]=="negative" else "#f5f5f5")
            np = "；".join(x["text"][:25] for x in s["news"])[:65]
            sec_rows_out += ("<div class=\'sec\'>"
                "<div class=\'secname\'>" + S_ICO.get(s["impact"],"⚖️") + " " + s["name"] + "</div>"
                "<div class=\'secimp\' style=\'color:" + ic + ";background:" + ib + "\'>" + s["impact_txt"] + "</div>"
                "<div class=\'secdesc\'>" + np + "…</div></div>")
        html += card("📊 板块影响一览", sec_rows_out)

    hold_cards = ""
    for ha in hold_analysis:
        ic = sc(ha["impact"])
        ib = "#ffeaea" if ha["impact"]=="positive" else ("#e8f5ee" if ha["impact"]=="negative" else "#f5f5f5")
        ico = S_ICO.get(ha["impact"],"⚖️")
        it = {"positive":"偏多","negative":"偏空","neutral":"中性"}.get(ha["impact"],"中性")
        if ha["relevant"]:
            rel_items = "<br>".join("• " + x["text"][:55] + ("..." if len(x["text"])>55 else "") for x in ha["relevant"][:2])
        else:
            rel_items = "周末暂无相关消息，关注周一开盘"
        hold_cards += ("<div class=\'nitem\'><div class=\'nico\'>" + ico + "</div><div class=\'nbody\'>"
            "<div class=\'ntext\'><b>" + ha["name"] + "</b> "
            "<span style=\'color:" + ic + ";background:" + ib + ";font-size:10px;padding:1px 6px;border-radius:10px;font-weight:700\'>" + it + "</span>"
            " <span style=\'font-size:11px;color:#aaa\'>" + str(ha["shares"]) + "股/成本{:.2f}元</span></div>".format(ha["cost"]) +
            "<div class=\'nmeta\'>相关：" + rel_items + "</div></div></div>")

    order_rows = ""
    for ha in hold_analysis:
        imp = ha["impact"]
        if imp == "positive":
            order_rows += ("<div style=\'padding:8px;background:#f0fff4;border-radius:8px;margin-bottom:8px;font-size:12px;line-height:1.5\'>"
                "<b style=\'color:#3a9e4f\'>🟢 关注买入机会</b><br>"
                "积极信号：利好消息支撑，考虑逢低加仓。<br>"
                "建议挂「价格提醒」：涨超+5%提醒减仓；跌超-5%提醒关注。</div>")
        elif imp == "negative":
            order_rows += ("<div style=\'padding:8px;background:#fff5f5;border-radius:8px;margin-bottom:8px;font-size:12px;line-height:1.5\'>"
                "<b style=\'color:#e34a4a\'>🔴 关注卖出风险</b><br>"
                "风险信号：利空消息压制，建议设置止损提醒。<br>"
                "建议挂「止损提醒」：跌破成本价-5%提醒；跌破-8%确认是否离场。</div>")
        else:
            order_rows += ("<div style=\'padding:8px;background:#f8f8f8;border-radius:8px;margin-bottom:8px;font-size:12px;line-height:1.5\'>"
                "<b style=\'color:#888\'>🟡 观望为主</b><br>"
                "中性信号：暂无必要调整现有条件单，关注周一开盘方向再定。</div>")

    html += card("📋 持仓影响分析", hold_cards)
# 周末增强：财报日历
    cal = fetch_earnings_calendar()
    if cal:
        cal_rows = ""
        for item in cal[:8]:
            cal_rows += (
                f"<div style='display:flex;gap:10px;padding:7px 0;border-bottom:1px solid #f5f5f5'>"
                f"<div style='font-size:11px;color:#888;width:70px;flex-shrink:0'>{item.get('date','')}</div>"
                f"<div style='font-size:12px;color:#444;flex:1'>{item.get('title','')}</div></div>"
            )
        html += card("📅 未来2周财经日历（财报+宏观）", cal_rows)
    else:
        html += card("📅 未来2周财经日历", "<div style='text-align:center;color:#888;font-size:12px'>暂无数据</div>");
    html += card("🎯 条件单建议 & 操作参考", order_rows)
    est_total_mv = sum(h["shares"]*h["cost"] for h in HOLDINGS)
    html += card("💼 账户仓位参考", pos_bar(est_total_mv))
    html += "<div class=\'ft\'>Generated by 虾兵2号 🦞 · GitHub Actions云端</div></div></body></html>"
    return html, title

# ━━━━ 主入口 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def main():
    # 根据北京时间自动判断报告类型，忽略命令行参数
    n, _ = now_str()
    hour = n.hour
    is_weekend = n.weekday() >= 5
    
    if is_weekend:
        mode = "weekend"
        news = fetch_news()
        a50 = fetch_a50()
        html, subject = build_weekend_report(news, a50)
    elif hour < 12:
        mode = "morning"
        us_q = fetch_us_quotes()
        north_data = fetch_north_money()
        breadth = fetch_market_breadth()
        quotes = fetch_quotes()
        hvals = calc_holding_values()
        news = fetch_news()
        html, subject = build_morning_report(us_q, quotes, hvals, news, north_data, breadth)
    else:
        mode = "afternoon"
        quotes = fetch_quotes()
        hvals = calc_holding_values()
        news = fetch_news()
        html, subject = build_afternoon_report(quotes, hvals, news)
    print("📊 报告生成完毕: " + subject)
    send_email(subject, html)
    print("✅ 完成!")

if __name__ == "__main__":
    main()
