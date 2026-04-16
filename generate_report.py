#!/usr/bin/env python3
"""
GitHub Actions 云端：生成A股投资早报/盘尾简报 HTML 邮件
用法：
  python3 generate_report.py [morning|afternoon]
"""
import requests, datetime, json, sys, os

# ── 用户配置 ─────────────────────────────────────────────
TOTAL_CASH = 150000.0
HOLDINGS = [
    {"code": "002223", "name": "鱼跃医疗", "shares": 700,  "cost": 32.50},
    {"code": "002142", "name": "宁波银行", "shares": 600,  "cost": 30.83},
    {"code": "002736", "name": "国信证券", "shares": 2000, "cost": 12.04},
]
SMTP_USER = '704901171@qq.com'
SMTP_PASS = 'yoyqmwluklabbcic'
SMTP_HOST = 'smtp.qq.com'
SMTP_PORT = 465
# ─────────────────────────────────────────────────────────

# 行情API
def fetch_quotes():
    try:
        codes = "sh000001,sz399001,sz399006,hkHSI,hkHSTECH"
        url = f"http://hq.sinajs.cn/list={codes}"
        r = requests.get(url, headers={"Referer": "http://finance.sina.com.cn"}, timeout=10)
        r.encoding = 'gbk'
        raw = r.text.strip()
        result = {}
        for line in raw.split('\n'):
            if '=' not in line: continue
            key = line.split('=')[0].split('_')[-1]
            val = line.split('"')[1] if '"' in line else ''
            parts = val.split(',')
            if len(parts) >= 4:
                name = parts[0]
                close = float(parts[1])
                change = float(parts[3]) if parts[3] else 0.0
                pct = float(parts[2]) if parts[2] else 0.0
                result[key] = {"name": name, "close": close, "pct": pct, "change": change}
        return result
    except Exception as e:
        print(f"行情获取失败: {e}")
        return {}

# 个股当前价
def fetch_stock_price(code):
    try:
        prefix = "sh" if code.startswith("6") else "sz"
        url = f"http://hq.sinajs.cn/list={prefix}{code}"
        r = requests.get(url, headers={"Referer": "http://finance.sina.com.cn"}, timeout=10)
        r.encoding = 'gbk'
        val = r.text.split('"')[1].split(',')
        return float(val[3]) if len(val) > 3 else 0.0
    except:
        return 0.0

# 发邮件
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

# ── HTML 生成 ────────────────────────────────────────────
def trend_color(pct):
    c = float(pct)
    if c > 0: return "#e34a4a"
    if c < 0: return "#3a9e4f"
    return "#888"

def trend_arrow(pct):
    c = float(pct)
    if c > 0: return "▲"
    if c < 0: return "▼"
    return "—"

def html_report(quotes, holding_values, total_value, mode):
    now = datetime.datetime.now()
    wmap = {'0':'周日','1':'周一','2':'周二','3':'周三','4':'周四','5':'周五','6':'周六'}
    date_str = f"{now.year}年{now.month}月{now.day}日 {wmap[str(now.weekday())]}"
    title_time = f"{'📈 早盘快报' if mode=='morning' else '📊 盘尾简报'} · {date_str}"

    # 指数卡片
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
            idx_cards += f"""
    <div class="idx-card">
      <div class="idx-name">{name}</div>
      <div class="idx-close">{close:,.2f}</div>
      <div class="idx-pct" style="color:{trend_color(pct)}">{trend_arrow(pct)} {pct:+.2f}%</div>
    </div>"""

    # 大盘多空
    avg_pct = 0
    cnt = 0
    for key in ["sh000001","sz399001","sz399006"]:
        if key in quotes:
            avg_pct += float(quotes[key].get("pct",0))
            cnt += 1
    avg_pct = avg_pct/cnt if cnt else 0
    bull = avg_pct > 0.3
    bear = avg_pct < -0.3
    trend_bg = "#fff5f5" if bull else ("#f0fff4" if bear else "#f8f8f8")
    trend_txt = "📈 大盘偏多" if bull else ("📉 大盘偏空" if bear else "⚖️ 大盘震荡")
    trend_note = "市场情绪较好，可适当关注机会" if bull else ("注意控制仓位风险" if bear else "盘面平稳，观望为主")

    # 持仓明细
    cash = TOTAL_CASH - sum(h["shares"]*h["price"] for h in holding_values)
    hold_rows = ""
    for h in holding_values:
        pct_total = h["market_value"] / total_value * 100
        hold_rows += f"""
    <tr>
      <td>{h['name']}</td>
      <td>{h['code']}</td>
      <td>{h['shares']}</td>
      <td>{h['cost']:.2f}</td>
      <td>{h['price']:.2f}</td>
      <td style="color:{trend_color((h['price']-h['cost'])/h['cost']*100)}">{((h['price']-h['cost'])/h['cost']*100):+.1f}%</td>
      <td>{pct_total:.1f}%</td>
    </tr>"""

    # 仓位概览
    total_mv = sum(h["market_value"] for h in holding_values)
    invest_pct = total_mv / TOTAL_CASH * 100
    cash_pct = 100 - invest_pct

    # 分析师推荐板块
    recommend_sections = [
        {"板块": "大金融（银行/券商）", "逻辑": "低估值+政策宽松预期"},
        {"板块": "医药医疗", "逻辑": "防御性强+老龄化趋势"},
    ]
    rec_rows = ""
    for r in recommend_sections:
        rec_rows += f"<li><b>{r['板块']}</b> — {r['逻辑']}</li>"

    html = f"""<!DOCTYPE html>
<html><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title_time}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system,'PingFang SC','Microsoft YaHei',sans-serif; background: #f5f6fa; color: #222; padding: 12px; max-width: 600px; margin: 0 auto; }}
  h1 {{ font-size: 18px; margin-bottom: 12px; color: #333; }}
  .card {{ background: #fff; border-radius: 10px; padding: 16px; margin-bottom: 12px; box-shadow: 0 1px 4px rgba(0,0,0,0.08); }}
  .section-title {{ font-size: 13px; font-weight: 600; color: #888; margin-bottom: 10px; text-transform: uppercase; letter-spacing: .5px; }}
  .idx-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; }}
  .idx-card {{ background: #f8f9fa; border-radius: 8px; padding: 10px 6px; text-align: center; }}
  .idx-name {{ font-size: 11px; color: #888; margin-bottom: 4px; }}
  .idx-close {{ font-size: 15px; font-weight: 700; color: #333; }}
  .idx-pct {{ font-size: 12px; font-weight: 600; margin-top: 2px; }}
  .trend-banner {{ padding: 12px 16px; border-radius: 10px; margin-bottom: 12px; background: {trend_bg}; text-align: center; }}
  .trend-banner strong {{ font-size: 16px; }}
  .trend-banner p {{ font-size: 12px; color: #666; margin-top: 4px; }}
  .pos-bar-wrap {{ background: #eee; border-radius: 6px; height: 20px; overflow: hidden; display: flex; margin: 8px 0; }}
  .pos-bar-invest {{ background: linear-gradient(90deg,#4a90d9,#6ab0f0); height: 100%; display: flex; align-items: center; justify-content: center; color: #fff; font-size: 10px; font-weight: 600; }}
  .pos-bar-cash {{ background: #e8f4ea; height: 100%; display: flex; align-items: center; justify-content: center; color: #2a7a40; font-size: 10px; font-weight: 600; }}
  .pos-legend {{ display: flex; justify-content: space-between; font-size: 12px; color: #888; margin-top: 4px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 12px; }}
  th {{ background: #f0f2f5; padding: 8px 4px; text-align: left; color: #888; font-weight: 500; border-bottom: 1px solid #eee; }}
  td {{ padding: 8px 4px; border-bottom: 1px solid #f5f5f5; }}
  .cash-row {{ display: flex; justify-content: space-between; font-size: 13px; padding: 10px 0; border-top: 1px solid #eee; margin-top: 8px; }}
  .cash-row span {{ color: #2a7a40; font-weight: 600; }}
  ul.recommend {{ padding-left: 16px; font-size: 13px; line-height: 2; }}
  .footer {{ text-align: center; font-size: 11px; color: #aaa; margin-top: 8px; }}
</style></head><body>

<h1>{title_time}</h1>

<!-- 大盘多空 -->
<div class="trend-banner">
  <strong>{trend_txt}</strong>
  <p>{trend_note}</p>
</div>

<!-- 指数 -->
<div class="card">
  <div class="section-title">📊 大盘指数</div>
  <div class="idx-grid">{idx_cards}
  </div>
</div>

<!-- 仓位概览 -->
<div class="card">
  <div class="section-title">💼 仓位概览</div>
  <div class="pos-bar-wrap">
    <div class="pos-bar-invest" style="width:{invest_pct:.1f}%">{invest_pct:.1f}% 持仓</div>
    <div class="pos-bar-cash" style="width:{cash_pct:.1f}%">{cash_pct:.1f}% 现金</div>
  </div>
  <div class="pos-legend">
    <span>持仓 {total_mv:,.0f} 元</span>
    <span>现金 {cash:,.0f} 元</span>
    <span>总计 {TOTAL_CASH:,.0f} 元</span>
  </div>
</div>

<!-- 持仓明细 -->
<div class="card">
  <div class="section-title">📋 持仓明细</div>
  <table>
    <tr><th>名称</th><th>代码</th><th>股数</th><th>成本</th><th>现价</th><th>盈亏%</th><th>占总%</th></tr>
    {hold_rows}
  </table>
  <div class="cash-row">现金 <span>{cash:,.0f} 元</span></div>
</div>

<!-- 推荐板块 -->
<div class="card">
  <div class="section-title">🔍 当日关注板块</div>
  <ul class="recommend">{rec_rows}</ul>
</div>

<div class="footer">Generated by 虾兵2号 🦞 · GitHub Actions</div>
</body></html>"""
    return html

# ── 主流程 ────────────────────────────────────────────────
def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ("afternoon" if datetime.datetime.now().hour >= 14 else "morning")
    now = datetime.datetime.now()
    date_str = now.strftime("%m月%d日")

    quotes = fetch_quotes()
    holding_values = []
    for h in HOLDINGS:
        price = fetch_stock_price(h["code"])
        mv = h["shares"] * price
        holding_values.append({**h, "price": price, "market_value": mv})

    total_value = sum(x["market_value"] for x in holding_values) + TOTAL_CASH

    subject = f"{'📈' if mode=='morning' else '📊'} 【{date_str}】A股{'早报' if mode=='morning' else '盘尾简报'} | 总值 {total_value:,.0f}元"
    html = html_report(quotes, holding_values, total_value, mode)

    with open("report.html", "w", encoding="utf-8") as f:
        f.write(html)

    # 发邮件
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
    print(f"✅ {subject}")

if __name__ == '__main__':
    main()
