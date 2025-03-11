import csv
import scrapy
import pymysql
import whois
import os
import tldextract
import re
from bs4 import BeautifulSoup
from twisted.internet import error
from scrapy.spidermiddlewares.httperror import HttpError
from twisted.internet.error import ConnectionLost
from twisted.internet.error import ConnectionDone

class ExampleSpider(scrapy.Spider):
    name = "example"
    handle_httpstatus_all = True
    visited_urls = []
    connect_urls = []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Kết nối database
        self.db = pymysql.connect(
            host="mysql_container",
            user="root",
            password="12345678",
            database="urls"
        )
        self.cursor = self.db.cursor()

        # Lấy danh sách URL từ database
        self.cursor.execute("SELECT id, url FROM company_list WHERE url IS NOT NULL AND url != '' AND url NOT LIKE 'NA'")
        self.start_urls = [{"id": row[0], "url": str(row[1]).strip()} for row in self.cursor.fetchall()]

        if not self.start_urls:
            self.log("Không có URL nào để crawl.", level=scrapy.log.ERROR)

        # Mở file CSV
        self.csv_file = open("output.csv", "w", newline="", encoding="utf-8")
        self.csv_writer = csv.writer(self.csv_file)
        self.csv_writer.writerow([
            "id", "url", "status", "redirect_url",
            "is_domain_for_sale", "is_domain_expired", "is_domain_parking", "is_domain_managed",
            "is_seo_spam", "is_admin_panel"
        ])
        self.visited_urls = set()
        self.connect_urls = set()

    def start_requests(self):
        """ Gửi request đến danh sách URL lấy từ database """
        for item in self.start_urls:
            url = item["url"].strip()
            if url.startswith('http://.') or url.startswith('https://.'):
                url = url.split('://', 1)[0] + '://' + url.split('://', 1)[1].lstrip('.')
            yield scrapy.Request(
                url=url,
                callback=self.parse,
                errback=self.handle_error,
                meta={"original_url": item["url"], "id": item["id"], "redirect_times": 0}
            )

    def closed(self, reason):
        """ Đóng kết nối database và file CSV khi Scrapy kết thúc """
        self.csv_file.close()
        self.db.close()

    def parse(self, response):
        """ Xử lý phản hồi từ request Scrapy """
        original_url = response.meta.get("original_url", response.url)
        record_id = response.meta.get("id", None)
        redirect_urls = response.request.meta.get("redirect_urls", [])
        status = response.status

        is_domain_for_sale = False
        is_domain_expired = False
        is_domain_parking = False
        is_domain_managed = False
        is_seo_spam = False
        is_admin_panel = False

        if original_url in self.visited_urls:
            return
        self.visited_urls.add(original_url)

        redirect_url = redirect_urls[-1] if redirect_urls else None
        if original_url != response.url:
            redirect_url = response.url

        if status == 200:
            soup = BeautifulSoup(response.text, "html.parser")
            title = soup.title.string if soup.title else ""
            body = response.text.lower()

            # Kiểm tra domain for sale / expired
            if any(keyword in body for keyword in ["for sale", "buy this domain", "domain is for sale"]):
                is_domain_for_sale = True

            # Kiểm tra thẻ meta description
            meta_tags = soup.find_all('meta', attrs={'name': 'description'})
            meta_content = " ".join([meta.get("content", "").lower() for meta in meta_tags])

            # Kiểm tra domain expired dựa trên title và meta description
            if title:
                title_lower = title.lower()
                if any(keyword in title_lower for keyword in ["domain for sale", "available for purchase", "expired domain"]):
                    is_domain_expired = True

            if any(keyword in meta_content for keyword in ["domain expired", "this domain is available", "purchase this domain"]):
                is_domain_expired = True

            # Kiểm tra domain parking dựa trên số lượng link và nội dung meta
            links = soup.find_all('a')
            if len(links) > 50 or any(keyword in body for keyword in ["related links", "sponsored listings", "click here to buy"]):
                is_domain_parking = True

            if any(keyword in meta_content for keyword in ["this domain is parked", "parking page", "advertisements served"]):
                is_domain_parking = True

            # Kiểm tra SEO Spam
            meta_desc = soup.find("meta", attrs={"name": "description"})
            meta_desc_content = meta_desc["content"] if meta_desc else ""
            keywords = ["casino", "loan", "cheap", "viagra", "bitcoin", "betting"]
            keyword_count = sum(body.count(kw) for kw in keywords)
            if keyword_count > 20 or len(links) > 100 or any(kw in meta_desc_content.lower() for kw in keywords):
                is_seo_spam = True

            # Kiểm tra trang quản trị
            admin_keywords = ["admin", "login", "dashboard", "wp-admin", "signin"]
            if any(kw in response.url.lower() for kw in admin_keywords):
                is_admin_panel = True
            login_form = soup.find("form", {"action": re.compile(r"(login|admin|signin)", re.IGNORECASE)})
            password_field = soup.find("input", {"type": "password"})
            if login_form or password_field:
                is_admin_panel = True

        # Kiểm tra Domain Managed
        try:
            domain_info = whois.whois(response.url)
            managed_domains = ["godaddy.com", "namecheap.com", "sedo.com"]
            if any(manager in str(domain_info.get("registrar", "")).lower() for manager in managed_domains):
                is_domain_managed = True
        except Exception:
            pass

        # Ghi dữ liệu vào CSV
        self.csv_writer.writerow([
            record_id, original_url, status, redirect_url,
            is_domain_for_sale, is_domain_expired, is_domain_parking, is_domain_managed,
            is_seo_spam, is_admin_panel
        ])
        self.csv_file.flush()

    def handle_error(self, failure):
        """ Xử lý lỗi khi request thất bại (GIỮ NGUYÊN CODE CŨ) """
        request = failure.request
        record_id = request.meta.get("id", None)
        status = "ERROR"
        original_url = request.meta.get("original_url", request.url)

        status = self.get_error_status(failure)
        proxy = "http://133.232.93.66:80"

        if isinstance(failure.value, scrapy.spidermiddlewares.httperror.HttpError):
            status = failure.value.response.status
            self.log_error(record_id, original_url, status)
            return

        if status in ["CONNECT_ERROR", "CONNECTION_REFUSED"]:
            if request.url not in self.connect_urls:
                self.connect_urls.add(request.url)
                yield scrapy.Request(
                    request.url,
                    callback=self.parse,
                    errback=self.handle_error,
                    meta={
                        "original_url": original_url,
                        "id": record_id,
                        "redirect_times": 0, 
                        "proxy": proxy,
                    },
                    dont_filter=True,
                )
                return
            elif request.url.startswith("https://") and request.url.replace("https://", "http://") not in self.connect_urls:
                http_url = request.url.replace("https://", "http://")
                self.connect_urls.add(http_url)
                yield scrapy.Request(
                    http_url,
                    callback=self.parse,
                    errback=self.handle_error,
                    meta={
                        "original_url": original_url,
                        "id": record_id,
                        "redirect_times": 0, 
                        "proxy": proxy,
                    },
                    dont_filter=True,
                )
                return
            elif request.url.startswith("http://") and request.url.replace("http://", "https://") not in self.connect_urls:
                https_url = request.url.replace("http://", "https://")
                self.connect_urls.add(https_url)
                yield scrapy.Request(
                    https_url,
                    callback=self.parse,
                    errback=self.handle_error,
                    meta={
                        "original_url": original_url,
                        "id": record_id,
                        "redirect_times": 0, 
                        "proxy": proxy,
                    },
                    dont_filter=True,
                )
                return

        if status == "SSL_ERROR":
            if request.url.startswith("https://"):
                http_url = request.url.replace("https://", "http://")
                http_url = re.sub(r"http://+", "http://", http_url)
                if http_url not in self.visited_urls:
                    self.visited_urls.add(http_url)
                    yield scrapy.Request(
                        http_url,
                        callback=self.parse,
                        errback=self.handle_error,
                        meta={"original_url": original_url, "id": record_id, "redirect_times": 0, },
                        dont_filter=True,
                    )
                    return
        
        if status == "DNS_ERROR":
            parsed_url = re.match(r"(https?://)([^/]+)(/?.*)", request.url)
            if parsed_url:
                scheme, domain, path = parsed_url.groups()
                
                # Nếu chưa có 'www.', thử thêm vào
                if not domain.startswith("www."):
                    new_url = f"{scheme}www.{domain}{path}"
                    if new_url not in self.visited_urls:
                        self.visited_urls.add(new_url)
                        yield scrapy.Request(
                            new_url,
                            callback=self.parse,
                            errback=self.handle_error,
                            meta={"original_url": original_url, "id": record_id},
                            dont_filter=True,
                        )
                        return

        if request.url.startswith("http://") or request.url.startswith("https://"):
            # Phân tích URL thành các phần
            parsed_url = re.match(r"(https?://)([^/]+)(/?.*)", request.url)
            if parsed_url:
                scheme, domain, path = parsed_url.groups()
                
                # Nếu domain không có "www.", thêm vào
                if not domain.startswith("www."):
                    domain = "www." + domain

                # Chuyển sang HTTPS nếu đang dùng HTTP
                https_url = f"https://{domain}{path}"
                
                if https_url not in self.visited_urls:
                    self.visited_urls.add(https_url)
                    yield scrapy.Request(
                        https_url,
                        callback=self.parse,
                        errback=self.handle_error,
                        meta={"original_url": original_url, "id": record_id},
                        dont_filter=True,  # Đảm bảo Scrapy không bỏ qua request nàym
                    )
                    return

        self.log_error(record_id, original_url, status)

    def get_error_status(self, failure):
        """ Xác định loại lỗi từ failure """
        failure_msg = str(failure.value).lower()
        print(f"❌ hhhhhh: {failure_msg}")
        if failure.check(error.DNSLookupError):
            return "DNS_ERROR"
        elif failure.check(error.TimeoutError, error.TCPTimedOutError):
            return "TIMEOUT"
        elif failure.check(error.ConnectionRefusedError):
            return "CONNECTION_REFUSED"
        elif failure.check(error.ConnectError):
            return "CONNECT_ERROR"
        elif failure.check(HttpError):
            response = failure.value.response
            if response:
                return response.status 
            return "HTTP_ERROR"
        elif failure.check(error.SSLError) or "SSL" in str(failure.value):
            return "SSL_ERROR"
        elif isinstance(failure.value, error.ConnectionLost):
            return "CONNECTION_LOST"
        elif isinstance(failure.value, error.ConnectionDone):
            return "CONNECTION_CLOSED"
        elif "connectionlost" in failure_msg:
            return "CONNECTION_LOST"
        elif "connectiondone" in failure_msg:
            return "CONNECTION_CLOSED"
        elif "connectionreset" in failure_msg:
            return "CONNECTION_RESET"

        return "ERROR"

    def log_error(self, record_id, url, status):
        """ Ghi lỗi vào CSV """
        self.csv_writer.writerow([record_id, url, status, None, None, None, None, None, None, None])
        self.csv_file.flush()
        # print(f"❌ Logged: {url} -> {status}")
