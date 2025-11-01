#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ip2.py 完整版本（自动下载 DB-IP CSV + 国家标签输出）
"""
import requests, gzip, shutil, csv, socket, subprocess, platform, sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

# ---------------- 配置 ----------------
SRC_URL = "https://raw.githubusercontent.com/tianshipapa/cfipcaiji/refs/heads/main/ip.txt"
IP_CSV = Path(__file__).parent / "dbip-country-lite.csv"
CSV_URL = "https://download.db-ip.com/free/dbip-country-lite-2025-11.csv.gz"
OUT_FILE = Path(__file__).parent / "ip.txt"

PING_TIMEOUT = 2.0
TCP_TIMEOUT = 1.0
MAX_WORKERS = 8

COUNTRIES = ["sg","hk","jp","tw","kr","us","cn"]

# ---------------- 下载 DB-IP CSV ----------------
def download_dbip_csv():
    if IP_CSV.exists():
        print(f"{IP_CSV} 已存在，跳过下载。")
        return
    print(f"下载 {CSV_URL} ...")
    try:
        r = requests.get(CSV_URL, stream=True, timeout=30)
        r.raise_for_status()
        gz_path = IP_CSV.with_suffix(".csv.gz")
        with open(gz_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
        # 解压
        with gzip.open(gz_path, "rb") as f_in, open(IP_CSV, "wb") as f_out:
            shutil.copyfileobj(f_in, f_out)
        gz_path.unlink()
        print("下载并解压完成。")
    except Exception as e:
        print("下载失败:", e)
        sys.exit(1)

# ---------------- IP 工具 ----------------
def is_ipv4(ip: str) -> bool:
    parts = ip.split(".")
    return len(parts)==4 and all(p.isdigit() and 0<=int(p)<=255 for p in parts)

def ip2int(ip: str) -> int:
    parts = [int(p) for p in ip.split(".")]
    return (parts[0]<<24) + (parts[1]<<16) + (parts[2]<<8) + parts[3]

def load_ip_db(csv_path: Path):
    db = []
    with csv_path.open("r", encoding="utf-8") as f:
        reader = csv.reader(f)
        for row in reader:
            start_ip, end_ip, country = row
            start_ip = start_ip.strip('"')
            end_ip = end_ip.strip('"')
            country = country.lower()
            if not is_ipv4(start_ip) or not is_ipv4(end_ip):
                continue  # 跳过 IPv6
            db.append((ip2int(start_ip), ip2int(end_ip), country))
    return db

def query_country(ip: str, db) -> str:
    n = ip2int(ip)
    for start, end, country in db:
        if start <= n <= end:
            return country
    return ""

def extract_ipv4(line: str) -> str:
    parts = line.strip().split()
    for p in parts:
        if is_ipv4(p):
            return p
    return ""

# ---------------- 可达性 ----------------
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

# ---------------- 主流程 ----------------
def main():
    # 1. 下载 DB-IP CSV
    download_dbip_csv()
    db = load_ip_db(IP_CSV)

    # 2. 下载源 IP 列表
    try:
        r = requests.get(SRC_URL, timeout=30)
        r.raise_for_status()
        text = r.text
    except Exception as e:
        print("Fetch failed:", e)
        sys.exit(1)

    # 3. 提取 IP
    ips = []
    line_map = {}
    for line in text.splitlines():
        ip = extract_ipv4(line)
        if ip:
            ips.append(ip)
            line_map[ip] = line
    print(f"抓到的 IP 数量: {len(ips)}")
    if not ips:
        print("No IP found.")
        sys.exit(0)

    # 4. 过滤国家
    candidates = []
    ip_country_map = {}
    for ip in ips:
        country = query_country(ip, db)
        ip_country_map[ip] = country
        if any(c in country for c in COUNTRIES):
            candidates.append(ip)
    print(f"候选 IP 数量（符合国家条件）: {len(candidates)}")
    if not candidates:
        print("No candidates found.")
        sys.exit(0)

    # 5. 并发检测可达性
    reachable = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        fut_map = {ex.submit(is_reachable, ip): ip for ip in candidates}
        for fut in as_completed(fut_map):
            ip = fut_map[fut]
            try:
                if fut.result():
                    country = ip_country_map.get(ip,"").upper()
                    reachable.append(f"{line_map[ip]} #{country}")
            except:
                continue
    print(f"可达 IP 数量: {len(reachable)}")

    # 6. 写入文件
    if reachable:
        OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
        with OUT_FILE.open("w", encoding="utf-8") as f:
            for ln in reachable:
                f.write(ln+"\n")
        print(f"成功写入 {OUT_FILE}")
    else:
        print("没有可达 IP 写入文件。")

if __name__=="__main__":
    main()