#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
调试版 ip2.py
- 抓取 IP 列表
- 批量查询国家（Chinaz siteip）
- 并发检测可达性（ping/TCP 80/443）
- 打印调试信息，保存最终可达 IP 到 ip.txt
"""
import requests, re, sys, time, platform, subprocess, socket
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from bs4 import BeautifulSoup

URL = "https://raw.githubusercontent.com/tianshipapa/cfipcaiji/refs/heads/main/ip.txt"
OUT_FILE = Path(__file__).parent / "ip.txt"
RE_IPV4 = re.compile(r'(\d{1,3}(?:\.\d{1,3}){3})')
PING_TIMEOUT = 2.0
TCP_TIMEOUT = 1.0
MAX_WORKERS = 8
CHINAZ_SITEIP_URL = "https://ip.tool.chinaz.com/siteip"

# 想要保留的国家
COUNTRIES = ["sg","hk","jp","tw","kr","us","cn"]

# ---------------- 工具函数 ----------------

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
    if not m:
        return None
    ip = m.group(1)
    for p in ip.split("."):
        if not (0 <= int(p) <= 255):
            return None
    return ip

def ping_host(ip: str) -> bool:
    system = platform.system().lower()
    try:
        cmd = ["ping","-n","1","-w",str(int(PING_TIMEOUT*1000)),ip] if system=="windows" else ["ping","-c","1",ip]
        res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=PING_TIMEOUT+0.5)
        return res.returncode==0
    except:
        return False

def tcp_connect(ip: str, ports=(80,443)) -> bool:
    for port in ports:
        try:
            with socket.create_connection((ip, port), timeout=TCP_TIMEOUT):
                return True
        except:
            continue
    return False

def is_reachable(ip: str) -> bool:
    return ping_host(ip) or tcp_connect(ip)

# ---------------- 查询国家 ----------------

def query_chinaz_siteip(ip_list: List[str], batch_size: int = 100, delay: float = 0.5) -> Dict[str,str]:
    ip_country: Dict[str,str] = {}
    for i in range(0, len(ip_list), batch_size):
        batch = ip_list[i:i+batch_size]
        print(f"查询批次: {batch}")
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
            if len(tds) >= 2:
                ip_text = tds[0].get_text(strip=True)
                country_text = tds[1].get_text(strip=True).lower()
                if ip_text in batch:
                    ip_country[ip_text] = country_text
        time.sleep(delay)
    print(f"Chinaz siteip 返回结果: {ip_country}")
    return ip_country

# ---------------- 主流程 ----------------

def main():
    text = fetch_text()
    ips = []
    line_map = {}
    for idx, line in enumerate(text.splitlines()):
        line = line.strip()
        if not line:
            continue
        ip = extract_ipv4(line)
        if ip:
            ips.append(ip)
            line_map[ip] = line
    print(f"抓到的 IP 数量: {len(ips)}")
    if not ips:
        print("No IP found in the source.")
        sys.exit(0)

    ip2country = query_chinaz_siteip(ips)
    if not ip2country:
        print("No countries returned from Chinaz siteip.")
        sys.exit(0)

    # 候选 IP 按国家过滤
    candidates: List[Tuple[str,str]] = []
    for ip,country in ip2country.items():
        if any(c in country for c in COUNTRIES):
            candidates.append((ip, line_map[ip]))
    print(f"候选 IP 数量（符合国家条件）: {len(candidates)}")

    # 并发检测可达性
    reachable: List[str] = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        future_map = {ex.submit(is_reachable, ip): ip for ip,_ in candidates}
        for fut in as_completed(future_map):
            ip = future_map[fut]
            try:
                if fut.result():
                    reachable.append(line_map[ip])
            except:
                continue
    print(f"可达 IP 数量: {len(reachable)}")

    # 写入文件
    if reachable:
        OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
        with OUT_FILE.open("w",encoding="utf-8") as f:
            for ln in reachable:
                f.write(ln+"\n")
        print(f"成功写入 {OUT_FILE}")
    else:
        print("没有可达 IP 写入文件。")

if __name__=="__main__":
    main()