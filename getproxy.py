import asyncio
import aiohttp
import re
import os
import sys
from collections import defaultdict
import geoip2.database
from bs4 import BeautifulSoup
import logging

# Cấu hình hệ thống logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

class DownloadProxies:
    def __init__(self) -> None:
        # Danh sách API để lấy proxy
        self.api = {
            'socks4': [''],
            'socks5': [''],
            'http': ['https://api.proxyscrape.com/v4/free-proxy-list/get?request=display_proxies&proxy_format=ipport&format=text']
        }
        self.proxy_dict = defaultdict(set)  # Lưu trữ proxy theo loại
        self.country_proxies = defaultdict(list)  # Lưu trữ proxy theo quốc gia
        self.semaphore = asyncio.Semaphore(500)  # Giới hạn kết nối đồng thời
        self.ip_country_cache = {}  # Cache lưu trữ IP và quốc gia
        self.geoip_readers = self.setup_geoip()  # Khởi tạo GeoIP reader

    def setup_geoip(self):
        """Thiết lập cơ sở dữ liệu GeoIP"""
        geoip_db_paths = {
            'country': 'GeoLite2-Country.mmdb',
            'city': 'GeoLite2-City.mmdb',
            'asn': 'GeoLite2-ASN.mmdb'
        }
        download_urls = {
            'country': [
                'https://github.com/P3TERX/GeoLite.mmdb/raw/download/GeoLite2-Country.mmdb',
                'https://git.io/GeoLite2-Country.mmdb'
            ],
            'city': [
                'https://github.com/P3TERX/GeoLite.mmdb/raw/download/GeoLite2-City.mmdb',
                'https://git.io/GeoLite2-City.mmdb'
            ],
            'asn': [
                'https://github.com/P3TERX/GeoLite.mmdb/raw/download/GeoLite2-ASN.mmdb',
                'https://git.io/GeoLite2-ASN.mmdb'
            ]
        }
        readers = {}
        for key, path in geoip_db_paths.items():
            if not os.path.exists(path):
                logger.info(f"Không tìm thấy file {path}. Bắt đầu tải về...")
                success = self.download_geoip_database(key, path, download_urls[key])
                if not success:
                    logger.error(f"Không thể tải {path}. Dừng chương trình.")
                    sys.exit(1)
            try:
                readers[key] = geoip2.database.Reader(path)
                logger.info(f"Đã tải {key} GeoIP database từ {path}.")
            except Exception as e:
                logger.error(f"Lỗi khi tải {path}: {e}")
                sys.exit(1)
        return readers

    def download_geoip_database(self, key, path, urls):
        """Tải cơ sở dữ liệu GeoIP từ URL"""
        for url in urls:
            try:
                logger.info(f"Đang tải {path} từ {url}")
                response = requests.get(url, timeout=30)
                if response.status_code == 200:
                    with open(path, 'wb') as f: f.write(response.content)
                    logger.info(f"Đã tải thành công {path} từ {url}")
                    return True
                else:
                    logger.warning(f"Không thể tải {path} từ {url}. Mã trạng thái: {response.status_code}")
            except Exception as e:
                logger.warning(f"Lỗi khi tải {path} từ {url}: {e}")
        return False

    async def get_proxies(self):
        """Lấy tất cả proxy từ các API"""
        async with aiohttp.ClientSession() as session:
            tasks = []
            for proxy_type, apis in self.api.items():
                for api in apis: tasks.append(self.fetch_proxies(session, proxy_type, api))
            await asyncio.gather(*tasks)
        self.proxy_dict = {k: list(v) for k, v in self.proxy_dict.items()}
        for proxy_type in self.proxy_dict:
            logger.info(f"Tổng số {proxy_type.upper()} proxy nhận được: {len(self.proxy_dict[proxy_type])}")

    def ip_to_country_local(self, ip):
        """Xác định quốc gia từ IP"""
        try:
            response = self.geoip_readers['country'].country(ip)
            country = response.country.name or 'Không xác định'
            return country
        except Exception: return 'Không xác định'

    def ip_to_city_local(self, ip):
        """Xác định thành phố từ IP"""
        try:
            response = self.geoip_readers['city'].city(ip)
            city = response.city.name or 'Không xác định'
            return city
        except Exception: return 'Không xác định'

    def ip_to_asn_local(self, ip):
        """Xác định ASN từ IP"""
        try:
            response = self.geoip_readers['asn'].asn(ip)
            asn = response.autonomous_system_organization or 'Không xác định'
            return asn
        except Exception: return 'Không xác định'

    async def sort_proxies_by_country(self):
        """Phân loại proxy theo quốc gia"""
        loop = asyncio.get_event_loop()
        unique_ips = set(proxy.split(':')[0] for proxies in self.proxy_dict.values() for proxy in proxies)
        tasks = [loop.run_in_executor(None, self.ip_to_country_local, ip) for ip in unique_ips]
        countries = await asyncio.gather(*tasks)
        ip_to_country_map = {ip: country for ip, country in zip(unique_ips, countries)}

        for proxy_type, proxies in self.proxy_dict.items():
            for proxy in proxies:
                ip, port = proxy.split(':')
                country = ip_to_country_map.get(ip, 'Không xác định')
                if country != 'Không xác định':
                    self.country_proxies[country].append((proxy_type, proxy))
        logger.info("Đã phân loại proxy theo quốc gia.")

    def save_proxies_by_country(self):
        """Lưu proxy theo thư mục quốc gia"""
        os.makedirs('world', exist_ok=True)
        for country, proxies in self.country_proxies.items():
            safe_country = re.sub(r'[\\/*?:"<>|]', "_", country)
            country_dir = os.path.join('world', safe_country)
            os.makedirs(country_dir, exist_ok=True)
            file_path = os.path.join(country_dir, 'proxies.txt')
            try:
                with open(file_path, 'w') as f:
                    for proxy_type, proxy in proxies: f.write(f"{proxy_type.upper()} {proxy}\n")
                logger.info(f"Đã lưu proxy cho {country} vào {country_dir}")
            except Exception as e:
                logger.error(f"Lỗi khi lưu proxy cho {country}: {e}")

    def save_all_proxies(self):
        """Lưu tất cả proxy theo loại"""
        os.makedirs('proxies', exist_ok=True)
        file_paths = {
            'http': os.path.join('proxies', 'http.txt'),
            'socks4': os.path.join('proxies', 'socks4.txt'),
            'socks5': os.path.join('proxies', 'socks5.txt'),
            'all': os.path.join('proxies', 'all.txt')
        }
      
        for proxy_type, proxies in self.proxy_dict.items():
            try:
                with open(file_paths[proxy_type], 'w') as type_file: type_file.write('\n'.join(proxies))
                logger.info(f"Đã lưu {proxy_type.upper()} proxy vào {file_paths[proxy_type]}")
            except Exception as e: logger.error(f"Lỗi khi lưu {proxy_type.upper()} proxy: {e}")

        all_proxies = set()
        for proxies in self.proxy_dict.values(): all_proxies.update(proxies)
        try:
            with open(file_paths['all'], 'w') as all_file: all_file.write('\n'.join(all_proxies))
            logger.info(f"Đã lưu tất cả proxy vào {file_paths['all']}")
        except Exception as e: logger.error(f"Lỗi khi lưu tất cả proxy: {e}")

    async def validate_proxy(self, session, proxy):
        """Kiểm tra proxy có hoạt động không"""
        test_url = 'http://www.google.com'
        try:
            async with session.get(test_url, proxy=f'http://{proxy}', timeout=5): return True
        except: return False

    async def validate_single_proxy(self, session, proxy_type, proxy):
        """Kiểm tra từng proxy"""
        is_valid = await self.validate_proxy(session, proxy)
        return proxy_type, proxy, is_valid

    async def validate_proxies(self):
        """Kiểm tra tất cả proxy"""
        valid_proxies = defaultdict(set)
        async with aiohttp.ClientSession() as session:
            tasks = []
            for proxy_type, proxies in self.proxy_dict.items():
                for proxy in proxies: tasks.append(self.validate_single_proxy(session, proxy_type, proxy))
            results = await asyncio.gather(*tasks)
            for proxy_type, proxy, is_valid in results:
                if is_valid: valid_proxies[proxy_type].add(proxy)
        self.proxy_dict = valid_proxies
        logger.info("Đã hoàn thành kiểm tra proxy.")

    async def execute(self):
        """Thực thi toàn bộ quy trình"""
        logger.info("Bắt đầu tải proxy...")
        await self.get_proxies()
        logger.info("Hoàn thành tải proxy.")

        logger.info("Bắt đầu phân loại proxy theo quốc gia...")
        await self.sort_proxies_by_country()

        logger.info("Bắt đầu kiểm tra proxy...")
        await self.validate_proxies()

        logger.info("Đã hoàn thành phân loại và kiểm tra proxy.")

        logger.info("Bắt đầu lưu proxy theo quốc gia...")
        self.save_proxies_by_country()

        logger.info("Bắt đầu lưu tất cả proxy...")
        self.save_all_proxies()

        logger.info("Đã hoàn thành tất cả thao tác.")

    def close(self):
        """Đóng kết nối GeoIP"""
        for reader in self.geoip_readers.values(): reader.close()

if __name__ == '__main__':
    import requests  
    d = DownloadProxies()
    try: asyncio.run(d.execute())
    finally: d.close()
