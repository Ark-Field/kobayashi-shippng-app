from datetime import date, datetime, timedelta
import io
import os
import pandas as pd
import requests
import streamlit as st

# ReportLab関連のインポート（PDF出力用）
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

# --------------------------------------------------
# 1. ページ初期設定
# --------------------------------------------------
st.set_page_config(page_title="小林断裁 出荷管理表", layout="wide")

st.title("✂️ 小林断裁 出荷管理表 ＆ 作業管理システム")


# --------------------------------------------------
# 2. 日本語フォント登録処理（ReportLab用・通常＋太字対応版）
# --------------------------------------------------
def setup_japanese_fonts():
    regular_font = "Helvetica"
    bold_font = "Helvetica-Bold"

    local_regular = "NotoSansJP-Regular.ttf"
    local_bold = "NotoSansJP-Bold.ttf"

    if os.path.exists(local_regular):
        try:
            pdfmetrics.registerFont(TTFont("JPFont", local_regular))
            regular_font = "JPFont"
            bold_font = "JPFont"
        except Exception as e:
            print(f"同梱通常フォント登録エラー: {e}")

    if os.path.exists(local_bold):
        try:
            pdfmetrics.registerFont(TTFont("JPFontBold", local_bold))
            bold_font = "JPFontBold"
        except Exception as e:
            print(f"同梱太字フォント登録エラー: {e}")

    if regular_font == "Helvetica":
        win_font = os.path.join(
            os.environ.get("SystemRoot", "C:\\Windows"), "Fonts", "msgothic.ttc"
        )
        if os.path.exists(win_font):
            try:
                pdfmetrics.registerFont(TTFont("JPFont", win_font, subfontIndex=0))
                regular_font = "JPFont"
                bold_font = "JPFont"
            except Exception as e:
                print(f"Windowsフォント登録エラー: {e}")

    if regular_font != "Helvetica":
        try:
            pdfmetrics.registerFontFamily(
                "JPFamily",
                normal=regular_font,
                bold=bold_font,
                italic=regular_font,
                boldItalic=bold_font,
            )
        except Exception as e:
            print(f"フォントファミリー登録エラー: {e}")

    return regular_font, bold_font


FONT_NAME, BOLD_FONT_NAME = setup_japanese_fonts()

# --------------------------------------------------
# 3. サイドバー設定（APIキー・共通設定）
# --------------------------------------------------
st.sidebar.header("⚙️ 接続・認証設定")

try:
    default_key_18 = st.secrets.get(
        "app18_api_key", st.secrets.get("pockets_api_key", "")
    )
except Exception:
    default_key_18 = ""

try:
    default_key_27 = st.secrets.get(
        "app27_api_key", st.secrets.get("pockets_api_key", "")
    )
except Exception:
    default_key_27 = ""

api_key_18 = st.sidebar.text_input(
    "App 18 用 APIキー", value=default_key_18, type="password"
)
api_key_27 = st.sidebar.text_input(
    "App 27 用 APIキー", value=default_key_27, type="password"
)

st.sidebar.markdown("---")
st.sidebar.info(
    "💡 **対象期間の自動計算**\n"
    "・開始日：本日の 1日前\n"
    "・終了日：本日の 18日後"
)

today = date.today()
default_start = today - timedelta(days=1)
default_end = today + timedelta(days=18)

col_d1, col_d2 = st.sidebar.columns(2)
with col_d1:
    start_date = st.date_input("検索開始日", value=default_start)
with col_d2:
    end_date = st.date_input("検索終了日", value=default_end)


# --------------------------------------------------
# 4. APIデータ取得関数
# --------------------------------------------------
def fetch_pocket_records(api_key, app_id, date_field, start_date, end_date):
    if not api_key:
        return []

    url = f"https://app060.at-pocket.com/seihon03_bb/api/apps/{app_id}/records"
    headers = {"X-At-Pocket-API-Key": api_key, "Accept": "application/json"}

    start_str = start_date.strftime("%Y-%m-%d")
    end_str = end_date.strftime("%Y-%m-%d")

    params = {
        "query": (
            f'{date_field} >= "{start_str}" and {date_field} <= "{end_str}"'
        )
    }

    try:
        response = requests.get(url, headers=headers, params=params, timeout=15)
        if response.status_code != 200:
            response = requests.get(url, headers=headers, timeout=15)

        if response.status_code == 200:
            res_json = response.json()
            return res_json.get("records", res_json.get("data", []))
        else:
            return []
    except Exception:
        return []


def extract_pocket_field_val(raw_val):
    if raw_val is None:
        return ""
    if isinstance(raw_val, list):
        extracted = []
        for item in raw_val:
            if isinstance(item, dict):
                extracted.append(str(item.get("value", item.get("name", ""))))
            else:
                extracted.append(str(item))
        return " ".join([e for e in extracted if e and e.lower() != "none"])
    elif isinstance(raw_val, dict):
        return str(raw_val.get("value", raw_val.get("name", ""))).strip()
    else:
        val_str = str(raw_val).strip()
        if val_str.lower() == "none":
            return ""
        return val_str


def get_field_multi_key(inner, keys):
    """ハイフン/アンダースコア表記ゆれに対応してフィールド値を取得"""
    for k in keys:
        if k in inner and inner.get(k) is not None:
            val = extract_pocket_field_val(inner.get(k))
            if val != "":
                return val
    return ""


def is_within_date_range(date_str, start_d, end_d):
    """YYYY-MM-DD 形式の日付文字列が対象期間内かを判定"""
    if not date_str:
        return False
    try:
        parsed_d = datetime.strptime(str(date_str)[:10], "%Y-%m-%d").date()
        return start_d <= parsed_d <= end_d
    except ValueError:
        return False


# --------------------------------------------------
# 5. データ集計・グループ分けメイン処理（App 18 ＆ App 27 統合）
# --------------------------------------------------
def load_and_classify_data(api_key_18, api_key_27, start_date, end_date):
    parsed_items = []

    # --- App ID: 18 の取得（社内加工 1〜5・納期 field18-58） ---
    records_18 = fetch_pocket_records(
        api_key_18, 18, "field18-58", start_date, end_date
    )
    for r in records_18:
        record_id = str(
            r.get("id")
            or r.get("recordId")
            or r.get("record", {}).get("id")
            or r.get("record", {}).get("recordId")
            or ""
        ).strip()
        if record_id.lower() == "none":
            record_id = ""

        detail_url = (
            f"https://app060.at-pocket.com/seihon03_bb/apps/18/records/{record_id}/detail"
            if record_id
            else ""
        )

        inner = r.get("record", r)

        delivery_date = extract_pocket_field_val(inner.get("field18-58"))
        if not is_within_date_range(delivery_date, start_date, end_date):
            continue

        cust = extract_pocket_field_val(inner.get("field18-84"))
        item = extract_pocket_field_val(inner.get("field18-15"))
        qty = extract_pocket_field_val(inner.get("field18-18")) or "0"
        spec = extract_pocket_field_val(inner.get("field18-121"))
        order_no = extract_pocket_field_val(inner.get("js25"))
        hanyu = extract_pocket_field_val(inner.get("field18-57"))
        gai_kubun = extract_pocket_field_val(inner.get("field18-106"))
        completed = bool(inner.get("field18-89", False))

        kakou_fields = [
            ("加工内容①", extract_pocket_field_val(inner.get("kakou18-1"))),
            ("加工内容②", extract_pocket_field_val(inner.get("kakou18-2"))),
            ("加工内容③", extract_pocket_field_val(inner.get("kakou18-3"))),
            ("加工内容④", extract_pocket_field_val(inner.get("kakou18-4"))),
            ("加工内容⑤", extract_pocket_field_val(inner.get("kakou18-5"))),
        ]

        matched_count = 0
        for prefix, word_val in kakou_fields:
            if word_val:
                group_name = f"{prefix}: {word_val}"
                parsed_items.append({
                    "レコードID": record_id,
                    "詳細リンク": detail_url,
                    "アプリ": "App 18",
                    "作業区分": prefix,
                    "単語": word_val,
                    "グループ": group_name,
                    "納入日/納期日": delivery_date[:10],
                    "納入日メモ": "",
                    "搬入日": hanyu[:10],
                    "搬入日メモ": "",
                    "受注番号": order_no,
                    "得意先名": cust,
                    "品名": item,
                    "受注数量": qty,
                    "仕様1/依頼事項": spec,
                    "外注先": "",
                    "外注区分": gai_kubun,
                    "作業完了": completed,
                })
                matched_count += 1

        if matched_count == 0:
            parsed_items.append({
                "レコードID": record_id,
                "詳細リンク": detail_url,
                "アプリ": "App 18",
                "作業区分": "未分類",
                "単語": "未分類",
                "グループ": "未分類（加工）",
                "納入日/納期日": delivery_date[:10],
                "納入日メモ": "",
                "搬入日": hanyu[:10],
                "搬入日メモ": "",
                "受注番号": order_no,
                "得意先名": cust,
                "品名": item,
                "受注数量": qty,
                "仕様1/依頼事項": spec,
                "外注先": "",
                "外注区分": gai_kubun,
                "作業完了": completed,
            })

    # --- App ID: 27 の取得（外注・納期 field-141_10 で抽出） ---
    records_27 = fetch_pocket_records(
        api_key_27, 27, "field-141_10", start_date, end_date
    )

    for r in records_27:
        record_id = str(
            r.get("id")
            or r.get("recordId")
            or r.get("record", {}).get("id")
            or r.get("record", {}).get("recordId")
            or ""
        ).strip()
        if record_id.lower() == "none":
            record_id = ""

        detail_url = (
            f"https://app060.at-pocket.com/seihon03_bb/apps/27/records/{record_id}/detail"
            if record_id
            else ""
        )

        inner = r.get("record", r)

        delivery_date = get_field_multi_key(
            inner, ["field-141_10", "field141_10", "field-141-10"]
        )
        if not is_within_date_range(delivery_date, start_date, end_date):
            continue

        delivery_memo = get_field_multi_key(
            inner, ["field-141_11", "field141_11", "field-141-11"]
        )
        hanyu = get_field_multi_key(
            inner, ["field-141_1", "field141_1", "field-141-1"]
        )
        hanyu_memo = get_field_multi_key(
            inner, ["field-141_2", "field141_2", "field-141-2"]
        )
        cust = get_field_multi_key(inner, ["field18-84"])
        item = get_field_multi_key(inner, ["field18-15"])
        qty = (
            get_field_multi_key(
                inner, ["field-141_6", "field141_6", "field-141-6"]
            )
            or "0"
        )
        spec = get_field_multi_key(
            inner, ["field-141_12", "field141_12", "field-141-12"]
        )
        supplier = get_field_multi_key(
            inner, ["field-141_5", "field141_5", "field-141-5"]
        )
        order_no = extract_pocket_field_val(inner.get("field27-3"))

        group_name = f"外注: {supplier}" if supplier else "外注"

        parsed_items.append({
            "レコードID": record_id,
            "詳細リンク": detail_url,
            "アプリ": "App 27",
            "作業区分": "外注",
            "単語": supplier if supplier else "外注",
            "グループ": group_name,
            "納入日/納期日": delivery_date[:10],
            "納入日メモ": delivery_memo,
            "搬入日": hanyu[:10],
            "搬入日メモ": hanyu_memo,
            "受注番号": order_no,
            "得意先名": cust,
            "品名": item,
            "受注数量": qty,
            "仕様1/依頼事項": spec,
            "外注先": supplier,
            "外注区分": supplier if supplier else "外注",
            "作業完了": False,
        })

    if not parsed_items:
        return pd.DataFrame()

    df = pd.DataFrame(parsed_items)
    if "詳細リンク" not in df.columns:
        df["詳細リンク"] = ""

    df = df.sort_values(
        by=["作業区分", "単語", "納入日/納期日"], ascending=[True, True, True]
    )
    return df


# --------------------------------------------------
# 6. PDF生成関数（太字フォント対応・新外注項目対応）
# --------------------------------------------------
def generate_all_schedule_pdf(df_all, start_date_str, end_date_str):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        leftMargin=15,
        rightMargin=15,
        topMargin=15,
        bottomMargin=15,
    )

    styles = getSampleStyleSheet()
    cell_style = ParagraphStyle(
        "TableCell",
        parent=styles["Normal"],
        fontName=BOLD_FONT_NAME,
        fontSize=7,
        leading=8.5,
        textColor=colors.HexColor("#0F172A"),
    )
    header_style = ParagraphStyle(
        "TableHeader",
        parent=styles["Normal"],
        fontName=BOLD_FONT_NAME,
        fontSize=7.2,
        leading=8.8,
        textColor=colors.white,
        alignment=1,
    )
    title_style = ParagraphStyle(
        "TitleStyle",
        parent=styles["Normal"],
        fontName=BOLD_FONT_NAME,
        fontSize=13,
        leading=15,
        textColor=colors.HexColor("#1E3A8A"),
    )
    group_heading_style = ParagraphStyle(
        "GroupHeading",
        parent=styles["Normal"],
        fontName=BOLD_FONT_NAME,
        fontSize=9.5,
        leading=11.5,
        textColor=colors.HexColor("#1E3A8A"),
        spaceBefore=8,
        spaceAfter=3,
    )

    elements = []
    today_str = date.today().strftime("%Y年%m月%d日")

    elements.append(Paragraph("小林断裁 出荷管理表 （一括出力）", title_style))
    elements.append(Spacer(1, 3))
    elements.append(
        Paragraph(
            f"<font name='{FONT_NAME}' size=8 color='#64748B'>発行日: {today_str} | 対象期間: {start_date_str} 〜 {end_date_str}</font>",
            styles["Normal"],
        )
    )
    elements.append(Spacer(1, 8))

    unique_groups = sorted(df_all["グループ"].unique().tolist())
    col_widths = [62, 72, 62, 72, 95, 138, 46, 139, 130]

    for g_name in unique_groups:
        df_group = df_all[df_all["グループ"] == g_name]
        if df_group.empty:
            continue

        elements.append(
            Paragraph(f"【 {g_name} 】 （件数: {len(df_group)}件）", group_heading_style)
        )

        table_data = [[
            Paragraph("納品日", header_style),
            Paragraph("納入日メモ", header_style),
            Paragraph("搬入日", header_style),
            Paragraph("搬入日メモ", header_style),
            Paragraph("得意先名", header_style),
            Paragraph("品名", header_style),
            Paragraph("数量", header_style),
            Paragraph("依頼内容", header_style),
            Paragraph("外注先", header_style),
        ]]

        for _, row in df_group.iterrows():
            table_data.append([
                Paragraph(str(row.get("納入日/納期日", "")), cell_style),
                Paragraph(str(row.get("納入日メモ", "")), cell_style),
                Paragraph(str(row.get("搬入日", "")), cell_style),
                Paragraph(str(row.get("搬入日メモ", "")), cell_style),
                Paragraph(str(row.get("得意先名", "")), cell_style),
                Paragraph(str(row.get("品名", "")), cell_style),
                Paragraph(str(row.get("受注数量", "")), cell_style),
                Paragraph(str(row.get("仕様1/依頼事項", "")), cell_style),
                Paragraph(
                    str(row.get("外注先", "") or row.get("外注区分", "")), cell_style
                ),
            ])

        t = Table(table_data, colWidths=col_widths, repeatRows=1)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1E3A8A")),
            ("ALIGN", (0, 0), (-1, -1), "LEFT"),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
            ("TOPPADDING", (0, 0), (-1, -1), 2.5),
            ("LEFTPADDING", (0, 0), (-1, -1), 2.5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 2.5),
            ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#CBD5E1")),
        ]))

        elements.append(t)
        elements.append(Spacer(1, 7))

    doc.build(elements)
    buffer.seek(0)
    return buffer


def generate_matrix_pdf(pivot_res, start_date_str, end_date_str, selected_g_name):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        leftMargin=15,
        rightMargin=15,
        topMargin=15,
        bottomMargin=15,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "TitleStyle",
        parent=styles["Normal"],
        fontName=BOLD_FONT_NAME,
        fontSize=12,
        leading=14,
        textColor=colors.HexColor("#1E3A8A"),
    )

    cell_style = ParagraphStyle(
        "MatrixCell",
        parent=styles["Normal"],
        fontName=BOLD_FONT_NAME,
        fontSize=6,
        leading=7.5,
        textColor=colors.HexColor("#0F172A"),
    )
    header_style = ParagraphStyle(
        "MatrixHeader",
        parent=styles["Normal"],
        fontName=BOLD_FONT_NAME,
        fontSize=6.5,
        leading=8,
        textColor=colors.white,
        alignment=1,
    )

    elements = []
    today_str = date.today().strftime("%Y年%m月%d日")

    elements.append(
        Paragraph(
            f"小林断裁 出荷管理表 （スケジュールマトリクス表: {selected_g_name}）",
            title_style,
        )
    )
    elements.append(Spacer(1, 3))
    elements.append(
        Paragraph(
            f"<font name='{FONT_NAME}' size=7.5 color='#64748B'>発行日: {today_str} | 対象期間: {start_date_str} 〜 {end_date_str}</font>",
            styles["Normal"],
        )
    )
    elements.append(Spacer(1, 8))

    columns = list(pivot_res.columns)
    table_data = []

    header_row = [Paragraph(str(c), header_style) for c in columns]
    table_data.append(header_row)

    for _, row in pivot_res.iterrows():
        row_cells = []
        for c in columns:
            val = str(row[c]) if pd.notna(row[c]) else ""
            row_cells.append(Paragraph(val, cell_style))
        table_data.append(row_cells)

    total_width = 812
    col_count = len(columns)
    if col_count > 2:
        fixed_w1, fixed_w2 = 65, 165
        date_w = max(15, (total_width - (fixed_w1 + fixed_w2)) / (col_count - 2))
        col_widths = [fixed_w1, fixed_w2] + [date_w] * (col_count - 2)
    else:
        col_widths = [total_width / col_count] * col_count

    t = Table(table_data, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1E3A8A")),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#CBD5E1")),
    ]))

    elements.append(t)
    doc.build(elements)
    buffer.seek(0)
    return buffer


# --------------------------------------------------
# 7. メイン画面レイアウト
# --------------------------------------------------
st.markdown(
    f"### ✂️ 小林断裁 出荷管理表 （期間:"
    f" {start_date.strftime('%Y/%m/%d')} 〜"
    f" {end_date.strftime('%Y/%m/%d')}）"
)

if st.button("データを取り込んで出荷管理表を表示する", type="primary"):
    if not api_key_18 or not api_key_27:
        st.error(
            "👈 左側のサイドバーに App 18 と App 27 の両方のAPIキーを入力してください。"
        )
    else:
        with st.spinner("データを取得・展開中..."):
            df_all = load_and_classify_data(
                api_key_18, api_key_27, start_date, end_date
            )
            st.session_state["df_all"] = df_all

if "df_all" in st.session_state and not st.session_state["df_all"].empty:
    df_all = st.session_state["df_all"]

    for col_default in [
        "詳細リンク",
        "納入日メモ",
        "搬入日メモ",
        "外注先",
    ]:
        if col_default not in df_all.columns:
            df_all[col_default] = ""

    tab_list, tab_gantt = st.tabs([
        "📋 見出し別 出荷管理表・CSV/PDF",
        "📊 スケジュール・マトリクス表（ガント風）",
    ])

    view_cols_screen = [
        "納入日/納期日",
        "納入日メモ",
        "搬入日",
        "搬入日メモ",
        "得意先名",
        "品名",
        "受注数量",
        "仕様1/依頼事項",
        "外注先",
        "詳細リンク",
    ]
    view_cols_csv = [
        "納入日/納期日",
        "納入日メモ",
        "搬入日",
        "搬入日メモ",
        "得意先名",
        "品名",
        "受注数量",
        "仕様1/依頼事項",
        "外注先",
    ]

    # --- タブ1：見出し別リスト・PDF/CSV ---
    with tab_list:
        unique_groups = sorted(df_all["グループ"].unique().tolist())
        selected_group = st.selectbox(
            "表示する見出し（グループ）で絞り込む",
            ["すべて表示"] + unique_groups,
            key="sel_grp",
        )

        st.markdown("---")

        pdf_buffer = generate_all_schedule_pdf(
            df_all,
            start_date.strftime("%Y/%m/%d"),
            end_date.strftime("%Y/%m/%d"),
        )
        st.download_button(
            label="🖨️ 全グループ一括印字用PDFをダウンロード（用紙節約・連続出力）",
            data=pdf_buffer,
            file_name=(
                f"小林断裁_出荷管理表_一括_{start_date.strftime('%Y%m%d')}.pdf"
            ),
            mime="application/pdf",
            type="primary",
        )
        st.markdown("---")

        target_groups = (
            unique_groups if selected_group == "すべて表示" else [selected_group]
        )

        for g_name in target_groups:
            df_g = df_all[df_all["グループ"] == g_name].copy()
            if df_g.empty:
                continue

            st.markdown(f"#### 🔹 **【 {g_name} 】 （件数: {len(df_g)}件）**")

            styled_df = df_g[view_cols_screen].style.set_properties(
                subset=["納入日/納期日", "品名", "受注数量", "外注先"],
                **{"background-color": "#F8FAFC", "color": "#0F172A"},
            )

            st.dataframe(
                styled_df,
                column_config={
                    "納入日/納期日": st.column_config.TextColumn("納品日"),
                    "仕様1/依頼事項": st.column_config.TextColumn("依頼内容"),
                    "詳細リンク": st.column_config.LinkColumn(
                        "🔗 データ詳細",
                        help="at-pocketの該当データ画面へジャンプします",
                        display_text="📝 詳細を開く",
                    ),
                },
                use_container_width=True,
                hide_index=True,
            )

            safe_g_name = g_name.replace(":", "").replace(" ", "_")
            csv_data = df_g[view_cols_csv].to_csv(index=False).encode("utf-8-sig")

            st.download_button(
                label=f"📥 {g_name} のCSVをダウンロード（表崩れ防止版）",
                data=csv_data,
                file_name=(
                    f"小林断裁_{safe_g_name}_{start_date.strftime('%Y%m%d')}.csv"
                ),
                mime="text/csv",
                key=f"csv_{safe_g_name}",
            )
            st.markdown("---")

    # --- タブ2：スケジュール・マトリクス表（ガントチャート風） ---
    with tab_gantt:
        st.markdown("### 📊 スケジュール・マトリクス表（縦軸：案件 ✕ 横軸：日付）")
        st.write(
            "検索期間内の全日付を横軸に展開し、どの案件がどの日程に予定されているかをマトリクス形式で俯瞰できます。"
        )

        g_list = sorted(df_all["グループ"].unique().tolist())
        selected_g_matrix = st.selectbox(
            "グループで絞り込む", ["すべて表示"] + g_list, key="matrix_g"
        )

        df_matrix_base = df_all.copy()
        if selected_g_matrix != "すべて表示":
            df_matrix_base = df_matrix_base[
                df_matrix_base["グループ"] == selected_g_matrix
            ]

        if df_matrix_base.empty:
            st.warning("該当するデータがありません。")
        else:
            def build_case_label(row):
                cust_str = str(row.get("得意先名", "") or "").strip()
                item_str = str(row.get("品名", "") or "").strip()
                sup_str = str(row.get("外注先", "") or "").strip()
                h_memo = str(row.get("搬入日メモ", "") or "").strip()
                d_memo = str(row.get("納入日メモ", "") or "").strip()

                base = f"[{cust_str}] {item_str}".strip()
                if sup_str:
                    base += f" (外注:{sup_str})"

                memos = []
                if h_memo:
                    memos.append(f"搬入メモ:{h_memo}")
                if d_memo:
                    memos.append(f"納品メモ:{d_memo}")
                if memos:
                    base += f" [{' / '.join(memos)}]"
                return base

            def build_cell_text(group_rows):
                entries = []
                for _, r in group_rows.iterrows():
                    qty_val = str(r.get("受注数量", "") or "").strip()
                    h_memo = str(r.get("搬入日メモ", "") or "").strip()
                    d_memo = str(r.get("納入日メモ", "") or "").strip()

                    memo_parts = []
                    if h_memo:
                        memo_parts.append(f"搬入メモ:{h_memo}")
                    if d_memo:
                        memo_parts.append(f"納品メモ:{d_memo}")

                    if memo_parts:
                        entries.append(f"{qty_val} ({' / '.join(memo_parts)})")
                    elif qty_val:
                        entries.append(qty_val)
                return " / ".join(entries)

            df_matrix_base["案件名"] = df_matrix_base.apply(build_case_label, axis=1)
            df_matrix_base["_セル表示"] = df_matrix_base.apply(
                lambda r: build_cell_text(pd.DataFrame([r])), axis=1
            )

            date_range = pd.date_range(start=start_date, end=end_date)
            date_cols_str = [d.strftime("%Y-%m-%d") for d in date_range]

            pivot_df = pd.pivot_table(
                df_matrix_base,
                index=["グループ", "案件名"],
                columns="納入日/納期日",
                values="_セル表示",
                aggfunc=lambda x: " / ".join([str(v) for v in x if str(v).strip()]),
                fill_value="",
            )

            for d_str in date_cols_str:
                if d_str not in pivot_df.columns:
                    pivot_df[d_str] = ""

            pivot_df = pivot_df[date_cols_str]
            pivot_res = pivot_df.reset_index()

            st.dataframe(pivot_res, use_container_width=True)

            st.markdown("---")
            matrix_pdf_buffer = generate_matrix_pdf(
                pivot_res,
                start_date.strftime("%Y-%m-%d"),
                end_date.strftime("%Y-%m-%d"),
                selected_g_matrix,
            )
            st.download_button(
                label="🖨️ マトリクス表のPDFをダウンロード",
                data=matrix_pdf_buffer,
                file_name=f"小林断裁_マトリクス表_{selected_g_matrix.replace(':', '').replace(' ', '_')}_{start_date.strftime('%Y%m%d')}.pdf",
                mime="application/pdf",
                type="primary",
            )

elif "df_all" in st.session_state:
    st.warning("指定された期間に該当するデータが見つかりませんでした。")