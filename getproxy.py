import asyncio
import aiohttp
import re
import os
import sys
from collections import defaultdict
import geoip2.database
import logging

# Cấu hình logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

class ProxyManager:
    def __init__(self) -> None:
        # Các nguồn proxy (giữ nguyên cấu trúc nhưng thêm HTTPS)
        self.api = {
            'http': ['https://api.proxyscrape.com/v4/free-proxy-list/get?request=display_proxies&proxy_format=ipport&format=text&protocol=http'],
            'https': ['https://api.proxyscrape.com/v4/free-proxy-list/get?request=display_proxies&proxy_format=ipport&format=text&protocol=https'],
            'socks4': ['https://api.proxyscrape.com/v4/free-proxy-list/get?request=display_proxies&proxy_format=ipport&format=text&protocol=socks4'],
            'socks5': ['https://api.proxyscrape.com/v4/free-proxy-list/get?request=display_proxies&proxy_format=ipport&format=text&protocol=socks5']
        }
        self.proxy_dict = defaultdict(set)
        self.country_proxies = defaultdict(list)
        self.geoip_reader = self.setup_geoip()

    def setup_geoip(self):
        """Thiết lập GeoIP database cho quốc gia"""
        geoip_path = 'GeoLite2-Country.mmdb'
        download_urls = [
            'https://github.com/P3TERX/GeoLite.mmdb/raw/download/GeoLite2-Country.mmdb',
            'https://git.io/GeoLite2-Country.mmdb'
        ]
        
        if not os.path.exists(geoip_path):
            logger.info("Đang tải GeoIP database...")
            if not self.download_geoip_database(geoip_path, download_urls):
                logger.error("Không thể tải GeoIP database")
                sys.exit(1)
        
        try:
            return geoip2.database.Reader(geoip_path)
        except Exception as e:
            logger.error(f"Lỗi khi tải GeoIP: {e}")
            sys.exit(1)

    def download_geoip_database(self, path, urls):
        """Tải GeoIP database nếu chưa có"""
        import requests
        for url in urls:
            try:
                response = requests.get(url, timeout=30)
                if response.status_code == 200:
                    with open(path, 'wb') as f: 
                        f.write(response.content)
                    return True
            except Exception as e:
                logger.warning(f"Lỗi khi tải từ {url}: {e}")
        return False

    async def fetch_proxies(self):
        """Lấy proxy từ các API"""
        async with aiohttp.ClientSession() as session:
            tasks = []
            for proxy_type, apis in self.api.items():
                for api in apis:
                    tasks.append(self._fetch_proxy_type(session, proxy_type, api))
            await asyncio.gather(*tasks)
        
        # Chuyển từ set sang list
        self.proxy_dict = {k: list(v) for k, v in self.proxy_dict.items()}
        
        # Log số lượng proxy mỗi loại
        for proxy_type, proxies in self.proxy_dict.items():
            logger.info(f"Tìm thấy {len(proxies)} {proxy_type.upper()} proxy")

    async def _fetch_proxy_type(self, session, proxy_type, api):
        """Lấy proxy từ API cụ thể"""
        try:
            async with session.get(api, timeout=15) as response:
                if response.status == 200:
                    text = await response.text()
                    proxies = re.findall(r'\d{1,3}(?:\.\d{1,3}){3}:\d{2,5}', text)
                    if proxies:
                        self.proxy_dict[proxy_type].update(proxies)
        except Exception as e:
            logger.error(f"Lỗi khi lấy {proxy_type} từ {api}: {e}")

    def ip_to_country(self, ip):
        """Xác định quốc gia từ IP"""
        try:
            return self.geoip_reader.country(ip).country.name or 'Unknown'
        except Exception:
            return 'Unknown'

    async def sort_by_country(self):
        """Phân loại proxy theo quốc gia"""
        loop = asyncio.get_event_loop()
        ips = {proxy.split(':')[0] for proxies in self.proxy_dict.values() for proxy in proxies}
        
        # Xác định quốc gia cho từng IP
        countries = await asyncio.gather(*[
            loop.run_in_executor(None, self.ip_to_country, ip) 
            for ip in ips
        ])
        
        ip_country_map = dict(zip(ips, countries))
        
        # Phân loại proxy theo quốc gia
        for proxy_type, proxies in self.proxy_dict.items():
            for proxy in proxies:
                ip = proxy.split(':')[0]
                if (country := ip_country_map.get(ip)) != 'Unknown':
                    self.country_proxies[country].append((proxy_type, proxy))
        
        logger.info(f"Đã phân loại proxy vào {len(self.country_proxies)} quốc gia")

    def save_proxies(self):
        """Lưu proxy vào các file theo loại và quốc gia"""
        # Tạo thư mục gốc
        os.makedirs('proxies', exist_ok=True)
        
        # Lưu proxy theo loại
        for proxy_type, proxies in self.proxy_dict.items():
            with open(f'proxies/{proxy_type}.txt', 'w') as f:
                f.write('\n'.join(proxies))
        
        # Lưu tất cả proxy
        all_proxies = [p for proxies in self.proxy_dict.values() for p in proxies]
        with open('proxies/all.txt', 'w') as f:
            f.write('\n'.join(all_proxies))
        
        # Lưu theo quốc gia
        os.makedirs('proxies/countries', exist_ok=True)
        for country, proxies in self.country_proxies.items():
            safe_name = re.sub(r'[\\/*?:"<>|]', '_', country)
            with open(f'proxies/countries/{safe_name}.txt', 'w') as f:
                f.write('\n'.join(f"{p[0]} {p[1]}" for p in proxies))
        
        logger.info("Đã lưu tất cả proxy vào thư mục 'proxies'")

    async def execute(self):
        """Thực thi chương trình"""
        logger.info("Bắt đầu lấy proxy...")
        await self.fetch_proxies()
        
        logger.info("Phân loại proxy theo quốc gia...")
        await self.sort_by_country()
        
        logger.info("Lưu proxy vào file...")
        self.save_proxies()
        
        logger.info("Hoàn thành!")

    def close(self):
        """Đóng kết nối"""
        self.geoip_reader.close()

if __name__ == '__main__':
    manager = ProxyManager()
    try:
        asyncio.run(manager.execute())
    finally:
        manager.close()