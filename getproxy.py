import asyncio
import aiohttp
import os
import geoip2.database
from collections import defaultdict

class ProxySorter:
    def __init__(self):
        # Cấu hình database GeoIP
        self.geoip_db = 'GeoLite2-Country.mmdb'
        self.proxy_dict = defaultdict(list)
        self.country_proxies = defaultdict(list)
        
        # Kiểm tra và tải GeoIP database nếu chưa có
        if not os.path.exists(self.geoip_db):
            self.download_geoip_database()
            
        self.geoip_reader = geoip2.database.Reader(self.geoip_db)

    def download_geoip_database(self):
        """Tải GeoIP database nếu chưa có"""
        import requests
        url = 'https://git.io/GeoLite2-Country.mmdb'
        try:
            print("Đang tải GeoIP database...")
            r = requests.get(url, timeout=30)
            with open(self.geoip_db, 'wb') as f:
                f.write(r.content)
            print("Đã tải xong GeoIP database")
        except Exception as e:
            print(f"Lỗi khi tải GeoIP database: {e}")
            exit(1)

    def ip_to_country(self, ip):
        """Xác định quốc gia từ địa chỉ IP"""
        try:
            response = self.geoip_reader.country(ip)
            return response.country.name or 'Không xác định'
        except:
            return 'Không xác định'

    async def load_proxies(self, file_path):
        """Đọc danh sách proxy từ file"""
        with open(file_path, 'r') as f:
            proxies = f.read().splitlines()
        
        # Phân loại proxy theo loại (http/socks4/socks5)
        for proxy in proxies:
            if proxy:  # Bỏ qua dòng trống
                parts = proxy.split()
                if len(parts) >= 2:
                    proxy_type = parts[0].lower()
                    proxy_addr = parts[1]
                    self.proxy_dict[proxy_type].append(proxy_addr)

    async def sort_by_country(self):
        """Phân loại proxy theo quốc gia"""
        for proxy_type, proxies in self.proxy_dict.items():
            for proxy in proxies:
                ip = proxy.split(':')[0]
                country = self.ip_to_country(ip)
                if country != 'Không xác định':
                    self.country_proxies[country].append(f"{proxy_type.upper()} {proxy}")

    def save_to_files(self):
        """Lưu proxy đã phân loại vào thư mục theo quốc gia"""
        os.makedirs('Proxy_Theo_Quoc_Gia', exist_ok=True)
        
        for country, proxies in self.country_proxies.items():
            # Tạo tên thư mục an toàn
            safe_country = ''.join(c if c.isalnum() else '_' for c in country)
            country_dir = os.path.join('Proxy_Theo_Quoc_Gia', safe_country)
            
            os.makedirs(country_dir, exist_ok=True)
            with open(os.path.join(country_dir, 'proxies.txt'), 'w') as f:
                f.write('\n'.join(proxies))
            
            print(f"Đã lưu {len(proxies)} proxy cho {country}")

    def close(self):
        """Đóng kết nối GeoIP database"""
        self.geoip_reader.close()

async def main():
    sorter = ProxySorter()
    
    try:
        # Đọc file proxy đầu vào (tạo file này trước khi chạy)
        await sorter.load_proxies('all_proxies.txt')
        
        # Phân loại theo quốc gia
        await sorter.sort_by_country()
        
        # Lưu kết quả
        sorter.save_to_files()
        
        print("Hoàn thành phân loại proxy!")
    finally:
        sorter.close()

if __name__ == '__main__':
    asyncio.run(main())
