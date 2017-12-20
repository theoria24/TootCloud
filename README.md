# TootCloud

あなたのトゥートからワードクラウドを作成。

## 必要なもの
たぶんこのあたりが入っていれば動きます。
#### [Python3](https://www.python.org/)
#### [Mastodon.py](https://github.com/halcy/Mastodon.py)
MastodonのAPIを叩くやつ  
`pip install Mastodon.py`

#### [MeCab](http://taku910.github.io/mecab/)
日本語をいい感じに分ける

#### [mecab-python3](https://github.com/SamuraiT/mecab-python3)
MeCabをPythonで扱うのに便利  
`pip install mecab-python3`

#### [word_cloud](https://github.com/amueller/word_cloud)
ワードクラウドを作成  
`pip install wordcloud`

#### [TinyDB](https://github.com/msiemens/tinydb)
インスタンスごとの`client_secret`とかを管理  
`pip install tinydb`

#### [Flask](http://flask.pocoo.org/)
手軽にウェブアプリケーションを作成
`pip install Flask`

## あると便利なもの
#### [mecab-ipadic-NEologd](https://github.com/neologd/mecab-ipadic-neologd)
固有名詞がいっぱい入っているので便利

## 含まれているもの
#### [Kazesawaフォント](https://kazesawa.github.io/)
[SIL Open Font License](http://scripts.sil.org/OFL)で提供されるフォント。きれい。

#### [Milligram](https://milligram.github.io)
[MIT License](https://opensource.org/licenses/mit-license.php)で提供されるCSSフレームワーク。軽い。

## 使い方
1. 上記のパッケージをあらかじめ準備してください。
1. `git clone https://github.com/theoria24/TootCloud.git`
1. `cd TootCloud`
1. `config.py.sample`を元に`config.py`を作成
1. `python3 main.py`

## やりたい
* 画像生成でタイムアウトになりがちなのでAjaxとかでなんとかする

## 何かあったら
issueや[@theoria@wug.fun](https://wug.fun/@theoria)にお願いします。プルリクもお待ちしております。

## ライセンス
MIT License

## その他
このプロジェクトは[theoria24/MstdnWordCloud](https://github.com/theoria24/MstdnWordCloud/)をウェブアプリケーションとして発展させたものです。
