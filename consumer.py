import sys
import os
# ライブラリを同梱フォルダから読み込むための設定
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'libs'))

import time
from datetime import datetime, date
import pytz

# --- 定数と設定 ---
SPREADSHEET_NAME = 'コスメ投稿案リスト'
SERVICE_ACCOUNT_FILE = 'google_credentials.json'
STATUS_COL = 4 # D列がstatus列

# --- APIクライアントとスプレッドシートクライアントの準備 ---
def setup_apis():
    try:
        import tweepy
        X_API_KEY = os.getenv('X_API_KEY')
        X_API_SECRET = os.getenv('X_API_SECRET')
        X_ACCESS_TOKEN = os.getenv('X_ACCESS_TOKEN')
        X_ACCESS_TOKEN_SECRET = os.getenv('X_ACCESS_TOKEN_SECRET')
        X_USERNAME = os.getenv('X_USERNAME')
        if not all([X_API_KEY, X_USERNAME]):
             print("🛑 X APIキーまたはユーザー名が設定されていません。")
             return None, None
        client_v2 = tweepy.Client(
            consumer_key=X_API_KEY, consumer_secret=X_API_SECRET,
            access_token=X_ACCESS_TOKEN, access_token_secret=X_ACCESS_TOKEN_SECRET
        )
        print("✅ X APIクライアントの準備が完了しました。")
        return client_v2, X_USERNAME
    except Exception as e:
        print(f"🛑 エラー: X APIキーの読み込みエラー: {e}")
        return None, None

def get_gspread_client():
    try:
        import gspread
        from google.oauth2.service_account import Credentials
        scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
        if os.path.exists(SERVICE_ACCOUNT_FILE):
            creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=scopes)
            return gspread.authorize(creds)
    except Exception as e:
        print(f"🛑 エラー: gspreadクライアントの取得中にエラー: {e}")
    return None

def post_to_x(client, text):
    """テキストツイートを投稿し、成功したらツイートIDを返す"""
    try:
        response = client.create_tweet(text=text)
        print(f"✅ Xへの投稿に成功！ Tweet ID: {response.data['id']}")
        return response.data['id']
    except Exception as e:
        print(f"🛑 Xへの投稿中にエラー: {e}")
        return None

def main():
    print("🚀 投稿ボットを実行します。")
    sys.stdout.flush()
    x_client, x_username = setup_apis()
    gc = get_gspread_client()

    if not x_client or not gc:
        print("🛑 クライアントの初期化に失敗。処理を終了します。"); return

    try:
        worksheet = gc.open(SPREADSHEET_NAME).sheet1
        all_posts = worksheet.get_all_records()

        jst = pytz.timezone('Asia/Tokyo')
        now = datetime.now(jst)
        print(f"現在の日本時間: {now.strftime('%Y-%m-%d %H:%M:%S')}")
        sys.stdout.flush()
        
        pending_posts = [post for post in all_posts if post.get('status') == 'pending']
        pending_posts.sort(key=lambda p: datetime.strptime(p.get('scheduled_time', '23:59'), "%H:%M").time())
        
        if not pending_posts:
            print("✅ 投稿待機中のタスクはありません。")
            return

        for i, post in enumerate(pending_posts):
            scheduled_time_str = post.get('scheduled_time')
            if not scheduled_time_str: continue

            scheduled_time_obj = datetime.strptime(scheduled_time_str, "%H:%M").time()
            scheduled_datetime_today = jst.localize(datetime.combine(date.today(), scheduled_time_obj))

            if now >= scheduled_datetime_today:
                print(f"⏰ 投稿時間です！ {post.get('post_type')} の投稿を実行します...")
                sys.stdout.flush()
                
                original_index = -1
                for idx, d in enumerate(all_posts):
                    if d.get('content') == post.get('content'):
                        original_index = idx
                        break
                if original_index == -1: continue
                row_num = original_index + 2

                print(f"  - ステータスを 'posting...' に更新します。(行番号: {row_num})")
                sys.stdout.flush()
                worksheet.update_cell(row_num, STATUS_COL, 'posting...')
                
                tweet_id = post_to_x(x_client, post.get('content'))
                
                if tweet_id:
                    posted_time = datetime.now(jst).strftime('%Y-%m-%d %H:%M:%S')
                    tweet_url = f"https://x.com/{x_username}/status/{tweet_id}"
                    worksheet.update_cells([
                        gspread.Cell(row_num, 4, 'posted'),
                        gspread.Cell(row_num, 5, posted_time),
                        gspread.Cell(row_num, 6, tweet_url)
                    ])
                    print(f"✅ スプレッドシートのステータスを'posted'に更新しました。")
                else:
                    worksheet.update_cell(row_num, STATUS_COL, 'failed')
                    print(f"⚠️ 投稿に失敗したため、ステータスを'failed'に更新しました。")
                
                print("✅ 投稿処理が完了したため、今回の実行を終了します。")
                return
        
        print("✅ 投稿予定時刻を過ぎたタスクはありません。")

    except Exception as e:
        print(f"🛑 投稿ボットのメイン処理でエラー: {e}")
        
    print("🏁 投稿ボットを終了します。")
    sys.stdout.flush()

if __name__ == "__main__":
    main()
