import os
import re
import sys
import requests
from collections import defaultdict
import geoip2.database
import logging

# Cấu hình hệ thống logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

class QuanLyProxy:
    def __init__(self):
        # Danh sách nguồn lấy proxy (đã bổ sung thêm nguồn)
        self.nguon_proxy = {
            'http': [
                'https://api.proxyscrape.com/v4/free-proxy-list/get?request=display_proxies&proxy_format=ipport&format=text&protocol=http',
                'https://proxyspace.pro/http.txt'
            ],
            'https': [
                'https://api.proxyscrape.com/v4/free-proxy-list/get?request=display_proxies&proxy_format=ipport&format=text&protocol=https'
            ],
            'socks4': [
                'https://api.proxyscrape.com/v4/free-proxy-list/get?request=display_proxies&proxy_format=ipport&format=text&protocol=socks4'
            ],
            'socks5': [
                'https://api.proxyscrape.com/v4/free-proxy-list/get?request=display_proxies&proxy_format=ipport&format=text&protocol=socks5'
            ]
        }
        self.danh_sach_proxy = defaultdict(set)  # Dùng set để tự động loại bỏ trùng lặp
        self.proxy_theo_quoc_gia = defaultdict(lambda: defaultdict(list))
        self.geoip_reader = self._khoi_tao_geoip()

    def _khoi_tao_geoip(self):
        """Khởi tạo cơ sở dữ liệu GeoIP"""
        duong_dan = 'GeoLite2-Country.mmdb'
        if not os.path.exists(duong_dan):
            self._tai_geoip(duong_dan)
        
        try:
            return geoip2.database.Reader(duong_dan)
        except Exception as e:
            logger.error(f"Lỗi khi tải GeoIP: {e}")
            sys.exit(1)

    def _tai_geoip(self, duong_dan):
        """Tải cơ sở dữ liệu GeoIP nếu chưa có"""
        danh_sach_url = [
            'https://github.com/P3TERX/GeoLite.mmdb/raw/download/GeoLite2-Country.mmdb',
            'https://git.io/GeoLite2-Country.mmdb'
        ]
        
        for url in danh_sach_url:
            try:
                phan_hoi = requests.get(url, timeout=30)
                if phan_hoi.status_code == 200:
                    with open(duong_dan, 'wb') as f:
                        f.write(phan_hoi.content)
                    logger.info("Đã tải thành công GeoIP")
                    return
            except Exception as e:
                logger.warning(f"Lỗi khi tải từ {url}: {e}")
        
        logger.error("Không thể tải GeoIP")
        sys.exit(1)

    def lay_proxy(self):
        """Lấy danh sách proxy từ các nguồn và loại bỏ trùng lặp"""
        for loai_proxy, danh_sach_url in self.nguon_proxy.items():
            for url in danh_sach_url:
                try:
                    phan_hoi = requests.get(url)
                    if phan_hoi.status_code == 200:
                        # Lọc và chỉ lấy các proxy hợp lệ
                        proxies = {p for p in re.findall(r'\d{1,3}(?:\.\d{1,3}){3}:\d{2,5}', phan_hoi.text) if p}
                        self.danh_sach_proxy[loai_proxy].update(proxies)
                        logger.info(f"Đã thêm {len(proxies)} proxy {loai_proxy.upper()} từ {url}")
                except Exception as e:
                    logger.error(f"Lỗi khi lấy proxy {loai_proxy} từ {url}: {e}")
        
        # Chuyển từ set sang list để tiện xử lý
        self.danh_sach_proxy = {k: list(v) for k, v in self.danh_sach_proxy.items()}
        
        # Log tổng số proxy mỗi loại sau khi đã loại bỏ trùng
        for loai_proxy, danh_sach in self.danh_sach_proxy.items():
            logger.info(f"Tổng số proxy {loai_proxy.upper()} sau khi lọc trùng: {len(danh_sach)}")

    def _xac_dinh_quoc_gia(self, ip):
        """Xác định quốc gia từ địa chỉ IP"""
        try:
            return self.geoip_reader.country(ip).country.name
        except Exception:
            return None

    def phan_loai_theo_quoc_gia(self):
        """Phân loại proxy theo quốc gia"""
        for loai_proxy, danh_sach in self.danh_sach_proxy.items():
            for proxy in danh_sach:
                ip = proxy.split(':')[0]
                if quoc_gia := self._xac_dinh_quoc_gia(ip):
                    self.proxy_theo_quoc_gia[quoc_gia][loai_proxy].append(proxy)
        
        logger.info(f"Đã phân loại proxy vào {len(self.proxy_theo_quoc_gia)} quốc gia")

    def luu_proxy(self):
        """Lưu proxy vào thư mục đã được tổ chức"""
        # Tạo thư mục chính
        os.makedirs('proxy/tong_hop', exist_ok=True)
        os.makedirs('proxy/quoc_gia', exist_ok=True)
        
        # Lưu tất cả proxy (đã loại bỏ trùng)
        with open('proxy/tong_hop/all.txt', 'w') as f:
            for loai_proxy in self.danh_sach_proxy.values():
                f.write('\n'.join(loai_proxy) + '\n')
        
        # Lưu theo loại proxy
        for loai_proxy, danh_sach in self.danh_sach_proxy.items():
            with open(f'proxy/tong_hop/{loai_proxy}.txt', 'w') as f:
                f.write('\n'.join(danh_sach))
        
        # Lưu theo quốc gia và loại proxy
        for quoc_gia, cac_loai in self.proxy_theo_quoc_gia.items():
            ten_thu_muc = f'proxy/quoc_gia/{self._chuan_hoa_ten(quoc_gia)}'
            os.makedirs(ten_thu_muc, exist_ok=True)
            
            for loai_proxy, danh_sach in cac_loai.items():
                with open(f'{ten_thu_muc}/{loai_proxy.upper()}.txt', 'w') as f:
                    f.write('\n'.join(danh_sach))
        
        logger.info("Đã lưu proxy thành công")

    def _chuan_hoa_ten(self, ten):
        """Chuẩn hóa tên thư mục"""
        return re.sub(r'[\\/*?:"<>|]', '_', ten)

    def thuc_thi(self):
        """Chạy toàn bộ quy trình"""
        logger.info("Bắt đầu quy trình xử lý proxy...")
        self.lay_proxy()
        self.phan_loai_theo_quoc_gia()
        self.luu_proxy()
        logger.info("Hoàn tất quá trình xử lý proxy")

    def dong(self):
        """Đóng kết nối và dọn dẹp tài nguyên"""
        self.geoip_reader.close()

if __name__ == '__main__':
    quan_ly = QuanLyProxy()
    try:
        quan_ly.thuc_thi()
    finally:
        quan_ly.dong()
