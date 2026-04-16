#!/usr/bin/env python3
"""
GitHub Actions 云端：A股投资报告（早报 / 盘尾 / 非交易日）
用法：
  python3 generate_report.py [morning|afternoon|weekend]
"""
import requests, datetime, json, sys, os, re

# ── 用户配置 ─────────────────────────────────────────────
TOTAL_CASH = 150000.0
HOLDINGS = [
    {"code": "002223", "name": "鱼跃医疗", "shares": 700,  "cost": 32.50,
     "tags": ["医药","医疗器械","养老","医保","健康"],
     "watch": "集采降价、医疗器械政策、老龄化"},
    {"code": "002142", "name": "宁波银行", "shares": 600,  "cost": 30.83,
     "tags": ["银行","降息","降准","房地产","信贷","LPR","息差"],
     "watch": "房地产风险、净息差、业绩增速"},
    {"code": "002736", "name": "国信证券", "shares": 2000, "cost": 12.04,
     "tags": ["券商","注册制","IPO","北交所","资本市场","交易量","两融"],
     "watch": "成交量、两融余额、IPO节奏"},
]
SMTP_USER = '704901171@qq.com'
SMTP_PASS = 'yoyqmwluklabbcic'
SMTP_HOST = 'smtp.qq.com'
SMTP_PORT = 465
# ─────────────────────────────────────────────────────────

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  行情数据
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def fetch_quotes():
    try:
        codes = "sh000001,sz399001,sz399006,hkHSI,hkHSTECH"
        r = requests.get(f"http://hq.sinajs.cn/list={codes}",
                         headers={"Referer": "http://finance.sina.com.cn"}, timeout=10)
        r.encoding = 'gbk'
        result = {}
        for line in r.text.strip().split('\n'):
            if '=' not in line: continue
            key = line.split('=')[0].split('_')[-1]
            val = line.split('"')[1] if '"' in line else ''
            parts = val.split(',')
            if len(parts) >= 4:
                result[key] = {
                    "name": parts[0],
                    "close": float(parts[1]),
                    "pct": float(parts[2]) if parts[2] else 0.0,
                    "change": float(parts[3]) if parts[3] else 0.0
                }
        return result
    except Exception as e:
        print(f"行情获取失败: {e}")
        return {}

def fetch_stock_price(code):
    try:
        prefix = "sh" if code.startswith("6") else "sz"
        r = requests.get(f"http://hq.sinajs.cn/list={prefix}{code}",
                         headers={"Referer": "http://finance.sina.com.cn"}, timeout=10)
        r.encoding = 'gbk'
        val = r.text.split('"')[1].split(',')
        return float(val[3]) if len(val) > 3 else 0.0
    except:
        return 0.0

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  消息数据
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def fetch_news():
    """抓取最新财经快讯，返回列表[{'text': str, 'time': str}]"""
    news = []
    # 新浪快讯
    try:
        r = requests.get(
            "https://zhibo.sina.com.cn/api/zhibo/feed?zhibo_id=152&page=1&page_size=20&tag_id=0&dire=f&dpc=1&pagesize=20&id=0",
            headers={"Referer": "https://finance.sina.com.cn"}, timeout=10)
        d = r.json()
        for item in d.get("result", {}).get("data", {}).get("feed", {}).get("list", []):
            txt = re.sub(r'<[^>]+>', '', item.get("rich_text", "")).strip()
            if txt and len(txt) > 10:
                # 过滤纯外盘/期货
                news.append({"text": txt, "source": "新浪"})
    except Exception as e:
        print(f"新浪快讯失败: {e}")

    # 东方财富资讯（今日公告）
    try:
        r = requests.get(
            "https://np-anotice-stock.eastmoney.com/api/security/ann"
            "?sr=-1&page_size=15&page_index=1&ann_type=SHA,CYB,SZA,HSZA,BJA"
            "&client_source=web&_=1",
            headers={"Referer": "https://www.eastmoney.com"}, timeout=10)
        d = r.json()
        for item in d.get("data", {}).get("list", []):
            title = item.get("title", "")
            if title:
                news.append({"text": title, "source": "东财公告"})
    except Exception as e:
        print(f"东财公告失败: {e}")

    return news

def fetch_a50():
    """获取A50期货涨跌幅"""
    try:
        r = requests.get(
            "https://hq.sinajs.cn/list=hsi05088",
            headers={"Referer": "http://finance.sina.com.cn"}, timeout=8)
        r.encoding = 'gbk'
        val = r.text.split('"')[1].split(',')
        if len(val) > 5:
            return float(val[5])  # 涨跌%
    except:
        pass
    return None

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  消息分析
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SENTIMENT_KEYWORDS = {
    "利好": ["上涨","反弹","突破","牛市","做多","加仓","增持","超配","买入","超预期","业绩增长","政策支持","降息","降准","宽松","万亿","资金流入","外资","北向","净买入"],
    "利空": ["下跌","暴跌","跳水","熊市","做空","减持","减仓","低配","卖出","不及预期","业绩下滑","监管","收紧","加息","缩表","外资流出","北向净卖出","踩雷"],
    "中性": ["震荡","横盘","观望","等待","平稳","波动","区间"],
}
SECTOR_KEYWORDS = {
    "医疗":    ["医疗","医药","医保","集采","医疗器械","老龄化","养老","健康中国","中药","创新药","疫苗"],
    "银行":    ["银行","降息","降准","LPR","信贷","房地产","息差","不良率","净息差","存款利率","村镇银行"],
    "券商":    ["券商","注册制","IPO","北交所","资本市场","两融","交易量","投行","并购重组","股票质押"],
    "科技":    ["AI","人工智能","半导体","芯片","国产替代","算力","大模型","英伟达"],
    "新能源":  ["新能源","锂电","光伏","储能","碳中和","电动车","固态电池","充电桩"],
    "消费":    ["消费","白酒","家电","汽车","内需","零售","618","双十一"],
    "宏观":    ["GDP","CPI","PPI","PMI","美联储","人民币","汇率","进出口","外贸","关税","经济数据","美股","港股"],
}

def analyze_sentiment(text):
    pos = neg = 0
    for kw in SENTIMENT_KEYWORDS["利好"]:
        if kw in text: pos += 1
    for kw in SENTIMENT_KEYWORDS["利空"]:
        if kw in text: neg += 1
    if pos > neg: return "positive"
    if neg > pos: return "negative"
    return "neutral"

def match_sectors(text):
    found = []
    for sector, kws in SECTOR_KEYWORDS.items():
        for kw in kws:
            if kw in text:
                found.append(sector)
                break
    return list(set(found)) if found else []

def match_holdings(text):
    """检查文本是否与持仓相关"""
    matches = []
    text_lower = text
    for h in HOLDINGS:
        # 名称/代码
        if h["name"].replace("医疗","").replace("银行","").replace("证券","") in text: matches.append(h)
        if h["code"] in text: matches.append(h)
        # 标签关键词
        for tag in h["tags"]:
            if tag in text: matches.append(h); break
    return [x for x in dict.fromkeys([h["name"] for h in matches])][:3]  # 去重，最多3个

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  邮件发送
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def send_email(subject, html):
    import smtplib, ssl
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    from email.header import Header
    msg = MIMEMultipart('alternative')
    msg['Subject'] = Header(subject, 'utf-8')
    msg['From'] = SMTP_USER
    msg['To'] = SMTP_USER
    msg.attach(MIMEText(html, 'html', 'utf-8'))
    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=context) as server:
        server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(SMTP_USER, [SMTP_USER], msg.as_string())
    print(f"✅ 邮件已发送: {subject}")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  颜色工具
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def trend_color(pct):
    c = float(pct)
    if c > 0: return "#e34a4a"
    if c < 0: return "#3a9e4f"
    return "#888"

def sentiment_color(s):
    return {"positive": "#e34a4a", "negative": "#3a9e4f", "neutral": "#888"}.get(s, "#888")

SENTIMENT_ICON = {"positive": "📈", "negative": "📉", "neutral": "⚖️"}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  工作日报告
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def generate_workday_report(quotes, holding_values, total_value, mode):
    now = datetime.datetime.now()
    wmap = {0:'周日',1:'周一',2:'周二',3:'周三',4:'周四',5:'周五',6:'周六'}
    date_str = f"{now.year}年{now.month}月{now.day}日 {wmap[now.weekday()]}"

    # ── 指数 ──
    idx_map = {
        "000001": ("上证指数", "sh000001"),
        "399001": ("深证成指", "sz399001"),
        "399006": ("创业板指", "sz399006"),
        "HSI":    ("恒生指数", "hkHSI"),
        "HSTECH": ("恒生科技", "hkHSTECH"),
    }
    idx_cards = ""
    for code, (name, key) in idx_map.items():
        q = quotes.get(key, {})
        pct = q.get("pct", 0)
        close = q.get("close", 0)
        if close:
            idx_cards += f"""<div class="idx-card">
      <div class="idx-name">{name}</div>
      <div class="idx-close">{close:,.2f}</div>
      <div class="idx-pct" style="color:{trend_color(pct)}">{'▲' if pct>0 else '▼' if pct<0 else '—'} {pct:+.2f}%</div>
    </div>"""

    # ── 大盘多空 ──
    avg_pct = sum(float(quotes.get(k,{}).get("pct",0)) for k in ["sh000001","sz399001","sz399006"])/3
    bull = avg_pct > 0.3; bear = avg_pct < -0.3
    trend_bg = "#fff5f5" if bull else ("#f0fff4" if bear else "#f8f8f8")
    trend_txt = "📈 大盘偏多" if bull else ("📉 大盘偏空" if bear else "⚖️ 大盘震荡")
    trend_note = "市场情绪较好，可适当关注机会" if bull else ("注意控制仓位风险" if bear else "盘面平稳，观望为主")

    # ── 持仓 ──
    cash = TOTAL_CASH - sum(h["shares"]*h["price"] for h in holding_values)
    hold_rows = ""
    for h in holding_values:
        mv = h["market_value"]
        pct_total = mv / total_value * 100
        pnl_pct = (h["price"]-h["cost"])/h["cost"]*100
        hold_rows += f"""<tr>
      <td>{h['name']}</td><td>{h['code']}</td><td>{h['shares']}</td>
      <td>{h['cost']:.2f}</td><td>{h['price']:.2f}</td>
      <td style="color:{trend_color(pnl_pct)}">{pnl_pct:+.1f}%</td>
      <td>{pct_total:.1f}%</td>
    </tr>"""
    total_mv = sum(h["market_value"] for h in holding_values)
    invest_pct = total_mv/TOTAL_CASH*100; cash_pct = 100-invest_pct

    # ── 推荐板块（按今日大盘强弱动态调整）──
    if bull:
        recs = [
            ("大金融（银行/券商）", "低估值 + 政策宽松预期，成交量回暖利好券商"),
            ("科技成长（AI/半导体）", "风险偏好提升，资金倾向于弹性板块"),
            ("新能源", "政策加码+超跌反弹概率"),
        ]
    elif bear:
        recs = [
            ("医药医疗", "防御性强 + 老龄化长期逻辑"),
            ("银行", "低估值抗跌，高股息防御"),
            ("消费", "政策刺激预期，内需托底"),
        ]
    else:
        recs = [
            ("大金融", "低估值修复预期，关注成交量信号"),
            ("医药", "业绩稳健，防御配置"),
            ("科技", "等待政策明朗，谨慎参与"),
        ]
    rec_rows = "".join(f"<li><b>{r[0]}</b> — {r[1]}</li>" for r in recs)

    title_time = f"{'📈 早盘快报' if mode=='morning' else '📊 盘尾简报'} · {date_str}"
    html = f"""<!DOCTYPE html><html><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title_time}</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;background:#f5f6fa;color:#222;padding:12px;max-width:600px;margin:0 auto}}
h1{{font-size:18px;margin-bottom:12px;color:#333}}
.card{{background:#fff;border-radius:10px;padding:16px;margin-bottom:12px;box-shadow:0 1px 4px rgba(0,0,0,.08)}}
.section-title{{font-size:12px;font-weight:600;color:#888;margin-bottom:10px;text-transform:uppercase;letter-spacing:.5px}}
.idx-grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}}
.idx-card{{background:#f8f9fa;border-radius:8px;padding:10px 6px;text-align:center}}
.idx-name{{font-size:11px;color:#888;margin-bottom:4px}}
.idx-close{{font-size:15px;font-weight:700;color:#333}}
.idx-pct{{font-size:12px;font-weight:600;margin-top:2px}}
.trend-banner{{padding:12px 16px;border-radius:10px;margin-bottom:12px;background:{trend_bg};text-align:center}}
.trend-banner strong{{font-size:16px}}
.trend-banner p{{font-size:12px;color:#666;margin-top:4px}}
.pos-bar-wrap{{background:#eee;border-radius:6px;height:20px;overflow:hidden;display:flex}}
.pos-bar-invest{{background:linear-gradient(90deg,#4a90d9,#6ab0f0);height:100%;display:flex;align-items:center;justify-content:center;color:#fff;font-size:10px;font-weight:600}}
.pos-bar-cash{{background:#e8f4ea;height:100%;display:flex;align-items:center;justify-content:center;color:#2a7a40;font-size:10px;font-weight:600}}
.pos-legend{{display:flex;justify-content:space-between;font-size:12px;color:#888;margin-top:4px}}
table{{width:100%;border-collapse:collapse;font-size:12px}}
th{{background:#f0f2f5;padding:8px 4px;text-align:left;color:#888;font-weight:500;border-bottom:1px solid #eee}}
td{{padding:8px 4px;border-bottom:1px solid #f5f5f5}}
.cash-row{{display:flex;justify-content:space-between;font-size:13px;padding:10px 0;border-top:1px solid #eee;margin-top:8px}}
.cash-row span{{color:#2a7a40;font-weight:600}}
ul{{padding-left:16px;font-size:13px;line-height:2}}
.footer{{text-align:center;font-size:11px;color:#aaa;margin-top:8px}}
</style></head><body>
<h1>{title_time}</h1>
<div class="trend-banner"><strong>{trend_txt}</strong><p>{trend_note}</p></div>
<div class="card"><div class="section-title">📊 大盘指数</div><div class="idx-grid">{idx_cards}</div></div>
<div class="card"><div class="section-title">💼 仓位概览</div>
<div class="pos-bar-wrap">
<div class="pos-bar-invest" style="width:{invest_pct:.1f}%">{invest_pct:.1f}% 持仓</div>
<div class="pos-bar-cash" style="width:{cash_pct:.1f}%">{cash_pct:.1f}% 现金</div>
</div>
<div class="pos-legend"><span>持仓 {total_mv:,.0f} 元</span><span>现金 {cash:,.0f} 元</span><span>总计 {TOTAL_CASH:,.0f} 元</span></div>
</div>
<div class="card"><div class="section-title">📋 持仓明细</div>
<table><tr><th>名称</th><th>代码</th><th>股数</th><th>成本</th><th>现价</th><th>盈亏%</th><th>占总%</th></tr>
{hold_rows}</table>
<div class="cash-row">现金 <span>{cash:,.0f} 元</span></div>
</div>
<div class="card"><div class="section-title">🔍 {'当' if mode=='morning' else '本'}日关注板块</div>
<ul>{rec_rows}</ul>
</div>
<div class="footer">Generated by 虾兵2号 🦞 · GitHub Actions</div>
</body></html>"""
    return html, title_time

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  周末/非交易日报告
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def generate_weekend_report(news_list, a50_pct):
    now = datetime.datetime.now()
    wmap = {0:'周日',1:'周一',2:'周二',3:'周三',4:'周四',5:'周五',6:'周六'}
    date_str = f"{now.year}年{now.month}月{now.day}日 {wmap[now.weekday()]}"

    # ── A50大盘情绪 ──
    if a50_pct is not None:
        a50_color = trend_color(a50_pct)
        a50_icon = "▲" if a50_pct > 0 else "▼" if a50_pct < 0 else "—"
        a50_panel = f"""<div class="a50-banner" style="background:{'#fff5f5' if a50_pct>0 else '#f0fff4' if a50_pct<0 else '#f8f8f8'}">
  <div class="a50-label">🌏 富时中国A50期货</div>
  <div class="a50-pct" style="color:{a50_color}">{a50_icon} {a50_pct:+.2f}%</div>
  <div class="a50-note">{'周一开盘偏多' if a50_pct>0.3 else '周一开盘偏弱' if a50_pct<-0.3 else '周一开盘平稳'}</div>
</div>"""
    else:
        a50_panel = ""

    # ── 消息分类 ──
    positive_news, negative_news, neutral_news = [], [], []
    sector_news = {}   # sector -> [(text, sentiment, holdings)]
    macro_news = []
    all_alerts = []

    for item in news_list:
        text = item["text"]
        sentiment = analyze_sentiment(text)
        sectors = match_sectors(text)
        holders = match_holdings(text)
        tagged = {
            "text": text[:200],
            "source": item.get("source", ""),
            "sentiment": sentiment,
            "sectors": sectors,
            "holders": holders,
        }
        if sentiment == "positive": positive_news.append(tagged)
        elif sentiment == "negative": negative_news.append(tagged)
        else: neutral_news.append(tagged)
        if "宏观" in sectors:
            macro_news.append(tagged)
        for s in sectors:
            sector_news.setdefault(s, []).append(tagged)

    # ── 大盘整体情绪 ──
    total = len(news_list) or 1
    pos_n = len(positive_news); neg_n = len(negative_news)
    overall = "positive" if pos_n > neg_n + 2 else "negative" if neg_n > pos_n + 2 else "neutral"
    overall_icon = {"positive":"📈","negative":"📉","neutral":"⚖️"}[overall]
    overall_txt = {
        "positive": "消息面偏暖，周一谨慎看多",
        "negative": "消息面偏空，注意控仓风险",
        "neutral": "消息面平稳，无明确方向"
    }[overall]

    # ── 持仓影响分析 ──
    holding_analysis = []
    for h in HOLDINGS:
        name = h["name"]
        # 相关板块
        tags = h["tags"]
        relevant = []
        for s in tags:
            if s in sector_news:
                relevant.extend(sector_news[s])
        # 去除重复
        seen = set(); deduped = []
        for x in relevant:
            key = x["text"][:30]
            if key not in seen:
                seen.add(key); deduped.append(x)
        relevant = deduped[:4]  # 最多4条

        pos_rel = sum(1 for x in relevant if x["sentiment"]=="positive")
        neg_rel = sum(1 for x in relevant if x["sentiment"]=="negative")

        if pos_rel > neg_rel:
            impact = "positive"; impact_icon = "📈"; impact_txt = "偏多"
        elif neg_rel > pos_rel:
            impact = "negative"; impact_icon = "📉"; impact_txt = "偏空"
        else:
            impact = "neutral"; impact_icon = "⚖️"; impact_txt = "中性"

        holding_analysis.append({
            "name": name, "code": h["code"], "cost": h["cost"],
            "shares": h["shares"],
            "watch": h["watch"],
            "impact": impact, "impact_icon": impact_icon, "impact_txt": impact_txt,
            "relevant_news": relevant,
            "pos_rel": pos_rel, "neg_rel": neg_rel,
        })

    # ── 条件单建议 ──
    order_suggestions = []
    for ha in holding_analysis:
        n = ha["name"]
        imp = ha["impact"]
        # 生成建议
        if imp == "positive":
            order_suggestions.append({
                "name": n, "code": ha["code"],
                "action": "🟢 关注买入机会",
                "cond": "若周一高开回落，可挂条件单：",
                "example": "建议挂「回落卖出」条件单：高于现价+2%触发提醒；低于成本价-5%自动触发止损提醒",
                "alert": "积极信号：利好消息支撑，考虑逢低加仓"
            })
        elif imp == "negative":
            order_suggestions.append({
                "name": n, "code": ha["code"],
                "action": "🔴 关注卖出风险",
                "cond": "若周一低开，可挂条件单：",
                "example": "建议挂「回落止损」条件单：跌破成本价-5%提醒；跌破成本价-8%二次确认是否离场",
                "alert": "风险信号：利空消息压制，建议设置止损提醒"
            })
        else:
            order_suggestions.append({
                "name": n, "code": ha["code"],
                "action": "🟡 观望为主",
                "cond": "暂无明确信号，保持观察：",
                "example": "建议挂「价格提醒」：涨超+5%提醒减仓；跌超-5%提醒关注",
                "alert": "中性信号：暂无必要调整现有条件单"
            })

    # ── 板块影响摘要 ──
    sector_summary = []
    for sector_name in ["医疗","银行","券商","科技","新能源","消费","宏观"]:
        if sector_name in sector_news:
            items = sector_news[sector_name]
            pos_c = sum(1 for x in items if x["sentiment"]=="positive")
            neg_c = sum(1 for x in items if x["sentiment"]=="negative")
            if pos_c > neg_c: imp_s = "positive"
            elif neg_c > pos_c: imp_s = "negative"
            else: imp_s = "neutral"
            icon_s = {"positive":"📈","negative":"📉","neutral":"⚖️"}[imp_s]
            sector_summary.append({
                "name": sector_name,
                "icon": icon_s,
                "impact": imp_s,
                "impact_txt": {"positive":"偏多","negative":"偏空","neutral":"中性"}[imp_s],
                "count": len(items),
                "news": items[:2]
            })
    sector_rows = ""
    for s in sector_summary[:6]:
        news_preview = "；".join(x["text"][:30] for x in s["news"])[:80]
        sector_rows += f"""<div class="sector-row">
  <div class="sector-name">{s['icon']} {s['name']}</div>
  <div class="sector-impact" style="color:{sentiment_color(s['impact'])}">{s['impact_txt']}</div>
  <div class="sector-news">{news_preview}…</div>
</div>"""

    # ── 重要快讯 ──
    important_news = (positive_news[:4] + negative_news[:4])[:8]
    news_rows = ""
    for n in important_news:
        icon = SENTIMENT_ICON.get(n["sentiment"], "⚖️")
        sectors_str = "·".join(n["sectors"]) if n["sectors"] else ""
        news_rows += f"""<div class="news-item">
  <div class="news-icon">{icon}</div>
  <div class="news-body">
    <div class="news-text">{n['text'][:150]}</div>
    <div class="news-meta">{n.get('source','')}{' · '+sectors_str if sectors_str else ''}</div>
  </div>
</div>"""

    title_time = f"📋 非交易日消息面分析 · {date_str}"
    html = f"""<!DOCTYPE html><html><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title_time}</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;background:#f5f6fa;color:#222;padding:12px;max-width:600px;margin:0 auto}}
h1{{font-size:18px;margin-bottom:12px;color:#333}}
h2{{font-size:14px;font-weight:600;color:#333;margin-bottom:8px}}
h3{{font-size:13px;color:#666;margin-bottom:4px}}
.card{{background:#fff;border-radius:10px;padding:16px;margin-bottom:12px;box-shadow:0 1px 4px rgba(0,0,0,.08)}}
.section-title{{font-size:12px;font-weight:600;color:#888;margin-bottom:10px;text-transform:uppercase;letter-spacing:.5px}}
.a50-banner{{padding:14px 16px;border-radius:10px;margin-bottom:12px;display:flex;align-items:center;gap:12px}}
.a50-label{{font-size:13px;font-weight:600;color:#333}}
.a50-pct{{font-size:18px;font-weight:700}}
.a50-note{{font-size:12px;color:#666;margin-left:auto}}
.overall-banner{{padding:12px 16px;border-radius:10px;margin-bottom:12px;background:{'#fff5f5' if overall=='positive' else '#f0fff4' if overall=='negative' else '#f8f8f8'};text-align:center}}
.overall-banner strong{{font-size:16px}}
.overall-banner p{{font-size:12px;color:#666;margin-top:4px}}
.summary-bar{{display:flex;gap:8px;margin-top:10px;justify-content:center}}
.summary-chip{{background:#f0f0f0;border-radius:20px;padding:3px 10px;font-size:11px;color:#666}}
.summary-chip.pos{{background:#ffeaea;color:#c0392b}}
.summary-chip.neg{{background:#e8f5ee;color:#27ae60}}
.news-item{{display:flex;gap:10px;padding:10px 0;border-bottom:1px solid #f5f5f5}}
.news-item:last-child{{border-bottom:none}}
.news-icon{{font-size:16px;flex-shrink:0;padding-top:2px}}
.news-body{{flex:1}}
.news-text{{font-size:13px;line-height:1.5;color:#333}}
.news-meta{{font-size:11px;color:#aaa;margin-top:3px}}
.sector-row{{display:grid;grid-template-columns:80px 50px 1fr;gap:8px;align-items:center;padding:8px 0;border-bottom:1px solid #f5f5f5;font-size:12px}}
.sector-name{{font-weight:600;color:#333}}
.sector-impact{{font-weight:600;text-align:center}}
.sector-news{{color:#888;font-size:11px;line-height:1.4}}
.holding-card{{border:1px solid #eee;border-radius:10px;padding:12px;margin-bottom:10px}}
.holding-header{{display:flex;align-items:center;gap:8px;margin-bottom:6px}}
.holding-name{{font-weight:600;font-size:14px}}
.holding-tag{{background:{'#ffeaea' if ha['impact']=='positive' else '#e8f5ee' if ha['impact']=='negative' else '#f5f5f5'};color:{'#c0392b' if ha['impact']=='positive' else '#27ae60' if ha['impact']=='negative' else '#666'};font-size:11px;padding:2px 8px;border-radius:10px;font-weight:600}}
.holding-cost{{font-size:11px;color:#aaa}}
.order-suggestion{{margin-top:8px;padding:8px;background:#f8f9fa;border-radius:6px;font-size:12px}}
.order-label{{color:#4a90d9;font-weight:600;margin-bottom:3px}}
.order-text{{color:#666;line-height:1.5}}
.alert-box{{margin-top:6px;padding:6px 10px;background:{'#fff5f5' if s['action'].startswith('🟢') else '#f0fff4' if s['action'].startswith('🔴') else '#f8f8f8'};border-radius:6px;font-size:12px;color:#333;border-left:3px solid {'#e34a4a' if s['action'].startswith('🟢') else '#3a9e4f' if s['action'].startswith('🔴') else '#aaa'}}
.footer{{text-align:center;font-size:11px;color:#aaa;margin-top:8px}}
</style></head><body>
<h1>{title_time}</h1>

{a50_panel}

<div class="overall-banner">
  <strong>{overall_icon} {overall_txt}</strong>
  <p>共分析 {len(news_list)} 条财经资讯 | 利好 {pos_n} 条 | 利空 {neg_n} 条</p>
  <div class="summary-bar">
    <span class="summary-chip pos">📈 利好 {pos_n}</span>
    <span class="summary-chip neg">📉 利空 {neg_n}</span>
  </div>
</div>

<div class="card">
  <div class="section-title">📰 重要财经快讯</div>
  {news_rows}
</div>

<div class="card">
  <div class="section-title">📊 板块影响一览</div>
  {sector_rows}
</div>

<div class="card">
  <div class="section-title">🎯 持仓影响分析 & 条件单建议</div>
"""

    for ha, s in zip(holding_analysis, order_suggestions):
        ha_impact_color = sentiment_color(ha["impact"])
        relevant_news_html = ""
        if ha["relevant_news"]:
            rel_items = "<br>".join(
                f"• {x['text'][:60]}{'…' if len(x['text'])>60 else ''}"
                for x in ha["relevant_news"][:2]
            )
            relevant_news_html = f"<div style='font-size:11px;color:#888;margin-top:6px'>相关快讯：{rel_items}</div>"

        html += f"""<div class="holding-card">
  <div class="holding-header">
    <span class="holding-name">{ha['name']}</span>
    <span class="holding-tag" style="color:{ha_impact_color};background:{'#ffeaea' if ha['impact']=='positive' else '#e8f5ee' if ha['impact']=='negative' else '#f5f5f5'}">
      {ha['impact_icon']} {ha['impact_txt']} | {ha['watch']}
    </span>
  </div>
  <div class="holding-cost">持仓 {ha['shares']} 股 | 成本价 {ha['cost']:.2f} 元</div>
  {relevant_news_html}
  <div class="order-suggestion">
    <div class="order-label">{s['action']}</div>
    <div class="order-text">{s['cond']}<br>{s['example']}</div>
  </div>
  <div class="alert-box">{s['alert']}</div>
</div>"""

    html += """
</div>
<div class="footer">Generated by 虾兵2号 🦞 · GitHub Actions · 非交易日报告</div>
</body></html>"""
    return html, title_time

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  主入口
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "morning"
    is_weekend = datetime.datetime.now().weekday() >= 5

    if mode == "weekend" or (mode in ("morning", "afternoon") and is_weekend):
        # 非交易日报告
        news = fetch_news()
        a50 = fetch_a50()
        html, subject = generate_weekend_report(news, a50)
    else:
        # 工作日报告
        quotes = fetch_quotes()
        holding_values = []
        for h in HOLDINGS:
            price = fetch_stock_price(h["code"])
            mv = h["shares"] * price
            holding_values.append({**h, "price": price, "market_value": mv})
        total_mv = sum(h["market_value"] for h in holding_values)
        html, subject = generate_workday_report(quotes, holding_values, total_mv, mode)

    print(f"📊 报告生成完毕: {subject}")
    print(f"📧 正在发送邮件到 {SMTP_USER} ...")
    send_email(subject, html)
    print("✅ 完成!")

if __name__ == "__main__":
    main()
