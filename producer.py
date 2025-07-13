import sys
import os
# ライブラリを同梱フォルダから読み込むための設定
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'libs'))

import random
import json
import requests
import time
import re
from datetime import datetime, date
import pytz

# --- 定数と設定 ---
SPREADSHEET_NAME = 'コスメ投稿案リスト'
SERVICE_ACCOUNT_FILE = 'google_credentials.json'
POSTING_SCHEDULE = {
    "21:00": "hybrid", "22:00": "hybrid", "22:30": "hybrid", "21:30": "hybrid", "14:00": "hybrid",
    "15:00": "hybrid", "12:30": "hybrid", "19:00": "hybrid", "11:00": "hybrid", "00:00": "hybrid"
}
SEASONAL_TOPICS = ["春の新作色っぽリップ", "夏の崩れない最強下地", "秋の抜け感ブラウンシャドウ", "冬の高保湿スキンケア", "紫外線対策 日焼け止め", "汗・皮脂に強いファンデーション"]
CONCERN_TOPICS = ["気になる毛穴の黒ずみ撃退法", "頑固なニキビ跡を隠すコンシーラー術", "敏感肌でも安心な低刺激コスメ", "ブルベ女子に似合う透明感チーク", "イエベ女子のための必勝アイシャドウ"]
TECHNIQUE_TOPICS = ["中顔面を短縮するメイクテクニック", "誰でも簡単！涙袋の作り方", "プロが教える眉毛の整え方", "チークをアイシャドウとして使う裏技", "証明写真 盛れるメイク術"]
ALL_TOPICS_SEED = SEASONAL_TOPICS + CONCERN_TOPICS + TECHNIQUE_TOPICS

# --- グローバル変数 ---
g_gemini_model = None
g_rakuten_app_id, g_rakuten_affiliate_id = None, None
g_amazon_access_key, g_amazon_secret_key, g_amazon_associate_tag = None, None, None

# --- 初期セットアップ ---
def setup_apis():
    global g_rakuten_app_id, g_rakuten_affiliate_id, g_amazon_access_key, g_amazon_secret_key, g_amazon_associate_tag, g_gemini_model
    print("デバッグ: APIセットアップを開始します。")
    sys.stdout.flush()
    try:
        import google.generativeai as genai
        GEMINI_API_KEY = os.getenv('GEMINI_API_KEY2')
        g_rakuten_app_id = os.getenv('RAKUTEN_APP_ID')
        g_rakuten_affiliate_id = os.getenv('RAKUTEN_AFFILIATE_ID')
        g_amazon_access_key = os.getenv('AMAZON_ACCESS_KEY')
        g_amazon_secret_key = os.getenv('AMAZON_SECRET_KEY')
        g_amazon_associate_tag = os.getenv('AMAZON_ASSOCIATE_TAG')
        
        if not all([GEMINI_API_KEY, g_rakuten_app_id, g_amazon_access_key]):
            print("🛑 エラー: 必要なAPIキーが環境変数に設定されていません。")
            return False
            
        genai.configure(api_key=GEMINI_API_KEY)
        g_gemini_model = genai.GenerativeModel('gemini-1.5-flash')
        print("✅ 全てのAPIキーを読み込み、モデルを準備しました。")
        return True
    except Exception as e:
        print(f"🛑 エラー: APIセットアップ中にエラー: {e}")
        return False

def get_gspread_client():
    print("デバッグ: スプレッドシートクライアントの準備を開始します。")
    sys.stdout.flush()
    try:
        import gspread
        from google.oauth2.service_account import Credentials
        scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
        if os.path.exists(SERVICE_ACCOUNT_FILE):
            creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=scopes)
            gc = gspread.authorize(creds)
            print("✅ gspreadクライアントの認証に成功しました。")
            return gc
    except Exception as e:
        print(f"🛑 エラー: gspreadクライアントの取得中にエラー: {e}")
    return None

def search_products(platform, keyword):
    print(f"  - {platform.capitalize()}を検索中... (キーワード: '{keyword}')")
    sys.stdout.flush()
    try:
        import requests
        if platform == "rakuten":
            params = {"applicationId": g_rakuten_app_id, "affiliateId": g_rakuten_affiliate_id, "keyword": keyword, "format": "json", "sort": random.choice(["standard", "-reviewCount"]), "hits": 10, "page": random.randint(1, 3)}
            response = requests.get("https://app.rakuten.co.jp/services/api/IchibaItem/Search/20220601", params=params)
            response.raise_for_status()
            return [{"name": i['Item']['itemName'], "url": i['Item']['affiliateUrl']} for i in response.json().get("Items", [])]
        elif platform == "amazon":
            from paapi5_python_sdk.api.default_api import DefaultApi
            from paapi5_python_sdk.models.partner_type import PartnerType
            from paapi5_python_sdk.models.search_items_request import SearchItemsRequest
            from paapi5_python_sdk.models.search_items_resource import SearchItemsResource
            from paapi5_python_sdk.rest import ApiException
            
            api_client = DefaultApi(access_key=g_amazon_access_key, secret_key=g_amazon_secret_key, host="webservices.amazon.co.jp", region="us-west-2")
            search_request = SearchItemsRequest(partner_tag=g_amazon_associate_tag, partner_type=PartnerType.ASSOCIATES, keywords=keyword, search_index="Beauty", resources=[SearchItemsResource.ITEMINFO_TITLE, SearchItemsResource.DETAILPAGEURL], item_count=10)
            response = api_client.search_items(search_request)
            return [{"name": i.item_info.title.display_value, "url": i.detail_page_url} for i in response.search_result.items] if response.search_result and response.search_result.items else []
    except Exception as e:
        print(f"  🛑 {platform.capitalize()} APIエラー: {e}")
    return []

def generate_hybrid_post(platform, topic_seed):
    print(f"  - 【{platform.upper()}】のテーマ「{topic_seed}」で投稿案を生成中...")
    sys.stdout.flush()
    try:
        model = g_gemini_model
        
        # STEP 1: テーマの決定
        theme_prompt = f"あなたは日本のSNSマーケティングの専門家です。X(Twitter)アカウント「ゆあ＠プチプラコスメ塾」のフォロワーが保存したくなるような投稿を作るため、以下の切り口から、具体的で魅力的な投稿テーマを1つ考えてください。\n# テーマの切り口\n{topic_seed}\n# 出力形式\nテーマの文字列のみ"
        response = model.generate_content(theme_prompt)
        topic = response.text.strip()
        print(f"  ✅ 生成された最終テーマ: {topic}")
        sys.stdout.flush()

        # STEP 2: 検索キーワードの生成
        keyword_prompt = f"以下の投稿テーマに最も関連性が高く、楽天市場で商品を検索するための具体的な検索キーワードを1つ生成してください。\n# 投稿テーマ\n{topic}\n# 指示\n- 楽天市場の商品名に含まれやすい、2〜3個の名詞の組み合わせにすること。\n- 回答はキーワード文字列のみ。"
        response = model.generate_content(keyword_prompt)
        keyword = response.text.strip().replace("　", " ")
        print(f"  ✅ 検索用キーワード: {keyword}")
        sys.stdout.flush()

        # STEP 3: 商品を検索
        items = search_products(platform, keyword)
        if not items:
            print(f"  ⚠️ {platform}で商品が見つかりませんでした。")
            return None
        print(f"  ✅ {platform}で{len(items)}件の商品を発見。")
        sys.stdout.flush()
        
        # STEP 4: 最終的な記事を執筆
        item_candidates = random.sample(items, min(len(items), 5))
        formatted_items_string = "\n".join([f"- 商品名: {i['name']}, URL: {i['url']}" for i in item_candidates])
        platform_name = "楽天市場" if platform == "rakuten" else "Amazon"
        platform_hashtag = "#楽天でみつけた神コスメ" if platform == "rakuten" else "#Amazonで見つけた"
        
        final_post_prompt = f"あなたはXアカウント「ゆあ＠プチプラコスメ塾」の運営者です。以下のテーマと**{platform_name}**の商品リストを基に、価値を提供しつつ自然に商品を1つ紹介する、500字以内の投稿を作成してください。\n#絶対的なルール\n- 【リンク位置・最重要】投稿の冒頭50文字以内で、テーマに関する悩みを一言で提示し、その解決策となる商品を「結論」として紹介し、アフィリエイトURLを記載すること。\n- 【深掘り】投稿の後半では、紹介した商品のさらに詳しい使い方や、関連する美容テクニックなどを解説し、記事全体の価値を高めること。\n- 【ハッシュタグ】最後に、投稿内容に最も関連性が高く、インプレッションを最大化できるハッシュタグを5〜6個厳選して付ける。`#PR`と`{platform_hashtag}`は必須。\n- 【品質】言及する商品は実在のものとし、推奨は文脈に適合していること。プレースホルダーは絶対に使わない。\n- 【その他】スマホでの見やすさを最優先する。マークダウン記法は使わない。あなた自身で文章を読み返し、不自然な点がないかセルフチェックしてから出力を完了する。\n#投稿テーマ\n{topic}\n#紹介して良い商品リスト（この中から1つだけ選ぶ）\n{formatted_items_string}\n#出力形式（JSON）\n{{\"content\": \"（生成した投稿文全体）\"}}"
        
        response = model.generate_content(final_post_prompt)
        result = json.loads(response.text.strip().replace("```json", "").replace("```", ""))
        
        import requests
        long_url_match = re.search(r'(https?://[^\s]+)', result['content'])
        if long_url_match:
            long_url = long_url_match.group(1)
            short_url = requests.get(f"http://tinyurl.com/api-create.php?url={long_url}").text
            final_content = result['content'].replace(long_url, short_url)
        else:
            final_content = result['content']
            
        print(f"  ✅ {platform.capitalize()}の投稿案を生成完了。")
        sys.stdout.flush()
        return {"type": f"{platform}_hybrid", "topic": f"{platform.capitalize()}投稿: {topic}", "content": final_content}
        
    except Exception as e:
        print(f"  🛑 ハイブリッド投稿の生成中にエラー: {e}")
        sys.stdout.flush()
        return None

if __name__ == "__main__":
    print("--- メイン処理の開始 ---")
    sys.stdout.flush()
    if not setup_apis(): raise SystemExit()
    
    gc = get_gspread_client()
    if not gc: raise SystemExit()

    try:
        sh = gc.open(SPREADSHEET_NAME)
        worksheet = sh.sheet1
        worksheet.clear() 
        header = ['scheduled_time', 'post_type', 'content', 'status', 'posted_time', 'posted_tweet_url']
        worksheet.append_row(header)
        print("✅ スプレッドシートを準備しました。")
        sys.stdout.flush()
    except Exception as e:
        print(f"🛑 スプレッドシートの準備中にエラー: {e}"); raise SystemExit()

    rows_to_add = []
    used_topics = set()
    target_post_count = len(POSTING_SCHEDULE)
    print(f"\n--- 今日の投稿案 {target_post_count}件の生成を開始します ---")
    sys.stdout.flush()
    
    while len(rows_to_add) < target_post_count:
        print(f"\n--- {len(rows_to_add) + 1}件目の投稿案を生成します ---")
        sys.stdout.flush()
        
        # 交互にプラットフォームを決定
        platform_to_use = "rakuten" if (len(rows_to_add) % 2 == 0) else "amazon"
        
        # トピックの選択
        if not list(set(ALL_TOPICS_SEED) - used_topics):
            used_topics = set()
        available_topics = list(set(ALL_TOPICS_SEED) - used_topics)
        topic_seed = random.choice(available_topics)
        used_topics.add(topic_seed)
        
        # 投稿生成
        post_data = generate_hybrid_post(platform_to_use, topic_seed)
        if post_data:
            rows_to_add.append(post_data)
        
        time.sleep(30)
    
    if rows_to_add:
        rows_for_sheet = []
        # 生成された投稿をスケジュール時刻に割り当て
        sorted_times = sorted(POSTING_SCHEDULE.keys())
        for i in range(len(rows_to_add)):
            time_str = sorted_times[i]
            post = rows_to_add[i]
            rows_for_sheet.append([time_str, post['topic'], post['content'], 'pending', '', ''])
        
        if rows_for_sheet:
            worksheet.append_rows(rows_for_sheet, value_input_option='USER_ENTERED')
            print(f"\n✅ スプレッドシートに{len(rows_for_sheet)}件の投稿案を全て書き込みました。")
            sys.stdout.flush()

    print("🏁 コンテンツ一括生成プログラムを終了します。")
    sys.stdout.flush()
