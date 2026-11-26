# -*- coding: utf-8 -*-
"""
複数の難易度表を取得して、beatoraja の folder/default.json に
カスタムフォルダ（表 → レベル）として追加する。

  python update_tables.py <URL一覧.txt> <元のdefault.json> <出力先default.json>

- 元の default.json の既存フォルダはそのまま残し、ROOT_NAME のフォルダだけを作り直す。
- 取得に失敗した表は cache フォルダの前回分を使う。
- 標準ライブラリだけで動く（Python 3.8 以降）。
"""
import json, os, re, sys, hashlib, urllib.request, urllib.parse

ROOT_NAME = "任意のフォルダ名"   # default.json に追加するフォルダ名（再実行時はこの名前のフォルダを置き換える）
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) beatoraja-table-folder"
# 曲の並び（ゲーム内のLAMP順などで同じ値の曲が並ぶときの順番になる）
#   "title" : タイトル順（同じタイトルは難易度順）
#   "table" : 各表に載っている順
ORDER = "title"
# beatoraja は同じ値の曲を SQL が返した順と逆に並べるので、逆順で返して画面上で正順にする。もし"True"で逆順になっていたら"False"に変更する。
REVERSE = True
HEX32 = re.compile(r"^[0-9a-fA-F]{32}$")
HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")


def to_url(s):
    """C:\\...\\header.json のようなローカルパスを file:// のURLに変換する"""
    if re.match(r"^[A-Za-z]:[\\/]", s) or s.startswith("\\\\"):
        from pathlib import PureWindowsPath
        return PureWindowsPath(s).as_uri()
    return s


def fetch(url):
    url = to_url(url)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read(), r.geturl()


def decode_text(raw):
    for enc in ("utf-8-sig", "cp932"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            pass
    return raw.decode("utf-8", "replace")


def load_json(raw):
    return json.loads(decode_text(raw).strip())


def find_header_url(page_url, html):
    # <meta name="bmstable" content="..."> （属性の順番が逆でも拾う）
    for pat in (r'<meta[^>]*name\s*=\s*["\']bmstable["\'][^>]*content\s*=\s*["\']([^"\']+)["\']',
                r'<meta[^>]*content\s*=\s*["\']([^"\']+)["\'][^>]*name\s*=\s*["\']bmstable["\']'):
        m = re.search(pat, html, re.I)
        if m:
            return urllib.parse.urljoin(page_url, m.group(1).strip())
    return None


def get_table(url):
    """URL（表のページ or header.json）から (header, data) を返す"""
    raw, real = fetch(url)
    header = None
    try:
        obj = load_json(raw)
        if isinstance(obj, dict) and "data_url" in obj:
            header, header_url = obj, real
    except ValueError:
        pass
    if header is None:
        found = find_header_url(real, decode_text(raw))
        # meta タグが無いときは「ページと同じ場所 / ページURLの下」の header.json を試す
        candidates = [found] if found else [urllib.parse.urljoin(real, "header.json"),
                                            real.rstrip("/") + "/header.json"]
        for cand in candidates:
            try:
                raw, header_url = fetch(cand)
                header = load_json(raw)
                break
            except Exception:
                header = None
        if not isinstance(header, dict) or "data_url" not in header:
            raise RuntimeError("header.json が見つからない（bmstable の meta タグ無し）")
    data_url = urllib.parse.urljoin(header_url, header["data_url"])
    raw, _ = fetch(data_url)
    data = load_json(raw)
    if not isinstance(data, list):
        raise RuntimeError("data_url の中身が配列ではない")
    return header, data


def cache_path(url):
    return os.path.join(CACHE_DIR, hashlib.md5(url.encode("utf-8")).hexdigest() + ".json")


def level_key(s):
    try:
        return (0, float(s), s)
    except ValueError:
        return (1, 0.0, s)


def build_table_folder(header, data):
    name = str(header.get("name") or "名称不明の表")
    symbol = str(header.get("symbol") or "")
    groups = {}
    for e in data:
        if not isinstance(e, dict):
            continue
        lv = str(e.get("level", "?"))
        g = groups.setdefault(lv, ({}, {}))
        md5 = str(e.get("md5") or "")
        sha = str(e.get("sha256") or "")
        if HEX32.match(md5):
            g[0].setdefault(md5.lower(), len(g[0]) + len(g[1]))
        elif HEX64.match(sha):
            g[1].setdefault(sha.lower(), len(g[0]) + len(g[1]))
    order = [str(x) for x in header.get("level_order") or []]
    levels = [l for l in order if l in groups] + sorted((l for l in groups if l not in order), key=level_key)
    folders, total = [], 0
    for lv in levels:
        md5s, shas = groups[lv]
        cond = []
        if md5s:
            cond.append("md5 IN (" + ",".join(f"'{m}'" for m in sorted(md5s)) + ")")
        if shas:
            cond.append("song.sha256 IN (" + ",".join(f"'{s}'" for s in sorted(shas)) + ")")
        if not cond:
            continue
        total += len(md5s) + len(shas)
        sql = "(" + " OR ".join(cond) + ")"
        if ORDER == "table":
            keys = sorted(list(md5s.items()) + list(shas.items()), key=lambda kv: kv[1])
            seq = "," + ",".join(k for k, _ in keys) + ","
            d = " DESC" if REVERSE else ""
            sql += (f" ORDER BY max(instr('{seq}', ',' || md5 || ','),"
                    f" instr('{seq}', ',' || song.sha256 || ',')){d}")
        else:
            d = " DESC" if REVERSE else ""
            sql += f" ORDER BY song.title COLLATE NOCASE{d}, song.difficulty{d}"
        folders.append({"name": f"{symbol}{lv}", "sql": sql})
    return {"name": name, "folder": folders}, total


def main(list_path, src_path, dst_path):
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(list_path, encoding="utf-8-sig") as f:
        urls = [l.strip() for l in f if l.strip() and not l.strip().startswith("#")]
    # 行頭に @ を付けた表は取得せず cache の前回分だけを使う（cache が無いときだけ1回取得する）

    # 元の default.json（読めなければ何も書かずに中止する）
    if os.path.exists(src_path):
        with open(src_path, "rb") as f:
            base = load_json(f.read())
        if not isinstance(base, list):
            sys.exit("元の default.json が配列ではないので中止しました")
    else:
        base = []

    tables, failed = [], []
    for line in urls:
        fixed = line.startswith("@")
        url = line[1:].strip() if fixed else line
        cp = cache_path(url)
        if fixed and os.path.exists(cp):
            with open(cp, encoding="utf-8") as f:
                c = json.load(f)
            folder, n = build_table_folder(c["header"], c["data"])
            tables.append(folder)
            print(f"[FIX] {folder['name']}  {len(folder['folder'])}レベル / {n}譜面  (cacheを使用)")
            continue
        try:
            header, data = get_table(url)
            with open(cp, "w", encoding="utf-8") as f:
                json.dump({"url": url, "header": header, "data": data}, f, ensure_ascii=False)
            status = "取得"
        except Exception as ex:
            if os.path.exists(cp):
                with open(cp, encoding="utf-8") as f:
                    c = json.load(f)
                header, data = c["header"], c["data"]
                status = f"失敗→前回分を使用 ({ex})"
            else:
                failed.append(url)
                print(f"[NG ] {url}\n      {ex}")
                continue
        folder, n = build_table_folder(header, data)
        tables.append(folder)
        print(f"[{'OK ' if status == '取得' else 'OLD'}] {folder['name']}  {len(folder['folder'])}レベル / {n}譜面  {'' if status == '取得' else status}")

    out = [f for f in base if not (isinstance(f, dict) and f.get("name") == ROOT_NAME)]
    out.append({"name": ROOT_NAME, "folder": tables})
    os.makedirs(os.path.dirname(os.path.abspath(dst_path)), exist_ok=True)
    tmp = dst_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    os.replace(tmp, dst_path)
    print(f"\n{len(tables)}/{len(urls)} 表を書き出しました -> {dst_path}")
    if failed:
        print("取得できなかった表:\n  " + "\n  ".join(failed))


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2], sys.argv[3])
