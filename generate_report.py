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
HOLDINGS = [
    {"code":"002223","name":"鱼跃医疗","shares":700,"cost":32.50,
     "tags":["医药","医疗器械","养老","医保","健康","中药","集采"],
     "watch":"集采降价、医疗器械政策、老龄化"},
    {"code":"002142","name":"宁波银行","shares":600,"cost":30.83,
     "tags":["银行","降息","降准","房地产","信贷","LPR","息差","存款"],
     "watch":"房地产风险、净息差、业绩增速"},
    {"code":"002736","name":"国信证券","shares":2000,"cost":12.04,
     "tags":["券商","注册制","IPO","北交所","资本市场","两融","投行","并购"],
     "watch":"成交量、两融余额、IPO节奏"},
]
SMTP_USER = "704901171@qq.com"
SMTP_PASS = "yoyqmwluklabbcic"
SMTP_HOST = "smtp.qq.com"
SMTP_PORT = 465
# ─────────────────────────────────────────────────────────

def fetch_quotes():
    try:
        r = requests.get(
            "http://hq.sinajs.cn/list=sh000001,sz399001,sz399006,hkHSI,hkHSTECH",
            headers={"Referer":"http://finance.sina.com.cn"}, timeout=10)
        r.encoding = "gbk"
        result = {}
        for line in r.text.strip().split("\n"):
            if "=" not in line: continue
            key = line.split("=")[0].split("_")[-1]
            val = line.split('"')[1] if '"' in line else ""
            parts = val.split(",")
            if len(parts) < 4: continue
            if key in ("hkHSI","hkHSTECH"):
                result[key] = {"name":parts[1],
                    "close":float(parts[6]) if parts[6] else float(parts[2]),
                    "pct":float(parts[8]) if parts[8] else 0.0,
                    "change":float(parts[7]) if parts[7] else 0.0}
            else:
                result[key] = {"name":parts[0],
                    "close":float(parts[1]),
                    "pct":float(parts[2]) if parts[2] else 0.0,
                    "change":float(parts[3]) if parts[3] else 0.0}
        return result
    except Exception as e:
        print(f"行情获取失败: {e}")
        return {}

def fetch_us_quotes():
    """获取昨夜美股数据（纳指/道指/标普500）via Yahoo Finance"""
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
    try:
        pre = "sh" if code.startswith("6") else "sz"
        r = requests.get(f"http://hq.sinajs.cn/list={pre}{code}",
                        headers={"Referer":"http://finance.sina.com.cn"}, timeout=10)
        r.encoding = "gbk"
        v = r.text.split('"')[1].split(",")
        return float(v[3]) if len(v) > 3 else 0.0
    except:
        return 0.0

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
           "净买入","开门红","涨停","大幅上涨","历史新高","超跌反弹","资金净流入"]
NEG_KWS = ["下跌","暴跌","跳水","熊市","做空","减持","减仓","低配","卖出","不及预期",
           "业绩下滑","监管","收紧","加息","缩表","外资流出","踩雷","黑天鹅","暴雷",
           "违约","美股大跌","跌停","历史新低","资金净流出"]
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
    n = datetime.datetime.now()
    wd = {0:"周日",1:"周一",2:"周二",3:"周三",4:"周四",5:"周五",6:"周六"}
    return n, f"{n.year}年{n.month}月{n.day}日 {wd[n.weekday()]} {n.strftime('%H:%M')}"

def calc_avg_pct(quotes):
    vals = [float(quotes.get(k,{}).get("pct",0)) for k in ["sh000001","sz399001","sz399006"]]
    return sum(vals)/len(vals) if vals else 0.0

def calc_holding_values():
    result = []
    for h in HOLDINGS:
        price = fetch_stock_price(h["code"])
        mv = h["shares"] * price
        result.append({**h,"price":price,"market_value":mv})
    return result

def get_position_advice(avg, total_mv):
    ratio = total_mv/TOTAL_CASH*100
    advices = []
    if avg > 1.0:
        advices.append({"icon":"📉","action":"⚠️ 减仓提示","color":"#e34a4a","bg":"#fff5f5",
            "text":f"大盘涨幅超1%，今日强势明显，建议适度减仓锁利，将仓位降至50%以下，落袋为安。个人持仓{ratio:.0f}%，注意高开后回落风险。"})
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

def get_recommended_sectors(avg, mode, news_list):
    bull = avg > 0.3; bear = avg < -0.3
    sec_cnt = {}
    for item in news_list:
        for s in match_sectors(item["text"]):
            sec_cnt[s] = sec_cnt.get(s,0)+1
    hot_secs = [s for s,_ in sorted(sec_cnt.items(),key=lambda x:-x[1])[:2]]
    hot_str = "、".join(hot_secs) if hot_secs else ""
    if bull:
        return [
            {"tag":"第1梯队 🥇","sector":"大金融（银行/券商）","stocks":"银行+券商",
             "desc":"低估值+政策宽松预期，成交量回暖直接利好券商，低估值银行估值修复。重点关注：宁波银行、国信证券。"},
            {"tag":"第2梯队 🥈","sector":"科技成长（AI/半导体）","stocks":"AI+半导体+算力",
             "desc":"风险偏好提升，资金追逐弹性板块，关注国产替代主线。" + (f" 近期{hot_str}消息催化。" if hot_str else "")},
            {"tag":"第3梯队 🥉","sector":"新能源","stocks":"锂电+光伏+储能",
             "desc":"政策加码+超跌反弹概率，固态电池产业化加速，关注龙头超跌机会。"},
        ]
    elif bear:
        return [
            {"tag":"第1梯队 🥇","sector":"医药医疗","stocks":"中药+医疗器械+创新药",
             "desc":"防御性强+老龄化长期逻辑，政策支持创新药。" + (f" 近期{hot_str}消息利好。" if hot_str else "")},
            {"tag":"第2梯队 🥈","sector":"大金融（银行/高股息）","stocks":"银行+高股息防御",
             "desc":"低估值抗跌，高股息防御，险资配置偏好，适合当前防御阶段。"},
            {"tag":"第3梯队 🥉","sector":"消费","stocks":"白酒+家电+汽车",
             "desc":"扩内需政策预期，内需托底逻辑，下跌空间有限，适合长线布局。"},
        ]
    else:
        personal = "个人持仓鱼跃医疗(医疗)、宁波银行(银行)、国信证券(券商)均属大金融+医疗方向。"
        return [
            {"tag":"第1梯队 🥇","sector":"大金融（券商/银行）","stocks":"券商+银行",
             "desc":"低估值修复预期，成交量若能持续万亿以上，券商弹性大。" + personal},
            {"tag":"第2梯队 🥈","sector":"医药","stocks":"中药+医疗器械",
             "desc":"业绩稳健，防御配置，集采边际影响减弱，适合当前震荡市。个人持仓鱼跃医疗属于医疗板块。"},
            {"tag":"第3梯队 🥉","sector":"科技","stocks":"AI应用+半导体",
             "desc":"等待政策明朗，关注一季报超预期个股。" + (f" 近期{hot_str}消息面关注。" if hot_str else " 消息面暂无明确催化，谨慎参与。")},
        ]

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
.sec{display:flex;align-items:center;gap:10px;padding:9px 0;border-bottom:1px solid #f5f5f5}
.sec:last-child{border-bottom:none}
.secname{font-size:12px;font-weight:700;color:#222;min-width:68px;flex-shrink:0}
.secimp{font-size:11px;font-weight:700;padding:2px 8px;border-radius:20px;min-width:44px;text-align:center;flex-shrink:0}
.secdesc{font-size:11px;color:#666;flex:1;line-height:1.4}
.rcard{border:1px solid #eee;border-radius:12px;padding:12px;margin-bottom:10px;background:#fafbff}
.rtag{font-size:10px;font-weight:700;padding:2px 8px;border-radius:20px;display:inline-block;margin-bottom:6px}
.rname{font-size:14px;font-weight:700;color:#222;margin-bottom:4px}
.rdesc{font-size:12px;color:#555;line-height:1.5}
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
            "<meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<title>" + title + "</title>" + CSS + "</head><body>"
            "<div class='wrap'>")

def title_div():
    n, ds = now_str()
    return "<h1>" + ds + "</h1>"

def card(lbl, body):
    return "<div class='card'><span class='lbl'>" + lbl + "</span>" + body + "</div>"

def banner(icon, title, note, bg):
    return ("<div class='banner' style='background:" + bg + "'>"
            "<h2>" + icon + " " + title + "</h2><p>" + note + "</p></div>")

def idx_grid(rows):
    return "<div class='igrid'>" + rows + "</div>"

def idx_card(name, close, pct):
    arrow = "▲" if pct > 0 else ("▼" if pct < 0 else "—")
    c = tc(pct)
    c_str = "{:,.2f}".format(close) if close >= 1 else "{:,.2f}".format(close)
    p_str = "{:+.2f}".format(pct)
    return ("<div class='icard'><div class='iname'>" + name + "</div>"
            "<div class='iclose'>" + c_str + "</div>"
            "<div class='ipct' style='color:" + c + "'>" + arrow + " " + p_str + "%</div></div>")

def pos_bar(total_mv):
    ratio = total_mv/TOTAL_CASH*100; inv = 100-ratio
    bi_w = ratio if ratio > 5 else 5; bc_w = inv if inv > 5 else 5
    return ("<div class='bar'>"
            "<div class='bi' style='width:" + "{:.1f}".format(bi_w) + "%'>" + "{:.0f}".format(ratio) + "% 持仓</div>"
            "<div class='bc' style='width:" + "{:.1f}".format(bc_w) + "%'>" + "{:.0f}".format(inv) + "% 现金</div>"
            "</div>"
            "<div class='bleg'>"
            "<span>📦 持仓 " + "{:,.0f}".format(total_mv) + "元</span>"
            "<span>💵 现金 " + "{:,.0f}".format(TOTAL_CASH-total_mv) + "元</span>"
            "<span>💰 总计 " + "{:,.0f}".format(TOTAL_CASH) + "元</span></div>")

def hold_table(hvals, total_mv):
    rows = ""
    for h in hvals:
        mv = h["market_value"]
        pnl = (h["price"]-h["cost"])/h["cost"]*100
        pct_t = mv/total_mv*100 if total_mv > 0 else 0
        price_str = "{:.2f}".format(h["price"]) if h["price"] else "—"
        rows += ("<tr>"
                 "<td><div class='hname'>" + h["name"] + "</div><div class='hcode'>" + h["code"] + "</div></td>"
                 "<td style='text-align:center'>" + str(h["shares"]) + "</td>"
                 "<td style='text-align:right'>{:.2f}</td>".format(h["cost"]) +
                 "<td style='text-align:right;color:" + tc(h["price"]-h["cost"]) + "'>" + price_str + "</td>"
                 "<td style='text-align:right;color:" + tc(pnl) + "'>" + "{:+.1f}".format(pnl) + "%</td>"
                 "<td style='text-align:right'>" + "{:.1f}".format(pct_t) + "%</td></tr>")
    return ("<table>"
            "<tr><th>名称/代码</th><th style='text-align:center'>股数</th><th style='text-align:right'>成本</th>"
            "<th style='text-align:right'>现价</th><th style='text-align:right'>盈亏%</th><th style='text-align:right'>占总%</th></tr>"
            + rows + "</table>")

def news_rows(tagged):
    out = ""
    for n in tagged[:8]:
        secs = "·".join(n["sectors"]) if n["sectors"] else ""
        meta = n.get("source","") + (" · "+secs if secs else "")
        txt = n["text"][:130] + ("…" if len(n["text"]) > 130 else "")
        out += ("<div class='nitem'><div class='nico'>" + S_ICO.get(n["sentiment"],"⚖️") + "</div>"
                "<div class='nbody'><div class='ntext'>" + txt + "</div>"
                "<div class='nmeta'>" + meta + "</div></div></div>")
    return out

def sec_rows(summary):
    out = ""
    for s in summary:
        ic = sc(s["impact"])
        ib = "#ffeaea" if s["impact"]=="positive" else ("#e8f5ee" if s["impact"]=="negative" else "#f5f5f5")
        np = "；".join(x["text"][:25] for x in s["news"])[:65]
        out += ("<div class='sec'>"
                "<div class='secname'>" + S_ICO.get(s["impact"],"⚖️") + " " + s["name"] + "</div>"
                "<div class='secimp' style='color:" + ic + ";background:" + ib + "'>" + s["impact_txt"] + "</div>"
                "<div class='secdesc'>" + np + "…</div></div>")
    return out

def rec_cards(recs):
    out = ""
    for rec in recs:
        out += ("<div class='rcard'>"
                "<div class='rtag' style='background:#f0f0f5;color:#333'>" + rec["tag"] + "</div>"
                "<div class='rname'>" + rec["sector"] + "</div>"
                "<div style='font-size:11px;color:#888;margin-bottom:6px'>" + rec["stocks"] + "</div>"
                "<div class='rdesc'>" + rec["desc"] + "</div></div>")
    return out

def adj_rows(advices):
    out = ""
    for adv in advices:
        out += ("<div class='adj'>"
                "<div class='adji'>" + adv["icon"] + "</div>"
                "<div class='adjb'>"
                "<div class='adjn' style='color:" + adv["color"] + "'>" + adv["action"] + "</div>"
                "<div class='adjt'>" + adv["text"] + "</div></div></div>")
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
        pnl = (price-h["cost"])/h["cost"]*100 if price else 0
        price_str = "{:.2f}元".format(price) if price else "获取中"
        pnl_str = ("+" if pnl >= 0 else "") + "{:.1f}".format(pnl)
        rel_txt = "；".join(x["text"][:28] for x in rel)[:85] if rel else "今日暂无直接相关消息，关注大盘整体走势"
        out += ("<div class='nitem'>"
                "<div class='nico'>" + S_ICO.get(imp,"⚖️") + "</div>"
                "<div class='nbody'>"
                "<div class='ntext'><b>" + h["name"] + "</b> "
                "<span style='color:" + ic + ";background:" + ib + ";font-size:10px;padding:1px 6px;border-radius:10px;font-weight:700'>" + it + "</span> "
                "<span style='font-size:11px;color:#aaa'>" + price_str + " " + pnl_str + "%</span>"
                "</div>"
                "<div class='nmeta'>相关：" + rel_txt + "…</div>"
                "</div></div>")
    return out


# ━━━━ 早盘报告 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def build_morning_report(us_q, quotes, hvals, news_list):
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
    for key,name in [("sh000001","上证指数"),("sz399001","深证成指"),("sz399006","创业板指"),
                      ("hkHSI","恒生指数"),("hkHSTECH","恒生科技")]:
        q = quotes.get(key,{}); c=q.get("close",0); p=q.get("pct",0)
        if c: idx_r += idx_card(name,c,p)
    html += card("📊 A股大盘", idx_grid(idx_r))

    # 大盘情绪
    tr_bg = "#fff5f5" if bull else ("#f0fff4" if bear else "#f8f8f8")
    tr_ic = "📈" if bull else ("📉" if bear else "⚖️")
    tr_txt = "大盘偏多" if bull else ("大盘偏空" if bear else "大盘震荡")
    tr_note = "市场情绪较好，可适当关注机会" if bull else ("注意控制仓位风险" if bear else "盘面平稳，观望为主")
    html += banner(tr_ic, "今日大盘预判：" + tr_txt, tr_note, tr_bg)

    # 仓位总览
    html += card("💼 账户仓位总览", pos_bar(total_mv))

    # 持仓明细
    html += card("📋 持仓个股复盘", hold_table(hvals, total_mv))

    # 消息面
    tagged = [{**x,"sentiment":analyze_sentiment(x["text"]),"sectors":match_sectors(x["text"])} for x in news_list]
    pos_n = [x for x in tagged if x["sentiment"]=="positive"]
    neg_n = [x for x in tagged if x["sentiment"]=="negative"]
    html += card("📰 重要消息面（利好 {:d} 条 / 利空 {:d} 条）".format(len(pos_n),len(neg_n)),
                 news_rows(pos_n+neg_n))

    # 今日推荐
    recs = get_recommended_sectors(avg,"morning",news_list)
    html += card("🔍 今日推荐板块 / 个股", rec_cards(recs))

    # 仓位建议
    adv = get_position_advice(avg,total_mv)
    html += card("🎯 仓位调整建议", adj_rows(adv))

    html += "<div class='ft'>Generated by 虾兵2号 🦞 · GitHub Actions云端</div></div></body></html>"
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
    for key,name in [("sh000001","上证指数"),("sz399001","深证成指"),("sz399006","创业板指"),
                      ("hkHSI","恒生指数"),("hkHSTECH","恒生科技")]:
        q = quotes.get(key,{}); c=q.get("close",0); p=q.get("pct",0)
        if c: idx_r += idx_card(name,c,p)
    if c: idx_r += idx_card(name,c,p)
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

    # 持仓个股今日影响分析
    html += card("📋 持仓个股今日影响分析", hold_analysis_rows(hvals,news_list))

    # 消息面
    tagged = [{**x,"sentiment":analyze_sentiment(x["text"]),"sectors":match_sectors(x["text"])} for x in news_list]
    pos_n = [x for x in tagged if x["sentiment"]=="positive"]
    neg_n = [x for x in tagged if x["sentiment"]=="negative"]
    html += card("📰 重要消息面（利好 {:d} 条 / 利空 {:d} 条）".format(len(pos_n),len(neg_n)), news_rows(pos_n+neg_n))

    # 明日推荐
    recs = get_recommended_sectors(avg,"afternoon",news_list)
    html += card("🔍 明日推荐板块 / 个股", rec_cards(recs))

    # 仓位建议
    adv = get_position_advice(avg,total_mv)
    html += card("🎯 仓位调整建议", adj_rows(adv))

    html += "<div class='ft'>Generated by 虾兵2号 🦞 · GitHub Actions云端</div></div></body></html>"
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
        html += card("📊 板块影响一览", sec_rows(sec_summary))

    hold_cards = ""
    for ha in hold_analysis:
        ic = sc(ha["impact"])
        ib = "#ffeaea" if ha["impact"]=="positive" else ("#e8f5ee" if ha["impact"]=="negative" else "#f5f5f5")
        ico = S_ICO.get(ha["impact"],"⚖️")
        it = {"positive":"偏多","negative":"偏空","中性":"neutral"}.get(ha["impact"],"中性")
        it = {"positive":"偏多","negative":"偏空","neutral":"中性"}.get(ha["impact"],"中性")
        if ha["relevant"]:
            rel_items = "<br>".join("• " + x["text"][:55] + ("..." if len(x["text"])>55 else "") for x in ha["relevant"][:2])
        else:
            rel_items = "周末暂无相关消息，关注周一开盘"
        hold_cards += ("<div class='nitem'><div class='nico'>" + ico + "</div><div class='nbody'>"
            "<div class='ntext'><b>" + ha["name"] + "</b> "
            "<span style='color:" + ic + ";background:" + ib + ";font-size:10px;padding:1px 6px;border-radius:10px;font-weight:700'>" + it + "</span>"
            " <span style='font-size:11px;color:#aaa'>" + str(ha["shares"]) + "股/成本{:.2f}元</span></div>".format(ha["cost"]) +
            "<div class='nmeta'>相关：" + rel_items + "</div></div></div>")

    order_rows = ""
    for ha in hold_analysis:
        imp = ha["impact"]
        if imp == "positive":
            order_rows += ("<div style='padding:8px;background:#f0fff4;border-radius:8px;margin-bottom:8px;font-size:12px;line-height:1.5'>"
                "<b style='color:#3a9e4f'>🟢 关注买入机会</b><br>"
                "积极信号：利好消息支撑，考虑逢低加仓。<br>"
                "建议挂「价格提醒」：涨超+5%提醒减仓；跌超-5%提醒关注。</div>")
        elif imp == "negative":
            order_rows += ("<div style='padding:8px;background:#fff5f5;border-radius:8px;margin-bottom:8px;font-size:12px;line-height:1.5'>"
                "<b style='color:#e34a4a'>🔴 关注卖出风险</b><br>"
                "风险信号：利空消息压制，建议设置止损提醒。<br>"
                "建议挂「止损提醒」：跌破成本价-5%提醒；跌破-8%确认是否离场。</div>")
        else:
            order_rows += ("<div style='padding:8px;background:#f8f8f8;border-radius:8px;margin-bottom:8px;font-size:12px;line-height:1.5'>"
                "<b style='color:#888'>🟡 观望为主</b><br>"
                "中性信号：暂无必要调整现有条件单，关注周一开盘方向再定。</div>")

    html += card("📋 持仓影响分析", hold_cards)
    html += card("🎯 条件单建议 & 操作参考", order_rows)
    est_total_mv = sum(h["shares"]*h["cost"] for h in HOLDINGS)
    html += card("💼 账户仓位参考", pos_bar(est_total_mv))
    html += "<div class='ft'>Generated by 虾兵2号 🦞 · GitHub Actions云端</div></div></body></html>"
    return html, title

# ━━━━ 主入口 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "morning"
    n, _ = now_str()
    is_weekend = n.weekday() >= 5
    if mode == "weekend" or (mode in ("morning","afternoon") and is_weekend):
        news = fetch_news()
        a50 = fetch_a50()
        html, subject = build_weekend_report(news, a50)
    elif mode == "morning":
        us_q = fetch_us_quotes()
        quotes = fetch_quotes()
        hvals = calc_holding_values()
        news = fetch_news()
        html, subject = build_morning_report(us_q, quotes, hvals, news)
    else:
        quotes = fetch_quotes()
        hvals = calc_holding_values()
        news = fetch_news()
        html, subject = build_afternoon_report(quotes, hvals, news)
    print("📊 报告生成完毕: " + subject)
    send_email(subject, html)
    print("✅ 完成!")

if __name__ == "__main__":
    main()
