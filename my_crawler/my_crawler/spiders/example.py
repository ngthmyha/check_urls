import csv
import requests
from bs4 import BeautifulSoup
import scrapy
import pymysql  # type: ignore
import whois  # type: ignore
from twisted.internet import error

class ExampleSpider(scrapy.Spider):
    name = "example"
    handle_httpstatus_all = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Kết nối database để lấy danh sách URL hợp lệ
        self.db = pymysql.connect(
            host="mysql_container", 
            user="root",
            password="12345678",
            database="urls"
        )
        self.cursor = self.db.cursor()
        
        self.cursor.execute("SELECT url FROM company_list WHERE url IS NOT NULL AND url != '' AND url NOT LIKE 'NA'")
        self.start_urls = [str(row[0]).strip() for row in self.cursor.fetchall()]
        
        if not self.start_urls:
            print("Không có URL nào để crawl.")

        self.csv_file = open("output.csv", mode="w", newline="", encoding="utf-8")
        self.csv_writer = csv.writer(self.csv_file)
        self.csv_writer.writerow(["url", "status", "redirect_url", "is_ssh"])

    def closed(self, reason):
        self.csv_file.close()
        self.db.close()

    def parse(self, response):
        page_status = response.status
        redirect_url = response.url if response.request.meta.get('redirect_urls') else None
        is_ssh = response.url.startswith("https://")

        # Ghi vào file CSV
        self.csv_writer.writerow([response.url, page_status, redirect_url, is_ssh])
        
        # Kiểm tra nội dung trang
        soup = BeautifulSoup(response.text, "html.parser")
        title = soup.title.string if soup.title else ""

        seo_keywords = ["for sale", "buy this domain", "available for purchase"]
        seo_meta_tags = ["domain for sale", "purchase this domain"]

        if any(keyword in response.text.lower() for keyword in seo_keywords) or any(tag in title.lower() for tag in seo_meta_tags):
            self.log(f"⚠️ {response.url} có thể là domain hết hạn hoặc bị bỏ hoang!")
        
        # Kiểm tra WHOIS
        try:
            domain_info = whois.whois(response.url)
            company_domains = ["godaddy.com", "namecheap.com", "sedo.com"]
            if any(manager in domain_info.get("registrar", "").lower() for manager in company_domains):
                self.log(f"⚠️ {response.url} có thể thuộc trang quản lý domain.")
        except Exception as e:
            self.log(f"Lỗi WHOIS cho {response.url}: {e}")

    def handle_error(self, failure):
        request = failure.request
        error_message = str(failure.value)
        status = "ERROR"  # Mặc định là lỗi

        # Xác định loại lỗi
        if failure.check(error.DNSLookupError):
            status = "DNS_ERROR"
        elif failure.check(error.TimeoutError, error.TCPTimedOutError):
            status = "TIMEOUT"
        elif failure.check(error.ConnectionRefusedError):
            status = "CONNECTION_REFUSED"

        # Ghi lỗi vào CSV
        self.csv_writer.writerow([request.url, status, None, None, None])

        # Không in log lỗi trên console
        self.log(f"❌ {status} for {request.url}", level=scrapy.log.DEBUG)
