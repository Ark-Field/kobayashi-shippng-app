from datetime import datetime
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
  # 1. GitHubリポジトリ内やアプリと同じフォルダにある同梱フォントを最優先で読み込む
  local_font_path = "NotoSansJP-Regular.ttf"
  if os.path.exists(local_font_path):
    try:
      pdfmetrics.registerFont(TTFont("JPFont", local_font_path))
      return "JPFont"
    except Exception as e:
      print(f"同梱フォント登録エラー: {e}")

  # 2. ローカルWindows環境用フォールバック
  win_font = os.path.join(
      os.environ.get("SystemRoot", "C:\\Windows"), "Fonts", "msgothic.ttc"
  )
  if os.path.exists(win_font):
    try:
      pdfmetrics.registerFont(TTFont("JPFont", win_font, subfontIndex=0))
      return "JPFont"
    except Exception as e:
      print(f"Windowsフォント登録エラー: {e}")

  # 3. どちらも見つからない場合の最終手段
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

today = datetime.date.today()
default_start = today - datetime.timedelta(days=1)
default_end = today + datetime.timedelta(days=18)

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
    item = extract_pocket_field_val(inner.get("field27-23"))  # 品名※
    qty = (
        extract_pocket_field_val(inner.get("field27-25")) or "0"
    )  # 受注数量※
    spec = extract_pocket_field_val(inner.get("field27-11"))  # 依頼事項
    order_no = extract_pocket_field_val(inner.get("field27-3"))  # 受注番号※
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
# 6. PDF一括生成関数（A4横型・自動折り返し・用紙節約連続出力）
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
      "TableCell",
      parent=styles["Normal"],
      fontName=FONT_NAME,
      fontSize=7.5,
      leading=9,
      textColor=colors.HexColor("#1E293B"),
  )
  header_style = ParagraphStyle(
      "TableHeader",
      parent=styles["Normal"],
      fontName=FONT_NAME,
      fontSize=8,
      leading=10,
      textColor=colors.white,
      alignment=1,
  )
  title_style = ParagraphStyle(
      "TitleStyle",
      parent=styles["Normal"],
      fontName=FONT_NAME,
      fontSize=14,
      leading=16,
      textColor=colors.HexColor("#1E3A8A"),
  )
  group_heading_style = ParagraphStyle(
      "GroupHeading",
      parent=styles["Normal"],
      fontName=FONT_NAME,
      fontSize=10,
      leading=12,
      textColor=colors.HexColor("#1E3A8A"),
      spaceBefore=10,
      spaceAfter=4,
  )

  elements = []
  today_str = datetime.date.today().strftime("%Y年%m月%d日")

  elements.append(
      Paragraph(f"<b>小林断裁 出荷管理表 （一括出力）</b>", title_style)
  )
  elements.append(Spacer(1, 4))
  elements.append(
      Paragraph(
          f"<font size=8 color='#64748B'>発行日: {today_str} | 対象期間:"
          f" {start_date_str} 〜 {end_date_str}</font>",
          styles["Normal"],
      )
  )
  elements.append(Spacer(1, 10))

  unique_groups = sorted(df_all["グループ"].unique().tolist())
  col_widths = [65, 65, 75, 110, 160, 50, 140, 137]

  for g_name in unique_groups:
    df_group = df_all[df_all["グループ"] == g_name]
    if df_group.empty:
      continue

    elements.append(
        Paragraph(
            f"<b>【 {g_name} 】</b> （件数: {len(df_group)}件）",
            group_heading_style,
        )
    )

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
    t.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1E3A8A")),
            ("ALIGN", (0, 0), (-1, -1), "LEFT"),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("LEFTPADDING", (0, 0), (-1, -1), 3),
            ("RIGHTPADDING", (0, 0), (-1, -1), 3),
            ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#CBD5E1")),
        ])
    )

    elements.append(t)
    elements.append(Spacer(1, 8))

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

  tab_list, tab_cal = st.tabs([
      "📋 見出し別 出荷管理表・CSV/PDF",
      "📅 日別スケジュール（カレンダー）ビュー",
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

  # --- タブ2：日別カレンダービュー ---
  with tab_cal:
    st.markdown("### 📅 日別スケジュールビュー（日付ごとの俯瞰）")
    st.write(
        "納入日（納期日）ごとに、その日出荷予定の案件をまとめて確認できます。"
    )

    dates = sorted(df_all["納入日/納期日"].unique().tolist())

    for d in dates:
      df_date = df_all[df_all["納入日/納期日"] == d]
      with st.expander(
          f"📌 【 {d} 】 出荷・納入予定 （合計: {len(df_date)} 件）",
          expanded=True,
      ):
        cal_cols = [
            "グループ",
            "受注番号",
            "得意先名",
            "品名",
            "受注数量",
            "仕様1/依頼事項",
            "外注区分",
        ]
        st.dataframe(
            df_date[cal_cols], use_container_width=True, hide_index=True
        )

elif "df_all" in st.session_state:
  st.warning("指定された期間に該当するデータが見つかりませんでした。")