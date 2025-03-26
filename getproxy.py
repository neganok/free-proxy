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

class DownloadProxies:
    def __init__(self) -> None:
        self.api = {
            'socks4': [''],
            'socks5': [''],
            'http': ['https://api.proxyscrape.com/v4/free-proxy-list/get?request=display_proxies&proxy_format=ipport&format=text']
        }
        self.proxy_dict = defaultdict(set)
        self.country_proxies = defaultdict(list)
        self.semaphore = asyncio.Semaphore(500)
        self.geoip_reader = self.setup_geoip()

    def setup_geoip(self):
        """Thiết lập GeoIP database chỉ cho quốc gia"""
        geoip_path = 'GeoLite2-Country.mmdb'
        download_urls = [
            'https://github.com/P3TERX/GeoLite.mmdb/raw/download/GeoLite2-Country.mmdb',
            'https://git.io/GeoLite2-Country.mmdb'
        ]
        
        if not os.path.exists(geoip_path):
            logger.info("Đang tải GeoIP database...")
            if not self.download_geoip_database(geoip_path, download_urls):
                logger.error("Không thể tải GeoIP database. Dừng chương trình.")
                sys.exit(1)
        
        try:
            reader = geoip2.database.Reader(geoip_path)
            logger.info("Đã tải GeoIP database thành công")
            return reader
        except Exception as e:
            logger.error(f"Lỗi khi tải GeoIP database: {e}")
            sys.exit(1)

    def download_geoip_database(self, path, urls):
        """Tải GeoIP database"""
        for url in urls:
            try:
                response = requests.get(url, timeout=30)
                if response.status_code == 200:
                    with open(path, 'wb') as f: f.write(response.content)
                    return True
            except Exception as e:
                logger.warning(f"Lỗi khi tải từ {url}: {e}")
        return False

    async def get_proxies(self):
        """Lấy proxy từ API"""
        async with aiohttp.ClientSession() as session:
            tasks = []
            for proxy_type, apis in self.api.items():
                for api in apis:
                    if api: tasks.append(self._fetch_proxies(session, proxy_type, api))
            await asyncio.gather(*tasks)
        
        self.proxy_dict = {k: list(v) for k, v in self.proxy_dict.items()}
        for proxy_type, proxies in self.proxy_dict.items():
            logger.info(f"Tổng {proxy_type.upper()} proxy: {len(proxies)}")

    async def _fetch_proxies(self, session, proxy_type, api):
        """Lấy proxy từ API"""
        try:
            async with self.semaphore, session.get(api, timeout=15) as response:
                if response.status == 200:
                    text = await response.text()
                    proxies = re.findall(r'\d{1,3}(?:\.\d{1,3}){3}:\d{2,5}', text)
                    if proxies:
                        self.proxy_dict[proxy_type].update(proxies)
                        logger.info(f"Nhận {len(proxies)} {proxy_type.upper()} proxy từ {api}")
        except Exception as e:
            logger.error(f"Lỗi khi tải từ {api}: {e}")

    def ip_to_country(self, ip):
        """Xác định quốc gia từ IP"""
        try:
            return self.geoip_reader.country(ip).country.name or 'Không xác định'
        except Exception:
            return 'Không xác định'

    async def sort_proxies_by_country(self):
        """Phân loại proxy theo quốc gia"""
        loop = asyncio.get_event_loop()
        ips = {proxy.split(':')[0] for proxies in self.proxy_dict.values() for proxy in proxies}
        countries = await asyncio.gather(*[loop.run_in_executor(None, self.ip_to_country, ip) for ip in ips])
        ip_country = dict(zip(ips, countries))

        for proxy_type, proxies in self.proxy_dict.items():
            for proxy in proxies:
                ip = proxy.split(':')[0]
                if (country := ip_country.get(ip)) != 'Không xác định':
                    self.country_proxies[country].append((proxy_type, proxy))
        
        logger.info(f"Đã phân loại proxy vào {len(self.country_proxies)} quốc gia")

    def save_proxies_by_country(self):
        """Lưu proxy theo quốc gia"""
        os.makedirs('world', exist_ok=True)
        for country, proxies in self.country_proxies.items():
            safe_name = re.sub(r'[\\/*?:"<>|]', "_", country)
            country_dir = os.path.join('world', safe_name)
            os.makedirs(country_dir, exist_ok=True)
            
            with open(os.path.join(country_dir, 'proxies.txt'), 'w') as f:
                f.write('\n'.join(f"{p[0].upper()} {p[1]}" for p in proxies))
            logger.info(f"Đã lưu {len(proxies)} proxy cho {country}")

    async def execute(self):
        """Thực thi chính"""
        logger.info("Bắt đầu quy trình...")
        await self.get_proxies()
        await self.sort_proxies_by_country()
        self.save_proxies_by_country()
        logger.info("Hoàn thành!")

    def close(self):
        """Dọn dẹp"""
        self.geoip_reader.close()

if __name__ == '__main__':
    import requests
    proxy_checker = DownloadProxies()
    try:
        asyncio.run(proxy_checker.execute())
    finally:
        proxy_checker.close()