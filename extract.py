"""記事の本文から「公演名・日程・会場・チケット受付開始日時」を抜き出す処理。

方法A（キーワードと日付の書き方から抜き出す）で作っています。
書き方が特殊な記事では取りこぼすことがあるので、通知には必ず記事URLを付けます。
"""

import re
import unicodedata
from datetime import date, datetime, timedelta, timezone

from bs4 import BeautifulSoup

JST = timezone(timedelta(hours=9))
WEEKDAYS = "月火水木金土日"

# ---------------------------------------------------------------
# 日付・時刻の見つけ方
#   2026年10月21日(水) / 2026/10/21 / 2026.8.28 / 10月22日(木) / 10/10(土) など
# ---------------------------------------------------------------
DATE_RE = re.compile(
    r"(?<![\d.,/])"
    r"(?:(?P<y>20\d{2})\s*[年/.]\s*)?"
    r"(?P<m>1[0-2]|0?[1-9])\s*"
    r"(?:月\s*(?P<d1>3[01]|[12]\d|0?[1-9])\s*日|[/.]\s*(?P<d2>3[01]|[12]\d|0?[1-9])(?![\d/]))"
    r"(?:\s*\([^()]{1,5}\))?"
)
# 日付の直後にある時刻（18:00 / 18時 / 18時30分）
TIME_AFTER_DATE_RE = re.compile(
    r"\s*(?:\([^()]{1,5}\))?\s*(?P<h>[01]?\d|2[0-3])\s*(?::\s*(?P<mi>[0-5]\d)|時\s*(?:(?P<mi2>[0-5]\d)\s*分)?)"
)
URL_RE = re.compile(r"https?://\S+")

# ---------------------------------------------------------------
# キーワード
# ---------------------------------------------------------------
# チケット受付を表す言葉
SALE_RE = re.compile(r"受付|先行|一般発売|一般販売|販売開始|発売開始|抽選|先着|プレリク|チケット発売")
# 見出しがチケットの話題かどうか
TICKET_HEADING_RE = re.compile(r"チケット|先行|発売|販売|受付|抽選|プレイガイド|一般|先着|プレリク|申し?込")
# チケット受付開始ではないもの（結果発表・入金期限・グッズなど）
NOT_SALE_RE = re.compile(r"結果|当落|抽選日|入金|支払|発券|引換|引き換え|グッズ|GOODS|商品|メンテナンス|リセール|終了|締切|〆切")
# 見出しの書き出しによく使われる記号
HEADING_MARKS = "■□▼▽●◆◇【<〈《[＜"
# 公演日の項目名
PERF_LABEL_RE = re.compile(r"^[■●◆・\s]*(?:日時|日程|公演日|開催日|日付)\s*[:：]?\s*")
VENUE_LABEL_RE = re.compile(r"^[■●◆・\s]*(?:会場|場所)\s*[:：]\s*(?P<v>.+)")
NOT_VENUE_RE = re.compile(r"開場|開演|OPEN|START|料金|円|¥|チケット|出演|※|http|受付|問い?合|発売|申し?込|時間", re.I)
# 会場名らしさ（日付の次の行を会場とみなすかどうかの判断に使う）
VENUE_HINT_RE = re.compile(
    r"・|ホール|HALL|PIT|Zepp|会館|LIVE ?HOUSE|ライブハウス|CLUB|QUATTRO|劇場|アリーナ|ARENA|ドーム|DOME"
    r"|スタジアム|THEATER|シアター|倶楽部|Hatch|LOFT|BASE|SPACE|メッセ|センター|[都道府県]",
    re.I,
)
# ライブ関連の記事かどうか（主にタイトルで判断する）
LIVE_RE = re.compile(r"ライブ|LIVE|公演|ツアー|TOUR|出演|開催|チケット|先行|フェス|FES|ワンマン|対バン|イベント|演奏会|発売", re.I)
NOT_LIVE_TITLE_RE = re.compile(r"グッズ|GOODS|メディア|メンテナンス|ステッカー|リリース", re.I)
# グッズ等の言葉があっても、これがあればライブ情報とみなす（例：「リリースツアー開催決定」）
STRONG_LIVE_TITLE_RE = re.compile(r"公演|出演|チケット|開催|ワンマン")
# 受付の種類の呼び方（本文やタイトルから読み取る）
SALE_LABEL_RE = re.compile(
    r"(ファンクラブ(?:会員)?(?:限定)?(?:チケット)?(?:最速)?先行|FC(?:会員)?(?:最速)?先行"
    r"|オフィシャル(?:HP|二次|最速)?先行(?: ?\d次)?|プレイガイド(?:最速)?先行|プレリクエスト先行"
    r"|(?:最速)?先着先行|U-\d+チケット先行(?: ?\d次)?|一般発売|先着販売)"
)


def html_to_lines(html):
    """記事のHTMLを、見た目どおりの行のリストにする。"""
    # HTMLソース内の改行は表示に関係ないので消す（文字が細切れになるのを防ぐ）
    html = re.sub(r"[\r\n]+", "", html or "")
    soup = BeautifulSoup(html, "html.parser")
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for tag in soup.find_all(["p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "dt", "dd", "table"]):
        tag.insert_before("\n")
        tag.insert_after("\n")
    text = unicodedata.normalize("NFKC", soup.get_text(""))
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.split("\n")]
    # WordPressが記事の最後に自動で付ける「The post ○○ appeared first on …」の行は除く
    return [line for line in lines if line and not (line.startswith("The post ") and "appeared first on" in line)]


def find_datetimes(line, base):
    """1行の中の日付をすべて見つける。年が書かれていなければ記事の日付から推測する。

    戻り値: [(datetime, 時刻が書かれていたか, 日付の開始位置, 日付・時刻の終了位置)] のリスト
    """
    results = []
    for m in DATE_RE.finditer(line):
        month = int(m.group("m"))
        day = int(m.group("d1") or m.group("d2"))
        year = int(m.group("y")) if m.group("y") else base.year
        try:
            d = date(year, month, day)
        except ValueError:
            continue
        # 年が省略されていて、記事より2か月以上前になるなら翌年のこと
        if not m.group("y") and d < base.date() - timedelta(days=60):
            try:
                d = date(year + 1, month, day)
            except ValueError:
                continue
        t = TIME_AFTER_DATE_RE.match(line, m.end())
        if t:
            minute = int(t.group("mi") or t.group("mi2") or 0)
            dt = datetime(d.year, d.month, d.day, int(t.group("h")), minute, tzinfo=JST)
            results.append((dt, True, m.start(), t.end()))
        else:
            results.append((datetime(d.year, d.month, d.day, tzinfo=JST), False, m.start(), m.end()))
    return results


def is_end_date(line, found):
    """「〜10/19(月)23:59まで」のような、受付の終了日時かどうか。"""
    before = line[:found[2]].rstrip()
    return bool(re.match(r"\s*(?:まで|迄)", line[found[3]:])) or before.endswith(("~", "〜"))


def is_heading(line):
    return line[0] in HEADING_MARKS or bool(re.fullmatch(r"<.*>|〈.*〉", line))


def clean_label(line):
    """見出し記号などを取り除いて、受付の種類名にする。例：「【 一般発売日 】10月11日」→「一般発売」"""
    label = line.lstrip(HEADING_MARKS + " ")
    label = re.split(r"[】\]>〉》＞:：]|(?<!\d)\d{1,4}\s*[年月/]", label)[0]
    label = label.replace("発売日", "発売")
    return label.strip()[:30]


def is_generic_label(label):
    """「チケット情報」「お申し込みはこちら」のように、受付の種類が分からない見出しかどうか。"""
    return label is None or not re.search(r"先行|発売|販売|先着|抽選|プレリク|FC|ファンクラブ", label)


def extract_title(lines, article_title):
    """公演名。本文に「タイトル：」があればそれを、なければ記事タイトルを整えて使う。"""
    for line in lines[:15]:
        m = re.match(r"^[■●◆・\s]*タイトル\s*[:：]\s*(.+)", line)
        if m:
            return m.group(1).strip()
    t = unicodedata.normalize("NFKC", article_title)
    t = re.sub(r"[”“\"′″]", "", t)
    # 「本日10月17日(土)10:00より」のような日時の部分を取り除く
    t = DATE_RE.sub("", t)
    t = re.sub(r"本日|\d{1,2}:\d{2}\s*[~〜]?|より", "", t)
    t = re.sub(r"\s*(?:への)?(?:出演|開催|追加公演|追加|公演)?(?:決定|発表|公開)[!！]*.*$", "", t)
    # 「Officialチケット2次先行受付開始!」のような受付の案内部分を取り除く
    shorter = re.sub(r"\s*(?:Official|オフィシャル|ファンクラブ|FC)?\s*(?:会員)?\s*(?:チケット)?\s*(?:\d次)?(?:最速)?"
                     r"(?:先行|一般発売|受付|チケット|プレリクエスト|プレイガイド).*$", "", t)
    if len(shorter) >= 4:
        t = shorter
    t = re.sub(r"[がの、]$", "", t.strip())
    return t.strip() or article_title


def extract_sales(lines, base, article_title):
    """チケット受付の開始日時を探す。"""
    sales = []
    section_label = None
    in_ticket = False
    title_label_m = SALE_LABEL_RE.search(unicodedata.normalize("NFKC", article_title))
    title_label = title_label_m.group(1) if title_label_m else None

    for i, raw in enumerate(lines):
        line = URL_RE.sub("", raw).strip()
        if not line:
            continue
        dts = find_datetimes(line, base)

        # 見出しなら、チケットの話題が始まったか終わったかを判断
        short_heading = (len(line) <= 20 and SALE_RE.search(line) and not dts
                         and not re.search(r"[。!！]|ます|ました|です", line))
        if is_heading(line) or short_heading:
            if TICKET_HEADING_RE.search(line) and not NOT_SALE_RE.search(line):
                in_ticket = True
                section_label = clean_label(line)
            else:
                in_ticket = False
                section_label = None

        if NOT_SALE_RE.search(line):
            continue
        # 「開場17:00 / 開演17:30 一般発売日:9/26(土)」のように公演時刻と同じ行にある場合は、受付の言葉より後ろだけ見る
        if re.search(r"開場|開演", line):
            km = SALE_RE.search(line)
            if not km:
                continue
            line = line[km.start():]
            dts = find_datetimes(line, base)
        # 終了日時（「〜10/19(月)23:59まで」など）は受付開始ではないので除く
        dts = [d for d in dts if not is_end_date(line, d)]
        # チケットの見出しの下で、日付から始まる行も受付日時とみなす（「■一般発売」の次の行が日付だけ、など）
        starts_with_date = bool(dts) and dts[0][2] <= 2
        is_sale_line = SALE_RE.search(line) or (
            in_ticket and section_label and (re.search(r"発売|販売|期間|受付|日時", line) or starts_with_date))
        if not is_sale_line:
            continue

        # 「受付期間：」だけの行で、次の行に日付がある書き方にも対応
        if not dts and re.search(r"(?:期間|日時|開始)\s*[:：]?\s*$", line):
            for nxt in lines[i + 1:i + 3]:
                nxt = URL_RE.sub("", nxt)
                if is_heading(nxt):
                    break
                dts = [d for d in find_datetimes(nxt, base) if not is_end_date(nxt, d)]
                if dts:
                    break
        if not dts:
            continue

        start, time_known = dts[0][:2]
        label = section_label
        if is_generic_label(label):
            # その行か、すぐ後の行（「・オフィシャル先行 4次 ¥8,000」など）から受付の種類を探す
            label = None
            for nxt in [line] + lines[i + 1:i + 4]:
                if nxt is not line and is_heading(nxt):
                    break
                m = SALE_LABEL_RE.search(nxt)
                if m:
                    label = m.group(1)
                    break
            label = label or title_label or "チケット受付"
        if "先着" in line and "先着" not in label:
            label += "（先着）"
        sales.append({"label": label, "start": start, "time_known": time_known})

    # 同じ日時を重複して拾った場合は、受付の種類が分かっている方を残す
    unique = {}
    for s in sales:
        if s["start"] not in unique or unique[s["start"]]["label"] == "チケット受付":
            unique[s["start"]] = s
    return list(unique.values())


def venue_from_nite(line):
    """「12/4(金)・12/5(土)に東京・豊洲PITにて開催」→「東京・豊洲PIT」"""
    m = re.search(r"([^、。,]+?)にて", line)
    if not m:
        return None
    venue = re.split(r"に|、", m.group(1))[-1]
    venue = DATE_RE.sub("", venue).strip(" 「」")
    return venue or None


def extract_performances(lines, base):
    """公演の日程と会場を探す。"""
    perfs = []
    appear_dates = []   # 「ハンブレッダーズは 12/20(日)に出演します」のような出演日
    in_ticket = False
    for i, raw in enumerate(lines):
        line = URL_RE.sub("", raw).strip()
        if not line:
            continue
        dts = find_datetimes(line, base)
        if is_heading(line):
            in_ticket = bool(TICKET_HEADING_RE.search(line)) and not dts
        if not dts or in_ticket or SALE_RE.search(line) or NOT_SALE_RE.search(line):
            continue
        if re.search(r"に出演(?:します|予定)", line):
            appear_dates.append(dts[0][0])

        labeled = PERF_LABEL_RE.match(line)
        starts_with_date = dts[0][2] <= 2
        if not (labeled or starts_with_date):
            continue

        venue = None
        same = VENUE_LABEL_RE.search(line)
        nite = venue_from_nite(line)
        # 日付の後ろに続く文字（例：「■ 10月24日(土) 福岡 電気ビル みらいホール」）
        m = DATE_RE.search(line)
        rest = line[m.end():].strip(" 、,") if m else ""
        if same:
            venue = same.group("v")
        elif nite:
            venue = nite
        elif rest and len(rest) <= 40 and not NOT_VENUE_RE.search(rest) and not find_datetimes(rest, base):
            venue = rest
        else:
            for nxt in lines[i + 1:i + 4]:
                nxt = nxt.strip()
                vm = VENUE_LABEL_RE.match(nxt)
                if vm:
                    venue = vm.group("v")
                    break
                if is_heading(nxt) or find_datetimes(nxt, base):
                    break
                # 日付だけの行の次の行は会場名とみなす。それ以外は会場名らしい言葉があるときだけ
                if (not labeled and len(nxt) <= 40 and not NOT_VENUE_RE.search(nxt)
                        and (not rest or VENUE_HINT_RE.search(nxt))):
                    venue = nxt
                    break
        perfs.append({"date": dts[0][0], "venue": venue.strip() if venue else None})

    # 日程が見つからない記事は「東京・豊洲PITにて開催」のような書き方を探す
    if not perfs:
        for line in lines[:6]:
            venue = venue_from_nite(line)
            if venue:
                dts = find_datetimes(line, base)
                perfs.append({"date": dts[0][0] if dts else None, "venue": venue})
                break

    # フェスなど複数日の開催で、出演日が書かれていればそちらを使う
    if appear_dates:
        venue = next((p["venue"] for p in perfs if p["venue"]), None)
        perfs = [{"date": d, "venue": venue} for d in appear_dates]

    # 同じ日の公演が「会場あり」と「会場不明」で重複したら、会場ありの方を残す
    unique = {}
    for p in perfs:
        key = p["date"]
        if key not in unique or (unique[key]["venue"] is None and p["venue"]):
            unique[key] = p
        elif p["venue"] and unique[key]["venue"] and p["venue"] != unique[key]["venue"]:
            unique[(key, p["venue"])] = p
    return list(unique.values())


def analyze(article_title, html, published):
    """記事1件を解析した結果をまとめて返す。"""
    lines = html_to_lines(html)
    sales = extract_sales(lines, published, article_title)
    title = unicodedata.normalize("NFKC", article_title)
    # タイトルがライブ関連か、本文にチケット受付日時があればライブ情報とみなす（グッズ等の記事は除く）
    excluded = NOT_LIVE_TITLE_RE.search(title) and not STRONG_LIVE_TITLE_RE.search(title)
    is_live = bool(LIVE_RE.search(title) or sales) and not excluded
    return {
        "is_live": is_live,
        "show_title": extract_title(lines, article_title),
        "performances": extract_performances(lines, published),
        "sales": sales,
    }


def fmt_dt(dt, time_known=True):
    """2026-10-22 12:00 → 「10/22(木) 12:00」の形にする。"""
    s = f"{dt.month}/{dt.day}({WEEKDAYS[dt.weekday()]})"
    if dt.year != datetime.now(JST).year:
        s = f"{dt.year}/" + s
    if time_known:
        s += f" {dt.hour}:{dt.minute:02d}"
    return s
