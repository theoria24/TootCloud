from collections import Counter
from pathlib import Path

from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from tinydb import TinyDB, Query
from mastodon import Mastodon
from wordcloud import WordCloud
from datetime import datetime
from numpy.random import randint
from xml.sax.saxutils import unescape
import re
import json
import requests
import MeCab
import threading
from threading import Lock

import emoji_utils
from emoji_utils import (
    build_placeholder_map,
    composite_emoji,
    extract_emoji_frequencies,
    is_placeholder,
    strip_emoji,
)

app = Flask(__name__)
app.config.from_object("config")
db = TinyDB("db.json")
qwy = Query()
m = MeCab.Tagger(app.config["MECAB_OPT"])
target_hinshi = ["名詞", "形容詞", "形容動詞"]
exclude = ["非自立", "接尾"]
with open("stopwordlist.txt") as f:
    swl = [s.strip() for s in f.readlines()]

# カラー絵文字設定（config.py で上書き可能）
_USE_COLOR_EMOJI: bool = app.config.get("USE_COLOR_EMOJI", True)
_EMOJI_MAX_COUNT: int = app.config.get("EMOJI_MAX_COUNT", 50)
_EMOJI_FONT_SIZE_SCALE: float = app.config.get("EMOJI_FONT_SIZE_SCALE", 1.0)
_TWEMOJI_ASSETS_PATH: Path = Path(
    app.config.get("TWEMOJI_ASSETS_PATH", "./assets/twemoji/svg")
)

# バックグラウンドタスク管理
tasks = {}
tasks_lock = Lock()


def make_mastodon_client(session_data):
    return Mastodon(
        client_id=session_data["client_id"],
        client_secret=session_data["client_secret"],
        access_token=session_data["access_token"],
        api_base_url=session_data["uri"],
    )


def update_task(task_id, **changes):
    with tasks_lock:
        task = tasks.get(task_id)
        if task is None:
            return
        task.update(changes)


def register_app(host):
    data = {
        "client_name": "TootCloud",
        "redirect_uris": app.config["SITE_URL"] + "/callback",
        "scopes": "read:accounts read:statuses write:media write:statuses",
        "website": app.config["SITE_URL"],
    }
    resp = requests.post(
        "https://{host}/api/v1/apps".format(host=host),
        data=data,
        headers={"User-Agent": "TootCloud"},
    )
    resp.raise_for_status()
    return resp.json()


def get_token(host, client_id, client_secret, code):
    data = {
        "grant_type": "authorization_code",
        "redirect_uri": app.config["SITE_URL"] + "/callback",
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
    }
    resp = requests.post(
        "https://{host}/oauth/token".format(host=host),
        data=data,
        headers={"User-Agent": "TootCloud"},
    )
    resp.raise_for_status()
    return resp.json()


def checkStatus():
    mstdn = make_mastodon_client(session)
    account = mstdn.account_verify_credentials()
    id = account["id"]
    acct = account["acct"]
    scnt = account["statuses_count"]
    return (id, scnt, acct)


def checkStatus_with_creds(session_data):
    """セッション情報をパラメータで受け取る版（スレッド内用）"""
    mstdn = make_mastodon_client(session_data)
    account = mstdn.account_verify_credentials()
    id = account["id"]
    acct = account["acct"]
    scnt = account["statuses_count"]
    return (id, scnt, acct)


def reform(text):
    text = re.sub(r":\w+:", "", text)
    text = re.sub(r"</?p>", "", text)
    text = re.sub(r'<a href=".*".*>(.*)</a>', "", text)
    text = re.sub(r"</?span.*>", "", text)
    text = re.sub(r"</?div.*>", "", text)
    text = re.sub(r"<br\s?/?>", "\n", text)
    text = unescape(text, {"&apos;": "'", "&quot;": '"'})
    return text


def collect_words(toots, exl):
    words = []
    clean = strip_emoji(toots)
    for chunk in m.parse(clean).splitlines()[:-1]:
        surface, feature = chunk.split("\t")
        parts = feature.split(",")
        hinshi = parts[0]
        if hinshi not in target_hinshi:
            continue
        if parts[1] in exl:
            continue
        if hinshi == "名詞":
            if surface not in exl:
                words.append(surface)
        else:
            if parts[6] not in exl:
                words.append(parts[6])
    return "\n".join(words)


def collect_words_and_emoji(toots, exl):
    """MeCabで単語を抽出し、絵文字の頻度も別途集計して返す。

    Parameters
    ----------
    toots : str
        投稿テキストの連結文字列（HTMLデコード済み）。
    exl : list
        除外語リスト。

    Returns
    -------
    tuple[str, dict]
        (改行区切りの単語列, {絵文字: 出現回数} の辞書)
    """
    emoji_freqs = extract_emoji_frequencies(toots)
    word_text = collect_words(toots, exl)
    return word_text, emoji_freqs


def getToots(id, lim, max, vis=["public"], mstdn=None):
    text = ""
    if mstdn is None:
        mstdn = make_mastodon_client(session)
    ltl = mstdn.account_statuses(id, limit=lim, max_id=max)
    for row in ltl:
        if row["reblog"] == None:
            if row["visibility"] in vis:
                text += reform(row["content"]) + "\n"
        toot_id = row["id"]
    return (text, toot_id)


def getToots_with_creds(id, lim, max, session_data, vis=["public"], mstdn=None):
    """セッション情報をパラメータで受け取る版（スレッド内用）"""
    text = ""
    if mstdn is None:
        mstdn = make_mastodon_client(session_data)
    ltl = mstdn.account_statuses(id, limit=lim, max_id=max)
    for row in ltl:
        if row["reblog"] == None:
            if row["visibility"] in vis:
                text += reform(row["content"]) + "\n"
        toot_id = row["id"]
    return (text, toot_id)


def create_at(time):
    id = int(time) * 1000 + randint(1000)
    id = id << 16
    id += randint(2**16)
    return id


def _generate_wordcloud_image(word_text, emoji_freqs, output_path):
    """ワードクラウド画像を生成してファイルに保存する。

    カラー絵文字モードが有効な場合、絵文字をプレースホルダとしてレイアウトに
    混入させ、Twemoji SVG を合成して PNG に保存する。

    Parameters
    ----------
    word_text : str
        改行区切りの単語列（MeCab 出力）。
    emoji_freqs : dict
        {絵文字: 出現回数} の辞書。空でも可。
    output_path : str
        保存先 PNG ファイルパス。
    """
    word_list = [w for w in word_text.split("\n") if w.strip()]
    word_freqs = dict(Counter(word_list))

    background_color = "white"
    placeholder_to_emoji = {}

    if _USE_COLOR_EMOJI and emoji_freqs:
        placeholder_to_emoji, placeholder_freqs = build_placeholder_map(
            emoji_freqs,
            max_count=_EMOJI_MAX_COUNT,
        )
        combined_freqs = {**word_freqs, **placeholder_freqs}
    else:
        combined_freqs = word_freqs

    wc_obj = WordCloud(
        background_color=background_color,
        font_path="./Kazesawa-Regular.ttf",
        width=1024,
        height=768,
        collocations=False,
        stopwords="",
    ).generate_from_frequencies(combined_freqs)

    if _USE_COLOR_EMOJI and placeholder_to_emoji:
        # プレースホルダを背景色で描画して不可視にする
        wc_obj.layout_ = [
            (
                (word, count),
                font_size,
                position,
                orientation,
                background_color if is_placeholder(word) else color,
            )
            for (word, count), font_size, position, orientation, color
            in wc_obj.layout_
        ]

        img = wc_obj.to_image()
        img = composite_emoji(
            img,
            wc_obj.layout_,
            placeholder_to_emoji,
            assets_path=_TWEMOJI_ASSETS_PATH,
            font_size_scale=_EMOJI_FONT_SIZE_SCALE,
            wc_scale=getattr(wc_obj, "scale", 1.0),
            font_path=wc_obj.font_path,
        )
        img.save(output_path)
    else:
        wc_obj.to_file(output_path)


def wc(ttl, vis, exl):
    t = ttl
    check = checkStatus()
    if check[1] < t:
        t = check[1]
    id = check[0]
    mstdn = make_mastodon_client(session)
    toots = ""
    max = None
    while t > 0:
        batch_size = 40 if t > 40 else t
        data = getToots(id, batch_size, max, vis, mstdn)
        t -= batch_size
        toots += data[0]
        max = int(data[1]) - 1
    kekka, emoji_freqs = collect_words_and_emoji(toots, exl)
    if kekka == "" and not emoji_freqs:
        return None
    else:
        fn = str(create_at(int(datetime.now().timestamp())))
        _generate_wordcloud_image(kekka, emoji_freqs, "./static/out/" + fn + ".png")
        return fn


def wc_with_creds(task_id, ttl, vis, exl, session_data):
    """セッション情報をパラメータで受け取る版（スレッド内用）"""
    check = session_data["account"]
    total_count = min(ttl, check[1])
    update_task(
        task_id,
        total_count=total_count,
        fetched_count=0,
        progress=0,
        message=f"トゥート取得中 0/{total_count}",
    )
    t = total_count
    id = check[0]
    mstdn = make_mastodon_client(session_data)
    toots = ""
    max = None
    fetched_count = 0
    while t > 0:
        batch_size = 40 if t > 40 else t
        data = getToots_with_creds(id, batch_size, max, session_data, vis, mstdn)
        t -= batch_size
        toots += data[0]
        max = int(data[1]) - 1
        fetched_count += batch_size
        progress = int((fetched_count / total_count) * 99) if total_count > 0 else 99
        update_task(
            task_id,
            fetched_count=fetched_count,
            total_count=total_count,
            progress=progress,
            message=f"トゥート取得中 {fetched_count}/{total_count}",
        )

    update_task(
        task_id,
        fetched_count=fetched_count,
        total_count=total_count,
        progress=99,
        message=f"形態素解析中（取得済み {fetched_count}/{total_count}）",
    )
    kekka, emoji_freqs = collect_words_and_emoji(toots, exl)
    if kekka == "" and not emoji_freqs:
        return None
    else:
        update_task(
            task_id,
            fetched_count=fetched_count,
            total_count=total_count,
            progress=99,
            message=f"画像生成中（取得済み {fetched_count}/{total_count}）",
        )
        fn = str(create_at(int(datetime.now().timestamp())))
        _generate_wordcloud_image(kekka, emoji_freqs, "./static/out/" + fn + ".png")
        return fn


def wc_background(task_id, ttl, vis, exl, session_data):
    """バックグラウンドでワードクラウドを生成"""
    try:
        update_task(
            task_id,
            status="processing",
            progress=0,
            message="準備中",
            fetched_count=0,
            total_count=0,
        )

        # ワードクラウド生成
        filename = wc_with_creds(task_id, ttl, vis, exl, session_data)

        if filename is None:
            update_task(
                task_id,
                status="error",
                progress=100,
                message="生成できる本文がありません",
                error="notext",
            )
        else:
            update_task(
                task_id,
                status="completed",
                progress=100,
                message="完了",
                filename=filename,
            )
    except Exception as e:
        update_task(
            task_id, status="error", progress=100, message="エラー", error=str(e)
        )
        print(f"Task {task_id} error: {e}")
        import traceback

        traceback.print_exc()


@app.route("/")
def index():
    return render_template("index.html", site_url=app.config["SITE_URL"])


@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("access_token") is not None:
        return redirect(url_for("setting"))
    else:
        try:
            instance = request.form["instance"]
        except:
            instance = ""
        if instance != "":
            instance = re.sub(r"https?://", "", instance)
            instance = re.sub(r"/$", "", instance)
            instance = instance.encode("idna").decode("utf-8")
            try:
                gotjson = json.loads(
                    requests.get(
                        "https://" + instance + "/api/v1/instance",
                        headers={"User-Agent": "TootCloud"},
                    ).text
                )
                if gotjson["uri"] == instance:
                    client_data = db.search(qwy.uri == instance)
                    if len(client_data) == 0:
                        rspns = register_app(instance)
                        db.insert(
                            {
                                "uri": instance,
                                "id": rspns["id"],
                                "client_id": rspns["client_id"],
                                "client_secret": rspns["client_secret"],
                            }
                        )
                        client_data = db.search(qwy.uri == instance)
                    client_data = client_data[0]
                    session["uri"] = instance
                    session["client_id"] = client_data["client_id"]
                    session["client_secret"] = client_data["client_secret"]
                    return render_template(
                        "login2.html", status="back", site_url=app.config["SITE_URL"]
                    )
                else:
                    return render_template(
                        "login.html",
                        status="back",
                        login="false",
                        site_url=app.config["SITE_URL"],
                    )
            except:
                return render_template(
                    "login.html",
                    status="back",
                    login="false",
                    site_url=app.config["SITE_URL"],
                )
        else:
            return render_template(
                "login.html", status="back", site_url=app.config["SITE_URL"]
            )


@app.route("/callback")
def callback():
    code = request.args.get("code")
    tkn = get_token(
        session["uri"], session["client_id"], session["client_secret"], code
    )
    session["access_token"] = tkn["access_token"]
    return redirect(url_for("setting"))


@app.route("/setting")
def setting():
    if session.get("access_token") is None:
        return redirect(url_for("login"))
    else:
        session["acct"] = checkStatus()[2]
        return render_template(
            "setting.html", status="logout", site_url=app.config["SITE_URL"]
        )


@app.route("/result", methods=["POST"])
def result():
    if session.get("access_token") is None:
        return redirect(url_for("login"))
    else:
        if request.method == "POST":
            num = int(request.form["TootsNum"])
            vis = request.form.getlist("visibility")
            ex_opt = len(request.form.getlist("defaultlist"))
            if ex_opt == 1:
                exl = swl
            else:
                exl = []
            ex = request.form["exlist"]
            exl.extend(re.split(r"\W+", ex))

            # タスクID生成
            task_id = str(create_at(int(datetime.now().timestamp())))

            # タスク情報登録
            with tasks_lock:
                tasks[task_id] = {
                    "status": "queued",
                    "created_at": datetime.now(),
                    "filename": None,
                    "error": None,
                    "progress": 0,
                    "message": "待機中",
                    "fetched_count": 0,
                    "total_count": 0,
                }

            # セッション情報を保存
            session_data = {
                "client_id": session["client_id"],
                "client_secret": session["client_secret"],
                "access_token": session["access_token"],
                "uri": session["uri"],
                "account": checkStatus(),
            }

            # バックグラウンドスレッド開始
            thread = threading.Thread(
                target=wc_background, args=(task_id, num, vis, exl, session_data)
            )
            thread.daemon = True
            thread.start()

            # 待機ページを返す
            return render_template(
                "waiting.html",
                task_id=task_id,
                status="logout",
                site_url=app.config["SITE_URL"],
            )
        else:
            return redirect(url_for("setting"))


@app.route("/check-status/<task_id>")
def check_status(task_id):
    """タスクの進行状況を確認"""
    with tasks_lock:
        if task_id not in tasks:
            return jsonify({"status": "not_found"}), 404

        task = tasks[task_id]
        response = {
            "status": task["status"],
            "created_at": task["created_at"].isoformat(),
        }
        response["progress"] = task.get("progress", 0)
        response["message"] = task.get("message", "")
        response["fetched_count"] = task.get("fetched_count", 0)
        response["total_count"] = task.get("total_count", 0)

        if task["status"] == "completed":
            response["filename"] = str(task["filename"])
        elif task["status"] == "error":
            response["error"] = task["error"]

        return jsonify(response)


@app.route("/result-view")
def result_view():
    """タスク完了後の結果表示ページ"""
    if session.get("access_token") is None:
        return redirect(url_for("login"))

    filename = request.args.get("filename")
    if not filename:
        return redirect(url_for("setting"))

    return render_template(
        "result.html",
        status="logout",
        filename=filename,
        site_url=app.config["SITE_URL"],
    )


@app.route("/toot", methods=["POST"])
def toot():
    img = request.args.get("img")
    text = request.form["maintext"]
    vsbl = request.form["visibility"]
    cw = bool(request.form.getlist("sensitive"))
    mstdn = Mastodon(
        client_id=session["client_id"],
        client_secret=session["client_secret"],
        access_token=session["access_token"],
        api_base_url=session["uri"],
    )
    media_path = "./static/out/" + img + ".png"
    image = mstdn.media_post(media_path)
    media_files = [image]
    status = mstdn.status_post(
        status=text, media_ids=media_files, visibility=vsbl, sensitive=cw
    )
    url = status["url"]
    return render_template(
        "toot.html", toot_url=url, status="logout", site_url=app.config["SITE_URL"]
    )


@app.route("/logout")
def logout():
    session.pop("uri", None)
    session.pop("client_id", None)
    session.pop("client_secret", None)
    session.pop("access_token", None)
    return redirect(url_for("index"))


if __name__ == "__main__":
    app.run()
