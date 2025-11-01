#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
中转/ip_chinaz_siteip.py
_从原始 IP 列表抓取 IP，通过 https://ip.tool.chinaz.com/siteip 批量查询国家，
并发检测 IP 可达性（先 ping，ping 失败则尝试 TCP 80/443），按每国上限保存结果。
输出文件：与脚本同目录下的 cm中转ip.txt（脚本不会自动创建目录）。
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
import re, sys, subprocess, platform, socket, time
from pathlib import Path
from typing import List, Dict, Tuple, Optional
import requests
from bs4 import BeautifulSoup

URL = "https://raw.githubusercontent.com/tianshipapa/cfipcaiji/refs/heads/main/ip.txt"
BASE_DIR = Path(__file__).parent
OUT_FILE = BASE_DIR / "cm中转ip.txt"

# 国家列表
COUNTRIES = ["sg", "hk", "jp", "tw", "kr", "us"]
MAX_PER_COUNTRY: Dict[str,int] = {"sg":30,"hk":20,"jp":20,"tw":10,"kr":10,"us":20}

RE_IPV4 = re.compile(r'(\d{1,3}(?:\.\d{1,3}){3})(?:/\d{1,2})?')
PING_TIMEOUT = 2.0
TCP_TIMEOUT = 1.0
MAX_WORKERS = 8
CHINAZ_SITEIP_URL = "https://ip.tool.chinaz.com/siteip"

# ---------------------- 工具函数 ----------------------

def fetch_text() -> str:
    try:
        r = requests.get(URL, headers={"User-Agent":"Mozilla/5.0"}, timeout=30)
        r.raise_for_status()
        return r.text
    except Exception as e:
        print("Fetch failed:", e)
        sys.exit(1)

def extract_ipv4(line: str) -> Optional[str]:
    m = RE_IPV4.search(line)
    if not m: return None
    ip = m.group(1)
    for p in ip.split("."):
        if not (0 <= int(p) <= 255):
            return None
    return ip

def ping_host(ip: str, timeout: float = PING_TIMEOUT) -> bool:
    system = platform.system().lower()
    try:
        cmd = ["ping","-n","1","-w",str(int(timeout*1000)),ip] if system=="windows" else ["ping","-c","1",ip]
        res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout+0.5)
        return res.returncode==0
    except:
        return False

def tcp_connect(ip: str, ports=(80,443), timeout: float = TCP_TIMEOUT) -> bool:
    for port in ports:
        try:
            with socket.create_connection((ip, port), timeout=timeout):
                return True
        except:
            continue
    return False

def is_reachable(ip: str) -> bool:
    return ping_host(ip) or tcp_connect(ip)

# ---------------------- Chinaz siteip 批量查询 ----------------------

def query_chinaz_siteip(ip_list: List[str], batch_size: int = 100, delay: float = 0.5) -> Dict[str,str]:
    ip_country: Dict[str,str] = {}
    for i in range(0, len(ip_list), batch_size):
        batch = ip_list[i:i+batch_size]
        data = {"ip":"\n".join(batch)}
        headers = {"User-Agent":"Mozilla/5.0", "Content-Type":"application/x-www-form-urlencoded"}
        try:
            r = requests.post(CHINAZ_SITEIP_URL, data=data, headers=headers, timeout=10)
            r.raise_for_status()
        except Exception as e:
            print(f"请求失败: {e}")
            continue
        soup = BeautifulSoup(r.text,"html.parser")
        for tr in soup.select("table tr"):
            tds = tr.find_all("td")
            if len(tds)>=2:
                ip_text = tds[0].get_text(strip=True)
                country_text = tds[1].get_text(strip=True).lower()
                if ip_text in batch:
                    for c in COUNTRIES:
                        if c in country_text:
                            ip_country[ip_text] = c
                            break
        time.sleep(delay)
    return ip_country

# ---------------------- 收集候选 ----------------------

def collect_candidates(text: str) -> List[Tuple[int,str,str,str]]:
    seen, ips, lines_dict = set(), [], {}
    for idx,line in enumerate(text.splitlines()):
        line = line.strip()
        if not line or line in seen: continue
        ip = extract_ipv4(line)
        if not ip: continue
        seen.add(line)
        ips.append(ip)
        lines_dict[ip] = (idx,line)
    ip2country = query_chinaz_siteip(ips)
    candidates = []
    for ip,country in ip2country.items():
        if country not in COUNTRIES: continue
        idx,line = lines_dict[ip]
        candidates.append((idx,line,country,ip))
    return candidates

# ---------------------- 并发测试 ----------------------

def run_concurrent_tests(candidates: List[Tuple[int,str,str,str]]) -> Tuple[Dict[str,List[Tuple[int,str]]],int]:
    saved = {c:[] for c in COUNTRIES}
    tested = 0
    if not candidates: return saved,0
    futures = {}
    workers = min(MAX_WORKERS,max(1,len(candidates)))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for cand in candidates:
            idx,line,country,ip = cand
            fut = ex.submit(is_reachable,ip)
            futures[fut] = cand
        for fut in as_completed(list(futures.keys())):
            cand = futures.get(fut)
            if not cand: continue
            idx,line,country,ip = cand
            tested += 1
            try: ok = fut.result()
            except: ok = False
            if ok and len(saved[country])<MAX_PER_COUNTRY.get(country,0):
                saved[country].append((idx,line))
            if all(len(saved[c])>=MAX_PER_COUNTRY.get(c,0) for c in COUNTRIES):
                for other_fut in list(futures.keys()):
                    if not other_fut.done():
                        try: other_fut.cancel()
                        except: pass
                break
    for c in COUNTRIES: saved[c].sort(key=lambda t:t[0])
    return saved,tested

# ---------------------- 输出 ----------------------

def write_output(saved: Dict[str,List[Tuple[int,str]]], out_path: Path = OUT_FILE):
    if not out_path.parent.exists():
        print(f"输出目录 {out_path.parent} 不存在，请先创建目录。")
        sys.exit(2)
    lines = []
    for c in COUNTRIES: lines.extend([ln for (_,ln) in saved.get(c,[])])
    with out_path.open("w",encoding="utf-8",newline="\n") as f:
        for ln in lines: f.write(ln+"\n")

# ---------------------- 主流程 ----------------------

def main():
    text = fetch_text()
    candidates = collect_candidates(text)
    if not candidates:
        print("No candidates found.")
        sys.exit(0)
    saved,tested = run_concurrent_tests(candidates)
    total_saved = sum(len(v) for v in saved.values())
    if total_saved==0:
        print(f"No reachable lines found (tested {tested} candidates).")
    else:
        write_output(saved,OUT_FILE)
        print(f"Saved {total_saved} lines to {OUT_FILE} (tested {tested} candidates).")
        for c in COUNTRIES:
            print(f"  {c.upper()}: saved {len(saved.get(c,[]))}/{MAX_PER_COUNTRY.get(c)}")
    sys.exit(0)

if __name__=="__main__":
    main()