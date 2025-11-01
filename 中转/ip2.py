#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
中转/ip.py
_从 https://raw.githubusercontent.com/tianshipapa/cfipcaiji/refs/heads/main/ip.txt 拉取 IP，
通过 GeoIP 判断国家，再筛选 COUNTRIES 并去重，
并发检测 IP 可达性（先 ping，ping 失败则尝试 TCP 80/443），按每国上限保存结果。
输出文件：与脚本同目录下的 cm中转ip.txt（脚本不会自动创建目录）。
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
import re
import sys
import subprocess
import platform
import socket
from pathlib import Path
from typing import Optional, Dict, List, Tuple

import geoip2.database

URL = "https://raw.githubusercontent.com/tianshipapa/cfipcaiji/refs/heads/main/ip.txt"
BASE_DIR = Path(__file__).parent
OUT_FILE = BASE_DIR / "ip.txt"
GEOIP_DB_PATH = BASE_DIR / "GeoLite2-Country.mmdb"

# 要支持的国家标签（小写 ISO2 code）
COUNTRIES = ["sg", "hk", "jp", "tw", "kr", "us"]

# 每个国家最多保存多少条
MAX_PER_COUNTRY: Dict[str, int] = {
    "sg": 30,
    "hk": 20,
    "jp": 20,
    "tw": 10,
    "kr": 10,
    "us": 20,
}

# IPv4 匹配
RE_IPV4 = re.compile(r'(\d{1,3}(?:\.\d{1,3}){3})(?:/\d{1,2})?')

# 超时设置
PING_TIMEOUT = 2.0
TCP_TIMEOUT = 1.0

MAX_WORKERS = 8

# 打开 GeoIP 数据库
reader = geoip2.database.Reader(GEOIP_DB_PATH)


def fetch_text() -> str:
    """获取文本数据"""
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
    except Exception as e_requests:
        from urllib import request
        req = request.Request(URL, headers={
            "User-Agent": "Mozilla/5.0 (compatible; GithubAction/1.0)",
            "Accept": "*/*",
            "Connection": "close",
        })
        with request.urlopen(req, timeout=30) as resp:
            data = resp.read()
            return data.decode("utf-8", errors="replace")


def extract_ipv4(line: str) -> Optional[str]:
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


def ping_host(ip: str, timeout: float = PING_TIMEOUT) -> bool:
    system = platform.system().lower()
    try:
        if system == "windows":
            cmd = ["ping", "-n", "1", "-w", str(int(timeout * 1000)), ip]
        else:
            cmd = ["ping", "-c", "1", ip]
        res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout + 0.5)
        return res.returncode == 0
    except Exception:
        return False


def tcp_connect(ip: str, ports=(80, 443), timeout: float = TCP_TIMEOUT) -> bool:
    for port in ports:
        try:
            with socket.create_connection((ip, port), timeout=timeout):
                return True
        except Exception:
            continue
    return False


def is_reachable(ip: str) -> bool:
    if ping_host(ip, timeout=PING_TIMEOUT):
        return True
    return tcp_connect(ip, ports=(80, 443), timeout=TCP_TIMEOUT)


def primary_tag_of_line(line: str) -> Optional[str]:
    """
    使用 GeoIP 判断国家，匹配 COUNTRIES
    """
    ip = extract_ipv4(line)
    if not ip:
        return None
    try:
        response = reader.country(ip)
        country_code = response.country.iso_code.lower()
    except Exception:
        return None

    if country_code in COUNTRIES:
        return country_code
    return None


def collect_candidates(text: str) -> List[Tuple[int, str, str, str]]:
    seen = set()
    candidates: List[Tuple[int, str, str, str]] = []
    for idx, raw in enumerate(text.splitlines()):
        line = raw.strip()
        if not line:
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
        candidates.append((idx, line, tag, ip))
    return candidates


def run_concurrent_tests(candidates: List[Tuple[int, str, str, str]]) -> Tuple[Dict[str, List[Tuple[int, str]]], int]:
    saved: Dict[str, List[Tuple[int, str]]] = {c: [] for c in COUNTRIES}
    tested = 0
    if not candidates:
        return saved, 0

    futures = {}
    workers = min(MAX_WORKERS, max(1, len(candidates)))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for cand in candidates:
            idx, line, tag, ip = cand
            fut = ex.submit(is_reachable, ip)
            futures[fut] = cand

        for fut in as_completed(list(futures.keys())):
            cand = futures.get(fut)
            if cand is None:
                continue
            idx, line, tag, ip = cand
            tested += 1
            try:
                ok = fut.result()
            except Exception:
                ok = False
            if ok and len(saved[tag]) < MAX_PER_COUNTRY.get(tag, 0):
                saved[tag].append((idx, line))
            if all(len(saved[c]) >= MAX_PER_COUNTRY.get(c, 0) for c in COUNTRIES):
                for other_fut in list(futures.keys()):
                    if not other_fut.done():
                        try:
                            other_fut.cancel()
                        except Exception:
                            pass
                break

    for c in COUNTRIES:
        saved[c].sort(key=lambda t: t[0])
    return saved, tested


def write_output(saved: Dict[str, List[Tuple[int, str]]], out_path: Path = OUT_FILE) -> None:
    if not out_path.parent.exists():
        print(f"输出目录 {out_path.parent} 不存在，请先创建目录。")
        sys.exit(2)

    lines: List[str] = []
    for c in COUNTRIES:
        lines.extend([ln for (_, ln) in saved.get(c, [])])

    with out_path.open("w", encoding="utf-8", newline="\n") as f:
        for ln in lines:
            f.write(ln + "\n")


def main():
    try:
        text = fetch_text()
    except Exception as e:
        print("Fetch failed:", e)
        sys.exit(1)

    candidates = collect_candidates(text)
    if not candidates:
        print("No candidates found for tags.")
        sys.exit(0)

    saved, tested = run_concurrent_tests(candidates)
    total_saved = sum(len(v) for v in saved.values())

    if total_saved == 0:
        print(f"No reachable lines found (tested {tested} candidates).")
    else:
        write_output(saved, OUT_FILE)
        print(f"Saved {total_saved} lines to {OUT_FILE} (tested {tested} candidates).")
        for c in COUNTRIES:
            print(f"  {c.upper()}: saved {len(saved.get(c, []))}/{MAX_PER_COUNTRY.get(c)}")

    sys.exit(0)


if __name__ == "__main__":
    main()