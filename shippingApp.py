from datetime import date, datetime, timedelta
import io
import os
import urllib.request
import pandas as pd
import requests
import streamlit as st

# ReportLab関連のインポート（PDF出力用）
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet

# --------------------------------------------------
# 1. ページ初期設定
# --------------------------------------------------
st.set_page_config(page_title="小林断裁 出荷管理表", layout="wide")

st.title("✂️ 小林断裁 出荷管理表 ＆ 作業管理システム")

# --------------------------------------------------
# 2. 日本語フォント登録処理（ReportLab用・完全対応版）
# --------------------------------------------------
def setup_japanese_font():
    local_font_path = "NotoSansJP-Regular.ttf"
    if os.path.exists(local_font_path):
        try:
            pdfmetrics.registerFont(TTFont("JPFont", local_font_path))
            return "JPFont"
        except Exception as e:
            print(f"同梱フォント登録エラー: {e}")

    win_font = os.path.join(
        os.environ.get("SystemRoot", "C:\\Windows"), "Fonts", "msgothic.ttc"
    )
    if os.path.exists(win_font):
        try:
            pdfmetrics.registerFont(TTFont("JPFont", win_font, subfontIndex=0))
            return "JPFont"
        except Exception as e:
            print(f"Windowsフォント登録エラー: {e}")

    return "Helvetica"

FONT_NAME = setup_japanese_font()

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


# --------------------------------------------------
# 5. データ集計・グループ分けメイン処理（App 18 ＆ App 27 統合）
# --------------------------------------------------
def load_and_classify_data(api_key_18, api_key_27, start_date, end_date):
    parsed_items = []

    # --- App ID: 18 の取得（社内加工 1〜5） ---
    records_18 = fetch_pocket_records(
        api_key_18, 18, "field18-58", start_date, end_date
    )
    for r in records_18:
        inner = r.get("record", r)
        record_id = r.get("id", inner.get("id", ""))

        delivery_date = extract_pocket_field_val(inner.get("field18-58"))
        if not delivery_date:
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
                    "アプリ": "App 18",
                    "作業区分": prefix,
                    "単語": word_val,
                    "グループ": group_name,
                    "納入日/納期日": delivery_date[:10],
                    "搬入日": hanyu[:10],
                    "受注番号": order_no,
                    "得意先名": cust,
                    "品名": item,
                    "受注数量": qty,
                    "仕様1/依頼事項": spec,
                    "外注区分": gai_kubun,
                    "作業完了": completed,
                })
                matched_count += 1

        if matched_count == 0:
            parsed_items.append({
                "レコードID": record_id,
                "アプリ": "App 18",
                "作業区分": "未分類",
                "単語": "未分類",
                "グループ": "未分類（加工）",
                "納入日/納期日": delivery_date[:10],
                "搬入日": hanyu[:10],
                "受注番号": order_no,
                "得意先名": cust,
                "品名": item,
                "受注数量": qty,
                "仕様1/依頼事項": spec,
                "外注区分": gai_kubun,
                "作業完了": completed,
            })

    # --- App ID: 27 の取得（外注） ---
    records_27 = fetch_pocket_records(
        api_key_27, 27, "field27-16", start_date, end_date
    )
    for r in records_27:
        inner = r.get("record", r)
        record_id = r.get("id", inner.get("id", ""))

        delivery_date = extract_pocket_field_val(inner.get("field27-16"))  # 納期日
        if not delivery_date:
            continue

        cust = extract_pocket_field_val(inner.get("field27-22"))  # 得意先名
        item = extract_pocket_field_val(inner.get("field27-23"))  # 品名
        qty = extract_pocket_field_val(inner.get("field27-25")) or "0"  # 受注数量
        spec = extract_pocket_field_val(inner.get("field27-11"))  # 依頼事項
        order_no = extract_pocket_field_val(inner.get("field27-3"))  # 受注番号
        hanyu = extract_pocket_field_val(inner.get("field27-14"))  # 搬入日
        supplier = extract_pocket_field_val(inner.get("field27-4"))  # 外注先名

        group_name = f"外注: {supplier}" if supplier else "外注"

        parsed_items.append({
            "レコードID": record_id,
            "アプリ": "App 27",
            "作業区分": "外注",
            "単語": supplier if supplier else "外注",
            "グループ": group_name,
            "納入日/納期日": delivery_date[:10],
            "搬入日": hanyu[:10],
            "受注番号": order_no,
            "得意先名": cust,
            "品名": item,
            "受注数量": qty,
            "仕様1/依頼事項": spec,
            "外注区分": f"外注先: {supplier}",
            "作業完了": False,
        })

    if not parsed_items:
        return pd.DataFrame()

    df = pd.DataFrame(parsed_items)
    df = df.sort_values(
        by=["作業区分", "単語", "納入日/納期日"], ascending=[True, True, True]
    )
    return df


# --------------------------------------------------
# 6. PDF生成関数（通常一覧用 ＆ マトリクス表用）
# --------------------------------------------------
def generate_all_schedule_pdf(df_all, start_date_str, end_date_str):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        leftMargin=20,
        rightMargin=20,
        topMargin=20,
        bottomMargin=20,
    )

    styles = getSampleStyleSheet()
    cell_style = ParagraphStyle(
        "TableCell", parent=styles["Normal"], fontName=FONT_NAME, fontSize=7.5, leading=9, textColor=colors.HexColor("#1E293B")
    )
    header_style = ParagraphStyle(
        "TableHeader", parent=styles["Normal"], fontName=FONT_NAME, fontSize=8, leading=10, textColor=colors.white, alignment=1
    )
    title_style = ParagraphStyle(
        "TitleStyle", parent=styles["Normal"], fontName=FONT_NAME, fontSize=14, leading=16, textColor=colors.HexColor("#1E3A8A")
    )
    group_heading_style = ParagraphStyle(
        "GroupHeading", parent=styles["Normal"], fontName=FONT_NAME, fontSize=10, leading=12, textColor=colors.HexColor("#1E3A8A"), spaceBefore=10, spaceAfter=4
    )

    elements = []
    today_str = date.today().strftime("%Y年%m月%d日")

    elements.append(Paragraph(f"<b>小林断裁 出荷管理表 （一括出力）</b>", title_style))
    elements.append(Spacer(1, 4))
    elements.append(Paragraph(f"<font size=8 color='#64748B'>発行日: {today_str} | 対象期間: {start_date_str} 〜 {end_date_str}</font>", styles["Normal"]))
    elements.append(Spacer(1, 10))

    unique_groups = sorted(df_all["グループ"].unique().tolist())
    col_widths = [65, 65, 75, 110, 160, 50, 140, 137]

    for g_name in unique_groups:
        df_group = df_all[df_all["グループ"] == g_name]
        if df_group.empty:
            continue

        elements.append(Paragraph(f"<b>【 {g_name} 】</b> （件数: {len(df_group)}件）", group_heading_style))

        table_data = [[
            Paragraph("納入日/納期日", header_style),
            Paragraph("搬入日", header_style),
            Paragraph("受注番号", header_style),
            Paragraph("得意先名", header_style),
            Paragraph("品名", header_style),
            Paragraph("数量", header_style),
            Paragraph("仕様 / 依頼事項", header_style),
            Paragraph("外注区分・備考", header_style),
        ]]

        for idx, row in df_group.iterrows():
            table_data.append([
                Paragraph(str(row["納入日/納期日"]), cell_style),
                Paragraph(str(row["搬入日"]), cell_style),
                Paragraph(str(row["受注番号"]), cell_style),
                Paragraph(str(row["得意先名"]), cell_style),
                Paragraph(str(row["品名"]), cell_style),
                Paragraph(str(row["受注数量"]), cell_style),
                Paragraph(str(row["仕様1/依頼事項"]), cell_style),
                Paragraph(str(row["外注区分"]), cell_style),
            ])

        t = Table(table_data, colWidths=col_widths, repeatRows=1)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1E3A8A")),
            ("ALIGN", (0, 0), (-1, -1), "LEFT"),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("LEFTPADDING", (0, 0), (-1, -1), 3),
            ("RIGHTPADDING", (0, 0), (-1, -1), 3),
            ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#CBD5E1")),
        ]))

        elements.append(t)
        elements.append(Spacer(1, 8))

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
        "TitleStyle", parent=styles["Normal"], fontName=FONT_NAME, fontSize=12, leading=14, textColor=colors.HexColor("#1E3A8A")
    )
    
    # マトリクス表用のコンパクトなセルスタイル
    cell_style = ParagraphStyle(
        "MatrixCell", parent=styles["Normal"], fontName=FONT_NAME, fontSize=6, leading=7.5, textColor=colors.HexColor("#1E293B")
    )
    header_style = ParagraphStyle(
        "MatrixHeader", parent=styles["Normal"], fontName=FONT_NAME, fontSize=6.5, leading=8, textColor=colors.white, alignment=1
    )

    elements = []
    today_str = date.today().strftime("%Y年%m月%d日")

    elements.append(Paragraph(f"<b>小林断裁 出荷管理表 （スケジュールマトリクス表: {selected_g_name}）</b>", title_style))
    elements.append(Spacer(1, 3))
    elements.append(Paragraph(f"<font size=7.5 color='#64748B'>発行日: {today_str} | 対象期間: {start_date_str} 〜 {end_date_str}</font>", styles["Normal"]))
    elements.append(Spacer(1, 8))

    # テーブルデータの組み立て
    columns = list(pivot_res.columns)
    table_data = []

    # ヘッダー行
    header_row = [Paragraph(str(c), header_style) for c in columns]
    table_data.append(header_row)

    # データ行
    for _, row in pivot_res.iterrows():
        row_cells = []
        for c in columns:
            val = str(row[c]) if pd.notna(row[c]) else ""
            row_cells.append(Paragraph(val, cell_style))
        table_data.append(row_cells)

    # カラム幅の自動割り当て (A4横型幅 = ~812 pt利用可能)
    # 0列目（グループ）: 70pt, 1列目（案件名）: 150pt, 残りを日付列で均等分割
    total_width = 812
    col_count = len(columns)
    if col_count > 2:
        fixed_w1, fixed_w2 = 65, 140
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

    tab_list, tab_gantt = st.tabs([
        "📋 見出し別 出荷管理表・CSV/PDF",
        "📊 スケジュール・マトリクス表（ガント風）",
    ])

    view_cols_screen = [
        "納入日/納期日",
        "搬入日",
        "受注番号",
        "得意先名",
        "品名",
        "受注数量",
        "仕様1/依頼事項",
        "外注区分",
    ]
    view_cols_csv = [
        "納入日/納期日",
        "搬入日",
        "受注番号",
        "得意先名",
        "品名",
        "受注数量",
        "外注区分",
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

            st.markdown(f"#### 🔹 【 {g_name} 】 （件数: {len(df_g)}件）")
            st.dataframe(
                df_g[view_cols_screen], use_container_width=True, hide_index=True
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
        st.write("検索期間内の全日付を横軸に展開し、どの案件がどの日程に予定されているかをマトリクス形式で俯瞰できます。")

        g_list = sorted(df_all["グループ"].unique().tolist())
        selected_g_matrix = st.selectbox("グループで絞り込む", ["すべて表示"] + g_list, key="matrix_g")

        df_matrix_base = df_all.copy()
        if selected_g_matrix != "すべて表示":
            df_matrix_base = df_matrix_base[df_matrix_base["グループ"] == selected_g_matrix]

        if df_matrix_base.empty:
            st.warning("該当するデータがありません。")
        else:
            df_matrix_base["案件名"] = (
                "[" + df_matrix_base["得意先名"].fillna("") + "] " + 
                df_matrix_base["品名"].fillna("") + 
                " (No:" + df_matrix_base["受注番号"].fillna("") + ")"
            )

            date_range = pd.date_range(start=start_date, end=end_date)
            date_cols_str = [d.strftime("%Y-%m-%d") for d in date_range]

            pivot_df = pd.pivot_table(
                df_matrix_base,
                index=["グループ", "案件名"],
                columns="納入日/納期日",
                values="受注数量",
                aggfunc=lambda x: " / ".join([str(v) for v in x if v]),
                fill_value=""
            )

            for d_str in date_cols_str:
                if d_str not in pivot_df.columns:
                    pivot_df[d_str] = ""

            pivot_df = pivot_df[date_cols_str]

            # 画面表示用にインデックスをリセット
            pivot_res = pivot_df.reset_index()

            st.dataframe(pivot_res, use_container_width=True)

            st.markdown("---")
            # マトリクス表PDFダウンロードボタン
            matrix_pdf_buffer = generate_matrix_pdf(
                pivot_res,
                start_date.strftime("%Y/%m/%d"),
                end_date.strftime("%Y/%m/%d"),
                selected_g_matrix
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