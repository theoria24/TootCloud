# TootCloud

あなたのトゥートからワードクラウドを作成。

## 使い方
1. `git clone https://github.com/theoria24/TootCloud.git`
1. `cd TootCloud`
1. `pip install -r requirements.txt`
1. `config.py.sample`を元に`config.py`を作成
1. `python main.py`

## 必要なもの
### [Python3](https://www.python.org/)
### [MeCab](http://taku910.github.io/mecab/)
日本語を分けるのに必要

## あると便利なもの
### [mecab-ipadic-NEologd](https://github.com/neologd/mecab-ipadic-neologd)
固有名詞がいっぱい入っているので便利

## 含まれているもの
### [Kazesawaフォント](https://kazesawa.github.io/)
[SIL Open Font License](http://scripts.sil.org/OFL)で提供されるフォント。きれい。

### [Milligram](https://milligram.github.io)
[MIT License](https://opensource.org/licenses/mit-license.php)で提供されるCSSフレームワーク。軽い。

## requirements.txtで入るもの
* [Mastodon.py](https://github.com/halcy/Mastodon.py) 2.x
* [mecab-python3](https://github.com/SamuraiT/mecab-python3) 1.x
* [word_cloud](https://github.com/amueller/word_cloud) 1.9.x
* [TinyDB](https://github.com/msiemens/tinydb) 4.x
* [Flask](https://flask.palletsprojects.com/) 3.x
* [Matplotlib](https://matplotlib.org/) 3.10.x

## やりたい
* 画像生成でタイムアウトになりがちなのでAjaxとかでなんとかする

## 何かあったら
issueや[@theoria@wug.fun](https://wug.fun/@theoria)にお願いします。プルリクもお待ちしております。

## ライセンス
MIT License

## その他
このプロジェクトは[theoria24/MstdnWordCloud](https://github.com/theoria24/MstdnWordCloud/)をウェブアプリケーションとして発展させたものです。
