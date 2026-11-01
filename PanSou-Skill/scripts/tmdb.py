#!/usr/bin/env python3
"""
TMDB 影视资料查询（官方 v3 API）

用法:
  python3 tmdb.py 尸变                  # 中文名 / 原名 / 英文名都能搜
  python3 tmdb.py "The Weight" 2026     # 第二个参数可限定年份
  python3 tmdb.py 监狱雄心 --json       # 机器可读
  python3 tmdb.py --id 1290418          # 已知 TMDB id 时直取

输出: 中文名 / 原名 / 年份 / 类型 / 片长 / 导演 / 编剧 / 主演(角色) / 简介

API key 读取顺序:
  1. 环境变量 TMDB_API_KEY
  2. <skill>/.secrets/tmdb_api_key（本 skill 目录内，600 权限，已 gitignore）
  3. ~/.config/tmdb/api_key（旧位置，兼容保留）
"""
import json
import os
import subprocess
import sys
import urllib.parse

API = "https://api.themoviedb.org/3"
# 路径从脚本位置反推，整个 skill 目录可移动
SKILL_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEY_FILES = [
    os.path.join(SKILL_ROOT, ".secrets", "tmdb_api_key"),
    os.path.expanduser("~/.config/tmdb/api_key"),
]


def api_key():
    k = os.environ.get("TMDB_API_KEY", "").strip()
    if k:
        return k
    for path in KEY_FILES:
        try:
            with open(path) as f:
                v = f.read().strip()
            if v:
                return v
        except OSError:
            continue
    return ""


def call(path, **params):
    key = api_key()
    if not key:
        sys.exit("没有 TMDB API key。设置环境变量 TMDB_API_KEY，"
                 "或写入 %s" % KEY_FILES[0])
    params.setdefault("api_key", key)
    params.setdefault("language", "zh-CN")
    url = "%s%s?%s" % (API, path, urllib.parse.urlencode(params))
    # 走 curl：稳定、不受 python 证书/代理差异影响
    r = subprocess.run(["curl", "-sS", "--max-time", "30", url], capture_output=True)
    if r.returncode != 0:
        sys.exit("请求失败：%s" % r.stderr.decode("utf8", "ignore")[:200])
    try:
        d = json.loads(r.stdout.decode("utf8", "ignore"))
    except json.JSONDecodeError:
        sys.exit("返回不是 JSON，检查网络或 key")
    if isinstance(d, dict) and d.get("status_code"):
        sys.exit("TMDB 报错 %s：%s" % (d["status_code"], d.get("status_message")))
    return d


def search(query, year=None):
    params = {"query": query, "include_adult": "false"}
    if year:
        params["year"] = str(year)
    d = call("/search/movie", **params)
    return d.get("results") or []


def detail(mid):
    d = call("/movie/%s" % mid, append_to_response="credits")
    crew = (d.get("credits") or {}).get("crew") or []
    cast = (d.get("credits") or {}).get("cast") or []
    return {
        "id": d.get("id"),
        "title_zh": d.get("title") or "",
        "title_orig": d.get("original_title") or "",
        "year": (d.get("release_date") or "")[:4],
        "genres": [g.get("name") for g in (d.get("genres") or [])],
        "runtime": d.get("runtime") or 0,
        "directors": [c.get("name") for c in crew if c.get("job") == "Director"],
        "writers": list(dict.fromkeys(
            c.get("name") for c in crew
            if c.get("job") in ("Writer", "Screenplay", "Story"))),
        "cast": [(c.get("name"), c.get("character") or "") for c in cast[:6]],
        "overview": (d.get("overview") or "").strip(),
        "rating": d.get("vote_average") or 0,
        "votes": d.get("vote_count") or 0,
    }


def render(d):
    out = ["中文名: %s" % (d["title_zh"] or "?")]
    if d["title_orig"] and d["title_orig"] != d["title_zh"]:
        out.append("原名:   %s" % d["title_orig"])
    if d["year"]:
        out.append("年份:   %s" % d["year"])
    if d["genres"]:
        out.append("类型:   %s" % " / ".join(d["genres"]))
    if d["runtime"]:
        out.append("片长:   %d h %d m" % (d["runtime"] // 60, d["runtime"] % 60))
    if d["directors"]:
        out.append("导演:   %s" % "、".join(d["directors"]))
    if d["writers"]:
        out.append("编剧:   %s" % "、".join(d["writers"]))
    if d["cast"]:
        out.append("主演:   %s" % "、".join(
            "%s(%s)" % (a, b) if b else a for a, b in d["cast"]))
    if d["votes"]:
        out.append("评分:   %.1f（%d 票）" % (d["rating"], d["votes"]))
    if d["overview"]:
        out.append("简介:   %s" % d["overview"])
    return "\n".join(out)


def main():
    args = sys.argv[1:]
    as_json = "--json" in args
    args = [a for a in args if not a.startswith("--")]

    if not args:
        print(__doc__)
        return

    mid = None
    if "--id" in sys.argv:
        mid = args[0]
    else:
        year = next((a for a in args[1:] if len(a) == 4 and a.isdigit()), None)
        results = search(args[0], year)
        if not results:
            print("TMDB 没搜到「%s」" % args[0])
            return
        mid = results[0]["id"]
        others = results[1:6]

    d = detail(mid)
    if as_json:
        d["other_matches"] = [] if "--id" in sys.argv else [
            {"id": o["id"], "title": o.get("title"),
             "original_title": o.get("original_title"),
             "year": (o.get("release_date") or "")[:4]} for o in others]
        print(json.dumps(d, ensure_ascii=False, indent=2))
        return

    print(render(d))
    if "--id" not in sys.argv and others:
        print("\n(还有 %d 个同名结果: %s)" % (
            len(others),
            ", ".join("%s/%s(id=%s)" % (o.get("title"), (o.get("release_date") or "")[:4], o["id"])
                      for o in others)))


if __name__ == "__main__":
    main()
