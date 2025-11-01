#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
中转/ip.py
_从 https://zip.cm.edu.kg/all.txt 拉取数据，筛选包含 #SG/#HK/#JP/#TW/#KR/#US 的行并去重，
按每国上限保存结果。
输出文件：与脚本同目录下的 cm中转ip.txt（脚本不会自动创建目录）。
"""
import re
import sys
from pathlib import Path
from typing import Optional, Dict, List, Tuple

URL = "https://zip.cm.edu.kg/all.txt"
BASE_DIR = Path(__file__).parent
OUT_FILE = BASE_DIR / "cm中转ip.txt"

# 支持的国家标签
COUNTRIES = ["sg", "hk", "jp", "tw", "kr", "us"]

# 每个国家最多保存多少条
MAX_PER_COUNTRY: Dict[str, int] = {
    "sg": 50,
    "hk": 30,
    "jp": 20,
    "tw": 10,
    "kr": 10,
    "us": 30,
}

# 正则匹配标签与 IPv4
PAT_TAG = re.compile(r'#(?:sg|hk|jp|tw|kr|us)\b', re.IGNORECASE)
RE_IPV4 = re.compile(r'(\d{1,3}(?:\.\d{1,3}){3})(?:/\d{1,2})?')


def fetch_text() -> str:
    """优先使用 requests，否则使用 urllib 回退。返回文本（str）。"""
    try:
        import requests
        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; GithubAction/1.0)",
            "Accept": "*/*",
            "Connection": "close",
        }
        r = requests.get(URL, headers=headers, timeout=30)
        r.raise_for_status()
        if not r.encoding:
            r.encoding = r.apparent_encoding or "utf-8"
        return r.text
    except Exception:
        from urllib import request
        req = request.Request(URL, headers={
            "User-Agent": "Mozilla/5.0 (compatible; GithubAction/1.0)",
            "Accept": "*/*",
            "Connection": "close",
        })
        with request.urlopen(req, timeout=30) as resp:
            data = resp.read()
        for enc in ("utf-8", "latin1"):
            try:
                return data.decode(enc)
            except Exception:
                pass
        return data.decode("utf-8", errors="replace")


def extract_ipv4(line: str) -> Optional[str]:
    """从行中提取 IPv4（忽略可能的 /n 后缀）"""
    m = RE_IPV4.search(line)
    if not m:
        return None
    ip = m.group(1)
    parts = ip.split('.')
    for p in parts:
        try:
            if not (0 <= int(p) <= 255):
                return None
        except Exception:
            return None
    return ip


def primary_tag_of_line(line: str) -> Optional[str]:
    """按 COUNTRIES 顺序返回该行的主标签"""
    low = line.lower()
    for c in COUNTRIES:
        if f"#{c}" in low:
            return c
    return None


def collect_candidates(text: str) -> List[Tuple[int, str, str]]:
    """扫描文本并收集候选项，返回列表 (index, line, tag)"""
    seen = set()
    candidates: List[Tuple[int, str, str]] = []
    for idx, raw in enumerate(text.splitlines()):
        line = raw.strip()
        if not line:
            continue
        if not PAT_TAG.search(line):
            continue
        if line in seen:
            continue
        seen.add(line)
        tag = primary_tag_of_line(line)
        if not tag:
            continue
        ip = extract_ipv4(line)
        if not ip:
            continue
        candidates.append((idx, line, tag))
    return candidates


def save_candidates(candidates: List[Tuple[int, str, str]]):
    saved: Dict[str, List[Tuple[int, str]]] = {c: [] for c in COUNTRIES}
    for idx, line, tag in candidates:
        if len(saved[tag]) < MAX_PER_COUNTRY.get(tag, 0):
            saved[tag].append((idx, line))

    if not OUT_FILE.parent.exists():
        print(f"输出目录 {OUT_FILE.parent} 不存在，请先创建目录再运行。")
        sys.exit(2)

    lines: List[str] = []
    for c in COUNTRIES:
        lines.extend([ln for (_, ln) in saved.get(c, [])])

    with OUT_FILE.open("w", encoding="utf-8", newline="\n") as f:
        for ln in lines:
            f.write(ln + "\n")

    print(f"✅ 保存完成，共 {sum(len(v) for v in saved.values())} 条记录到 {OUT_FILE}")


def main():
    text = fetch_text()
    candidates = collect_candidates(text)
    if not candidates:
        print("No candidates found for tags.")
        sys.exit(0)

    save_candidates(candidates)


if __name__ == "__main__":
    main()