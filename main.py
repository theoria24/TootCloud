from flask import Flask, render_template, request, redirect, url_for, session
from tinydb import TinyDB, Query
from mastodon import Mastodon
from wordcloud import WordCloud
from datetime import datetime
from numpy.random import *
import re
import json
import requests
import MeCab


app = Flask(__name__)
app.config.from_object('config')
db = TinyDB('db.json')
qwy = Query()


def register_app(host):
    data = {
        'client_name': 'TootCloud',
        'redirect_uris': app.config['SITE_URL'] + '/callback',
        'scopes': 'read write',
        'website': app.config['SITE_URL']
    }
    resp = requests.post("https://{host}/api/v1/apps".format(host=host), data=data)
    resp.raise_for_status()
    return resp.json()


def get_token(host, client_id, client_secret, code):
    data = {
        'grant_type': 'authorization_code',
        'redirect_uri': app.config['SITE_URL'] + '/callback',
        'client_id': client_id,
        'client_secret': client_secret,
        'code': code
    }
    resp = requests.post("https://{host}/oauth/token".format(host=host), data=data)
    resp.raise_for_status()
    return resp.json()


def checkStatus():
    mstdn = Mastodon(
        client_id = session['client_id'],
        client_secret = session['client_secret'],
        access_token = session['access_token'],
        api_base_url = session['uri'])
    id = mstdn.account_verify_credentials()["id"]
    scnt = mstdn.account_verify_credentials()["statuses_count"]
    return(id, scnt)


def reform(text):
    text = re.sub(":\w+:", "", text)
    text = re.sub("</?p>", "", text)
    text = re.sub("<a href=\".*\".*>(.*)</a>", "", text)
    text = re.sub("</?span.*>", "", text)
    text = re.sub("</?div.*>", "", text)
    text = re.sub("<br\s?/?>", '\n', text)
    return(text)


def getToots(id, lim, max, vis=["public"]):
    text = ""
    mstdn = Mastodon(
        client_id = session['client_id'],
        client_secret = session['client_secret'],
        access_token = session['access_token'],
        api_base_url = session['uri'])
    ltl = mstdn.account_statuses(id, limit=lim, max_id=max)
    for row in ltl:
        if row["reblog"] == None:
            if row["visibility"] in vis:
                text += reform(row["content"]) + "\n"
        toot_id = row["id"]
    return(text, toot_id)


def create_at(time):
    id  = int(time) * 1000 + randint(1000)
    id  = id << 16
    id += randint(2**16)
    return(id)


def wc(ttl, vis, exl):
    t = ttl
    check = checkStatus()
    print(check)
    if check[1] < t:
        t = check[1]
    id = check[0]
    toots = ""
    max = None
    while t > 0:
        print(t, max)
        if t > 40:
            data = getToots(id, 40, max, vis)
        else:
            data = getToots(id, t, max, vis)
        t -= 40
        # print(data[0])
        toots += data[0]
        max = int(data[1]) - 1
    kekka = ""
    m = MeCab.Tagger()
    m.parse("")
    node = m.parseToNode(toots)
    target_hinshi = ['名詞', '形容詞', '形容動詞']
    exclude = ['非自立', '接尾']
    while node:
        if node.feature.split(',')[0] in target_hinshi:
            if node.feature.split(',')[1] not in exclude:
                if node.feature.split(',')[0] == '名詞':
                    # print(node.surface)
                    if node.surface not in exl:
                        kekka += node.surface + "\n"
                else:
                    if node.feature.split(',')[6] not in exl:
                        kekka += node.feature.split(',')[6] + "\n"
        node = node.next
    wordcloud = WordCloud(background_color="white", font_path="./Kazesawa-Regular.ttf", width=1024, height=768, stopwords="").generate(kekka)
    fn = create_at(datetime.now().strftime("%s"))
    wordcloud.to_file("./static/out/"+str(fn)+".png")
    return(fn)


@app.route('/')
def index():
    return render_template('index.html', site_url=app.config['SITE_URL'])


@app.route('/login', methods=['GET', 'POST'])
def login():
    if session.get('access_token') is not None:
        return redirect(url_for('setting'))
    else:
        try:
            instance = request.form['instance']
        except:
            instance = ""
        if instance != "":
            instance = re.sub(r'https?://', "", instance)
            instance = re.sub(r'/$', "", instance)
            instance = instance.encode('idna').decode('utf-8')
            try:
                gotjson = json.loads(requests.get("https://"+instance+"/api/v1/instance").text)
                if gotjson['uri'] == instance:
                    client_data = db.search(qwy.uri == instance)
                    if len(client_data) == 0:
                        rspns = register_app(instance)
                        db.insert({'uri': instance, 'id': rspns['id'], 'client_id': rspns['client_id'], 'client_secret': rspns['client_secret']})
                        client_data = db.search(qwy.uri == instance)
                    client_data = client_data[0]
                    session['uri'] = instance
                    session['client_id'] = client_data['client_id']
                    session['client_secret'] = client_data['client_secret']
                    return render_template('login2.html', status="back", site_url=app.config['SITE_URL'])
                else:
                    return render_template('login.html', status="back", login="false", site_url=app.config['SITE_URL'])
            except:
                return render_template('login.html', status="back", login="false", site_url=app.config['SITE_URL'])
        else:
            return render_template('login.html', status="back", site_url=app.config['SITE_URL'])


@app.route('/callback')
def callback():
    code = request.args.get('code')
    tkn = get_token(session['uri'], session['client_id'], session['client_secret'], code)
    session['access_token'] = tkn['access_token']
    return redirect(url_for('setting'))


@app.route('/setting')
def setting():
    if session.get('access_token') is None:
        return redirect(url_for('login'))
    else:
        return render_template('setting.html', status="logout", site_url=app.config['SITE_URL'])


@app.route('/result', methods=['POST'])
def result():
    if session.get('access_token') is None:
        return redirect(url_for('login'))
    else:
        if request.method == 'POST':
            num = int(request.form["TootsNum"])
            vis = request.form.getlist("visibility")
            ex = request.form["ExcludeWord"]
            exl = re.split('\W+', ex)
            filename = wc(num, vis, exl)
            return render_template('result.html', status="logout", filename=filename, site_url=app.config['SITE_URL'])
        else:
            return redirect(url_for('setting'))


@app.route('/toot', methods=['POST'])
def toot():
    img = request.args.get('img')
    text = request.form['maintext']
    vsbl = request.form['visibility']
    mstdn = Mastodon(
        client_id = session['client_id'],
        client_secret = session['client_secret'],
        access_token = session['access_token'],
        api_base_url = session['uri'])
    path = "./static/out/" + img + ".png"
    media_files = [mstdn.media_post(media, "image/png") for media in [path]]
    text += " " + media_files[0]['text_url']
    status = mstdn.status_post(status=text, media_ids=media_files, visibility=vsbl)
    url = status['url']
    return render_template('toot.html', toot_url=url, status="logout", site_url=app.config['SITE_URL'])


@app.route('/logout')
def logout():
    session.pop('uri', None)
    session.pop('client_id', None)
    session.pop('client_secret', None)
    session.pop('access_token', None)
    return redirect(url_for('index'))


if __name__ == '__main__':
    app.run()
